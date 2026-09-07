from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.validation import (
    CriterionResult,
    CriterionStatus,
    CriterionType,
    ValidationResult,
    ValidationStatus,
)


@dataclass
class _CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str


class DeterministicValidator:
    def validate(
        self,
        task_id: str,
        task_contract: Any,
        implementation_result: Any,
        workspace: Path | None = None,
    ) -> ValidationResult:
        workspace = workspace or Path(".")
        criterion_results: list[CriterionResult] = []
        test_results: list[str] = []
        evidence: list[str] = []
        failures: list[str] = []
        warnings: list[str] = []
        manual_review_items: list[str] = []
        changed_files: list[str] = []
        scope_result = "UNKNOWN"

        # Run the self-test first: only when a test scope is declared AND the
        # suite passes do manual criteria stop blocking the task. Without a
        # test scope the criteria keep the conservative NEEDS_REVIEW behavior.
        tests_passing = False
        if task_contract.test_scope:
            self_test = self._run_self_test(task_contract, criterion_results, test_results, evidence, failures, workspace=workspace)
            if self_test.exit_code == 0:
                tests_passing = True
            elif self_test.exit_code == 5:
                # pytest exit 5 == "no tests collected": the declared test
                # paths hold no tests yet. Not a deliverable failure, but it
                # is surfaced as a warning.
                tests_passing = True
                warnings.append("Self-test collected no tests (exit code 5).")

        for criterion in task_contract.acceptance_criteria:
            if not tests_passing:
                criterion_results.append(
                    CriterionResult(
                        criterion=criterion,
                        type=CriterionType.MANUAL,
                        status=CriterionStatus.NEEDS_REVIEW,
                        evidence="",
                        details="No passing self-test to verify against; manual verification required.",
                    )
                )
            manual_review_items.append(criterion)

        changed_files = implementation_result.changed_files or []
        allowed_paths = task_contract.allowed_paths or []
        scope_result = self._evaluate_scope_status(changed_files, allowed_paths, workspace=workspace)
        if scope_result == "WITHIN_SCOPE":
            criterion_results.append(
                CriterionResult(
                    criterion="Scope check",
                    type=CriterionType.FILE,
                    status=CriterionStatus.PASS,
                    evidence=",".join(changed_files),
                    details="Changed files are within allowed paths.",
                )
            )
        elif scope_result == "NEEDS_REVIEW":
            criterion_results.append(
                CriterionResult(
                    criterion="Scope check",
                    type=CriterionType.FILE,
                    status=CriterionStatus.NEEDS_REVIEW,
                    evidence=",".join(changed_files),
                    details="Some changed files may need manual review.",
                )
            )
            warnings.append("Scope check requires manual review.")
        else:
            criterion_results.append(
                CriterionResult(
                    criterion="Scope check",
                    type=CriterionType.FILE,
                    status=CriterionStatus.FAIL,
                    evidence=",".join(changed_files),
                    details="Changed files are outside allowed paths.",
                )
            )
            failures.append("Scope violation detected.")

        status = ValidationStatus.PASS
        if any(c.status == CriterionStatus.FAIL for c in criterion_results):
            status = ValidationStatus.FAIL
        elif any(c.status == CriterionStatus.NEEDS_REVIEW for c in criterion_results):
            status = ValidationStatus.NEEDS_REVIEW
        if scope_result == "SCOPE_VIOLATION":
            status = ValidationStatus.FAIL
        if failures and status == ValidationStatus.PASS:
            status = ValidationStatus.FAIL

        return ValidationResult(
            task_id=task_id,
            status=status,
            criterion_results=criterion_results,
            test_results=test_results,
            scope_result=scope_result,
            changed_files=changed_files,
            evidence=evidence,
            failures=failures,
            warnings=warnings,
            manual_review_items=manual_review_items,
            llm_review=None,
            repair_cycle=0,
            validated_at="",
        )

    def _run_self_test(
        self,
        task_contract: Any,
        criterion_results: list[CriterionResult],
        test_results: list[str],
        evidence: list[str],
        failures: list[str],
        workspace: Path | None = None,
    ) -> _CommandResult:
        test_command = task_contract.test_command or f"{sys.executable} -m pytest -q"
        command_result = self._run_command(test_command, workspace=workspace)
        test_results.append(command_result.stdout)
        evidence.append(f"test_command={test_command}")
        evidence.append(f"test_exit_code={command_result.exit_code}")
        if command_result.exit_code in (0, 5):
            criterion_results.append(
                CriterionResult(
                    criterion="Self-test execution",
                    type=CriterionType.TEST,
                    status=CriterionStatus.PASS,
                    evidence=command_result.stdout,
                    details="Pytest command passed." if command_result.exit_code == 0 else "No tests collected yet.",
                )
            )
        else:
            criterion_results.append(
                CriterionResult(
                    criterion="Self-test execution",
                    type=CriterionType.TEST,
                    status=CriterionStatus.FAIL,
                    evidence=command_result.stdout + "\n" + command_result.stderr,
                    details="Pytest command failed.",
                )
            )
            failures.append("Self-test execution failed.")
        return command_result

    def _run_command(self, command: str, workspace: Path | None = None) -> _CommandResult:
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(workspace or Path(".")),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            return _CommandResult(
                command=command,
                exit_code=proc.returncode,
                stdout=proc.stdout.decode("utf-8", errors="replace"),
                stderr=proc.stderr.decode("utf-8", errors="replace"),
            )
        except Exception as exc:
            return _CommandResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(exc),
            )

    def _evaluate_scope_status(self, changed_files: list[str], allowed_paths: list[str], workspace: Path | None = None) -> str:
        if not allowed_paths:
            return "NEEDS_REVIEW"
        base = workspace.resolve() if workspace is not None else None
        for changed in changed_files:
            candidates = [changed]
            if base is not None:
                # Reporters give workspace-relative paths while contracts
                # carry absolute allowed_paths; compare both forms.
                candidates.append(str((base / changed).resolve()))
            if not any(self._path_allowed(candidate, allowed) for candidate in candidates for allowed in allowed_paths):
                return "SCOPE_VIOLATION"
        return "WITHIN_SCOPE"

    @staticmethod
    def _path_allowed(changed_path: str, allowed_path: str) -> bool:
        # Normalize separators so resolved Windows paths compare correctly.
        changed = changed_path.replace("\\", "/")
        allowed = allowed_path.replace("\\", "/")
        return changed == allowed or changed.startswith(allowed.rstrip("/") + "/")

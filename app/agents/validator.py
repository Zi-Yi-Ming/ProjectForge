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

        for criterion in task_contract.acceptance_criteria:
            criterion_results.append(
                CriterionResult(
                    criterion=criterion,
                    type=CriterionType.MANUAL,
                    status=CriterionStatus.NEEDS_REVIEW,
                    evidence="",
                    details="MVP does not implement automatic criterion verification.",
                )
            )
            manual_review_items.append(criterion)

        test_command = f"{sys.executable} -m pytest -q"
        command_result = self._run_command(test_command, workspace=workspace)
        test_results.append(command_result.stdout)
        evidence.append(f"test_command={test_command}")
        evidence.append(f"test_exit_code={command_result.exit_code}")
        if command_result.exit_code == 0:
            criterion_results.append(
                CriterionResult(
                    criterion="Self-test execution",
                    type=CriterionType.TEST,
                    status=CriterionStatus.PASS,
                    evidence=command_result.stdout,
                    details="Pytest command returned exit code 0.",
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

        changed_files = implementation_result.changed_files or []
        allowed_paths = task_contract.allowed_paths or []
        scope_result = self._evaluate_scope_status(changed_files, allowed_paths)
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

    def _evaluate_scope_status(self, changed_files: list[str], allowed_paths: list[str]) -> str:
        if not allowed_paths:
            return "NEEDS_REVIEW"
        for changed in changed_files:
            if not any(self._path_allowed(changed, allowed) for allowed in allowed_paths):
                return "SCOPE_VIOLATION"
        return "WITHIN_SCOPE"

    @staticmethod
    def _path_allowed(changed_path: str, allowed_path: str) -> bool:
        return changed_path == allowed_path or changed_path.startswith(allowed_path.rstrip("/") + "/")

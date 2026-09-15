from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.scope_policy import (
    NEEDS_REVIEW,
    SCOPE_MODE_ENFORCE,
    SCOPE_VIOLATION,
    WITHIN_SCOPE,
    evaluate_scope,
    path_allowed,
    resolve_scope_mode,
)
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
    def __init__(self, scope_mode: str | None = None, self_test_timeout: float = 120.0) -> None:
        # Explicit > env (PROJECTFORGE_SCOPE_MODE) > default (warn).
        self.scope_mode = resolve_scope_mode(scope_mode)
        # Self-test timeout was previously hardcoded to 120s; it is now
        # configurable so it can be aligned with the runner's --timeout budget.
        self.self_test_timeout = self_test_timeout

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
        scope_result = evaluate_scope(changed_files, allowed_paths, workspace=workspace)
        # A violation only fails the task when enforcement is on; in warn mode
        # it is recorded so real runs can be measured before it can kill work.
        scope_violation_enforced = scope_result == SCOPE_VIOLATION and self.scope_mode == SCOPE_MODE_ENFORCE
        if scope_result == WITHIN_SCOPE:
            criterion_results.append(
                CriterionResult(
                    criterion="Scope check",
                    type=CriterionType.FILE,
                    status=CriterionStatus.PASS,
                    evidence=",".join(changed_files),
                    details="Changed files are within allowed paths.",
                )
            )
        elif scope_result == NEEDS_REVIEW:
            criterion_results.append(
                CriterionResult(
                    criterion="Scope check",
                    type=CriterionType.FILE,
                    status=CriterionStatus.NEEDS_REVIEW,
                    evidence=",".join(changed_files),
                    details="No task-level paths declared; scope could not be verified.",
                )
            )
            warnings.append("Scope check requires manual review.")
        elif scope_violation_enforced:
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
        else:
            # warn mode: observe without judging. Emitting a NEEDS_REVIEW
            # criterion here would still change the task's outcome (NEEDS_REVIEW
            # blocks the task), which would defeat the point of measuring false
            # positives before switching enforcement on. The observation is
            # recorded in warnings/evidence instead.
            warnings.append(
                "Scope violation not enforced (PROJECTFORGE_SCOPE_MODE=warn): "
                + ",".join(changed_files)
            )
            evidence.append(f"scope_violation_would_be={changed_files}")

        checkpoint = getattr(implementation_result, "git_checkpoint", None)
        head_before = (checkpoint.head_before if checkpoint else "") or ""
        head_after = (checkpoint.head_after if checkpoint else "") or ""
        git_changed = list(checkpoint.changed_files or []) if checkpoint else []
        if head_before and head_after:
            # The workspace is under git: cross-check the executor's
            # self-reported changes against what git actually saw.
            if head_before == head_after:
                if changed_files:
                    criterion_results.append(
                        CriterionResult(
                            criterion="Git checkpoint",
                            type=CriterionType.GIT,
                            status=CriterionStatus.FAIL,
                            evidence=f"claimed={changed_files}",
                            details="Executor reported changed files but HEAD is unchanged.",
                        )
                    )
                    failures.append("Git checkpoint contradicts reported changes.")
                else:
                    criterion_results.append(
                        CriterionResult(
                            criterion="Git checkpoint",
                            type=CriterionType.GIT,
                            status=CriterionStatus.PASS,
                            evidence=f"{head_before[:8]}..{head_after[:8]}",
                            details="No file changes, consistent with the report.",
                        )
                    )
            else:
                criterion_results.append(
                    CriterionResult(
                        criterion="Git checkpoint",
                        type=CriterionType.GIT,
                        status=CriterionStatus.PASS,
                        evidence=f"{head_before[:8]}..{head_after[:8]} changed={len(git_changed)}",
                        details="Workspace HEAD advanced; changes are auditable in the run artifacts.",
                    )
                )
                evidence.append(f"git_changed_files={git_changed}")
        elif checkpoint is not None:
            warnings.append("Workspace is not under git version control; file changes cannot be audited.")

        status = ValidationStatus.PASS
        if any(c.status == CriterionStatus.FAIL for c in criterion_results):
            status = ValidationStatus.FAIL
        elif any(c.status == CriterionStatus.NEEDS_REVIEW for c in criterion_results):
            status = ValidationStatus.NEEDS_REVIEW
        if scope_violation_enforced:
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
            validated_at=datetime.now(timezone.utc).isoformat(),
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
        # Default pytest invocation is passed as a safe argv list (no
        # tokenization needed, and it sidesteps spaced-python-path issues on
        # Windows). A custom test_command from the contract is a string and is
        # tokenized without a shell by _run_command.
        if task_contract.test_command:
            resolved_command: str | list[str] = task_contract.test_command
            command_result = self._run_command(task_contract.test_command, workspace=workspace)
        else:
            resolved_command = [sys.executable, "-m", "pytest", "-q"]
            command_result = self._run_command(resolved_command, workspace=workspace)
        test_results.append(command_result.stdout)
        evidence.append(f"test_command={resolved_command}")
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

    @staticmethod
    def _tokenize_command(command: str) -> list[str]:
        # P19 explicitly forbids shell injection, so a test command sourced from
        # the LLM planner must never reach a shell. Tokenize into argv; shell
        # metacharacters (";", "&&", "|"...) become literal arguments instead of
        # being executed. posix=True is required for correct quote removal
        # (otherwise "python -c \"...\"" keeps the quotes and silently no-ops).
        return shlex.split(command, posix=True)

    def _run_command(self, command: str | list[str], workspace: Path | None = None) -> _CommandResult:
        args = command if isinstance(command, list) else self._tokenize_command(command)
        try:
            proc = subprocess.run(
                args,
                shell=False,
                cwd=str(workspace or Path(".")),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.self_test_timeout,
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
        """Deprecated shim: the policy lives in app.agents.scope_policy."""
        return evaluate_scope(changed_files, allowed_paths, workspace=workspace)

    @staticmethod
    def _path_allowed(changed_path: str, allowed_path: str) -> bool:
        """Deprecated shim: the policy lives in app.agents.scope_policy."""
        return path_allowed(changed_path, allowed_path)

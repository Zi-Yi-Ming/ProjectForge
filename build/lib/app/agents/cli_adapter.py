from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.agents.coding_agent import CodingAgentAdapter
from app.agents.sandbox_policy import SandboxUnavailableError, SandboxPolicy
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)


@dataclass
class _CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str


class CliAgentAdapter(CodingAgentAdapter):
    """Template for executors that drive a CLI coding agent inside a workspace.

    Subclasses provide the binary lookup, argv construction and agent name.
    This class owns workspace validation, the retry loop, timeout/exit-code
    to result mapping, git checkpoints and scope evaluation.
    """

    def __init__(
        self,
        workspace: Path | None = None,
        timeout_seconds: int = 900,
        sandbox_policy: SandboxPolicy | None = None,
        max_iterations: int = 3,
    ) -> None:
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds
        self.max_iterations = max_iterations
        self.sandbox_policy = sandbox_policy
        self.agent_binary = self.find_binary()

    def agent_name(self) -> str:
        raise NotImplementedError

    def find_binary(self) -> str:
        raise NotImplementedError

    def build_argv(self, prompt: str) -> list[str]:
        raise NotImplementedError

    def execute(
        self,
        task_contract: TaskContract,
        project_map: ProjectMap,
    ) -> AgentExecutionResult:
        started_at = self._now()
        result = self._run(task_contract, project_map)
        finished_at = self._now()
        result.started_at = started_at
        result.finished_at = finished_at
        result.task_id = task_contract.task_id
        result.agent = self.agent_name()
        return result

    def _run(
        self,
        task_contract: TaskContract,
        project_map: ProjectMap,
    ) -> AgentExecutionResult:
        if self.workspace is None or not self.workspace.exists() or not self.workspace.is_dir():
            return AgentExecutionResult(
                task_id=task_contract.task_id,
                agent=self.agent_name(),
                status=ExecutionStatus.ERROR,
                iterations=0,
                changed_files=[],
                scope_status=ScopeStatus.NEEDS_REVIEW,
                test_results=[],
                summary="",
                errors=[f"Workspace not found: {self.workspace}"],
                blocking_reason="Workspace not found",
                git_checkpoint=GitCheckpoint(),
            )

        workspace = self.workspace
        prompt = self._build_prompt(task_contract, project_map)
        head_before, pre_existing = self._git_checkpoint_before(workspace)

        for attempt in range(1, self.max_iterations + 1):
            result = self._run_single_attempt(
                workspace, task_contract, prompt, attempt, head_before, pre_existing
            )
            if result.status in {
                ExecutionStatus.IMPLEMENTED,
                ExecutionStatus.BLOCKED,
                ExecutionStatus.ERROR,
                ExecutionStatus.TIMEOUT,
            }:
                return result
            if attempt == self.max_iterations:
                result.iterations = attempt
                result.status = ExecutionStatus.FAILED
                return result
        raise AssertionError("unreachable")

    def _run_single_attempt(
        self,
        workspace: Path,
        task_contract: TaskContract,
        prompt: str,
        attempt: int,
        head_before: str,
        pre_existing: list[str],
    ) -> AgentExecutionResult:
        argv = self.build_argv(prompt)

        try:
            cmd = self._sandboxed_command(workspace, argv)
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
            )
            stdout = proc.stdout.decode("utf-8", errors="replace")
            stderr = proc.stderr.decode("utf-8", errors="replace")
            return_code = proc.returncode
        except subprocess.TimeoutExpired:
            return AgentExecutionResult(
                task_id=task_contract.task_id,
                agent=self.agent_name(),
                status=ExecutionStatus.TIMEOUT,
                iterations=attempt,
                changed_files=[],
                scope_status=ScopeStatus.NEEDS_REVIEW,
                test_results=[],
                summary="",
                errors=[f"{self.agent_name()} execution exceeded timeout"],
                blocking_reason=f"{self.agent_name()} execution exceeded timeout",
                git_checkpoint=GitCheckpoint(
                    head_before=head_before,
                    pre_existing_changes=pre_existing,
                ),
            )
        except SandboxUnavailableError as exc:
            return AgentExecutionResult(
                task_id=task_contract.task_id,
                agent=self.agent_name(),
                status=ExecutionStatus.ERROR,
                iterations=attempt,
                changed_files=[],
                scope_status=ScopeStatus.NEEDS_REVIEW,
                test_results=[],
                summary="",
                errors=[str(exc)],
                blocking_reason=str(exc),
                git_checkpoint=GitCheckpoint(
                    head_before=head_before,
                    pre_existing_changes=pre_existing,
                ),
            )
        except Exception as exc:
            return AgentExecutionResult(
                task_id=task_contract.task_id,
                agent=self.agent_name(),
                status=ExecutionStatus.ERROR,
                iterations=attempt,
                changed_files=[],
                scope_status=ScopeStatus.NEEDS_REVIEW,
                test_results=[],
                summary="",
                errors=[str(exc)],
                blocking_reason=str(exc),
                git_checkpoint=GitCheckpoint(
                    head_before=head_before,
                    pre_existing_changes=pre_existing,
                ),
            )

        if return_code != 0:
            return AgentExecutionResult(
                task_id=task_contract.task_id,
                agent=self.agent_name(),
                status=ExecutionStatus.FAILED,
                iterations=attempt,
                changed_files=[],
                scope_status=ScopeStatus.NEEDS_REVIEW,
                test_results=[],
                summary=stdout[:500],
                errors=[stderr[:500]],
                blocking_reason="",
                git_checkpoint=GitCheckpoint(
                    head_before=head_before,
                    pre_existing_changes=pre_existing,
                ),
            )

        changed_files, diff_metadata, head_after = self._git_checkpoint_after(workspace)
        agent_changes = [f for f in changed_files if f not in pre_existing]
        scope_status = self._evaluate_scope_from_files(agent_changes, task_contract.allowed_paths)

        return AgentExecutionResult(
            task_id=task_contract.task_id,
            agent=self.agent_name(),
            status=ExecutionStatus.IMPLEMENTED,
            iterations=attempt,
            changed_files=agent_changes,
            scope_status=scope_status,
            test_results=[],
            summary=stdout[:500],
            errors=[],
            blocking_reason="",
            git_checkpoint=GitCheckpoint(
                head_before=head_before,
                head_after=head_after,
                changed_files=agent_changes,
                diff_metadata=diff_metadata,
                pre_existing_changes=pre_existing,
            ),
        )

    def _sandboxed_command(self, workspace: Path, argv: list[str]) -> list[str]:
        if self.sandbox_policy is None:
            return list(argv)
        return self.sandbox_policy.wrap(workspace, argv)

    def _build_prompt(self, task_contract: TaskContract, project_map: ProjectMap) -> str:
        contract = task_contract
        parts = [
            f"You are executing Task {contract.task_id}: {contract.title}",
            f"Goal: {contract.goal}",
            f"Why: {contract.why}",
            "Project Map:",
            f"- architecture_style: {project_map.architecture_style}",
            f"- services: {', '.join(project_map.services)}",
            f"- modules: {', '.join(project_map.modules)}",
            f"- technology_stack: {', '.join(project_map.technology_stack)}",
            "Acceptance Criteria:",
        ]
        for idx, item in enumerate(contract.acceptance_criteria, start=1):
            parts.append(f"{idx}. {item}")
        parts.append("Out of Scope:")
        for item in contract.out_of_scope:
            parts.append(f"- {item}")
        parts.append("Allowed Paths:")
        for item in contract.allowed_paths:
            parts.append(f"- {item}")
        if contract.test_paths:
            parts.append("Test Paths (place deliverable tests here):")
            for item in contract.test_paths:
                parts.append(f"- {item}")
        parts.append("Execution Rules:")
        for item in contract.execution_rules:
            parts.append(f"- {item}")
        return "\n".join(parts)

    def _git_checkpoint_before(self, workspace: Path) -> tuple[str, list[str]]:
        head = self._run_git(["rev-parse", "HEAD"], workspace)
        status = self._run_git(["status", "--short"], workspace)
        files = [line.strip() for line in status.stdout.splitlines() if line.strip()]
        return head.stdout.strip(), files

    def _git_checkpoint_after(self, workspace: Path) -> tuple[list[str], str, str]:
        head = self._run_git(["rev-parse", "HEAD"], workspace)
        status = self._run_git(["status", "--short"], workspace)
        files = [line.strip() for line in status.stdout.splitlines() if line.strip()]
        diff_stat = self._run_git(["diff", "--stat"], workspace).stdout.strip()
        return files, diff_stat, head.stdout.strip()

    def _run_git(self, args: list[str], workspace: Path) -> _CommandResult:
        cmd = ["git"] + args
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(workspace),
                timeout=30,
            )
            return _CommandResult(
                command=" ".join(cmd),
                exit_code=proc.returncode,
                stdout=proc.stdout.decode("utf-8", errors="replace"),
                stderr=proc.stderr.decode("utf-8", errors="replace"),
            )
        except Exception as exc:
            return _CommandResult(
                command=" ".join(cmd),
                exit_code=-1,
                stdout="",
                stderr=str(exc),
            )

    def _evaluate_scope_from_files(self, changed_files: list[str], allowed_paths: list[str]) -> ScopeStatus:
        if not allowed_paths:
            return ScopeStatus.NEEDS_REVIEW
        base = self.workspace.resolve() if self.workspace is not None else None
        for changed in changed_files:
            candidates = [changed]
            if base is not None:
                # Reporters give workspace-relative paths while contracts
                # carry absolute allowed_paths; compare both forms.
                candidates.append(str((base / changed).resolve()))
            if not any(self._path_allowed(candidate, allowed) for candidate in candidates for allowed in allowed_paths):
                return ScopeStatus.SCOPE_VIOLATION
        return ScopeStatus.WITHIN_SCOPE

    @staticmethod
    def _path_allowed(changed_path: str, allowed_path: str) -> bool:
        # Normalize separators so resolved Windows paths compare correctly.
        changed = changed_path.replace("\\", "/")
        allowed = allowed_path.replace("\\", "/")
        return changed == allowed or changed.startswith(allowed.rstrip("/") + "/")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

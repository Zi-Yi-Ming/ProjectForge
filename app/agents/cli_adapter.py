from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.agents.coding_agent import CodingAgentAdapter
from app.agents.sandbox_policy import SandboxUnavailableError, SandboxPolicy
from app.agents.workspace_provider import FixedWorkspaceProvider, WorkspaceProvider
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
        workspace_provider: WorkspaceProvider | None = None,
    ) -> None:
        self.workspace = workspace
        # Single source of truth for where a task runs. It defaults to the fixed
        # shared workspace, so the serial path is byte-for-byte unchanged; a
        # parallel run swaps in a provider that hands back a per-branch worktree.
        self.workspace_provider = workspace_provider or FixedWorkspaceProvider(workspace)
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
        workspace = self.workspace_provider.workspace_for(task_contract)
        if workspace is None or not workspace.exists() or not workspace.is_dir():
            return AgentExecutionResult(
                task_id=task_contract.task_id,
                agent=self.agent_name(),
                status=ExecutionStatus.ERROR,
                iterations=0,
                changed_files=[],
                scope_status=ScopeStatus.NEEDS_REVIEW,
                test_results=[],
                summary="",
                errors=[f"Workspace not found: {workspace}"],
                blocking_reason="Workspace not found",
                git_checkpoint=GitCheckpoint(),
            )

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

        self._commit_task_changes(workspace, task_contract.task_id)
        changed_files, diff_metadata, head_after = self._git_checkpoint_after(workspace, head_before)
        agent_changes = [f for f in changed_files if f not in pre_existing]
        scope_status = self._evaluate_scope_from_files(agent_changes, task_contract.allowed_paths, workspace=workspace)

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
        if not self._workspace_owns_repo(workspace):
            return "", []
        head = self._run_git(["rev-parse", "HEAD"], workspace)
        status = self._run_git(["status", "--short"], workspace)
        files = [line.strip() for line in status.stdout.splitlines() if line.strip()]
        return head.stdout.strip(), files

    def _commit_task_changes(self, workspace: Path, task_id: str) -> None:
        """Commit the task's working-tree changes so each task has its own
        auditable commit (HEAD movement + per-task diff). Best-effort: a
        git-less workspace simply yields an empty checkpoint.

        Guards against committing into a foreign parent repository when the
        workspace is merely nested inside one: such a commit would pollute
        the host repo and make the per-task diff span unrelated files.

        The ``artifacts`` directory is excluded: the orchestrator writes
        audit artifacts into the workspace, and sweeping them into the
        per-task commit would make each task's diff include the previous
        task's artifacts.
        """
        try:
            if not self._workspace_owns_repo(workspace):
                return
            subprocess.run(
                ["git", "add", "-A", "--", ".", ":(exclude)artifacts"],
                cwd=str(workspace), capture_output=True, timeout=60, check=True,
            )
            subprocess.run(
                ["git", "commit", "-q", "-m", f"task {task_id}", "--allow-empty"],
                cwd=str(workspace), capture_output=True, timeout=60, check=True,
            )
        except Exception:
            pass

    @staticmethod
    def _workspace_owns_repo(workspace: Path) -> bool:
        """True when the workspace is (or is inside) its own repository
        rooted at the workspace itself — not a nested path of a foreign
        parent repository."""
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            if proc.returncode != 0:
                return False
            toplevel = Path(proc.stdout.decode("utf-8", "replace").strip())
            return toplevel.resolve() == Path(workspace).resolve()
        except Exception:
            return False

    def _git_checkpoint_after(self, workspace: Path, head_before: str = "") -> tuple[list[str], str, str]:
        head_after = self._run_git(["rev-parse", "HEAD"], workspace).stdout.strip()
        if head_before and head_after:
            # Per-task commits make the diff exact: only this task's changes.
            changed = self._run_git(["diff", "--name-only", f"{head_before}..{head_after}"], workspace).stdout
            files = [line.strip() for line in changed.splitlines() if line.strip()]
            diff_stat = self._run_git(["diff", "--stat", f"{head_before}..{head_after}"], workspace).stdout.strip()
            return files, diff_stat, head_after
        status = self._run_git(["status", "--short"], workspace)
        files = [line.strip() for line in status.stdout.splitlines() if line.strip()]
        diff_stat = self._run_git(["diff", "--stat"], workspace).stdout.strip()
        return files, diff_stat, head_after

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

    def _evaluate_scope_from_files(self, changed_files: list[str], allowed_paths: list[str], workspace: Path | None = None) -> ScopeStatus:
        """Delegate to the shared policy so the adapter and the validator
        cannot drift apart on what counts as a violation."""
        from app.agents.scope_policy import evaluate_scope

        return ScopeStatus(evaluate_scope(changed_files, allowed_paths, workspace=workspace or self.workspace))

    @staticmethod
    def _path_allowed(changed_path: str, allowed_path: str) -> bool:
        """Delegate to the shared policy (kept as a public-ish shim)."""
        from app.agents.scope_policy import path_allowed

        return path_allowed(changed_path, allowed_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

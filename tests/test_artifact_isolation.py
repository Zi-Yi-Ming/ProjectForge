"""Regression tests: audit artifacts must stay out of the task checkpoint.

Bug background (2026-09-14): the orchestrator wrote artifacts into the executor
workspace (``ArtifactStore(run_dir)``), and the CLI adapter commits the whole
working tree per task (``git add -A``). Probing a two-task run showed task T2's
checkpoint diff containing ``artifacts/T1_output.json`` and
``artifacts/T1_validation.json`` — the *previous* task's artifacts. That
contradicts the adapter's own contract ("per-task commits make the diff exact:
only this task's changes") and corrupts the audit trail the git checkpoint
feature exists to provide.

Two layers of fix are covered here:
1. ``ExecutionOrchestrator`` honours ``artifacts_root``, storing artifacts under
   ``runs/<run_id>/artifacts`` (the layout documented in docs/architecture.md).
2. ``CliAgentAdapter._commit_task_changes`` excludes ``artifacts`` from the
   per-task commit, so no workspace layout can leak them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.agents.cli_adapter import CliAgentAdapter
from app.agents.persistence import JsonExecutionPersistence
from app.agents.orchestrator import ExecutionOrchestrator
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus as ImplStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)
from app.schemas.task import Task, TaskGraph, TaskStatus


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60
    )


class _CommittingAdapter(CliAgentAdapter):
    """Mimics the real CLI adapter: writes a file, then commits the task."""

    def agent_name(self) -> str:
        return "probe"

    def find_binary(self) -> str:
        return "probe"

    def build_argv(self, prompt: str) -> list[str]:
        return []

    def _run(self, task_contract: TaskContract, project_map: ProjectMap) -> AgentExecutionResult:
        ws = self.workspace
        assert ws is not None
        (ws / f"{task_contract.task_id}_work.py").write_text(f"# {task_contract.task_id}\n", encoding="utf-8")
        head_before, pre_existing = self._git_checkpoint_before(ws)
        self._commit_task_changes(ws, task_contract.task_id)
        changed, _stat, head_after = self._git_checkpoint_after(ws, head_before)
        return AgentExecutionResult(
            task_id=task_contract.task_id,
            agent="probe",
            status=ImplStatus.IMPLEMENTED,
            iterations=1,
            changed_files=[f for f in changed if f not in pre_existing],
            scope_status=ScopeStatus.WITHIN_SCOPE,
            test_results=[],
            summary="probe",
            errors=[],
            blocking_reason="",
            git_checkpoint=GitCheckpoint(
                head_before=head_before, head_after=head_after, changed_files=changed
            ),
        )


def _two_task_graph() -> TaskGraph:
    def task(task_id: str, deps: list[str]) -> Task:
        return Task(
            id=task_id, phase_id="P1", title=task_id, goal="g", why="w", dependencies=deps,
            status=TaskStatus.PENDING, scope="Core", acceptance_criteria=[], out_of_scope=[],
            interview_points=[], test_paths=[],
        )

    return TaskGraph(
        project="proj",
        tasks=[task("T1", []), task("T2", ["T1"])],
        total_tasks=2, required_tasks=2, optional_tasks=0,
    )


def test_artifacts_go_to_runs_dir_not_workspace(tmp_path: Path) -> None:
    """With artifacts_root set, artifacts live under runs/<run_id>/artifacts."""
    workspace = tmp_path / "workspaces" / "proj"
    workspace.mkdir(parents=True)
    persistence = JsonExecutionPersistence(base_dir=tmp_path)

    orchestrator = ExecutionOrchestrator(
        adapter=_CommittingAdapter(workspace=workspace),
        persistence=persistence,
        artifacts_root=tmp_path / "runs",
    )
    run = orchestrator.run(_two_task_graph(), ProjectMap(), run_dir=workspace, run_id="run-art")

    assert run.status.value == "COMPLETED"
    assert (tmp_path / "runs" / "run-art" / "artifacts").is_dir()
    assert not (workspace / "artifacts").exists()


def test_no_artifacts_leak_into_any_task_checkpoint(tmp_path: Path) -> None:
    """The regression: T2's diff must not contain T1's artifacts."""
    workspace = tmp_path / "workspaces" / "proj"
    workspace.mkdir(parents=True)
    persistence = JsonExecutionPersistence(base_dir=tmp_path)

    orchestrator = ExecutionOrchestrator(
        adapter=_CommittingAdapter(workspace=workspace),
        persistence=persistence,
        artifacts_root=tmp_path / "runs",
    )
    orchestrator.run(_two_task_graph(), ProjectMap(), run_dir=workspace, run_id="run-leak")

    tracked = _git(["ls-files"], workspace).stdout.decode().split()
    assert tracked, "the workspace should have committed the task files"
    assert not any("artifacts" in path for path in tracked)

    # Walk every commit: none may contain an artifacts path.
    log = _git(["log", "--format=%H"], workspace).stdout.decode().split()
    for commit in log:
        names = _git(["show", "--name-only", "--format=", commit], workspace).stdout.decode()
        assert "artifacts" not in names


def test_adapter_commit_excludes_artifacts_directory(tmp_path: Path) -> None:
    """Second layer: even with artifacts inside the workspace, the per-task
    commit must not sweep them in."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _git(["init", "-q"], workspace)
    _git(["config", "user.email", "t@local"], workspace)
    _git(["config", "user.name", "T"], workspace)
    (workspace / "src.py").write_text("x = 1\n", encoding="utf-8")
    _git(["add", "-A"], workspace)
    _git(["commit", "-q", "-m", "baseline"], workspace)

    # Orchestrator-style artifacts written into the workspace.
    artifacts = workspace / "artifacts"
    artifacts.mkdir()
    (artifacts / "T1_output.json").write_text('{"t":"T1"}\n', encoding="utf-8")
    (artifacts / "T1_validation.json").write_text('{"s":"PASS"}\n', encoding="utf-8")

    adapter = _CommittingAdapter(workspace=workspace)
    (workspace / "src.py").write_text("x = 2\n", encoding="utf-8")
    adapter._commit_task_changes(workspace, "T2")

    diff = _git(["diff", "--name-only", "HEAD~1..HEAD"], workspace).stdout.decode()
    assert "artifacts" not in diff
    assert "src.py" in diff

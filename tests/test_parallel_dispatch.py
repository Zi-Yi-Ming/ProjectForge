from __future__ import annotations

import subprocess
from pathlib import Path

from app.agents.coding_agent import CodingAgentAdapter
from app.agents.mock_executor import MockExecutor
from app.agents.orchestrator import ExecutionOrchestrator
from app.schemas.execution import ExecutionRun, ExecutionStatus
from app.schemas.implementation import AgentExecutionResult, ProjectMap, TaskContract
from app.schemas.task import Task, TaskGraph, TaskStatus


def _task(tid: str, deps: list[str]) -> Task:
    return Task(
        id=tid, phase_id="P1", title=tid, goal=f"g-{tid}", why=f"w-{tid}",
        dependencies=deps, scope="Core", status=TaskStatus.PENDING,
        acceptance_criteria=[f"{tid} works"], out_of_scope=[], interview_points=[],
        test_paths=["tests"],
    )


def _graph_independent_with_dependent() -> TaskGraph:
    tasks = [_task("T1", []), _task("T2", []), _task("T3", ["T1", "T2"])]
    return TaskGraph(project="demo", tasks=tasks, total_tasks=3, required_tasks=3, optional_tasks=0)


def _graph_two_independent() -> TaskGraph:
    tasks = [_task("T1", []), _task("T2", [])]
    return TaskGraph(project="demo", tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


class _BranchCommittingExecutor(MockExecutor):
    """MockExecutor that commits inside the provider-resolved worktree, mirroring
    what the real CLI adapters do so a parallel merge actually carries files."""

    def __init__(self, *args, shared_file: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._shared_file = shared_file

    def execute(self, task_contract, project_map):
        result = super().execute(task_contract, project_map)
        ws = self.workspace_provider.workspace_for(task_contract)
        if ws is not None and (ws / ".git").exists():
            if self._shared_file:
                (ws / "shared.txt").write_text(f"content from {task_contract.task_id}\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=str(ws), check=True)
            subprocess.run(["git", "commit", "-q", "-m", f"task {task_contract.task_id}", "--allow-empty"], cwd=str(ws), check=True)
        return result


class _NoProviderExecutor(CodingAgentAdapter):
    def execute(self, task_contract, project_map) -> AgentExecutionResult:  # pragma: no cover
        raise NotImplementedError


def _status_of(run, tid: str) -> TaskStatus:
    return next(r for r in run.task_results if r.task_id == tid).status  # type: ignore[attr-defined]


def test_parallel_wave_merges_back_and_feeds_serial_dependent(tmp_path: Path) -> None:
    run_dir = tmp_path / "ws"
    run_dir.mkdir(parents=True)
    orch = ExecutionOrchestrator(
        adapter=_BranchCommittingExecutor(workspace=run_dir),
        parallel_enabled=True,
    )
    graph = _graph_independent_with_dependent()
    run = orch.run(graph, ProjectMap(), run_dir=run_dir)

    assert run.status == ExecutionStatus.COMPLETED
    assert all(t.status == TaskStatus.DONE for t in graph.tasks)
    # T1/T2 ran concurrently on branches; their files merged back to the main tree.
    assert (run_dir / "t1_impl.txt").exists()
    assert (run_dir / "t2_impl.txt").exists()
    # T3 (dependent, wave size 1) ran serially and still saw the merged results.
    assert (run_dir / "t3_impl.txt").exists()


def test_parallel_merge_conflict_fails_only_the_conflicting_task(tmp_path: Path) -> None:
    run_dir = tmp_path / "ws"
    run_dir.mkdir(parents=True)
    # Pre-existing file so both branches modify it -> a content conflict on merge.
    (run_dir / "shared.txt").write_text("baseline\n", encoding="utf-8")

    orch = ExecutionOrchestrator(
        adapter=_BranchCommittingExecutor(workspace=run_dir, shared_file=True),
        parallel_enabled=True,
    )
    graph = _graph_two_independent()
    run = orch.run(graph, ProjectMap(), run_dir=run_dir)

    statuses = {r.task_id: r.status for r in run.task_results}
    assert set(statuses.values()) == {TaskStatus.DONE.value, TaskStatus.FAILED.value}
    # The merged (winning) task owns the tree; the loser never left half-merged state.
    assert (run_dir / "shared.txt").read_text(encoding="utf-8") in {"content from T1\n", "content from T2\n"}
    # No stray conflict markers and no leaked worktree branches.
    branches = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=str(run_dir), capture_output=True, text=True).stdout
    assert not [b for b in branches.splitlines() if b.startswith("pf/")]


def test_serial_path_unchanged_when_parallel_disabled(tmp_path: Path) -> None:
    run_dir = tmp_path / "ws"
    run_dir.mkdir(parents=True)
    orch = ExecutionOrchestrator(adapter=_BranchCommittingExecutor(workspace=run_dir), parallel_enabled=False)
    graph = _graph_independent_with_dependent()
    run = orch.run(graph, ProjectMap(), run_dir=run_dir)
    assert run.status == ExecutionStatus.COMPLETED
    assert all(t.status == TaskStatus.DONE for t in graph.tasks)


def test_wave_parallel_declines_without_run_dir() -> None:
    orch = ExecutionOrchestrator(adapter=_BranchCommittingExecutor(workspace=None), parallel_enabled=True)
    run = ExecutionRun(run_id="r1", project="demo", status=ExecutionStatus.RUNNING, total_tasks=2, started_at="")
    graph = _graph_two_independent()
    handled = orch._run_wave_parallel(run, graph.tasks, graph, ProjectMap(), None, None)
    assert handled is False


def test_wave_parallel_declines_when_adapter_has_no_provider(tmp_path: Path) -> None:
    run_dir = tmp_path / "ws"
    (run_dir / ".git").mkdir(parents=True)  # make run_dir look like a repo dir
    orch = ExecutionOrchestrator(adapter=_NoProviderExecutor(), parallel_enabled=True)
    run = ExecutionRun(run_id="r1", project="demo", status=ExecutionStatus.RUNNING, total_tasks=2, started_at="")
    graph = _graph_two_independent()
    assert orch._run_wave_parallel(run, graph.tasks, graph, ProjectMap(), run_dir, None) is False

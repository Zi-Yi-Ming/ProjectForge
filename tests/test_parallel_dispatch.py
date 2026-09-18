from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.agents.artifact_store import ArtifactStore
from app.agents.coding_agent import CodingAgentAdapter
from app.agents.mock_executor import MockExecutor
from app.agents.orchestrator import ExecutionOrchestrator
from app.schemas.execution import ExecutionRun, ExecutionStatus
from app.schemas.implementation import AgentExecutionResult, GitCheckpoint, ProjectMap, TaskContract
from app.schemas.task import Task, TaskGraph, TaskStatus
from app.schemas.validation import CriterionResult, CriterionStatus, CriterionType, ValidationResult, ValidationStatus


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
    """MockExecutor that commits inside the provider-resolved worktree and reports
    a real git checkpoint, mirroring the CLI adapters so a parallel merge actually
    carries files and produces GIT_CHECKPOINT artifacts."""

    def __init__(self, *args, shared_file: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._shared_file = shared_file

    def _git(self, ws: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=str(ws), capture_output=True, text=True
        ).stdout.strip()

    def execute(self, task_contract, project_map):
        ws = self.workspace_provider.workspace_for(task_contract)
        has_repo = ws is not None and (ws / ".git").exists()
        head_before = self._git(ws, "rev-parse", "HEAD") if has_repo else ""
        result = super().execute(task_contract, project_map)
        if has_repo:
            if self._shared_file:
                (ws / "shared.txt").write_text(f"content from {task_contract.task_id}\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=str(ws), check=True)
            subprocess.run(["git", "commit", "-q", "-m", f"task {task_contract.task_id}", "--allow-empty"], cwd=str(ws), check=True)
            head_after = self._git(ws, "rev-parse", "HEAD")
            changed = [c for c in self._git(ws, "diff", "--name-only", f"{head_before}..{head_after}").splitlines() if c.strip()]
            result.git_checkpoint = GitCheckpoint(
                head_before=head_before, head_after=head_after, changed_files=changed,
                diff_metadata=f"{len(changed)} files",
            )
        return result


class _NoProviderExecutor(CodingAgentAdapter):
    def execute(self, task_contract, project_map) -> AgentExecutionResult:  # pragma: no cover
        raise NotImplementedError


def _conflict_result(orch: ExecutionOrchestrator, files: list[str]):
    from app.schemas.validation import ValidationResult
    return orch._merge_conflict_result(ValidationResult(task_id="T2", status=ValidationStatus.PASS), "T2", files)


def test_parallel_wave_merges_back_and_feeds_serial_dependent(tmp_path: Path) -> None:
    run_dir = tmp_path / "ws"
    run_dir.mkdir(parents=True)
    orch = ExecutionOrchestrator(
        adapter=_BranchCommittingExecutor(workspace=run_dir), parallel_enabled=True
    )
    graph = _graph_independent_with_dependent()
    run = orch.run(graph, ProjectMap(), run_dir=run_dir)

    assert run.status == ExecutionStatus.COMPLETED
    assert all(t.status == TaskStatus.DONE for t in graph.tasks)
    assert (run_dir / "t1_impl.txt").exists()
    assert (run_dir / "t2_impl.txt").exists()
    assert (run_dir / "t3_impl.txt").exists()  # serial dependent saw the merged results


def test_parallel_done_writes_git_checkpoint_artifact(tmp_path: Path) -> None:
    run_dir = tmp_path / "ws"
    run_dir.mkdir(parents=True)
    store = ArtifactStore(tmp_path / "art")
    orch = ExecutionOrchestrator(
        adapter=_BranchCommittingExecutor(workspace=run_dir), artifact_store=store, parallel_enabled=True
    )
    orch.run(_graph_independent_with_dependent(), ProjectMap(), run_dir=run_dir)

    git_artifacts = list(store.artifacts_dir.glob("*_git_*.json"))
    assert git_artifacts, "merged DONE tasks should emit a GIT_CHECKPOINT artifact"
    data = json.loads(git_artifacts[0].read_text(encoding="utf-8"))
    assert data.get("head_before") and data.get("head_after")
    assert data.get("head_before") != data.get("head_after")


def test_parallel_merge_conflict_fails_only_the_conflicting_task(tmp_path: Path) -> None:
    run_dir = tmp_path / "ws"
    run_dir.mkdir(parents=True)
    (run_dir / "shared.txt").write_text("baseline\n", encoding="utf-8")

    orch = ExecutionOrchestrator(
        adapter=_BranchCommittingExecutor(workspace=run_dir, shared_file=True), parallel_enabled=True
    )
    graph = _graph_two_independent()
    run = orch.run(graph, ProjectMap(), run_dir=run_dir)

    statuses = {r.task_id: r.status for r in run.task_results}
    assert set(statuses.values()) == {TaskStatus.DONE.value, TaskStatus.FAILED.value}
    assert (run_dir / "shared.txt").read_text(encoding="utf-8") in {"content from T1\n", "content from T2\n"}

    failed_record = next(r for r in run.task_results if r.status == TaskStatus.FAILED.value)
    vr = failed_record.validation_result
    assert vr.status == ValidationStatus.FAIL
    conflict_criteria = [
        c for c in vr.criterion_results
        if c.type == CriterionType.GIT and c.status == CriterionStatus.FAIL and "conflict" in c.evidence
    ]
    assert conflict_criteria, "the failed record must carry a GIT/FAIL merge-conflict criterion"
    assert "shared.txt" in vr.changed_files

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


def test_merge_conflict_result_from_scratch() -> None:
    orch = ExecutionOrchestrator(adapter=_NoProviderExecutor(), parallel_enabled=True)
    from app.schemas.validation import ValidationResult
    result = orch._merge_conflict_result(None, "T9", ["a.py", "b.py"])
    assert result.status == ValidationStatus.FAIL
    assert result.task_id == "T9"
    assert any(c.type == CriterionType.GIT and c.status == CriterionStatus.FAIL for c in result.criterion_results)
    assert set(result.changed_files) >= {"a.py", "b.py"}
    assert result.failures and "a.py" in result.failures[0]


def test_merge_conflict_result_preserves_base_and_does_not_mutate() -> None:
    from app.schemas.validation import CriterionResult, ValidationResult
    base = ValidationResult(
        task_id="T2", status=ValidationStatus.PASS,
        criterion_results=[CriterionResult(criterion="tests", type=CriterionType.TEST, status=CriterionStatus.PASS)],
    )
    orch = ExecutionOrchestrator(adapter=_NoProviderExecutor(), parallel_enabled=True)
    result = orch._merge_conflict_result(base, "T2", ["conflict.txt"])
    assert result.status == ValidationStatus.FAIL
    assert len(result.criterion_results) == 2  # original TEST criterion kept + conflict GIT appended
    # deep copy: the base is untouched
    assert base.status == ValidationStatus.PASS
    assert len(base.criterion_results) == 1


def test_wave_parallel_declines_without_run_dir() -> None:
    orch = ExecutionOrchestrator(adapter=_BranchCommittingExecutor(workspace=None), parallel_enabled=True)
    run = ExecutionRun(run_id="r1", project="demo", status=ExecutionStatus.RUNNING, total_tasks=2, started_at="")
    graph = _graph_two_independent()
    assert orch._run_wave_parallel(run, graph.tasks, graph, ProjectMap(), None, None) is False


def test_wave_parallel_declines_when_adapter_has_no_provider(tmp_path: Path) -> None:
    run_dir = tmp_path / "ws"
    (run_dir / ".git").mkdir(parents=True)
    orch = ExecutionOrchestrator(adapter=_NoProviderExecutor(), parallel_enabled=True)
    run = ExecutionRun(run_id="r1", project="demo", status=ExecutionStatus.RUNNING, total_tasks=2, started_at="")
    graph = _graph_two_independent()
    assert orch._run_wave_parallel(run, graph.tasks, graph, ProjectMap(), run_dir, None) is False


class _PassthroughAggregation:
    def aggregate(self, contract, execution_result, deterministic):
        return deterministic, None


class _IntegrationFailingValidator:
    """PASS for an isolated worktree; FAIL when asked to validate the integrated
    run_dir — simulating a sibling's merge breaking the combined tree."""

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = Path(run_dir).resolve()

    def validate(self, task_id, contract, execution_result, workspace=None):
        ws = Path(workspace).resolve() if workspace else None
        if ws is not None and ws == self._run_dir:
            return ValidationResult(
                task_id=task_id, status=ValidationStatus.FAIL,
                failures=["integrated test suite failed after merge"],
                changed_files=[f"integration_{task_id}.py"],
            )
        return ValidationResult(task_id=task_id, status=ValidationStatus.PASS)


def test_post_merge_revalidation_fails_merged_tasks(tmp_path: Path) -> None:
    run_dir = tmp_path / "ws"
    run_dir.mkdir(parents=True)
    store = ArtifactStore(tmp_path / "art")
    orch = ExecutionOrchestrator(
        adapter=_BranchCommittingExecutor(workspace=run_dir),
        validator=_IntegrationFailingValidator(run_dir),
        aggregation=_PassthroughAggregation(),
        artifact_store=store,
        parallel_enabled=True,
    )
    run = orch.run(_graph_two_independent(), ProjectMap(), run_dir=run_dir)

    # each task passed in isolation, but the integrated re-validation failed
    assert run.task_results
    for rec in run.task_results:
        assert rec.status == TaskStatus.FAILED.value
        integration_criteria = [
            c
            for c in (rec.validation_result.criterion_results or [])
            if c.type == CriterionType.TEST
            and c.status == CriterionStatus.FAIL
            and "integrated" in c.evidence
        ]
        assert integration_criteria, "merged task must carry a post-merge integration criterion"
    assert list(store.artifacts_dir.glob("*_integration_*")), "a POST_MERGE_INTEGRATION_FAIL artifact is written"


def test_post_merge_integration_result_from_scratch() -> None:
    orch = ExecutionOrchestrator(adapter=_NoProviderExecutor(), parallel_enabled=True)
    integrated = ValidationResult(
        task_id="T9", status=ValidationStatus.FAIL, failures=["boom"], changed_files=["x.py"]
    )
    result = orch._post_merge_integration_result(None, "T9", integrated)
    assert result.status == ValidationStatus.FAIL
    assert result.task_id == "T9"
    assert any(
        c.type == CriterionType.TEST and c.status == CriterionStatus.FAIL and "integrated" in c.evidence
        for c in result.criterion_results
    )
    assert "x.py" in result.changed_files


def test_post_merge_integration_result_preserves_base_without_mutating() -> None:
    base = ValidationResult(
        task_id="T2", status=ValidationStatus.PASS,
        criterion_results=[CriterionResult(criterion="tests", type=CriterionType.TEST, status=CriterionStatus.PASS)],
    )
    orch = ExecutionOrchestrator(adapter=_NoProviderExecutor(), parallel_enabled=True)
    integrated = ValidationResult(task_id="T2", status=ValidationStatus.FAIL, failures=["nope"])
    result = orch._post_merge_integration_result(base, "T2", integrated)
    assert result.status == ValidationStatus.FAIL
    assert len(result.criterion_results) == 2  # isolation-passed TEST kept + integration FAIL appended
    assert base.status == ValidationStatus.PASS  # deep copy: base untouched
    assert len(base.criterion_results) == 1

from __future__ import annotations

from pathlib import Path

from app.agents.parallel_orchestrator import ParallelExecutionOrchestrator
from app.agents.worker import Worker
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus as ImplExecutionStatus,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)
from app.schemas.task import Task, TaskGraph, TaskStatus


def _project_map():
    return ProjectMap(
        architecture_style="layered",
        services=["api"],
        modules=["app"],
        data_flow="api -> service",
        technology_stack=["python"],
        infrastructure=[],
    )


def _passed(task_id):
    return AgentExecutionResult(
        task_id=task_id,
        agent="mock",
        status=ImplExecutionStatus.IMPLEMENTED,
        iterations=1,
        changed_files=[],
        scope_status=ScopeStatus.WITHIN_SCOPE,
        test_results=[],
        summary="ok",
        errors=[],
        blocking_reason="",
    )


class FakeAdapter:
    def __init__(self, outcomes):
        self.outcomes = outcomes

    def execute(self, task_contract: TaskContract, project_map: ProjectMap):
        return self.outcomes[task_contract.task_id]


class FakeValidator:
    def validate(self, *args, **kwargs):
        from app.schemas.validation import ValidationResult, ValidationStatus
        return ValidationResult(
            task_id=args[0] if args else kwargs.get("task_id", ""),
            status=ValidationStatus.PASS,
            criterion_results=[],
            test_results=[],
            scope_result="WITHIN_SCOPE",
            changed_files=[],
            evidence=[],
            failures=[],
            warnings=[],
            manual_review_items=[],
            llm_review=None,
            repair_cycle=0,
            validated_at="",
        )


def test_each_worker_gets_own_workspace(tmp_path: Path) -> None:
    seen: dict[str, Path] = {}

    class TrackingAdapter:
        def execute(self, task_contract: TaskContract, project_map: ProjectMap):
            worker = Worker(adapter=self, workspace_factory=lambda task_id: tmp_path / "workspaces" / task_id)
            seen[task_contract.task_id] = worker._workspace_for(task_contract.task_id)
            return _passed(task_contract.task_id)

    graph = TaskGraph(
        project="demo",
        tasks=[
            Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], status=TaskStatus.READY, acceptance_criteria=[], out_of_scope=[], implementation_scope="core"),
            Task(id="T2", phase_id="P1", title="T2", goal="g", why="w", dependencies=[], status=TaskStatus.READY, acceptance_criteria=[], out_of_scope=[], implementation_scope="core"),
        ],
    )
    orchestrator = ParallelExecutionOrchestrator(
        adapter=TrackingAdapter(),
        project_map=_project_map(),
        base_dir=tmp_path,
        max_workers=2,
        validator=FakeValidator(),
        workspace_factory=lambda task_id: tmp_path / "workspaces" / task_id,
    )
    run = orchestrator.run(graph, "run-ws", tmp_path / "runs" / "run-ws")
    assert run.status.value == "COMPLETED"
    assert set(run.completed_tasks) >= {"T1", "T2"}
    assert seen["T1"] != seen["T2"]
    assert seen["T1"] == tmp_path / "workspaces" / "T1"
    assert seen["T2"] == tmp_path / "workspaces" / "T2"

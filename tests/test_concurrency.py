from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.parallel_orchestrator import ParallelExecutionOrchestrator
from app.agents.worker import WorkerResult
from app.agents.worker_pool import WorkerPool
from app.schemas.execution import ExecutionRun, ExecutionStatus
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus as ImplExecutionStatus,
    ProjectMap,
    ScopeStatus,
)
from app.schemas.task import Task, TaskGraph, TaskStatus


class MockAdapter:
    def __init__(self, outcomes):
        self.outcomes = outcomes

    def execute(self, task_contract, project_map):
        return self.outcomes[task_contract.task_id]


def _project_map() -> ProjectMap:
    return ProjectMap(
        architecture_style="layered",
        services=["api"],
        modules=["app"],
        data_flow="api -> service",
        technology_stack=["python"],
        infrastructure=[],
    )


def test_same_task_not_dispatched_twice() -> None:
    graph = TaskGraph(
        project="demo",
        tasks=[
            Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], status=TaskStatus.READY, acceptance_criteria=[], out_of_scope=[], implementation_scope="core"),
            Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], status=TaskStatus.READY, acceptance_criteria=[], out_of_scope=[], implementation_scope="core"),
        ],
    )
    outcomes = {
        "T1": AgentExecutionResult(task_id="T1", agent="mock", status=ImplExecutionStatus.IMPLEMENTED, iterations=1, changed_files=[], scope_status=ScopeStatus.WITHIN_SCOPE, test_results=[], summary="ok", errors=[], blocking_reason=""),
    }
    adapter = MockAdapter(outcomes)
    pool = WorkerPool(max_workers=2)
    results = pool.execute(graph.tasks, lambda task: WorkerResult(task_id=task.id, agent_result=adapter.execute(task, _project_map())))
    assert len(results) == 1
    assert results[0].task_id == "T1"


class MockValidator:
    def validate(self, task_id, task_contract, implementation_result, workspace=None):
        from app.schemas.validation import ValidationResult, ValidationStatus
        return ValidationResult(
            task_id=task_id,
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


def test_worker_exception_does_not_kill_others(tmp_path: Path) -> None:
    graph = TaskGraph(
        project="demo",
        tasks=[
            Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], status=TaskStatus.READY, acceptance_criteria=[], out_of_scope=[], implementation_scope="core"),
            Task(id="T2", phase_id="P1", title="T2", goal="g", why="w", dependencies=[], status=TaskStatus.READY, acceptance_criteria=[], out_of_scope=[], implementation_scope="core"),
        ],
    )
    good = AgentExecutionResult(task_id="T1", agent="mock", status=ImplExecutionStatus.IMPLEMENTED, iterations=1, changed_files=[], scope_status=ScopeStatus.WITHIN_SCOPE, test_results=[], summary="ok", errors=[], blocking_reason="")
    bad_task_id = "T2"

    class FailingAdapter:
        def execute(self, task_contract, project_map):
            if task_contract.task_id == bad_task_id:
                raise RuntimeError("worker boom")
            return good

    orchestrator = ParallelExecutionOrchestrator(adapter=FailingAdapter(), project_map=_project_map(), base_dir=tmp_path, max_workers=2, validator=MockValidator())  # type: ignore[arg-type]
    run = orchestrator.run(graph, "run-err", tmp_path / "runs" / "run-err")
    assert run.status == ExecutionStatus.COMPLETED
    assert any(r.task_id == "T1" for r in run.task_results)

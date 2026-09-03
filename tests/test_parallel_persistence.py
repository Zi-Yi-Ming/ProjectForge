from __future__ import annotations

from pathlib import Path

from app.agents.parallel_orchestrator import ParallelExecutionOrchestrator
from app.agents.persistence import JsonExecutionPersistence
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus as ImplExecutionStatus,
    ProjectMap,
    ScopeStatus,
)
from app.schemas.task import Task, TaskGraph, TaskStatus


class FakeAdapter:
    def __init__(self, outcomes):
        self.outcomes = outcomes

    def execute(self, task_contract, project_map):
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


def test_persists_parallel_task_records(tmp_path: Path) -> None:
    graph = TaskGraph(
        project="demo",
        tasks=[
            Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], status=TaskStatus.READY, acceptance_criteria=[], out_of_scope=[], implementation_scope="core"),
            Task(id="T2", phase_id="P1", title="T2", goal="g", why="w", dependencies=[], status=TaskStatus.READY, acceptance_criteria=[], out_of_scope=[], implementation_scope="core"),
        ],
    )
    outcomes = {"T1": _passed("T1"), "T2": _passed("T2")}
    orchestrator = ParallelExecutionOrchestrator(adapter=FakeAdapter(outcomes), project_map=_project_map(), base_dir=tmp_path, max_workers=2, validator=FakeValidator())
    run = orchestrator.run(graph, "run-p", tmp_path / "runs" / "run-p")
    persistence = JsonExecutionPersistence(tmp_path)
    loaded = persistence.load_run(run.run_id)
    assert loaded.status.value == "COMPLETED"
    assert set(loaded.completed_tasks) >= {"T1", "T2"}

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.agents.coding_agent import CodingAgentAdapter
from app.agents.parallel_orchestrator import ParallelExecutionOrchestrator
from app.agents.worker import WorkerResult
from app.schemas.execution import ExecutionRun, ExecutionStatus
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus as ImplExecutionStatus,
    ProjectMap,
    ScopeStatus,
)
from app.schemas.validation import ValidationResult, ValidationStatus
from app.schemas.task import Task, TaskGraph, TaskStatus


class MockAdapter(CodingAgentAdapter):
    def __init__(self, outcomes: dict[str, AgentExecutionResult]) -> None:
        self.outcomes = outcomes

    def execute(self, task_contract, project_map):
        return self.outcomes[task_contract.task_id]


class MockValidator:
    def validate(self, task_id, task_contract, implementation_result, workspace=None):
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


def _base_project_map() -> ProjectMap:
    return ProjectMap(
        architecture_style="layered",
        services=["api", "service", "worker"],
        modules=["app", "service", "worker"],
        data_flow="request -> service -> worker -> storage",
        technology_stack=["python"],
        infrastructure=["docker"],
    )


def _graph() -> TaskGraph:
    return TaskGraph(
        project="demo",
        tasks=[
            Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], status=TaskStatus.DONE, acceptance_criteria=[], out_of_scope=[], implementation_scope="core"),
            Task(id="T2", phase_id="P1", title="T2", goal="g", why="w", dependencies=["T1"], status=TaskStatus.READY, acceptance_criteria=[], out_of_scope=[], implementation_scope="core"),
            Task(id="T3", phase_id="P1", title="T3", goal="g", why="w", dependencies=["T1"], status=TaskStatus.READY, acceptance_criteria=[], out_of_scope=[], implementation_scope="core"),
        ],
    )


def _passed_result(task_id: str) -> AgentExecutionResult:
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


def test_parallel_orchestrator_runs_parallel_tasks(tmp_path: Path) -> None:
    graph = _graph()
    outcomes = {
        "T2": _passed_result("T2"),
        "T3": _passed_result("T3"),
    }
    adapter = MockAdapter(outcomes)
    orchestrator = ParallelExecutionOrchestrator(adapter=adapter, project_map=_base_project_map(), base_dir=tmp_path, max_workers=2, validator=MockValidator())
    run = orchestrator.run(graph, "run-1", tmp_path / "runs" / "run-1")
    assert run.status == ExecutionStatus.COMPLETED
    assert set(run.completed_tasks) >= {"T2", "T3"}

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.artifact_store import ArtifactStore
from app.agents.orchestrator import ExecutionOrchestrator
from app.agents.persistence import JsonExecutionPersistence
from app.agents.scheduler import TaskScheduler
from app.agents.validation_aggregator import ValidationAggregator
from app.agents.validator import DeterministicValidator
from app.schemas.execution import ExecutionRun, ExecutionStatus, TaskExecutionRecord
from app.schemas.implementation import AgentExecutionResult, ExecutionStatus as AgentExecutionStatus, ProjectMap, ScopeStatus
from app.schemas.persistence import Artifact, ArtifactType
from app.schemas.task import Task, TaskGraph, TaskStatus
from app.schemas.validation import ValidationResult, ValidationStatus


class MockAdapter:
    def execute(self, task_contract, project_map):
        return AgentExecutionResult(
            task_id=task_contract.task_id,
            agent="mock",
            status=AgentExecutionStatus.IMPLEMENTED,
            scope_status=ScopeStatus.WITHIN_SCOPE,
            iterations=1,
            changed_files=[],
            test_results=[],
            summary="ok",
        )


class MockValidator(DeterministicValidator):
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
        )


class MockAggregator(ValidationAggregator):
    def aggregate(self, task_contract, implementation_result, deterministic_result, llm_review=None):
        return deterministic_result, None


def _linear_graph() -> TaskGraph:
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g", why="w", dependencies=["T1"], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
    ]
    return TaskGraph(project="demo", phases=[], tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


def test_resume_skips_done_tasks(tmp_path: Path) -> None:
    graph = _linear_graph()
    persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_dir = tmp_path / "runs" / "run-resume"
    run_dir.mkdir(parents=True)
    artifact_store = ArtifactStore(run_dir)

    orchestrator = ExecutionOrchestrator(adapter=MockAdapter(), validator=MockValidator(), aggregation=MockAggregator(), persistence=persistence, artifact_store=artifact_store)
    first = orchestrator.run(graph, ProjectMap(architecture="", services=[], modules=[], technology=[], data_flow=""), run_dir=run_dir)
    assert first.status == ExecutionStatus.COMPLETED

    graph2 = _linear_graph()
    orchestrator2 = ExecutionOrchestrator(adapter=MockAdapter(), validator=MockValidator(), aggregation=MockAggregator(), persistence=persistence, artifact_store=artifact_store)
    resumed = orchestrator2.resume(first.run_id, graph2, ProjectMap(architecture="", services=[], modules=[], technology=[], data_flow=""), run_dir=run_dir)
    assert resumed.status == ExecutionStatus.COMPLETED


def test_resume_does_not_mark_in_progress_as_done(tmp_path: Path) -> None:
    graph = _linear_graph()
    persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_dir = tmp_path / "runs" / "run-inprogress"
    run_dir.mkdir(parents=True)
    artifact_store = ArtifactStore(run_dir)

    orchestrator = ExecutionOrchestrator(adapter=MockAdapter(), validator=MockValidator(), aggregation=MockAggregator(), persistence=persistence, artifact_store=artifact_store)
    first = orchestrator.run(graph, ProjectMap(architecture="", services=[], modules=[], technology=[], data_flow=""), run_dir=run_dir)
    assert first.status == ExecutionStatus.COMPLETED

    run_data = persistence.load_run(first.run_id)
    run_data.task_results[0].status = "IN_PROGRESS"
    persistence.save_run(run_data)

    graph2 = _linear_graph()
    orchestrator2 = ExecutionOrchestrator(adapter=MockAdapter(), validator=MockValidator(), aggregation=MockAggregator(), persistence=persistence, artifact_store=artifact_store)
    resumed = orchestrator2.resume(first.run_id, graph2, ProjectMap(architecture="", services=[], modules=[], technology=[], data_flow=""), run_dir=run_dir)
    assert resumed.status == ExecutionStatus.COMPLETED


def test_resume_does_not_rerun_failed_or_blocked_tasks(tmp_path: Path) -> None:
    graph = _linear_graph()
    persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_dir = tmp_path / "runs" / "run-failed"
    run_dir.mkdir(parents=True)
    artifact_store = ArtifactStore(run_dir)

    orchestrator = ExecutionOrchestrator(adapter=MockAdapter(), validator=MockValidator(), aggregation=MockAggregator(), persistence=persistence, artifact_store=artifact_store)
    first = orchestrator.run(graph, ProjectMap(architecture="", services=[], modules=[], technology=[], data_flow=""), run_dir=run_dir)
    assert first.status == ExecutionStatus.COMPLETED

    run_data = persistence.load_run(first.run_id)
    run_data.task_results[0].status = "FAILED"
    run_data.task_results[1].status = "BLOCKED"
    persistence.save_run(run_data)

    graph2 = _linear_graph()
    orchestrator2 = ExecutionOrchestrator(adapter=MockAdapter(), validator=MockValidator(), aggregation=MockAggregator(), persistence=persistence, artifact_store=artifact_store)
    resumed = orchestrator2.resume(first.run_id, graph2, ProjectMap(architecture="", services=[], modules=[], technology=[], data_flow=""), run_dir=run_dir)
    assert resumed.status == ExecutionStatus.BLOCKED

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.artifact_store import ArtifactStore
from app.agents.coding_agent import CodingAgentAdapter
from app.agents.failure_analyzer import FailureAnalyzer
from app.agents.orchestrator import ExecutionOrchestrator
from app.agents.replanner import Replanner
from app.agents.replan_applier import ReplanApplier
from app.agents.replan_persistence import ReplanPersistence
from app.agents.scheduler import TaskScheduler
from app.agents.validation_aggregator import ValidationAggregator
from app.agents.validator import DeterministicValidator
from app.agents.persistence import JsonExecutionPersistence
from app.schemas.execution import ExecutionRun, ExecutionStatus, TaskExecutionRecord
from app.schemas.implementation import AgentExecutionResult, ExecutionStatus as AgentExecutionStatus, ProjectMap, ScopeStatus
from app.schemas.replan import ReplanAction, ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus
from app.schemas.validation import ValidationResult, ValidationStatus


class MockAdapter:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    def execute(self, task_contract, project_map):
        self.calls.append(task_contract.task_id)
        return self.outcomes[task_contract.task_id]


class MockValidator(DeterministicValidator):
    def validate(self, task_id, task_contract, implementation_result, workspace=None):
        return ValidationResult(task_id=task_id, status=ValidationStatus.PASS, criterion_results=[], test_results=[], scope_result="WITHIN_SCOPE", changed_files=[], evidence=[], failures=[], warnings=[], manual_review_items=[], llm_review=None, repair_cycle=0)


class MockAggregator(ValidationAggregator):
    def aggregate(self, task_contract, implementation_result, deterministic_result, llm_review=None):
        return deterministic_result, None


def _linear_graph():
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g", why="w", dependencies=["T1"], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T3", phase_id="P1", title="T3", goal="g", why="w", dependencies=["T2"], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
    ]
    return TaskGraph(project="demo", phases=[], tasks=tasks, total_tasks=3, required_tasks=3, optional_tasks=0)


def _linear_graph_with_failed_t2():
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], scope="Core", status=TaskStatus.DONE, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g", why="w", dependencies=["T1"], scope="Core", status=TaskStatus.FAILED, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T3", phase_id="P1", title="T3", goal="g", why="w", dependencies=["T2"], scope="Core", status=TaskStatus.BLOCKED, acceptance_criteria=[], out_of_scope=[]),
    ]
    return TaskGraph(project="demo", phases=[], tasks=tasks, total_tasks=3, required_tasks=3, optional_tasks=0)


def test_failed_task_generates_blocked_run(tmp_path: Path) -> None:
    outcomes = {
        "T1": AgentExecutionResult(task_id="T1", agent="mock", status=AgentExecutionStatus.IMPLEMENTED, scope_status=ScopeStatus.WITHIN_SCOPE),
        "T2": AgentExecutionResult(task_id="T2", agent="mock", status=AgentExecutionStatus.FAILED, scope_status=ScopeStatus.WITHIN_SCOPE, errors=["fail"]),
        "T3": AgentExecutionResult(task_id="T3", agent="mock", status=AgentExecutionStatus.IMPLEMENTED, scope_status=ScopeStatus.WITHIN_SCOPE),
    }
    graph = _linear_graph()
    persistence = ReplanPersistence(base_dir=tmp_path)
    run_dir = tmp_path / "runs" / "run-e2e"
    run_dir.mkdir(parents=True)
    artifact_store = ArtifactStore(run_dir)
    orchestrator = ExecutionOrchestrator(adapter=MockAdapter(outcomes), validator=MockValidator(), aggregation=MockAggregator(), persistence=None, artifact_store=artifact_store, failure_analyzer=FailureAnalyzer(), replanner=Replanner(), replan_persistence=persistence, replan_applier=ReplanApplier())
    run = orchestrator.run(graph, ProjectMap(architecture="", services=[], modules=[], technology=[], data_flow=""), run_dir=run_dir)
    assert run.status == ExecutionStatus.BLOCKED
    assert run.blocking_reason == "NEEDS_USER_REPLAN_APPROVAL"
    proposals = persistence.list_proposals(run.run_id)
    assert len(proposals) == 1
    assert proposals[0].status == ReplanProposalStatus.PROPOSED


def test_approve_retry_and_resume(tmp_path: Path) -> None:
    outcomes_first = {
        "T1": AgentExecutionResult(task_id="T1", agent="mock", status=AgentExecutionStatus.IMPLEMENTED, scope_status=ScopeStatus.WITHIN_SCOPE),
        "T2": AgentExecutionResult(task_id="T2", agent="mock", status=AgentExecutionStatus.FAILED, scope_status=ScopeStatus.WITHIN_SCOPE, errors=["fail"]),
        "T3": AgentExecutionResult(task_id="T3", agent="mock", status=AgentExecutionStatus.IMPLEMENTED, scope_status=ScopeStatus.WITHIN_SCOPE),
    }
    outcomes_retry = {
        "T1": AgentExecutionResult(task_id="T1", agent="mock", status=AgentExecutionStatus.IMPLEMENTED, scope_status=ScopeStatus.WITHIN_SCOPE),
        "T2": AgentExecutionResult(task_id="T2", agent="mock", status=AgentExecutionStatus.IMPLEMENTED, scope_status=ScopeStatus.WITHIN_SCOPE),
        "T3": AgentExecutionResult(task_id="T3", agent="mock", status=AgentExecutionStatus.IMPLEMENTED, scope_status=ScopeStatus.WITHIN_SCOPE),
    }
    graph = _linear_graph()
    persistence = ReplanPersistence(base_dir=tmp_path)
    run_dir = tmp_path / "runs" / "run-approve"
    run_dir.mkdir(parents=True)
    artifact_store = ArtifactStore(run_dir)
    execution_persistence = JsonExecutionPersistence(base_dir=tmp_path)
    orchestrator = ExecutionOrchestrator(adapter=MockAdapter(outcomes_first), validator=MockValidator(), aggregation=MockAggregator(), persistence=execution_persistence, artifact_store=artifact_store, failure_analyzer=FailureAnalyzer(), replanner=Replanner(), replan_persistence=persistence, replan_applier=ReplanApplier())
    first = orchestrator.run(graph, ProjectMap(architecture="", services=[], modules=[], technology=[], data_flow=""), run_dir=run_dir)
    assert first.status == ExecutionStatus.BLOCKED
    proposals = persistence.list_proposals(first.run_id)
    assert len(proposals) == 1
    proposal = proposals[0]
    proposal.status = ReplanProposalStatus.APPROVED
    persistence.save_proposal(proposal)
    graph2 = _linear_graph()
    orchestrator2 = ExecutionOrchestrator(adapter=MockAdapter(outcomes_retry), validator=MockValidator(), aggregation=MockAggregator(), persistence=execution_persistence, artifact_store=artifact_store, failure_analyzer=FailureAnalyzer(), replanner=Replanner(), replan_persistence=persistence, replan_applier=ReplanApplier())
    orchestrator2.approve_and_apply(proposal, graph2)
    assert next(t for t in graph2.tasks if t.id == "T2").status == TaskStatus.PENDING
    resumed = orchestrator2.run(graph2, ProjectMap(architecture="", services=[], modules=[], technology=[], data_flow=""), run_dir=run_dir)
    assert resumed.status == ExecutionStatus.COMPLETED

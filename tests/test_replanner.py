from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.replanner import Replanner
from app.schemas.execution import ExecutionRun, ExecutionStatus
from app.schemas.replan import ReplanAction, ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus


def _graph_with_failed_task(task_id="T2", status=TaskStatus.FAILED):
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], scope="Core", status=TaskStatus.DONE, acceptance_criteria=[], out_of_scope=[]),
        Task(id=task_id, phase_id="P1", title=task_id, goal="g", why="w", dependencies=["T1"], scope="Core", status=status, acceptance_criteria=[], out_of_scope=[]),
    ]
    return TaskGraph(project="demo", phases=[], tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


def test_test_failure_generates_retry_proposal():
    replanner = Replanner(max_retries=2)
    graph = _graph_with_failed_task("T2", TaskStatus.FAILED)
    run = ExecutionRun(run_id="run-1", project="demo", status=ExecutionStatus.BLOCKED, blocking_reason="NEEDS_USER_REPLAN_APPROVAL")
    from app.schemas.replan import FailureAnalysis, FailureType, Recoverability, RecommendedAction
    analysis = FailureAnalysis(task_id="T2", failure_type=FailureType.TEST_FAILURE, recoverability=Recoverability.RETRYABLE, recommended_action=RecommendedAction.RETRY)
    proposal = replanner.propose(run, graph, analysis, attempt_counts={"T2": 0})
    assert proposal is not None
    assert proposal.action == ReplanAction.RETRY
    assert proposal.status == ReplanProposalStatus.PROPOSED


def test_timeout_generates_retry_proposal():
    replanner = Replanner(max_retries=2)
    graph = _graph_with_failed_task("T2", TaskStatus.FAILED)
    run = ExecutionRun(run_id="run-1", project="demo", status=ExecutionStatus.BLOCKED, blocking_reason="NEEDS_USER_REPLAN_APPROVAL")
    from app.schemas.replan import FailureAnalysis, FailureType, Recoverability, RecommendedAction
    analysis = FailureAnalysis(task_id="T2", failure_type=FailureType.TIMEOUT, recoverability=Recoverability.RETRYABLE, recommended_action=RecommendedAction.RETRY)
    proposal = replanner.propose(run, graph, analysis, attempt_counts={"T2": 0})
    assert proposal is not None
    assert proposal.action == ReplanAction.RETRY


def test_retry_limit_generates_block_proposal():
    replanner = Replanner(max_retries=2)
    graph = _graph_with_failed_task("T2", TaskStatus.FAILED)
    run = ExecutionRun(run_id="run-1", project="demo", status=ExecutionStatus.BLOCKED, blocking_reason="NEEDS_USER_REPLAN_APPROVAL")
    from app.schemas.replan import FailureAnalysis, FailureType, Recoverability, RecommendedAction
    analysis = FailureAnalysis(task_id="T2", failure_type=FailureType.TEST_FAILURE, recoverability=Recoverability.BLOCKED, recommended_action=RecommendedAction.BLOCK)
    proposal = replanner.propose(run, graph, analysis, attempt_counts={"T2": 2})
    assert proposal is not None
    assert proposal.action == ReplanAction.BLOCK


def test_split_generates_split_proposal():
    replanner = Replanner()
    graph = _graph_with_failed_task("T2", TaskStatus.FAILED)
    run = ExecutionRun(run_id="run-1", project="demo", status=ExecutionStatus.BLOCKED, blocking_reason="NEEDS_USER_REPLAN_APPROVAL")
    from app.schemas.replan import FailureAnalysis, FailureType, Recoverability, RecommendedAction
    analysis = FailureAnalysis(task_id="T2", failure_type=FailureType.UNKNOWN, recoverability=Recoverability.REPLAN_REQUIRED, recommended_action=RecommendedAction.SPLIT)
    proposal = replanner.propose(run, graph, analysis)
    assert proposal is not None
    assert proposal.action == ReplanAction.SPLIT
    assert len(proposal.proposed_changes) == 2


def test_unknown_failure_generates_block_proposal():
    replanner = Replanner()
    graph = _graph_with_failed_task("T2", TaskStatus.FAILED)
    run = ExecutionRun(run_id="run-1", project="demo", status=ExecutionStatus.BLOCKED, blocking_reason="NEEDS_USER_REPLAN_APPROVAL")
    from app.schemas.replan import FailureAnalysis, FailureType, Recoverability, RecommendedAction
    analysis = FailureAnalysis(task_id="T2", failure_type=FailureType.UNKNOWN, recoverability=Recoverability.NEEDS_USER, recommended_action=RecommendedAction.BLOCK)
    proposal = replanner.propose(run, graph, analysis)
    assert proposal is not None
    assert proposal.action == ReplanAction.BLOCK

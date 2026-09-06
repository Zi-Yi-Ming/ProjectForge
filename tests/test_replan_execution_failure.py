from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.failure_analyzer import FailureAnalyzer
from app.agents.persistence import JsonExecutionPersistence
from app.agents.replan_persistence import ReplanPersistence
from app.product.project_persistence import ProjectPersistence
from app.product.replan_control import ReplanControl
from app.product.run_control import RunControl
from app.product.service import ProjectService
from app.schemas.execution import ExecutionRun, ExecutionStatus, TaskExecutionRecord
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus as ImplExecutionStatus,
    GitCheckpoint,
    ScopeStatus,
)
from app.schemas.project import ProjectStatus
from app.schemas.replan import RecommendedAction, ReplanAction, ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus


class _ExecutionFailureExecutor:
    """Produces records shaped like real execution-phase failures:
    TIMEOUT (execution_result present, validation absent) or adapter crash
    (both absent)."""

    def __init__(self, with_execution_result: bool) -> None:
        self._with_execution_result = with_execution_result

    def run(self, task_graph: TaskGraph, project_map=None, run_dir=None) -> ExecutionRun:
        failed_task = next(t for t in task_graph.tasks if t.status == TaskStatus.FAILED)
        execution_result = None
        if self._with_execution_result:
            execution_result = AgentExecutionResult(
                task_id=failed_task.id,
                agent="fake",
                status=ImplExecutionStatus.TIMEOUT,
                iterations=1,
                changed_files=[],
                scope_status=ScopeStatus.NEEDS_REVIEW,
                test_results=[],
                summary="",
                errors=["Hermes execution exceeded timeout"],
                blocking_reason="timeout",
                git_checkpoint=GitCheckpoint(),
            )
        return ExecutionRun(
            run_id="run-fake",
            project=task_graph.project,
            status=ExecutionStatus.FAILED,
            total_tasks=len(task_graph.tasks),
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            failed_tasks=[failed_task.id],
            task_results=[
                TaskExecutionRecord(
                    task_id=failed_task.id,
                    phase=failed_task.phase_id,
                    title=failed_task.title,
                    status="FAILED",
                    execution_result=execution_result,
                    validation_result=None,
                    started_at="2026-01-01T00:00:00Z",
                    finished_at="2026-01-01T00:00:01Z",
                )
            ],
        )


def _graph_with_failed() -> TaskGraph:
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], status=TaskStatus.DONE, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g2", why="w2", dependencies=["T1"], status=TaskStatus.FAILED, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
    ]
    return TaskGraph(project="demo", tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


def _setup(tmp_path: Path, executor: _ExecutionFailureExecutor):
    persistence = ProjectPersistence(base_dir=tmp_path)
    execution_persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence)
    replan_control = ReplanControl(
        persistence=persistence,
        run_control=run_control,
        execution_persistence=execution_persistence,
        replan_persistence=ReplanPersistence(base_dir=tmp_path),
    )
    service = ProjectService(persistence=persistence, run_control=run_control)
    project = service.create("replan-exec-failure")
    for status in (ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY):
        service.transition_to(project.project_id, status)
    run = service.start_run(project.project_id, _graph_with_failed(), tmp_path, executor)
    return service, replan_control, project.project_id, run


@pytest.mark.parametrize("with_execution_result", [True, False])
def test_execution_failure_can_create_retry_proposal(tmp_path: Path, with_execution_result: bool) -> None:
    _, replan_control, project_id, run = _setup(tmp_path, _ExecutionFailureExecutor(with_execution_result))
    proposal = replan_control.create_proposal(project_id, run.run_id, _graph_with_failed())
    assert proposal.status == ReplanProposalStatus.PROPOSED
    assert proposal.action == ReplanAction.RETRY
    assert proposal.task_id == "T2"


@pytest.mark.parametrize("with_execution_result", [True, False])
def test_execution_failure_replan_cycle_approve_apply(tmp_path: Path, with_execution_result: bool) -> None:
    _, replan_control, project_id, run = _setup(tmp_path, _ExecutionFailureExecutor(with_execution_result))
    proposal = replan_control.create_proposal(project_id, run.run_id, _graph_with_failed())
    approved = replan_control.approve_proposal(project_id, run.run_id, proposal.proposal_id)
    assert approved.status == ReplanProposalStatus.APPROVED
    graph = _graph_with_failed()
    applied = replan_control.apply_proposal(project_id, proposal.proposal_id, graph, run_id=run.run_id)
    assert applied.status == ReplanProposalStatus.APPLIED
    reset = next(t for t in graph.tasks if t.id == "T2")
    assert reset.status == TaskStatus.PENDING


def test_failure_analyzer_handles_missing_execution_result() -> None:
    from app.schemas.implementation import ProjectMap, TaskContract

    contract = TaskContract(
        task_id="T2",
        project="demo",
        phase="P1",
        title="T2",
        goal="g2",
        why="w2",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="Core",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=[],
        test_scope=[],
        execution_rules=[],
    )
    analysis = FailureAnalyzer().analyze(
        task_contract=contract,
        implementation_result=None,
        validation_result=None,
        artifacts=[],
        attempt_count=1,
    )
    assert analysis.task_id == "T2"
    assert analysis.recommended_action == RecommendedAction.RETRY

    blocked = FailureAnalyzer().analyze(
        task_contract=contract,
        implementation_result=None,
        validation_result=None,
        artifacts=[],
        attempt_count=2,
    )
    assert blocked.recommended_action == RecommendedAction.BLOCK

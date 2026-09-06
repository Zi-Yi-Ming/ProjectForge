from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.failure_analyzer import FailureAnalyzer
from app.agents.replanner import Replanner
from app.agents.replan_applier import ReplanApplier
from app.agents.replan_persistence import ReplanPersistence
from app.agents.persistence import JsonExecutionPersistence
from app.product.errors import InvalidProjectStateError
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
from app.schemas.replan import ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus
from app.schemas.validation import ValidationResult, ValidationStatus


class FakeExecutor:
    def __init__(self, failed: bool = False) -> None:
        self._failed = failed

    def run(self, task_graph: TaskGraph, project_map=None, run_dir=None) -> ExecutionRun:
        if not self._failed:
            return ExecutionRun(
                run_id="run-fake",
                project=task_graph.project,
                status=ExecutionStatus.RUNNING,
                total_tasks=len(task_graph.tasks),
                started_at="2026-01-01T00:00:00Z",
            )
        failed_task = next(t for t in task_graph.tasks if t.status == TaskStatus.FAILED)
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
                    execution_result=AgentExecutionResult(
                        task_id=failed_task.id,
                        agent="fake",
                        status=ImplExecutionStatus.FAILED,
                        iterations=1,
                        changed_files=[],
                        scope_status=ScopeStatus.WITHIN_SCOPE,
                        test_results=[],
                        summary="fake failure",
                        errors=["fake failure"],
                        blocking_reason="",
                        git_checkpoint=GitCheckpoint(),
                    ),
                    validation_result=ValidationResult(
                        task_id=failed_task.id,
                        status=ValidationStatus.FAIL,
                        criterion_results=[],
                        test_results=[],
                        scope_result="WITHIN_SCOPE",
                        changed_files=[],
                        evidence=[],
                        failures=["fake failure"],
                        warnings=[],
                        manual_review_items=[],
                        llm_review=None,
                        repair_cycle=0,
                        validated_at="2026-01-01T00:00:00Z",
                    ),
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


def test_create_proposal_requires_failed_run(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    run_control = RunControl(execution_persistence=JsonExecutionPersistence(base_dir=tmp_path))
    replan_control = ReplanControl(persistence=persistence, run_control=run_control, replan_persistence=ReplanPersistence(base_dir=tmp_path))
    service = ProjectService(persistence=persistence, run_control=run_control)
    project = service.create("replan-demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    run = service.start_run(project.project_id, _graph_with_failed(), tmp_path, FakeExecutor())
    with pytest.raises(InvalidProjectStateError):
        replan_control.create_proposal(project.project_id, run.run_id, _graph_with_failed())


def test_approve_then_apply_proposal(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    run_control = RunControl(execution_persistence=JsonExecutionPersistence(base_dir=tmp_path))
    replan_control = ReplanControl(persistence=persistence, run_control=run_control, replan_persistence=ReplanPersistence(base_dir=tmp_path))
    service = ProjectService(persistence=persistence, run_control=run_control)
    project = service.create("replan-demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    run = service.start_run(project.project_id, _graph_with_failed(), tmp_path, FakeExecutor(failed=True))
    assert run.status == ExecutionStatus.FAILED
    proposal = replan_control.create_proposal(project.project_id, run.run_id, _graph_with_failed())
    assert proposal.status == ReplanProposalStatus.PROPOSED
    approved = replan_control.approve_proposal(project.project_id, run.run_id, proposal.proposal_id)
    assert approved.status == ReplanProposalStatus.APPROVED
    applied = replan_control.apply_proposal(project.project_id, proposal.proposal_id, _graph_with_failed(), run_id=run.run_id)
    assert applied.status == ReplanProposalStatus.APPLIED
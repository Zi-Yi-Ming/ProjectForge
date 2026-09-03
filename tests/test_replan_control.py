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
from app.schemas.execution import ExecutionRun, ExecutionStatus
from app.schemas.project import ProjectStatus
from app.schemas.replan import ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus


class FakeExecutor:
    def run(self, task_graph: TaskGraph, run_id: str, run_dir: Path) -> ExecutionRun:
        raise NotImplementedError


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
    run = service.start_run(project.project_id, _graph_with_failed(), tmp_path, FakeExecutor())
    run.status = ExecutionStatus.FAILED
    run_control.execution_persistence.save_run(run)
    proposal = replan_control.create_proposal(project.project_id, run.run_id, _graph_with_failed())
    assert proposal.status == ReplanProposalStatus.PROPOSED
    approved = replan_control.approve_proposal(project.project_id, run.run_id, proposal.proposal_id)
    assert approved.status == ReplanProposalStatus.APPROVED
    applied = replan_control.apply_proposal(project.project_id, proposal.proposal_id, _graph_with_failed(), run_id=run.run_id)
    assert applied.status == ReplanProposalStatus.APPLIED
from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.persistence import JsonExecutionPersistence
from app.api.app import create_api
from app.product.event_store import EventStore
from app.product.project_persistence import ProjectPersistence
from app.product.run_control import RunControl
from app.product.replan_control import ReplanControl
from app.product.service import ProjectService
from app.schemas.execution import ExecutionRun, ExecutionStatus, TaskExecutionRecord
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus as AgentExecutionStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
)
from app.schemas.replan import ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus
from app.schemas.validation import ValidationResult, ValidationStatus
from app.schemas.project import ProjectStatus
from fastapi.testclient import TestClient


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _RunningExecutor:
    def run(self, task_graph: TaskGraph, project_map: ProjectMap | None = None, run_dir: Path | None = None, run_id: str | None = None, cancel_check: "Callable[[], bool] | None" = None) -> ExecutionRun:
        return ExecutionRun(
            run_id="run-fake",
            project=task_graph.project,
            status=ExecutionStatus.RUNNING,
            total_tasks=len(task_graph.tasks),
            started_at=_now_iso(),
        )


class _FailedRunExecutor:
    def run(self, task_graph: TaskGraph, project_map: ProjectMap | None = None, run_dir: Path | None = None, run_id: str | None = None, cancel_check: "Callable[[], bool] | None" = None) -> ExecutionRun:
        failed_task = next(t for t in task_graph.tasks if t.status == TaskStatus.FAILED)
        failed_result = AgentExecutionResult(
            task_id=failed_task.id,
            agent="e2e",
            status=AgentExecutionStatus.FAILED,
            iterations=1,
            changed_files=[],
            scope_status=ScopeStatus.WITHIN_SCOPE,
            test_results=[],
            summary="synthetic failure",
            errors=["synthetic failure"],
            blocking_reason="",
            git_checkpoint=GitCheckpoint(),
        )
        validation = ValidationResult(
            task_id=failed_task.id,
            status=ValidationStatus.FAIL,
            criterion_results=[],
            test_results=[],
            scope_result="WITHIN_SCOPE",
            changed_files=[],
            evidence=[],
            failures=["synthetic failure"],
            warnings=[],
            manual_review_items=[],
            llm_review=None,
            repair_cycle=0,
            validated_at=_now_iso(),
        )
        record = TaskExecutionRecord(
            task_id=failed_task.id,
            phase=failed_task.phase_id,
            title=failed_task.title,
            status="FAILED",
            execution_result=failed_result,
            validation_result=validation,
            started_at=_now_iso(),
            finished_at=_now_iso(),
        )
        return ExecutionRun(
            run_id="run-fake",
            project=task_graph.project,
            status=ExecutionStatus.FAILED,
            total_tasks=len(task_graph.tasks),
            started_at=_now_iso(),
            finished_at=_now_iso(),
            failed_tasks=[failed_task.id],
            task_results=[record],
        )


def _graph_with_failed():
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], status=TaskStatus.DONE, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g2", why="w2", dependencies=["T1"], status=TaskStatus.FAILED, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
    ]
    return TaskGraph(project="demo", tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


def test_product_core_project_lifecycle_and_events(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    service = ProjectService(persistence=persistence, event_store=event_store)

    project = service.create("E2E Lifecycle")
    assert project.status.value == "CREATED"

    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    project = service.transition_to(project.project_id, ProjectStatus.READY)
    assert project.status.value == "READY"

    events = event_store.get_events(project.project_id)
    event_types = [e.event_type for e in events]
    assert "PROJECT_CREATED" in event_types
    assert "PROJECT_STATE_CHANGED" in event_types


def test_run_start_and_active_run_invariant(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    execution_persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence, event_store=event_store)
    service = ProjectService(persistence=persistence, event_store=event_store, run_control=run_control)

    project = service.create("E2E Run")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)

    run = service.start_run(project.project_id, _graph_with_failed(), tmp_path, _RunningExecutor())
    assert run.status == ExecutionStatus.RUNNING
    assert run.project == project.project_id

    with pytest.raises(Exception):
        service.start_run(project.project_id, _graph_with_failed(), tmp_path, _RunningExecutor())


def test_failure_replan_approve_apply_resume_via_product_core(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    execution_persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence, event_store=event_store)
    replan_control = ReplanControl(persistence=persistence, run_control=run_control, event_store=event_store, execution_persistence=execution_persistence)
    service = ProjectService(persistence=persistence, event_store=event_store, run_control=run_control, replan_control=replan_control)

    project = service.create("E2E Replan")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)

    run = service.start_run(project.project_id, _graph_with_failed(), tmp_path, _FailedRunExecutor())
    run = run_control.complete_run(project.project_id, run.run_id, ExecutionStatus.FAILED)
    assert run.status == ExecutionStatus.FAILED
    project = service.persistence.load_project(project.project_id)
    project.status = ProjectStatus.BLOCKED
    service.persistence.save_project(project)

    proposal = service.replan_control.create_proposal(project.project_id, run.run_id, _graph_with_failed())
    assert proposal.status == ReplanProposalStatus.PROPOSED

    proposal = service.replan_control.approve_proposal(project.project_id, run.run_id, proposal.proposal_id)
    assert proposal.status == ReplanProposalStatus.APPROVED

    proposal = service.replan_control.apply_proposal(project.project_id, proposal.proposal_id, _graph_with_failed(), run_id=run.run_id)
    assert proposal.status == ReplanProposalStatus.APPLIED

    resumed = service.replan_control.resume_project(project.project_id, _graph_with_failed(), tmp_path)
    assert resumed.run_id != run.run_id
    assert resumed.status == ExecutionStatus.RUNNING


def test_done_task_skip_on_resume(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    execution_persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence, event_store=event_store)
    replan_control = ReplanControl(persistence=persistence, run_control=run_control, event_store=event_store, execution_persistence=execution_persistence)
    service = ProjectService(persistence=persistence, event_store=event_store, run_control=run_control, replan_control=replan_control)

    project = service.create("E2E Done Skip")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)

    run = service.start_run(project.project_id, _graph_with_failed(), tmp_path, _FailedRunExecutor())
    run = run_control.complete_run(project.project_id, run.run_id, ExecutionStatus.FAILED)
    project = service.persistence.load_project(project.project_id)
    project.status = ProjectStatus.BLOCKED
    service.persistence.save_project(project)

    proposal = service.replan_control.create_proposal(project.project_id, run.run_id, _graph_with_failed())
    service.replan_control.approve_proposal(project.project_id, run.run_id, proposal.proposal_id)
    service.replan_control.apply_proposal(project.project_id, proposal.proposal_id, _graph_with_failed(), run_id=run.run_id)
    resumed = service.replan_control.resume_project(project.project_id, _graph_with_failed(), tmp_path)

    assert resumed.run_id != run.run_id
    assert resumed.status == ExecutionStatus.RUNNING

    graph_after = _graph_with_failed()
    done_tasks = [t.id for t in graph_after.tasks if t.status == TaskStatus.DONE]
    assert "T1" in done_tasks


def test_restart_recovery_project_run_proposal_and_events(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    execution_persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence, event_store=event_store)
    replan_control = ReplanControl(persistence=persistence, run_control=run_control, event_store=event_store, execution_persistence=execution_persistence)
    service = ProjectService(persistence=persistence, event_store=event_store, run_control=run_control, replan_control=replan_control)

    project = service.create("E2E Restart")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)

    run = service.start_run(project.project_id, _graph_with_failed(), tmp_path, _FailedRunExecutor())
    run = run_control.complete_run(project.project_id, run.run_id, ExecutionStatus.FAILED)
    project = service.persistence.load_project(project.project_id)
    project.status = ProjectStatus.BLOCKED
    service.persistence.save_project(project)

    proposal = service.replan_control.create_proposal(project.project_id, run.run_id, _graph_with_failed())
    service.replan_control.approve_proposal(project.project_id, run.run_id, proposal.proposal_id)
    service.replan_control.apply_proposal(project.project_id, proposal.proposal_id, _graph_with_failed(), run_id=run.run_id)

    persistence2 = ProjectPersistence(base_dir=tmp_path)
    event_store2 = EventStore(base_dir=tmp_path)
    execution_persistence2 = JsonExecutionPersistence(base_dir=tmp_path)
    run_control2 = RunControl(persistence=persistence2, execution_persistence=execution_persistence2, event_store=event_store2)
    replan_control2 = ReplanControl(persistence=persistence2, run_control=run_control2, event_store=event_store2, execution_persistence=execution_persistence2)
    service2 = ProjectService(persistence=persistence2, event_store=event_store2, run_control=run_control2, replan_control=replan_control2)
    reloaded = service2.load(project.project_id)
    assert reloaded.status.value == "BLOCKED"

    reloaded_proposal = service2.replan_control.get_proposal(run.run_id, proposal.proposal_id)
    assert reloaded_proposal.status == ReplanProposalStatus.APPLIED

    events = event_store.get_events(project.project_id)
    event_types = [e.event_type for e in events]
    assert "PROJECT_CREATED" in event_types
    assert "RUN_CREATED" in event_types
    assert "REPLAN_PROPOSED" in event_types
    assert "REPLAN_APPROVED" in event_types
    assert "REPLAN_APPLIED" in event_types


def test_api_project_lifecycle_and_run_start_contract(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    execution_persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence, event_store=event_store)
    replan_control = ReplanControl(persistence=persistence, run_control=run_control, event_store=event_store, execution_persistence=execution_persistence)
    service = ProjectService(persistence=persistence, event_store=event_store, run_control=run_control, replan_control=replan_control)
    client = TestClient(create_api(service=service))

    response = client.post("/projects", json={"name": "API E2E"})
    assert response.status_code == 201
    project_id = response.json()["project_id"]

    for target in ["ANALYZING", "PLANNING", "READY"]:
        response = client.post(f"/projects/{project_id}/transition", json={"target_status": target})
        assert response.status_code == 200

    # Starting a run via the API requires a persisted task graph; without one
    # the request is rejected as an invalid project state.
    response = client.post(f"/projects/{project_id}/runs", json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PROJECT_STATE"

    response = client.get(f"/projects/{project_id}/events")
    assert response.status_code == 200
    assert len(response.json()["events"]) >= 2


def test_cli_e2e_flow(tmp_path: Path) -> None:
    from typer.testing import CliRunner
    from app.cli.app import app

    runner = CliRunner()
    base = ["--base-dir", str(tmp_path)]
    result = runner.invoke(app, ["create", "CLI E2E"] + base)
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]

    for status in ["ANALYZING", "PLANNING", "READY"]:
        result = runner.invoke(app, ["transition", project_id, status] + base)
        assert result.exit_code == 0

    result = runner.invoke(app, ["events", project_id] + base)
    assert result.exit_code == 0
    assert "PROJECT_CREATED" in result.output

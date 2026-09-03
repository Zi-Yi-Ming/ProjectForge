from __future__ import annotations

from pathlib import Path

import pytest

from app.api.app import create_api
from app.product.errors import InvalidProjectStateError
from app.product.project_persistence import ProjectPersistence
from app.product.run_control import RunControl
from app.product.service import ProjectService
from app.schemas.execution import ExecutionStatus
from app.schemas.project import ProjectStatus
from app.schemas.task import Task, TaskGraph, TaskStatus
from fastapi.testclient import TestClient
from tests.fakes import FakeExecutor


def _graph_with_failed() -> TaskGraph:
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], status=TaskStatus.DONE, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g2", why="w2", dependencies=["T1"], status=TaskStatus.FAILED, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
    ]
    return TaskGraph(project="demo", tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


def _project_service(tmp_path: Path) -> ProjectService:
    persistence = ProjectPersistence(base_dir=tmp_path)
    run_control = RunControl()
    return ProjectService(persistence=persistence, run_control=run_control)


def _failed_run(service: ProjectService, project_id: str, task_graph: TaskGraph, run_dir: Path):
    run = service.start_run(project_id, task_graph, run_dir, FakeExecutor())
    run.status = ExecutionStatus.FAILED
    service.run_control.execution_persistence.save_run(run)
    service.run_control.complete_run(project_id, run.run_id, ExecutionStatus.FAILED)
    project = service.persistence.load_project(project_id)
    project.last_run_id = run.run_id
    service.persistence.save_project(project)
    return run


def test_create_replan_api(tmp_path: Path) -> None:
    service = _project_service(tmp_path)
    project = service.create("replan-api")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    run = _failed_run(service, project.project_id, _graph_with_failed(), tmp_path)
    client = TestClient(create_api(service=service))
    response = client.post(f"/projects/{project.project_id}/runs/{run.run_id}/replan", json={})
    assert response.status_code == 200
    assert response.json()["proposal"]["status"] == "PROPOSED"


def test_get_replan_api(tmp_path: Path) -> None:
    service = _project_service(tmp_path)
    project = service.create("replan-api")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    run = _failed_run(service, project.project_id, _graph_with_failed(), tmp_path)
    client = TestClient(create_api(service=service))
    response = client.post(f"/projects/{project.project_id}/runs/{run.run_id}/replan", json={})
    assert response.status_code == 200
    proposal_id = response.json()["proposal"]["proposal_id"]
    response = client.get(f"/projects/{project.project_id}/replans/{run.run_id}/{proposal_id}")
    assert response.status_code == 200
    assert response.json()["proposal"]["proposal_id"] == proposal_id


def test_approve_replan_api(tmp_path: Path) -> None:
    service = _project_service(tmp_path)
    project = service.create("replan-api")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    run = _failed_run(service, project.project_id, _graph_with_failed(), tmp_path)
    client = TestClient(create_api(service=service))
    response = client.post(f"/projects/{project.project_id}/runs/{run.run_id}/replan", json={})
    assert response.status_code == 200
    proposal_id = response.json()["proposal"]["proposal_id"]
    response = client.post(f"/projects/{project.project_id}/replans/{run.run_id}/{proposal_id}/approve", json={})
    assert response.status_code == 200
    assert response.json()["proposal"]["status"] == "APPROVED"


def test_reject_replan_api(tmp_path: Path) -> None:
    service = _project_service(tmp_path)
    project = service.create("replan-api")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    run = _failed_run(service, project.project_id, _graph_with_failed(), tmp_path)
    client = TestClient(create_api(service=service))
    response = client.post(f"/projects/{project.project_id}/runs/{run.run_id}/replan", json={})
    assert response.status_code == 200
    proposal_id = response.json()["proposal"]["proposal_id"]
    response = client.post(f"/projects/{project.project_id}/replans/{run.run_id}/{proposal_id}/reject", json={})
    assert response.status_code == 200
    assert response.json()["proposal"]["status"] == "REJECTED"


def test_apply_replan_api(tmp_path: Path) -> None:
    service = _project_service(tmp_path)
    project = service.create("replan-api")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    run = _failed_run(service, project.project_id, _graph_with_failed(), tmp_path)
    client = TestClient(create_api(service=service))
    response = client.post(f"/projects/{project.project_id}/runs/{run.run_id}/replan", json={})
    assert response.status_code == 200
    proposal_id = response.json()["proposal"]["proposal_id"]
    client.post(f"/projects/{project.project_id}/replans/{run.run_id}/{proposal_id}/approve", json={})
    response = client.post(f"/projects/{project.project_id}/replans/{run.run_id}/{proposal_id}/apply", json={})
    assert response.status_code == 200
    assert response.json()["proposal"]["status"] == "APPLIED"


def test_resume_api(tmp_path: Path) -> None:
    service = _project_service(tmp_path)
    project = service.create("replan-api")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    run = _failed_run(service, project.project_id, _graph_with_failed(), tmp_path)
    client = TestClient(create_api(service=service))
    response = client.post(f"/projects/{project.project_id}/runs/{run.run_id}/replan", json={})
    assert response.status_code == 200
    proposal_id = response.json()["proposal"]["proposal_id"]
    client.post(f"/projects/{project.project_id}/replans/{run.run_id}/{proposal_id}/approve", json={})
    client.post(f"/projects/{project.project_id}/replans/{run.run_id}/{proposal_id}/apply", json={})
    project_model = service.persistence.load_project(project.project_id)
    project_model.status = ProjectStatus.BLOCKED
    service.persistence.save_project(project_model)
    response = client.post(f"/projects/{project.project_id}/runs/resume", json={})
    assert response.status_code == 201
    assert response.json()["run"]["status"] == "RUNNING"


def test_resume_api_requires_applied_proposal(tmp_path: Path) -> None:
    service = _project_service(tmp_path)
    project = service.create("replan-api")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    run = _failed_run(service, project.project_id, _graph_with_failed(), tmp_path)
    client = TestClient(create_api(service=service))
    response = client.post(f"/projects/{project.project_id}/runs/resume", json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PROJECT_STATE"

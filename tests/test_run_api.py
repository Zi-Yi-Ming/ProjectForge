from __future__ import annotations

from pathlib import Path

import pytest

from app.api.app import create_api
from app.product.errors import InvalidProjectStateError
from app.product.project_persistence import ProjectPersistence
from app.product.run_control import RunControl
from app.product.service import ProjectService
from app.schemas.project import ProjectStatus
from app.schemas.task import Task, TaskGraph, TaskStatus
from fastapi.testclient import TestClient
from tests.fakes import FakeExecutor


def _graph() -> TaskGraph:
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], status=TaskStatus.READY),
        Task(id="T2", phase_id="P1", title="T2", goal="g2", why="w2", dependencies=["T1"], status=TaskStatus.PENDING),
    ]
    return TaskGraph(project="demo", tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


def _project_service(tmp_path: Path) -> ProjectService:
    persistence = ProjectPersistence(base_dir=tmp_path)
    return ProjectService(persistence=persistence, run_control=RunControl())


def test_start_run_api(tmp_path: Path) -> None:
    service = _project_service(tmp_path)
    project = service.create("run-api")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    client = TestClient(create_api(service=service))
    response = client.post(f"/projects/{project.project_id}/runs", json={})
    assert response.status_code == 201
    body = response.json()
    assert body["run"]["project_id"] == project.project_id
    assert body["run"]["status"] == "RUNNING"


def test_start_run_requires_ready(tmp_path: Path) -> None:
    service = _project_service(tmp_path)
    project = service.create("run-api")
    client = TestClient(create_api(service=service))
    response = client.post(f"/projects/{project.project_id}/runs", json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PROJECT_STATE"


def test_show_run_api(tmp_path: Path) -> None:
    service = _project_service(tmp_path)
    project = service.create("run-api")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    run = service.start_run(project.project_id, _graph(), tmp_path, FakeExecutor())
    client = TestClient(create_api(service=service))
    response = client.get(f"/projects/{project.project_id}/runs/{run.run_id}")
    assert response.status_code == 200
    assert response.json()["run"]["run_id"] == run.run_id


def test_cancel_run_api(tmp_path: Path) -> None:
    service = _project_service(tmp_path)
    project = service.create("run-api")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    run = service.start_run(project.project_id, _graph(), tmp_path, FakeExecutor())
    client = TestClient(create_api(service=service))
    response = client.post(f"/projects/{project.project_id}/runs/{run.run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "BLOCKED"

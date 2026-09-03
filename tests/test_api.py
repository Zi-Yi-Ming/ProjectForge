from fastapi.testclient import TestClient

from app.api.app import api, create_api
from app.product.errors import (
    ActiveRunExistsError,
    CommandNotAllowedError,
    InvalidStateTransitionError,
    ProjectNotFoundError,
)
from app.product.event_store import EventStore
from app.product.project_persistence import ProjectPersistence
from app.product.service import ProjectService
from app.schemas.project import ProjectStatus


def test_create_project(tmp_path):
    persistence = ProjectPersistence(base_dir=tmp_path)
    service = ProjectService(persistence=persistence)
    client = TestClient(create_api(service=service))

    response = client.post("/projects", json={"name": "API Demo"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "API Demo"
    assert body["status"] == "CREATED"
    assert body["project_id"].startswith("proj-")


def test_get_project(tmp_path):
    persistence = ProjectPersistence(base_dir=tmp_path)
    service = ProjectService(persistence=persistence)
    client = TestClient(create_api(service=service))

    created = client.post("/projects", json={"name": "API Demo"}).json()
    response = client.get(f"/projects/{created['project_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == created["project_id"]


def test_get_missing_project_returns_404():
    client = TestClient(create_api(service=ProjectService()))
    response = client.get("/projects/proj-missing")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "PROJECT_NOT_FOUND"


def test_valid_transition(tmp_path):
    persistence = ProjectPersistence(base_dir=tmp_path)
    service = ProjectService(persistence=persistence)
    client = TestClient(create_api(service=service))

    created = client.post("/projects", json={"name": "API Demo"}).json()
    response = client.post(
        f"/projects/{created['project_id']}/transition",
        json={"target_status": "ANALYZING"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ANALYZING"


def test_invalid_transition_returns_409(tmp_path):
    persistence = ProjectPersistence(base_dir=tmp_path)
    service = ProjectService(persistence=persistence)
    client = TestClient(create_api(service=service))

    created = client.post("/projects", json={"name": "API Demo"}).json()
    response = client.post(
        f"/projects/{created['project_id']}/transition",
        json={"target_status": "COMPLETED"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_get_events(tmp_path):
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    service = ProjectService(persistence=persistence, event_store=event_store)
    client = TestClient(create_api(service=service))

    created = client.post("/projects", json={"name": "API Demo"}).json()
    client.post(
        f"/projects/{created['project_id']}/transition",
        json={"target_status": "ANALYZING"},
    )
    response = client.get(f"/projects/{created['project_id']}/events")
    assert response.status_code == 200
    body = response.json()
    assert len(body["events"]) == 2
    assert body["events"][0]["event_type"] == "PROJECT_CREATED"


def test_persistence_restart_via_api(tmp_path):
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    service = ProjectService(persistence=persistence, event_store=event_store)
    client = TestClient(create_api(service=service))

    created = client.post("/projects", json={"name": "API Restart"}).json()
    project_id = created["project_id"]

    new_service = ProjectService(persistence=ProjectPersistence(base_dir=tmp_path), event_store=EventStore(base_dir=tmp_path))
    new_client = TestClient(create_api(service=new_service))
    response = new_client.get(f"/projects/{project_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "API Restart"

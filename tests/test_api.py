from fastapi.testclient import TestClient

from app.api.app import api, create_api
from app.product.errors import (
    ActiveRunExistsError,
    CommandNotAllowedError,
    InvalidStateTransitionError,
    ProjectNotFoundError,
)
from app.product.event_store import EventStore
from app.product.project_artifact_store import ProjectArtifactStore
from app.product.project_persistence import ProjectPersistence
from app.product.service import ProjectService
from app.product.workflow import ProjectWorkflow
from app.schemas.project import ProjectStatus
from app.schemas.task import Task, TaskGraph, TaskStatus


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


def _to_planning(service: ProjectService, project_id: str, *, with_graph: bool = False, tmp_path=None) -> None:
    service.transition_to(project_id, ProjectStatus.ANALYZING)
    service.transition_to(project_id, ProjectStatus.PLANNING)
    if with_graph:
        workflow = ProjectWorkflow(
            jd_analyzer=None, matcher=None, blueprint_agent=None, task_engine=None,
            artifact_store=ProjectArtifactStore(base_dir=tmp_path),
        )
        graph = TaskGraph(
            project=project_id,
            tasks=[Task(id="T1", phase_id="P1", title="hello", goal="Create hello.txt", status=TaskStatus.PENDING)],
            total_tasks=1, required_tasks=1, optional_tasks=0,
        )
        service.update_artifact_ref(project_id, "task_graph", workflow.persist_task_graph(project_id, graph))


def test_transition_to_ready_is_blocked(tmp_path):
    service = ProjectService(persistence=ProjectPersistence(base_dir=tmp_path))
    client = TestClient(create_api(service=service))
    project_id = client.post("/projects", json={"name": "Gate"}).json()["project_id"]
    _to_planning(service, project_id)

    response = client.post(f"/projects/{project_id}/transition", json={"target_status": "READY"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPROVAL_REQUIRED"


def test_approve_without_plan_is_rejected(tmp_path):
    service = ProjectService(persistence=ProjectPersistence(base_dir=tmp_path))
    client = TestClient(create_api(service=service))
    project_id = client.post("/projects", json={"name": "Gate"}).json()["project_id"]
    _to_planning(service, project_id)

    response = client.post(f"/projects/{project_id}/approve")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PROJECT_STATE"
    assert service.load(project_id).status == ProjectStatus.PLANNING


def test_approve_with_plan_reaches_ready(tmp_path):
    service = ProjectService(persistence=ProjectPersistence(base_dir=tmp_path))
    client = TestClient(create_api(service=service))
    project_id = client.post("/projects", json={"name": "Gate"}).json()["project_id"]
    _to_planning(service, project_id, with_graph=True, tmp_path=tmp_path)

    response = client.post(f"/projects/{project_id}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "READY"
    assert service.load(project_id).status == ProjectStatus.READY

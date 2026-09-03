from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.product.errors import ProjectNotFoundError
from app.product.event_store import EventStore
from app.product.project_persistence import ProjectPersistence
from app.product.service import ProjectService
from app.schemas.event import Actor, ProductEvent
from app.schemas.project import ProjectStatus


def test_persistence_create_and_reload(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    service = ProjectService(persistence=persistence)
    project = service.create("persisted")
    reloaded = service.load(project.project_id)
    assert reloaded.name == "persisted"
    assert reloaded.status == ProjectStatus.CREATED
    assert reloaded.project_id == project.project_id


def test_persistence_transition_persists_state(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    service = ProjectService(persistence=persistence)
    project = service.create("persisted")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    new_service = ProjectService(persistence=persistence)
    reloaded = new_service.load(project.project_id)
    assert reloaded.status == ProjectStatus.READY
    assert reloaded.current_stage == ProjectStatus.READY.value


def test_persistence_missing_project_raises(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    service = ProjectService(persistence=persistence)
    with pytest.raises(ProjectNotFoundError):
        service.load("proj-missing")


def test_event_created_after_project_create(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    service = ProjectService(persistence=persistence, event_store=event_store)
    project = service.create("evented")
    events = event_store.get_events(project.project_id)
    assert [event.event_type for event in events] == ["PROJECT_CREATED"]


def test_event_created_after_transition(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    service = ProjectService(persistence=persistence, event_store=event_store)
    project = service.create("evented")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    events = event_store.get_events(project.project_id)
    types = [event.event_type for event in events]
    assert types == ["PROJECT_CREATED", "PROJECT_STATE_CHANGED", "PROJECT_STATE_CHANGED"]
    assert events[1].payload == {"from": "CREATED", "to": "ANALYZING"}
    assert events[2].payload == {"from": "ANALYZING", "to": "PLANNING"}


def test_event_query_returns_ordered_events(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    service = ProjectService(persistence=persistence, event_store=event_store)
    project = service.create("evented")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    events = event_store.get_events(project.project_id)
    assert [event.event_type for event in events] == [
        "PROJECT_CREATED",
        "PROJECT_STATE_CHANGED",
        "PROJECT_STATE_CHANGED",
    ]
    assert events[1].payload == {"from": "CREATED", "to": "ANALYZING"}
    assert events[2].payload == {"from": "ANALYZING", "to": "PLANNING"}


def test_event_immutability(tmp_path: Path) -> None:
    event_store = EventStore(base_dir=tmp_path)
    event = event_store.append(
        ProductEvent(
            event_id="evt-immutable",
            event_type="PROJECT_CREATED",
            project_id="proj-immutable",
            timestamp="2026-01-01T00:00:00Z",
            actor=Actor.SYSTEM,
            payload={"name": "immutable"},
        )
    )
    events = event_store.get_events("proj-immutable")
    assert len(events) == 1
    events[0].payload["name"] = "mutated"
    reloaded = event_store.get_events("proj-immutable")
    assert reloaded[0].payload == {"name": "immutable"}


def test_event_idempotent_append(tmp_path: Path) -> None:
    event_store = EventStore(base_dir=tmp_path)
    event = ProductEvent(
        event_id="evt-idempotent",
        event_type="PROJECT_CREATED",
        project_id="proj-idempotent",
        timestamp="2026-01-01T00:00:00Z",
        actor=Actor.SYSTEM,
        payload={"name": "idempotent"},
    )
    event_store.append(event)
    event_store.append(event)
    events = event_store.get_events("proj-idempotent")
    assert len(events) == 1


def test_concurrent_event_append(tmp_path: Path) -> None:
    event_store = EventStore(base_dir=tmp_path)
    project_id = "proj-concurrent"

    def append_event(index: int) -> None:
        event_store.append(
            ProductEvent(
                event_id=f"evt-concurrent-{index}",
                event_type="PROJECT_STATE_CHANGED",
                project_id=project_id,
                timestamp=f"2026-01-01T00:00:0{index}Z",
                actor=Actor.SYSTEM,
                payload={"from": "A", "to": "B"},
            )
        )

    threads = [threading.Thread(target=append_event, args=(i,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    events = event_store.get_events(project_id)
    assert len(events) == 5
    assert len({event.event_id for event in events}) == 5


def test_restart_preserves_project_and_events(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    event_store = EventStore(base_dir=tmp_path)
    service = ProjectService(persistence=persistence, event_store=event_store)
    project = service.create("restart")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)

    new_service = ProjectService(persistence=ProjectPersistence(base_dir=tmp_path), event_store=EventStore(base_dir=tmp_path))
    reloaded = new_service.load(project.project_id)
    assert reloaded.status == ProjectStatus.READY
    events = new_service.event_store.get_events(project.project_id)
    assert [event.event_type for event in events] == [
        "PROJECT_CREATED",
        "PROJECT_STATE_CHANGED",
        "PROJECT_STATE_CHANGED",
        "PROJECT_STATE_CHANGED",
    ]

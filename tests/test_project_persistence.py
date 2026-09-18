from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
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


def test_events_same_instant_keep_append_order_across_offset_spellings(tmp_path: Path) -> None:
    # ProjectService emits "...Z" and RunControl emits "...+00:00". For the same
    # instant a raw string sort puts '+' (0x2B) before 'Z' (0x5A), which would
    # reverse the append order. The store must sort by the parsed instant, so
    # equal instants keep append order.
    event_store = EventStore(base_dir=tmp_path)
    same_instant = "2026-01-01T00:00:01.000000"
    event_store.append(
        ProductEvent(
            event_id="evt-a", event_type="RUN_STARTED", project_id="proj-ord",
            timestamp=f"{same_instant}Z", actor=Actor.SYSTEM, payload={},
        )
    )
    event_store.append(
        ProductEvent(
            event_id="evt-b", event_type="RUN_PROGRESS", project_id="proj-ord",
            timestamp=f"{same_instant}+00:00", actor=Actor.SYSTEM, payload={},
        )
    )
    ids = [e.event_id for e in event_store.get_events("proj-ord")]
    assert ids == ["evt-a", "evt-b"]


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


def test_event_store_respects_existing_events_on_reseed(tmp_path: Path) -> None:
    # ⑥e: the seen-id set is lazily seeded from disk on first append, so a fresh
    # EventStore instance must still dedupe against events written earlier.
    first = EventStore(base_dir=tmp_path)
    first.append(
        ProductEvent(
            event_id="evt-seed",
            event_type="PROJECT_CREATED",
            project_id="proj-seed",
            timestamp="2026-01-01T00:00:00Z",
            actor=Actor.SYSTEM,
            payload={},
        )
    )
    second = EventStore(base_dir=tmp_path)
    second.append(
        ProductEvent(
            event_id="evt-seed",
            event_type="OTHER",
            project_id="proj-seed",
            timestamp="2026-01-01T00:00:00Z",
            actor=Actor.SYSTEM,
            payload={},
        )
    )
    events = second.get_events("proj-seed")
    assert len(events) == 1
    assert events[0].event_type == "PROJECT_CREATED"


def test_event_store_id_cache_is_per_project(tmp_path: Path) -> None:
    # Regression guard: a single instance-level id cache would leak ids across
    # projects, so a second project's pre-existing event could be written twice.
    first = EventStore(base_dir=tmp_path)
    first.append(
        ProductEvent(
            event_id="evt-shared", event_type="STEP", project_id="proj-B",
            timestamp="2026-01-01T00:00:00Z", actor=Actor.SYSTEM, payload={},
        )
    )
    # A fresh store touches project A first, then B, on the same instance.
    second = EventStore(base_dir=tmp_path)
    second.append(
        ProductEvent(
            event_id="evt-a", event_type="STEP", project_id="proj-A",
            timestamp="2026-01-01T00:00:00Z", actor=Actor.SYSTEM, payload={},
        )
    )
    second.append(
        ProductEvent(
            event_id="evt-shared", event_type="STEP", project_id="proj-B",
            timestamp="2026-01-01T00:00:00Z", actor=Actor.SYSTEM, payload={},
        )
    )
    # B already had evt-shared on disk; it must not be appended again.
    assert len(second.get_events("proj-B")) == 1


def test_event_store_does_not_rotate_by_default(tmp_path: Path) -> None:
    store = EventStore(base_dir=tmp_path)
    for i in range(10):
        store.append(
            ProductEvent(
                event_id=f"evt-{i}", event_type="STEP", project_id="proj-norot",
                timestamp="2026-01-01T00:00:00Z", actor=Actor.SYSTEM, payload={"i": i},
            )
        )
    events_dir = tmp_path / "proj-norot" / "events"
    assert list(events_dir.glob("events-*.jsonl")) == []
    assert len(store.get_events("proj-norot")) == 10


def test_event_store_rotates_and_keeps_history(tmp_path: Path) -> None:
    store = EventStore(base_dir=tmp_path, max_file_bytes=200)
    n = 30
    for i in range(n):
        store.append(
            ProductEvent(
                event_id=f"evt-{i}", event_type="STEP", project_id="proj-rot",
                timestamp=f"2026-01-01T00:00:{i:02d}Z", actor=Actor.SYSTEM, payload={"i": i},
            )
        )
    # rotation happened ...
    events_dir = tmp_path / "proj-rot" / "events"
    assert len(list(events_dir.glob("events-*.jsonl"))) >= 1
    # ... yet no history is lost: every shard is still read back
    events = store.get_events("proj-rot")
    assert len(events) == n
    assert [e.event_id for e in events] == [f"evt-{i}" for i in range(n)]


def test_event_store_dedupes_across_rotation(tmp_path: Path) -> None:
    store = EventStore(base_dir=tmp_path, max_file_bytes=200)
    for i in range(20):
        store.append(
            ProductEvent(
                event_id=f"evt-{i}", event_type="STEP", project_id="proj-dedup",
                timestamp=f"2026-01-01T00:00:{i:02d}Z", actor=Actor.SYSTEM, payload={"i": i},
            )
        )
    # A fresh instance must load ids from rotated shards too, not just the active file.
    fresh = EventStore(base_dir=tmp_path, max_file_bytes=200)
    fresh.append(
        ProductEvent(
            event_id="evt-0", event_type="STEP", project_id="proj-dedup",
            timestamp="2026-01-01T00:00:00Z", actor=Actor.SYSTEM, payload={},
        )
    )
    assert len(fresh.get_events("proj-dedup")) == 20


def test_event_store_scales_without_duplicate_lines(tmp_path: Path) -> None:
    # Many appends must yield exactly that many lines (no per-append re-read
    # growth, and no silent drops from id collisions).
    store = EventStore(base_dir=tmp_path)
    n = 50
    for i in range(n):
        store.append(
            ProductEvent(
                event_id=f"evt-{i}",
                event_type="STEP",
                project_id="proj-scale",
                timestamp="2026-01-01T00:00:00Z",
                actor=Actor.SYSTEM,
                payload={"i": i},
            )
        )
    path = tmp_path / "proj-scale" / "events" / "events.jsonl"
    assert len(path.read_text(encoding="utf-8").splitlines()) == n
    assert len(store.get_events("proj-scale")) == n


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


def test_rapid_event_appends_are_never_dropped_or_reordered(tmp_path: Path) -> None:
    # Wall-clock-only ids collide on coarse timer granularity; a collision
    # used to be silently swallowed by append()'s dedupe.
    from app.product.event_store import new_event_id

    store = EventStore(base_dir=tmp_path)
    project_id = "proj-rapid"
    count = 200
    for index in range(count):
        store.append(
            ProductEvent(
                event_id=new_event_id(),
                event_type="EVT",
                project_id=project_id,
                run_id="",
                actor=Actor.SYSTEM,
                timestamp=datetime.now(timezone.utc).isoformat(),
                payload={"index": index},
            )
        )
    events = store.get_events(project_id)
    assert len(events) == count
    assert len({e.event_id for e in events}) == count
    assert [e.payload["index"] for e in events] == list(range(count))

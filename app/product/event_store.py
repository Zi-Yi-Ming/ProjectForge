from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.schemas.event import Actor, ProductEvent


def new_event_id() -> str:
    # Wall-clock microseconds alone collide (Windows timer granularity is
    # ~1ms), and append() dedupes by id -- a collision silently drops events.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"evt-{stamp}-{secrets.token_hex(4)}"


class EventStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(".runtime/projects")
        self._lock = Lock()
        # Lazily seeded set of known event ids for the lifetime of this store.
        # Replacing the old per-append full-file re-read (O(n^2) total) with a
        # one-time load + incremental updates keeps append() effectively O(1).
        self._seen_ids: set[str] | None = None

    def _load_seen_ids(self, path: Path) -> set[str]:
        ids: set[str] = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    ids.add(json.loads(line).get("event_id"))
                except json.JSONDecodeError:
                    continue
        return ids

    def append(self, event: ProductEvent) -> ProductEvent:
        project_dir = self.base_dir / event.project_id / "events"
        project_dir.mkdir(parents=True, exist_ok=True)
        path = project_dir / "events.jsonl"
        payload = event.model_dump()
        payload["actor"] = event.actor.value if isinstance(event.actor, Actor) else str(event.actor)
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            if self._seen_ids is None:
                self._seen_ids = self._load_seen_ids(path)
            if event.event_id in self._seen_ids:
                return event
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._seen_ids.add(event.event_id)
        return event

    def get_events(self, project_id: str) -> list[ProductEvent]:
        path = self.base_dir / project_id / "events" / "events.jsonl"
        if not path.exists():
            return []
        events: list[ProductEvent] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    actor_value = data.get("actor", "SYSTEM")
                    if isinstance(actor_value, str):
                        data["actor"] = Actor(actor_value)
                    events.append(ProductEvent.model_validate(data))
                except (json.JSONDecodeError, ValueError):
                    continue
        # Stable sort on timestamp only: ties keep append order, which is the
        # event log's source of truth (ids are not order-significant).
        events.sort(key=lambda e: e.timestamp)
        return events

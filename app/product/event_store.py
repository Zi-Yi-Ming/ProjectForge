from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any

from app.schemas.event import Actor, ProductEvent


class EventStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(".runtime/projects")
        self._lock = Lock()

    def append(self, event: ProductEvent) -> ProductEvent:
        project_dir = self.base_dir / event.project_id / "events"
        project_dir.mkdir(parents=True, exist_ok=True)
        path = project_dir / "events.jsonl"
        payload = event.model_dump()
        payload["actor"] = event.actor.value if isinstance(event.actor, Actor) else str(event.actor)
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            existing_ids = set()
            if path.exists():
                for existing_line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        existing_event = json.loads(existing_line)
                        existing_ids.add(existing_event.get("event_id"))
                    except json.JSONDecodeError:
                        continue
            if event.event_id in existing_ids:
                return event
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
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
        events.sort(key=lambda e: (e.timestamp, e.event_id))
        return events

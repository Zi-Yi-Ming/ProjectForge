from __future__ import annotations

import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.schemas.event import Actor, ProductEvent

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - platform-specific
    fcntl = None

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - platform-specific
    msvcrt = None


@contextmanager
def _file_lock(lock_path: Path):
    """Advisory exclusive lock on a sidecar file, serializing appends across
    processes (a CLI run and a long-lived API server sharing one events dir).

    Falls back to a no-op when neither fcntl nor msvcrt is available, so the
    store still works (single-process, threading.Lock-guarded) on exotic
    platforms — just without cross-process serialization there.
    """
    if fcntl is None and msvcrt is None:
        yield
        return
    with open(lock_path, "a+b") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        else:  # msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def new_event_id() -> str:
    # Wall-clock microseconds alone collide (Windows timer granularity is
    # ~1ms), and append() dedupes by id -- a collision silently drops events.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"evt-{stamp}-{secrets.token_hex(4)}"


class EventStore:
    ACTIVE_FILENAME = "events.jsonl"
    ROTATED_PATTERN = "events-*.jsonl"

    def __init__(self, base_dir: Path | None = None, max_file_bytes: int | None = None) -> None:
        self.base_dir = base_dir or Path(".runtime/projects")
        self._lock = Lock()
        # Rotation is opt-in: None keeps one ever-growing file, as before.
        self.max_file_bytes = max_file_bytes
        # Lazily seeded id sets, keyed *per project*. A single instance-level set
        # would leak ids across projects, so a pre-existing event of a second
        # project could be appended twice. One load per project (not per append)
        # keeps append() effectively O(1) without the old O(n^2) re-read.
        self._seen: dict[str, set[str]] = {}

    def _events_dir(self, project_id: str) -> Path:
        return self.base_dir / project_id / "events"

    def _lock_path(self, project_dir: Path) -> Path:
        return project_dir / ".append.lock"

    def _shard_paths(self, project_dir: Path) -> list[Path]:
        """Rotated shards (oldest first) plus the active file when present.

        Rotated names embed a fixed-width timestamp, so lexical sort is
        chronological.
        """
        shards = sorted(project_dir.glob(self.ROTATED_PATTERN))
        active = project_dir / self.ACTIVE_FILENAME
        if active.exists():
            shards.append(active)
        return shards

    def _load_seen_ids(self, paths: list[Path]) -> set[str]:
        ids: set[str] = set()
        for path in paths:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    ids.add(json.loads(line).get("event_id"))
                except json.JSONDecodeError:
                    continue
        return ids

    def _rotate_if_needed(self, project_dir: Path, active: Path) -> None:
        if not self.max_file_bytes or not active.exists():
            return
        try:
            if active.stat().st_size < self.max_file_bytes:
                return
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
            os.replace(active, project_dir / f"events-{stamp}-{secrets.token_hex(4)}.jsonl")
        except Exception:
            return

    def append(self, event: ProductEvent) -> ProductEvent:
        project_dir = self._events_dir(event.project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        active = project_dir / self.ACTIVE_FILENAME
        payload = event.model_dump()
        payload["actor"] = event.actor.value if isinstance(event.actor, Actor) else str(event.actor)
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock, _file_lock(self._lock_path(project_dir)):
            if event.project_id not in self._seen:
                self._seen[event.project_id] = self._load_seen_ids(self._shard_paths(project_dir))
            if event.event_id in self._seen[event.project_id]:
                return event
            with active.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._seen[event.project_id].add(event.event_id)
            self._rotate_if_needed(project_dir, active)
        return event

    @staticmethod
    def _sort_key(event: ProductEvent) -> datetime:
        # Producers emit UTC but in two spellings: "...Z" (ProjectService) and
        # "...+00:00" (RunControl/ReplanControl). A raw string compare puts
        # '+00:00' before 'Z' for the SAME instant, so interleaved events get
        # reversed. Sort by the parsed instant instead; equal instants keep
        # append order (the stable sort), which is the log's source of truth.
        ts = event.timestamp or ""
        # datetime.fromisoformat only accepts a trailing "Z" from 3.11; target
        # is 3.10+, so normalize it to an explicit offset first.
        text = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def get_events(self, project_id: str) -> list[ProductEvent]:
        project_dir = self._events_dir(project_id)
        events: list[ProductEvent] = []
        # Read every shard: rotated history must stay visible, otherwise
        # rotation would silently hide older events.
        for path in self._shard_paths(project_dir):
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
        # Stable sort on the parsed instant: ties keep append order, which is
        # the event log's source of truth (ids are not order-significant).
        events.sort(key=self._sort_key)
        return events

from __future__ import annotations

import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.schemas.implementation import TaskContract


@runtime_checkable
class WorkspaceProvider(Protocol):
    """Decides which directory a single task executes in.

    A serial run hands back the one shared workspace for every task, so the
    dependency chain keeps seeing prior tasks' files on disk. A parallel run
    resolves a per-branch worktree here, which is what lets the adapter stop
    owning a fixed directory.
    """

    def workspace_for(self, task: TaskContract) -> Path | None:
        ...


class FixedWorkspaceProvider:
    """Always returns the same directory — the shared ``run_dir`` of a serial run."""

    def __init__(self, workspace: Path | None) -> None:
        self._workspace = workspace

    def workspace_for(self, task: TaskContract) -> Path | None:
        return self._workspace


class WorktreeWorkspaceProvider:
    """Routes each bound task to its own worktree, unbound tasks to ``run_dir``.

    The lock guards cross-thread access: parallel dispatch (step 3b) binds a
    task to its worktree from the dispatcher thread while the adapter reads the
    mapping from a worker thread. The ``run_dir`` fallback lets one provider
    serve a mixed serial + parallel segment.
    """

    def __init__(self, run_dir: Path | None) -> None:
        self._run_dir = run_dir
        self._lock = threading.Lock()
        self._bindings: dict[str, Path] = {}

    def bind(self, task_id: str, path: Path) -> None:
        with self._lock:
            self._bindings[task_id] = Path(path)

    def unbind(self, task_id: str) -> None:
        with self._lock:
            self._bindings.pop(task_id, None)

    def workspace_for(self, task: TaskContract) -> Path | None:
        with self._lock:
            return self._bindings.get(task.task_id, self._run_dir)

from __future__ import annotations

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

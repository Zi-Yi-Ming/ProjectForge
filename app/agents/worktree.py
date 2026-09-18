from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class WorktreeError(RuntimeError):
    """A git worktree operation that must not be swallowed failed loudly."""


@dataclass
class MergeResult:
    ok: bool
    conflicted_files: list[str] = field(default_factory=list)
    detail: str = ""


class WorktreeManager:
    """Git worktree lifecycle for one run.

    Isolates a task on its own branch/worktree off a base commit, merges the
    branch back into the primary checkout, and cleans up. Deliberately kept
    apart from the orchestrator so the destructive git surface is independently
    testable and parallel dispatch (step 3b) stays opt-in.
    """

    def __init__(self, repo_root: Path, timeout: int = 60) -> None:
        self.repo_root = Path(repo_root)
        self.timeout = timeout

    def _git(self, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout,
        )

    @staticmethod
    def _out(proc: subprocess.CompletedProcess) -> str:
        return proc.stdout.decode("utf-8", "replace").strip()

    @staticmethod
    def _err(proc: subprocess.CompletedProcess) -> str:
        return proc.stderr.decode("utf-8", "replace").strip()

    def head(self) -> str:
        proc = self._git(["rev-parse", "HEAD"])
        return self._out(proc) if proc.returncode == 0 else ""

    def conflicts(self) -> list[str]:
        proc = self._git(["diff", "--name-only", "--diff-filter=U"])
        if proc.returncode != 0:
            return []
        return [line.strip() for line in self._out(proc).splitlines() if line.strip()]

    def create(self, branch: str, path: Path, base: str = "HEAD") -> Path:
        path = Path(path)
        proc = self._git(["worktree", "add", "-b", branch, str(path), base])
        if proc.returncode != 0:
            raise WorktreeError(f"git worktree add failed: {self._err(proc)}")
        return path

    def merge(self, branch: str) -> MergeResult:
        proc = self._git(["merge", "--no-ff", "--no-edit", branch])
        if proc.returncode == 0:
            return MergeResult(ok=True, detail=self._out(proc))
        conflicted = self.conflicts()
        # Restore the primary tree exactly as it stood before the attempt; a
        # conflict becomes a FAILED task upstream, never a half-merged tree.
        self._git(["merge", "--abort"])
        return MergeResult(ok=False, conflicted_files=conflicted, detail=self._err(proc))

    def remove(self, path: Path, branch: str | None = None) -> None:
        path = Path(path)
        self._git(["worktree", "remove", "--force", str(path)])
        if branch:
            self._git(["branch", "-D", branch])
        self._git(["worktree", "prune"])

"""Regression tests for workspace git isolation.

Bug background (2026-09-13): a run workspace that is merely *nested*
inside an unrelated parent repository made the orchestrator's baseline
check short-circuit ("already inside a work tree") and the CLI adapter
commit task artifacts into the parent repo's history. Real-world symptom:
the VM checkout accumulated ``task T_REAL`` commits authored by the user
instead of the isolated demo workspace.

The fix has two layers:
1. ``ExecutionOrchestrator._ensure_git_baseline`` must create a nested,
   self-contained repo when the run dir is not the repository root.
2. ``CliAgentAdapter`` must refuse to commit unless the workspace *owns*
   its repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agents.orchestrator import ExecutionOrchestrator


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], path)
    _git(["config", "user.email", "outer@test.local"], path)
    _git(["config", "user.name", "Outer"], path)
    (path / "outer.txt").write_text("outer\n", encoding="utf-8")
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "outer baseline"], path)


def _head(path: Path) -> str:
    return _git(["rev-parse", "HEAD"], path).stdout.decode().strip()


def _toplevel(path: Path) -> Path:
    raw = _git(["rev-parse", "--show-toplevel"], path).stdout.decode().strip()
    return Path(raw).resolve()


def _orchestrator() -> ExecutionOrchestrator:
    from tests.fakes import FakeExecutor  # noqa: F401  (import sanity)

    class _Noop:
        pass

    return ExecutionOrchestrator(adapter=_Noop())  # type: ignore[arg-type]


def test_baseline_creates_nested_repo_when_inside_foreign_repo(tmp_path: Path) -> None:
    """A workspace nested in a parent repo must get its own repository."""
    outer = tmp_path / "outer"
    _init_repo(outer)
    workspace = outer / "workspaces" / "proj-1"
    workspace.mkdir(parents=True)

    orchestrator = _orchestrator()
    orchestrator._ensure_git_baseline(workspace)

    # The workspace now owns a repository rooted at itself...
    assert _toplevel(workspace) == workspace.resolve()
    # ...and the parent repo's HEAD is untouched.
    assert _head(outer) == _git(["rev-parse", "HEAD"], outer).stdout.decode().strip()
    assert _head(outer) != _head(workspace)


def test_baseline_does_not_reuse_parent_repo_for_nested_workspace(tmp_path: Path) -> None:
    """Committing in the workspace must not add commits to the parent repo."""
    outer = tmp_path / "outer"
    _init_repo(outer)
    parent_head_before = _head(outer)

    workspace = outer / "runs" / "run-1" / "ws"
    workspace.mkdir(parents=True)

    orchestrator = _orchestrator()
    orchestrator._ensure_git_baseline(workspace)

    # Simulate what the CLI adapter does after a task.
    _git(["config", "user.email", "inner@test.local"], workspace)
    _git(["config", "user.name", "Inner"], workspace)
    (workspace / "artifact.py").write_text("x = 1\n", encoding="utf-8")
    _git(["add", "-A"], workspace)
    _git(["commit", "-q", "-m", "task T1", "--allow-empty"], workspace)

    # Parent history is unchanged: the task commit stayed in the workspace.
    assert _head(outer) == parent_head_before
    assert _head(workspace) != parent_head_before


def test_baseline_reuses_own_repo_when_workspace_is_toplevel(tmp_path: Path) -> None:
    """A workspace that already owns its repo keeps its existing history."""
    workspace = tmp_path / "ws"
    _init_repo(workspace)
    head_before = _head(workspace)
    (workspace / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    orchestrator = _orchestrator()
    orchestrator._ensure_git_baseline(workspace)

    # Existing repo with commits is left alone (no baseline commit added).
    assert _head(workspace) == head_before


def test_baseline_inits_repo_when_no_git_at_all(tmp_path: Path) -> None:
    """A plain directory outside any repo gets initialised as before."""
    workspace = tmp_path / "plain"  # tmp_path itself is not a git repo
    workspace.mkdir()

    orchestrator = _orchestrator()
    orchestrator._ensure_git_baseline(workspace)

    assert _toplevel(workspace) == workspace.resolve()
    assert _head(workspace)  # baseline commit exists


# --- second layer: the CLI adapter must refuse foreign-repo commits ---


def test_adapter_refuses_commit_when_workspace_did_not_get_its_own_repo(tmp_path: Path) -> None:
    """Even without the orchestrator baseline, the adapter must not commit
    task artifacts into a foreign parent repository."""
    from app.agents.cli_adapter import CliAgentAdapter
    from app.schemas.implementation import ProjectMap, TaskContract

    outer = tmp_path / "outer"
    _init_repo(outer)
    parent_head_before = _head(outer)

    # Deliberately skip the orchestrator baseline to exercise the guard.
    workspace = outer / "leaked" / "ws"
    workspace.mkdir(parents=True)
    (workspace / "artifact.py").write_text("x = 1\n", encoding="utf-8")

    class _Adapter(CliAgentAdapter):
        def agent_name(self) -> str:  # pragma: no cover - not used
            return "fake"

        def find_binary(self) -> str:  # pragma: no cover - not used
            return "fake"

        def build_argv(self, prompt: str) -> list[str]:  # pragma: no cover
            return []

        def _run(self, task_contract: TaskContract, project_map: ProjectMap):  # pragma: no cover
            raise NotImplementedError

    adapter = _Adapter(workspace=workspace)
    assert adapter._workspace_owns_repo(workspace) is False
    adapter._commit_task_changes(workspace, "T1")

    # No commit leaked into the parent repository.
    assert _head(outer) == parent_head_before
    # The workspace files stay untracked (never staged into the parent repo).
    tracked = _git(["ls-files"], outer).stdout.decode().strip()
    assert "leaked" not in tracked


def test_checkpoint_before_is_empty_for_foreign_repo(tmp_path: Path) -> None:
    """Checkpoint reads must not borrow HEAD from a foreign parent repo."""
    from app.agents.cli_adapter import CliAgentAdapter

    outer = tmp_path / "outer"
    _init_repo(outer)
    workspace = outer / "nested" / "ws"
    workspace.mkdir(parents=True)

    class _Adapter(CliAgentAdapter):
        def agent_name(self) -> str:  # pragma: no cover
            return "fake"

        def find_binary(self) -> str:  # pragma: no cover
            return "fake"

        def build_argv(self, prompt: str) -> list[str]:  # pragma: no cover
            return []

        def _run(self, task_contract, project_map):  # pragma: no cover
            raise NotImplementedError

    adapter = _Adapter(workspace=workspace)
    head_before, pre_existing = adapter._git_checkpoint_before(workspace)
    assert head_before == ""
    assert pre_existing == []


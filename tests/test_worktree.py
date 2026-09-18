from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agents.mock_executor import MockExecutor
from app.agents.worktree import WorktreeManager
from app.agents.workspace_provider import WorkspaceProvider, WorktreeWorkspaceProvider
from app.schemas.implementation import ProjectMap, TaskContract


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "main"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "PF Test")
    _git(root, "config", "user.email", "pf@test.local")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    (root / "shared.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "baseline")
    return root


def _commit_in(worktree: Path, filename: str, content: str, message: str) -> None:
    (worktree / filename).write_text(content, encoding="utf-8")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", message)


def test_head_reports_baseline_commit(repo: Path) -> None:
    mgr = WorktreeManager(repo)
    head = mgr.head()
    assert head
    assert head == _git(repo, "rev-parse", "HEAD")


def test_create_write_commit_merge_back(repo: Path, tmp_path: Path) -> None:
    mgr = WorktreeManager(repo)
    wt = tmp_path / "wt-a"
    mgr.create("pf/a", wt)
    assert wt.is_dir()
    _commit_in(wt, "a.py", "print('a')\n", "task a")

    result = mgr.merge("pf/a")
    assert result.ok
    assert (repo / "a.py").exists()

    mgr.remove(wt, "pf/a")
    assert not wt.exists()


def test_two_independent_branches_both_merge(repo: Path, tmp_path: Path) -> None:
    mgr = WorktreeManager(repo)
    wa = tmp_path / "wt-a"
    wb = tmp_path / "wt-b"
    mgr.create("pf/a", wa)
    mgr.create("pf/b", wb)
    _commit_in(wa, "a.py", "a\n", "task a")
    _commit_in(wb, "b.py", "b\n", "task b")

    assert mgr.merge("pf/a").ok
    assert mgr.merge("pf/b").ok
    assert (repo / "a.py").exists()
    assert (repo / "b.py").exists()


def test_merge_conflict_lists_files_and_aborts_clean(repo: Path, tmp_path: Path) -> None:
    mgr = WorktreeManager(repo)
    wa = tmp_path / "wt-a"
    wb = tmp_path / "wt-b"
    mgr.create("pf/a", wa)
    mgr.create("pf/b", wb)
    _commit_in(wa, "shared.txt", "from A\n", "a touches shared")
    _commit_in(wb, "shared.txt", "from B\n", "b touches shared")

    assert mgr.merge("pf/a").ok
    head_after_a = mgr.head()

    conflict = mgr.merge("pf/b")
    assert not conflict.ok
    assert "shared.txt" in conflict.conflicted_files

    # The abort left the primary tree exactly as it was after the successful merge:
    # no leftover conflict markers, no half-merged state, HEAD unmoved.
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "from A\n"
    assert mgr.conflicts() == []
    assert mgr.head() == head_after_a


def test_provider_binds_and_falls_back(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bound = tmp_path / "bound"
    bound.mkdir()
    provider = WorktreeWorkspaceProvider(run_dir)

    assert provider.workspace_for(TaskContract(task_id="T1")) == run_dir  # unbound
    provider.bind("T2", bound)
    assert provider.workspace_for(TaskContract(task_id="T2")) == bound
    provider.unbind("T2")
    assert provider.workspace_for(TaskContract(task_id="T2")) == run_dir


def test_provider_satisfies_protocol_and_drives_executor(tmp_path: Path) -> None:
    assert isinstance(WorktreeWorkspaceProvider(None), WorkspaceProvider)

    shared = tmp_path / "shared"
    shared.mkdir()
    branch = tmp_path / "branch"
    branch.mkdir()
    provider = WorktreeWorkspaceProvider(shared)
    provider.bind("T9", branch)

    MockExecutor(workspace=shared, workspace_provider=provider).execute(
        TaskContract(task_id="T9"), ProjectMap()
    )
    assert (branch / "t9_impl.txt").exists()
    assert not (shared / "t9_impl.txt").exists()

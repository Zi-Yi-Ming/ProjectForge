from __future__ import annotations

from pathlib import Path

from app.agents.cli_adapter import CliAgentAdapter
from app.agents.mock_executor import MockExecutor
from app.agents.workspace_provider import FixedWorkspaceProvider, WorkspaceProvider
from app.schemas.implementation import ExecutionStatus, ProjectMap, TaskContract


def _contract(task_id: str) -> TaskContract:
    return TaskContract(task_id=task_id)


class _RoutingProvider:
    """Hands each task id its own directory — a stand-in for per-branch worktrees."""

    def __init__(self, mapping: dict[str, Path]) -> None:
        self._mapping = mapping

    def workspace_for(self, task: TaskContract) -> Path | None:
        return self._mapping[task.task_id]


class _StubAdapter(CliAgentAdapter):
    def agent_name(self) -> str:  # pragma: no cover - trivial
        return "stub"

    def find_binary(self) -> str:  # pragma: no cover - trivial
        return "stub"

    def build_argv(self, prompt: str) -> list[str]:  # pragma: no cover - trivial
        return []


def test_fixed_provider_returns_same_dir_for_every_task(tmp_path: Path) -> None:
    provider = FixedWorkspaceProvider(tmp_path)
    assert provider.workspace_for(_contract("T1")) == tmp_path
    assert provider.workspace_for(_contract("T2")) == tmp_path


def test_fixed_provider_can_hold_none() -> None:
    assert FixedWorkspaceProvider(None).workspace_for(_contract("T1")) is None


def test_fixed_provider_satisfies_protocol() -> None:
    assert isinstance(FixedWorkspaceProvider(Path(".")), WorkspaceProvider)


def test_mock_executor_default_uses_shared_workspace(tmp_path: Path) -> None:
    ex = MockExecutor(workspace=tmp_path)
    result = ex.execute(_contract("T1"), ProjectMap())
    assert (tmp_path / "t1_impl.txt").exists()
    assert "t1_impl.txt" in result.changed_files


def test_mock_executor_routes_each_task_to_provider_dir(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    ex = MockExecutor(workspace=tmp_path, workspace_provider=_RoutingProvider({"T1": a, "T2": b}))
    ex.execute(_contract("T1"), ProjectMap())
    ex.execute(_contract("T2"), ProjectMap())
    assert (a / "t1_impl.txt").exists()
    assert (b / "t2_impl.txt").exists()
    # The shared attribute directory stays untouched: the provider is the source of truth.
    assert not (tmp_path / "t1_impl.txt").exists()


def test_mock_executor_none_provider_workspace_writes_nothing(tmp_path: Path) -> None:
    ex = MockExecutor(workspace=tmp_path, workspace_provider=FixedWorkspaceProvider(None))
    result = ex.execute(_contract("T1"), ProjectMap())
    assert result.status == ExecutionStatus.IMPLEMENTED
    assert result.changed_files == []
    assert not (tmp_path / "t1_impl.txt").exists()


def test_cli_adapter_default_provider_resolves_to_workspace(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    stub = _StubAdapter(workspace=missing)
    result = stub.execute(_contract("T1"), ProjectMap())
    assert result.status == ExecutionStatus.ERROR
    assert any(str(missing) in err for err in result.errors)


def test_cli_adapter_provider_overrides_workspace_attribute(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    # self.workspace points at a real dir, but the provider returns a missing one;
    # the not-found error proves the run resolved its workspace through the provider.
    stub = _StubAdapter(workspace=tmp_path, workspace_provider=FixedWorkspaceProvider(missing))
    result = stub.execute(_contract("T1"), ProjectMap())
    assert result.status == ExecutionStatus.ERROR
    assert any(str(missing) in err for err in result.errors)

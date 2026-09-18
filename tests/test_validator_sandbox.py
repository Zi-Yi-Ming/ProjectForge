from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.agents.mock_executor import MockExecutor
from app.agents.sandbox_policy import (
    SandboxUnavailableError,
    ValidatorSandboxPolicy,
)
from app.agents.validator import DeterministicValidator
from app.product.service import ProjectService, resolve_validator_sandbox_enabled


class _FakeProc:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = b"ok"
        self.stderr = b""


class _RecordingPolicy:
    """SandboxPolicy stand-in: records the argv it was asked to wrap and returns
    a recognizable wrapped command."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, list[str]]] = []

    def is_available(self) -> bool:
        return True

    def wrap(self, workspace: Path, command: list[str]) -> list[str]:
        self.calls.append((workspace, list(command)))
        return ["bwrap-sim", *command]


class _UnavailablePolicy:
    def is_available(self) -> bool:
        return False

    def wrap(self, workspace: Path, command: list[str]) -> list[str]:
        raise SandboxUnavailableError("bwrap missing")


# --- DeterministicValidator._run_command wrapping behavior ---

def test_validator_wraps_argv_when_policy_set(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0)

    monkeypatch.setattr("app.agents.validator.subprocess.run", fake_run)
    policy = _RecordingPolicy()
    validator = DeterministicValidator(sandbox_policy=policy)

    result = validator._run_command([sys.executable, "-m", "pytest", "-q"], workspace=Path("/ws"))

    assert result.exit_code == 0
    # subprocess receives the wrapped command, not the bare one
    assert seen["argv"][0] == "bwrap-sim"
    assert list(seen["argv"])[1:] == [sys.executable, "-m", "pytest", "-q"]
    # the policy saw the original (unwrapped) argv and the workspace
    assert policy.calls[0][1] == [sys.executable, "-m", "pytest", "-q"]


def test_validator_leaves_argv_untouched_without_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0)

    monkeypatch.setattr("app.agents.validator.subprocess.run", fake_run)
    validator = DeterministicValidator()

    validator._run_command([sys.executable, "-m", "pytest", "-q"], workspace=Path("/ws"))

    assert seen["argv"] == [sys.executable, "-m", "pytest", "-q"]


def test_validator_tokenizes_string_command_then_wraps(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0)

    monkeypatch.setattr("app.agents.validator.subprocess.run", fake_run)
    validator = DeterministicValidator(sandbox_policy=_RecordingPolicy())

    # custom string command is tokenized (no shell) then handed to the policy
    validator._run_command("pytest -q", workspace=Path("/ws"))
    assert seen["argv"][0] == "bwrap-sim"
    assert list(seen["argv"])[1:] == ["pytest", "-q"]


def test_validator_fails_closed_when_sandbox_unavailable() -> None:
    validator = DeterministicValidator(sandbox_policy=_UnavailablePolicy())
    result = validator._run_command([sys.executable, "-m", "pytest"], workspace=Path("/ws"))
    # never raises out to abort the run; surfaces as a failed command
    assert result.exit_code == -1
    assert "bwrap missing" in result.stderr


# --- ValidatorSandboxPolicy emitted command ---

def test_validator_sandbox_policy_wraps_expected_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)
    policy = ValidatorSandboxPolicy()
    ws = tmp_path / "work"
    ws.mkdir()

    wrapped = policy.wrap(ws, [sys.executable, "-m", "pytest", "-q"])

    assert wrapped[0] == "bwrap"
    assert "--unshare-pid" in wrapped and "--unshare-ipc" in wrapped
    # host read-only, workspace the only writable bind
    assert wrapped.count("--ro-bind") == 1 and wrapped[wrapped.index("--ro-bind") + 1] == "/"
    ws_abs = str(ws.resolve())
    assert wrapped[wrapped.index("--bind") + 1] == ws_abs and wrapped[wrapped.index("--bind") + 2] == ws_abs
    # scratch space + original command tail preserved
    assert "--tmpfs" in wrapped
    assert wrapped[-4:] == [sys.executable, "-m", "pytest", "-q"]
    # running tests needs no credentials: no agent config/home mounts
    joined = " ".join(wrapped)
    assert ".hermes" not in joined and "--ro-bind" in joined


def test_validator_sandbox_policy_unavailable_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    policy = ValidatorSandboxPolicy()
    assert policy.is_available() is False
    with pytest.raises(SandboxUnavailableError):
        policy.wrap(tmp_path, ["pytest"])


# --- service resolver + wiring ---

@pytest.mark.parametrize(
    "value,expected",
    [("", True), ("1", True), ("true", True), ("on", True), ("0", False), ("false", False), ("off", False), ("no", False)],
)
def test_resolve_validator_sandbox_enabled(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("PROJECTFORGE_VALIDATOR_SANDBOX", value)
    assert resolve_validator_sandbox_enabled() is expected


def test_mock_execution_path_validator_not_sandboxed(tmp_path: Path) -> None:
    service = ProjectService(
        base_dir=tmp_path,
        executor_factory=lambda run_dir, timeout: MockExecutor(workspace=run_dir),
    )
    orch = service._build_executor(tmp_path / "ws")
    # injected factory => not the real path => validator stays on the host
    assert orch.validator.sandbox_policy is None


def test_real_path_validator_sandboxed_when_bwrap_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)
    service = ProjectService(base_dir=tmp_path)  # no factory => real path
    policy = service._validator_sandbox_policy(real_execution=True)
    assert isinstance(policy, ValidatorSandboxPolicy)


def test_real_path_validator_not_sandboxed_without_bwrap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    service = ProjectService(base_dir=tmp_path)
    assert service._validator_sandbox_policy(real_execution=True) is None

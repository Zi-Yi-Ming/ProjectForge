from __future__ import annotations

import pytest

from app.product.service import (
    DEFAULT_TASK_TIMEOUT_SECONDS,
    ProjectService,
    resolve_event_max_file_bytes,
    resolve_max_run_seconds,
    resolve_rollback_on_failure,
    resolve_task_timeout,
)


def test_default_timeout_is_300() -> None:
    assert resolve_task_timeout() == DEFAULT_TASK_TIMEOUT_SECONDS == 300


def test_explicit_value_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECTFORGE_TASK_TIMEOUT_SECONDS", "999")
    assert resolve_task_timeout(42) == 42


def test_env_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECTFORGE_TASK_TIMEOUT_SECONDS", "120")
    assert resolve_task_timeout() == 120


@pytest.mark.parametrize("bad", ["abc", "0", "-5", ""])
def test_invalid_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("PROJECTFORGE_TASK_TIMEOUT_SECONDS", bad)
    assert resolve_task_timeout() == DEFAULT_TASK_TIMEOUT_SECONDS


def test_event_max_file_bytes_unset_means_no_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROJECTFORGE_EVENT_MAX_FILE_BYTES", raising=False)
    assert resolve_event_max_file_bytes() is None


def test_event_max_file_bytes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECTFORGE_EVENT_MAX_FILE_BYTES", "1048576")
    assert resolve_event_max_file_bytes() == 1048576


@pytest.mark.parametrize("bad", ["abc", "0", "-1", ""])
def test_event_max_file_bytes_invalid_is_no_rotation(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("PROJECTFORGE_EVENT_MAX_FILE_BYTES", bad)
    assert resolve_event_max_file_bytes() is None


def test_service_passes_timeout_to_executor_factory(tmp_path) -> None:
    seen: list[tuple] = []

    def factory(run_dir, timeout_seconds):
        seen.append((run_dir, timeout_seconds))
        return None  # unused: we only assert the factory contract

    service = ProjectService(base_dir=tmp_path, executor_factory=factory, task_timeout=42)
    service._build_executor(tmp_path / "ws")
    assert seen == [(tmp_path / "ws", 42)]


def test_service_timeout_resolves_from_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECTFORGE_TASK_TIMEOUT_SECONDS", "77")
    service = ProjectService(base_dir=tmp_path)
    assert service.task_timeout == 77


def test_self_test_timeout_follows_task_timeout(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # ⑥c: the validator's self-test timeout was a hardcoded 120s that ignored the
    # configured --timeout. It must now be governed by the same knob.
    monkeypatch.delenv("PROJECTFORGE_MAX_RUN_SECONDS", raising=False)
    service = ProjectService(base_dir=tmp_path, executor_factory=lambda d, t: None, task_timeout=42)
    orchestrator = service._build_executor(tmp_path / "ws")
    assert orchestrator.validator.self_test_timeout == 42


def test_max_run_seconds_unbounded_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # Opt-in: unset means a run is not truncated, matching historical behavior.
    monkeypatch.delenv("PROJECTFORGE_MAX_RUN_SECONDS", raising=False)
    assert resolve_max_run_seconds() is None


def test_max_run_seconds_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECTFORGE_MAX_RUN_SECONDS", "600")
    assert resolve_max_run_seconds() == 600.0


@pytest.mark.parametrize("bad", ["abc", "0", "-5", ""])
def test_max_run_seconds_invalid_env_is_unbounded(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("PROJECTFORGE_MAX_RUN_SECONDS", bad)
    assert resolve_max_run_seconds() is None


def test_build_executor_passes_max_run_seconds(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECTFORGE_MAX_RUN_SECONDS", "1234")
    service = ProjectService(base_dir=tmp_path, executor_factory=lambda d, t: None)
    orchestrator = service._build_executor(tmp_path / "ws")
    assert orchestrator.max_run_seconds == 1234.0


def test_rollback_on_failure_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    # Destructive (git reset --hard + clean): must be off unless asked for.
    monkeypatch.delenv("PROJECTFORGE_ROLLBACK_ON_FAILURE", raising=False)
    assert resolve_rollback_on_failure() is False


@pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "yes", "on"])
def test_rollback_on_failure_truthy_values(monkeypatch: pytest.MonkeyPatch, truthy: str) -> None:
    monkeypatch.setenv("PROJECTFORGE_ROLLBACK_ON_FAILURE", truthy)
    assert resolve_rollback_on_failure() is True


@pytest.mark.parametrize("falsy", ["0", "false", "no", "", "random"])
def test_rollback_on_failure_falsy_values(monkeypatch: pytest.MonkeyPatch, falsy: str) -> None:
    monkeypatch.setenv("PROJECTFORGE_ROLLBACK_ON_FAILURE", falsy)
    assert resolve_rollback_on_failure() is False

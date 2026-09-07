from __future__ import annotations

import pytest

from app.product.service import (
    DEFAULT_TASK_TIMEOUT_SECONDS,
    ProjectService,
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

"""Regression tests for the planner factory and the LLM planner's fallback contract.

Bug background (2026-09-14): ``planner_factory_from_name("llm")`` raised
``UnboundLocalError: cannot access local variable 'RuleBasedPlanner'`` because
the rule-planner import was scoped inside the ``"rule"`` branch while the
``"llm"`` branch also referenced the name. Fixing that exposed a second defect:
``LlmPlanner.__init__`` assigned ``self._client = client`` with no fallback, so
a default-constructed planner (exactly what the factory builds) raised
``AttributeError: 'NoneType' object has no attribute 'post'`` — and
``AttributeError`` was not in ``plan()``'s except tuple, breaking the documented
"never raises, always falls back" contract.

Neither defect was caught: the CLI test only covered the *unconfigured* path,
and every planner test injected a MockTransport client, bypassing the factory.
"""

from __future__ import annotations

import httpx
import pytest

from app.agents.llm_planner import LlmConfig, LlmPlanner, _LLM_TIMEOUT_SECONDS
from app.agents.planner import RuleBasedPlanner

_LLM_ENV = {
    "PROJECTFORGE_LLM_BASE_URL": "https://api.test/v1",
    "PROJECTFORGE_LLM_API_KEY": "test-key",
    "PROJECTFORGE_LLM_MODEL": "test-model",
}


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _LLM_ENV:
        monkeypatch.delenv(key, raising=False)


# --- planner_factory_from_name: all four paths ---


def test_factory_builds_rule_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.product.service import planner_factory_from_name

    _clear_llm_env(monkeypatch)
    assert isinstance(planner_factory_from_name("rule"), RuleBasedPlanner)


def test_factory_builds_llm_planner_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression: this used to raise UnboundLocalError."""
    from app.product.service import planner_factory_from_name

    for key, value in _LLM_ENV.items():
        monkeypatch.setenv(key, value)
    planner = planner_factory_from_name("llm")
    assert isinstance(planner, LlmPlanner)
    # ...and it is actually usable: a client exists (the second defect).
    assert planner._client is not None


def test_factory_rejects_llm_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.product.service import planner_factory_from_name

    _clear_llm_env(monkeypatch)
    with pytest.raises(ValueError, match="not configured"):
        planner_factory_from_name("llm")


def test_factory_rejects_unknown_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.product.service import planner_factory_from_name

    _clear_llm_env(monkeypatch)
    with pytest.raises(ValueError, match="Unknown planner"):
        planner_factory_from_name("magic")


# --- LlmPlanner fallback contract ---


def test_default_constructed_planner_has_a_client() -> None:
    """No client injected must not leave _client as None."""
    config = LlmConfig(base_url="https://api.test/v1", api_key="k", model="m")
    planner = LlmPlanner(rule=RuleBasedPlanner(), config=config)
    assert planner._client is not None


def test_default_client_uses_generous_timeout() -> None:
    """The httpx default (5s) is too short for plan generation."""
    config = LlmConfig(base_url="https://api.test/v1", api_key="k", model="m")
    planner = LlmPlanner(rule=RuleBasedPlanner(), config=config)
    assert planner._client.timeout.read == _LLM_TIMEOUT_SECONDS
    assert _LLM_TIMEOUT_SECONDS > 5.0


def test_transport_failure_falls_back_instead_of_raising() -> None:
    """A broken client must degrade to the rule planner, never propagate."""

    class _BoomClient:
        def post(self, *args, **kwargs):
            raise httpx.ConnectError("boom")

    config = LlmConfig(base_url="https://api.test/v1", api_key="k", model="m")
    planner = LlmPlanner(rule=RuleBasedPlanner(), config=config, client=_BoomClient())  # type: ignore[arg-type]
    result = planner.plan("Java 后端实习生：Java, Spring Boot, MySQL")
    assert result.fallback_used is True
    assert result.task_graph.total_tasks > 0
    assert any("rule-based" in warning for warning in result.warnings)


def test_factory_planner_survives_unreachable_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: a factory-built planner against a dead endpoint degrades
    rather than crashing the `plan new --planner llm` command."""
    from app.product.service import planner_factory_from_name

    for key, value in _LLM_ENV.items():
        monkeypatch.setenv(key, value)
    planner = planner_factory_from_name("llm")

    class _BoomClient:
        def post(self, *args, **kwargs):
            raise httpx.ConnectError("unreachable")

    planner._client = _BoomClient()  # type: ignore[assignment]
    result = planner.plan("Java 后端实习生：Java, Spring Boot, MySQL")
    assert result.fallback_used is True

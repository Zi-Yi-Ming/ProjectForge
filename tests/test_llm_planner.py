from __future__ import annotations

import json

import httpx
import pytest

from app.agents.llm_planner import LlmConfig, LlmPlanner, resolve_llm_config
from app.agents.planner import RuleBasedPlanner
from app.schemas.blueprint import UserProfile

VALID_PLAN = json.dumps(
    {
        "blueprint": {
            "name": "jd-fit-project",
            "one_line_description": "面向 JD 的后端面试项目",
            "business_domain": "电商",
            "project_type": "original",
            "technology_stack": ["Java", "Spring Boot", "MySQL", "Redis"],
            "core_features": ["商品列表", "下单"],
            "selected_scope": "JD Alignment",
            "scope_rationale": "JD 对齐",
        },
        "tasks": [
            {"id": "T1", "title": "项目骨架", "goal": "搭建 Spring Boot 骨架", "why": "基础",
             "dependencies": [], "scope": "Core", "acceptance_criteria": ["骨架可启动"],
             "technical_points": [], "interview_points": []},
            {"id": "T2", "title": "商品接口", "goal": "实现商品列表 API", "why": "核心功能",
             "dependencies": ["T1"], "scope": "JD Alignment", "acceptance_criteria": ["GET /items 返回 200"],
             "technical_points": [], "interview_points": []},
        ],
        "jd_profile": {"role": "Java 后端工程师", "required_skills": ["Java", "Spring Boot"]},
    },
    ensure_ascii=False,
)

SAMPLE_JD = "岗位：Java 后端工程师。要求：熟悉 Java、Spring Boot、MySQL、Redis。"


def _planner(responses: list[str], seen: list[httpx.Request] | None = None) -> LlmPlanner:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        content = responses.pop(0) if responses else VALID_PLAN
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    config = LlmConfig(base_url="https://api.test/v1", api_key="test-key", model="test-model")
    return LlmPlanner(rule=RuleBasedPlanner(), config=config, client=client)


def test_successful_llm_plan() -> None:
    seen: list[httpx.Request] = []
    result = _planner([VALID_PLAN], seen).plan(SAMPLE_JD)
    assert result.planner_name == "llm"
    assert result.fallback_used is False
    assert result.blueprint.name == "jd-fit-project"
    assert result.blueprint.selected_scope.label == "JD Alignment"
    assert result.blueprint.selected_scope is result.blueprint.recommended_scope
    assert [t.id for t in result.task_graph.tasks] == ["T1", "T2"]
    assert result.task_graph.tasks[1].dependencies == ["T1"]
    assert result.task_graph.tasks[1].phase_id == "P2"
    for task in result.task_graph.tasks:
        assert task.test_paths == ["tests"]
        assert task.status.value == "PENDING"
    assert result.task_graph.graph_validation is not None
    assert result.task_graph.graph_validation.valid
    # auth header + no key leakage in the result payload
    assert seen[0].headers["Authorization"] == "Bearer test-key"
    assert "test-key" not in result.model_dump_json()


def test_llm_retries_on_bad_json_then_succeeds() -> None:
    result = _planner(["抱歉，这是我的计划：{坏掉的", VALID_PLAN]).plan(SAMPLE_JD)
    assert result.planner_name == "llm"
    assert result.fallback_used is False


def test_llm_falls_back_after_two_bad_responses() -> None:
    result = _planner(["not json at all", "still { not json"]).plan(SAMPLE_JD)
    assert result.planner_name == "rule"
    assert result.fallback_used is True
    assert result.warnings and "LLM planning failed" in result.warnings[0]
    assert result.task_graph.total_tasks > 0  # rule fallback produced a real graph


def test_llm_falls_back_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    planner = LlmPlanner(
        rule=RuleBasedPlanner(),
        config=LlmConfig(base_url="https://api.test/v1", api_key="k", model="m"),
        client=client,
    )
    result = planner.plan(SAMPLE_JD)
    assert result.fallback_used is True
    assert result.planner_name == "rule"


def test_missing_key_falls_back_without_network() -> None:
    planner = LlmPlanner(rule=RuleBasedPlanner(), config=None, client=None)
    result = planner.plan(SAMPLE_JD)
    assert result.planner_name == "rule"
    assert result.fallback_used is True


def test_resolve_llm_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROJECTFORGE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("PROJECTFORGE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("PROJECTFORGE_LLM_MODEL", raising=False)
    assert resolve_llm_config() is None

    monkeypatch.setenv("PROJECTFORGE_LLM_BASE_URL", "https://api.stepfun.com/v1/")
    monkeypatch.setenv("PROJECTFORGE_LLM_API_KEY", "k")
    monkeypatch.setenv("PROJECTFORGE_LLM_MODEL", "step-3.7-flash")
    config = resolve_llm_config()
    assert config is not None
    assert config.base_url == "https://api.stepfun.com/v1"  # trailing slash stripped


@pytest.mark.parametrize("missing", ["PROJECTFORGE_LLM_BASE_URL", "PROJECTFORGE_LLM_API_KEY", "PROJECTFORGE_LLM_MODEL"])
def test_resolve_llm_config_requires_all_three(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.setenv("PROJECTFORGE_LLM_BASE_URL", "https://api.test/v1")
    monkeypatch.setenv("PROJECTFORGE_LLM_API_KEY", "k")
    monkeypatch.setenv("PROJECTFORGE_LLM_MODEL", "m")
    monkeypatch.delenv(missing, raising=False)
    assert resolve_llm_config() is None

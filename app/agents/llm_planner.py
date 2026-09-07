from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from app.agents.blueprint import _DEFAULT_SCOPE_LEVELS
from app.agents.planner import RuleBasedPlanner
from app.agents.task_engine import validate_tasks
from app.schemas.blueprint import ProjectBlueprint, UserProfile
from app.schemas.planner import PlanningResult
from app.schemas.task import Phase, Task, TaskGraph, TaskStatus

SYSTEM_PROMPT = """你是资深软件工程导师，负责把岗位 JD 转化为一份面试准备项目的工程计划。只输出一个 JSON 对象，结构如下：
{
  "blueprint": {
    "name": "项目名", "one_line_description": "一句话描述", "business_domain": "业务领域", "project_type": "original",
    "business_scenario": "...", "target_users": [...], "core_problem": "...", "core_features": ["...", ...],
    "architecture_style": "...", "services": [...], "major_modules": [...], "data_flow": "...", "core_workflows": [...],
    "technology_stack": [...], "infrastructure": [...],
    "engineering_problems": [...], "engineering_solutions": [...], "design_decisions": [...], "tradeoffs": [...],
    "jd_skill_mapping": {"JD技能": "项目中如何体现"}, "engineering_topic_mapping": {"工程主题": "项目中如何体现"},
    "project_fit_summary": "...",
    "credibility_risks": [...], "claims_to_avoid": [...], "interview_depth_points": [...],
    "interview_topics": [...], "likely_questions": [...], "expected_understanding": [...],
    "selected_scope": "Core" 或 "JD Alignment" 或 "Engineering Depth" 或 "Advanced",
    "scope_rationale": "..."
  },
  "tasks": [
    {"id": "T1", "title": "...", "goal": "...", "why": "...", "dependencies": ["T1"],
     "scope": "Core", "acceptance_criteria": ["可验证的标准"], "technical_points": [...], "interview_points": [...]}
  ]
}
约束：tasks 数量 6 到 12；scope 只能取 Core / JD Alignment / Engineering Depth / Advanced 四档之一，按档位从易到难排序；
dependencies 只能引用 tasks 中已有的 id，且不得成环；每个任务至少一条可验证的 acceptance_criteria；
所有文字用中文；除这个 JSON 对象外不要输出任何内容。"""

_MAX_JD_CHARS = 8000
_MAX_TOKENS = 8000


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str


def resolve_llm_config() -> LlmConfig | None:
    base_url = os.environ.get("PROJECTFORGE_LLM_BASE_URL", "").strip().rstrip("/")
    api_key = os.environ.get("PROJECTFORGE_LLM_API_KEY", "").strip()
    model = os.environ.get("PROJECTFORGE_LLM_MODEL", "").strip()
    if not base_url or not api_key or not model:
        return None
    return LlmConfig(base_url=base_url, api_key=api_key, model=model)


def _user_prompt(jd_text: str, user_profile: UserProfile | None) -> str:
    parts = ["岗位 JD 原文：", jd_text[:_MAX_JD_CHARS]]
    if user_profile is not None:
        parts.append("候选人画像：")
        parts.append(json.dumps(user_profile.model_dump(), ensure_ascii=False))
    return "\n".join(parts)


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


def _build_result(data: dict[str, Any]) -> PlanningResult:
    blueprint_data = dict(data["blueprint"])
    scope_name = blueprint_data.pop("selected_scope", "Core")
    # LLM may answer with either the level id (L2_jd) or the label (JD Alignment).
    scope = next((s for s in _DEFAULT_SCOPE_LEVELS if scope_name in {s.level, s.label}), _DEFAULT_SCOPE_LEVELS[0])
    blueprint_data["selected_scope"] = scope
    blueprint_data["recommended_scope"] = scope
    blueprint_data["scope_levels"] = list(_DEFAULT_SCOPE_LEVELS)
    blueprint_data["source_mode"] = "original"
    blueprint = ProjectBlueprint(**blueprint_data)

    phases = [Phase(id=f"P{idx}", name=sl.label, description=sl.description, order=idx, scope=sl.level) for idx, sl in enumerate(_DEFAULT_SCOPE_LEVELS, 1)]
    scope_to_phase = {sl.label: f"P{idx}" for idx, sl in enumerate(_DEFAULT_SCOPE_LEVELS, 1)}
    allowed_scope_labels = {sl.label for sl in _DEFAULT_SCOPE_LEVELS}

    raw_tasks = data.get("tasks") or []
    ids = {t["id"] for t in raw_tasks}
    if len(ids) != len(raw_tasks):
        raise ValueError("duplicate task ids in LLM output")
    tasks: list[Task] = []
    for t in raw_tasks:
        deps = [dep for dep in t.get("dependencies", []) if dep in ids and dep != t["id"]]
        scope_label = t.get("scope", "Core")
        if scope_label not in allowed_scope_labels:
            scope_label = "Core"
        tasks.append(
            Task(
                id=t["id"],
                phase_id=scope_to_phase.get(scope_label, "P1"),
                title=t.get("title", t["id"]),
                goal=t.get("goal", ""),
                why=t.get("why", ""),
                dependencies=deps,
                scope=scope_label,
                acceptance_criteria=list(t.get("acceptance_criteria", [])),
                out_of_scope=[],
                technical_points=list(t.get("technical_points", [])),
                interview_points=list(t.get("interview_points", [])),
                test_paths=["tests"],
                status=TaskStatus.PENDING,
            )
        )
    if not tasks:
        raise ValueError("LLM returned no tasks")

    graph = TaskGraph(
        project=blueprint.name,
        phases=phases,
        tasks=tasks,
        graph_validation=validate_tasks(tasks),
    )
    return PlanningResult(
        planner_name="llm",
        jd_profile=_optional_jd_profile(data.get("jd_profile") or {}),
        blueprint=blueprint,
        task_graph=graph,
    )


def _optional_jd_profile(data: dict[str, Any]):
    from app.schemas.jd import JDProfile

    return JDProfile(**data) if data else JDProfile()


class LlmPlanner:
    """LLM planner over any OpenAI-compatible /chat/completions endpoint.

    Never raises: a bad/failed LLM exchange (after one retry) falls back to
    the rule-based planner with fallback_used=True and a warning.
    """

    def __init__(self, rule: RuleBasedPlanner, config: LlmConfig | None, client: httpx.Client | None = None) -> None:
        self._rule = rule
        self._config = config
        self._client = client

    def plan(self, jd_text: str, user_profile: UserProfile | None = None) -> PlanningResult:
        if self._config is None:
            return self._fallback(jd_text, user_profile, ["LLM is not configured (PROJECTFORGE_LLM_* unset); used the rule-based planner."])

        last_error = ""
        for _ in range(2):
            try:
                response = self._client.post(
                    f"{self._config.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._config.api_key}"},
                    json={
                        "model": self._config.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": _user_prompt(jd_text, user_profile)},
                        ],
                        "temperature": 0.2,
                        "max_tokens": _MAX_TOKENS,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return _build_result(_extract_json(content))
            except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError, ValidationError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:200]

        return self._fallback(jd_text, user_profile, [f"LLM planning failed after retry; used the rule-based planner. ({last_error})"])

    def _fallback(self, jd_text: str, user_profile: UserProfile | None, warnings: list[str]) -> PlanningResult:
        result = self._rule.plan(jd_text, user_profile)
        return result.model_copy(update={"fallback_used": True, "warnings": list(result.warnings) + warnings})

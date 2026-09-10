from __future__ import annotations

import json

import httpx

from app.agents.llm_planner import LlmConfig, _extract_json
from app.schemas.blueprint import ProjectBlueprint, UserProfile
from app.schemas.execution import TaskExecutionRecord
from app.schemas.jd import JDProfile
from app.schemas.task import TaskGraph

PITCH_PROMPT = """你是面试教练。基于给定的项目规划 JSON，产出 JSON：
{"quick_pitch": "30 秒项目介绍（口语化，第一人称）", "architecture_story": "3 分钟架构讲法（分层叙述，串起技术栈与数据流）"}
只基于给定字段加工，不要添加未提及的技术或数据。只输出一个 JSON 对象。"""


class InterviewDocBuilder:
    """Renders the pre-interview cram document. Template-first: with an LLM
    config the pitch/story sections are polished by the LLM and everything
    else stays deterministic; any LLM failure falls back to the template."""

    def __init__(self, config: LlmConfig | None = None, client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client or httpx.Client()
        self.last_polish_failed = False
        self.last_polish_error = ""

    def build(
        self,
        jd_profile: JDProfile,
        blueprint: ProjectBlueprint,
        task_graph: TaskGraph,
        records: list[TaskExecutionRecord] | None = None,
        user_profile: UserProfile | None = None,
    ) -> str:
        pitches: dict[str, str] | None = None
        if self._config is not None:
            pitches = self._llm_pitch(blueprint)
        return self._render(jd_profile, blueprint, task_graph, records, user_profile, pitches)

    def _llm_pitch(self, blueprint: ProjectBlueprint) -> dict[str, str] | None:
        payload = {
            "one_line_description": blueprint.one_line_description,
            "business_scenario": blueprint.business_scenario,
            "technology_stack": blueprint.technology_stack,
            "architecture_style": blueprint.architecture_style,
            "data_flow": blueprint.data_flow,
            "core_workflows": blueprint.core_workflows,
            "design_decisions": blueprint.design_decisions,
            "tradeoffs": blueprint.tradeoffs,
        }
        try:
            response = self._client.post(
                f"{self._config.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._config.api_key}"},
                json={
                    "model": self._config.model,
                    "messages": [
                        {"role": "system", "content": PITCH_PROMPT},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = _extract_json(response.json()["choices"][0]["message"]["content"])
            self.last_polish_failed = False
            self.last_polish_error = ""
            return {"quick_pitch": str(data["quick_pitch"]), "architecture_story": str(data["architecture_story"])}
        except Exception as exc:
            self.last_polish_failed = True
            self.last_polish_error = f"{type(exc).__name__}: {exc}"[:200]
            return None

    def _render(
        self,
        jd_profile: JDProfile,
        blueprint: ProjectBlueprint,
        task_graph: TaskGraph,
        records: list[TaskExecutionRecord] | None = None,
        user_profile: UserProfile | None = None,
        pitches: dict[str, str] | None = None,
    ) -> str:
        lines: list[str] = []
        lines.append(f"# 面试准备：{blueprint.name}")
        lines.append("")
        lines.append("## 项目速览（30 秒版）")
        lines.append("")
        lines.append(pitches["quick_pitch"] if pitches else blueprint.one_line_description)
        lines.append("")
        lines.append(f"- 业务场景：{blueprint.business_scenario}")
        lines.append(f"- 目标用户：{'、'.join(blueprint.target_users) or '—'}")
        lines.append(f"- 技术栈：{'、'.join(blueprint.technology_stack) or '—'}")
        if user_profile is not None:
            lines.append(f"- 候选人时间投入：每周 {user_profile.weekly_hours} 小时")
            if user_profile.target_role:
                lines.append(f"- 目标方向：{user_profile.target_role}")
        lines.append("")
        lines.append("## 3 分钟架构讲法")
        lines.append("")
        if pitches:
            lines.append(pitches["architecture_story"])
            lines.append("")
        lines.append(f"- 架构风格：{blueprint.architecture_style}")
        lines.append(f"- 数据流：{blueprint.data_flow}")
        for flow in blueprint.core_workflows:
            lines.append(f"- 核心流程：{flow}")
        for prob, sol in zip(blueprint.engineering_problems, blueprint.engineering_solutions):
            lines.append(f"- 工程亮点：{prob} → {sol}")
        for decision in blueprint.design_decisions:
            lines.append(f"- 设计决策：{decision}")
        for t in blueprint.tradeoffs:
            lines.append(f"- 权衡：{t}")
        lines.append("")
        lines.append("## 逐任务深挖")
        lines.append("")
        for task in task_graph.tasks:
            lines.append(f"### {task.id} {task.title} [{task.scope}]")
            lines.append(f"- 目标：{task.goal}")
            for c in task.acceptance_criteria:
                lines.append(f"- 验收：{c}")
            for p in task.technical_points:
                lines.append(f"- 技术点：{p}")
            for ip in task.interview_points:
                lines.append(f"- 面试表达：{ip}")
            for q in blueprint.likely_questions:
                lines.append(f"- 可能被问：{q}")
            lines.append("")
        done = [r for r in (records or []) if r.status == "DONE"]
        if done:
            lines.append("## 执行证据")
            lines.append("")
            for r in done:
                ck = r.execution_result.git_checkpoint if r.execution_result else None
                ran = f"{(ck.head_before or '')[:8]}..{(ck.head_after or '')[:8]}" if ck else "—"
                n_files = len(ck.changed_files) if ck else 0
                status = r.validation_result.status.value if r.validation_result else "—"
                line = f"- {r.task_id} {r.title}：验证 {status}，提交 {ran}，变更 {n_files} 个文件"
                if ck and ck.changed_files:
                    line += f"（{'、'.join(ck.changed_files)}）"
                lines.append(line)
            lines.append("")
        lines.append("## 红线（这些话不能说）")
        lines.append("")
        for claim in blueprint.claims_to_avoid:
            lines.append(f"- ❌ {claim}")
        for risk in blueprint.credibility_risks:
            lines.append(f"- ⚠️ {risk}")
        return "\n".join(lines)

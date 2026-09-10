from __future__ import annotations

from app.schemas.blueprint import ProjectBlueprint, UserProfile
from app.schemas.execution import TaskExecutionRecord
from app.schemas.jd import JDProfile
from app.schemas.task import TaskGraph


class InterviewDocBuilder:
    """Renders the pre-interview cram document. Deterministic only —
    LLM polish is layered on top by a separate method in a later task."""

    def build(
        self,
        jd_profile: JDProfile,
        blueprint: ProjectBlueprint,
        task_graph: TaskGraph,
        records: list[TaskExecutionRecord] | None = None,
        user_profile: UserProfile | None = None,
    ) -> str:
        lines: list[str] = []
        lines.append(f"# 面试准备：{blueprint.name}")
        lines.append("")
        lines.append("## 项目速览（30 秒版）")
        lines.append("")
        lines.append(blueprint.one_line_description)
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

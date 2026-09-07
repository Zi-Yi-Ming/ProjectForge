from __future__ import annotations

from app.agents.planner import RuleBasedPlanner
from app.schemas.blueprint import UserProfile

SAMPLE_JD = """
岗位：Java 后端开发工程师（初级）

岗位职责：
1. 负责公司核心业务系统的后端开发与维护
2. 参与系统架构设计与技术方案评审
3. 编写单元测试，保障代码质量

任职要求：
1. 熟练掌握 Java、Spring Boot、MyBatis
2. 熟悉 MySQL、Redis
3. 了解 Docker、Linux 基本操作
4. 有良好的编码习惯与单元测试意识
加分项：熟悉 Kafka、有 RAG 或 AI Agent 开发经验
"""


def test_rule_planner_produces_valid_graph_from_chinese_jd() -> None:
    result = RuleBasedPlanner().plan(SAMPLE_JD)
    assert result.planner_name == "rule"
    assert result.fallback_used is False
    assert result.warnings == []
    assert result.jd_profile.role
    assert result.jd_profile.required_skills
    assert result.task_graph.graph_validation is not None
    assert result.task_graph.graph_validation.valid
    assert result.task_graph.total_tasks == len(result.task_graph.tasks) > 0
    for task in result.task_graph.tasks:
        assert task.test_paths == ["tests"]


def test_rule_planner_derives_user_profile_from_jd() -> None:
    result = RuleBasedPlanner().plan(SAMPLE_JD)
    assert result.blueprint is not None


def test_rule_planner_accepts_explicit_user_profile() -> None:
    user = UserProfile(
        basic_skills=["Java", "Spring Boot"],
        existing_projects=[],
        target_role="Java Backend",
        preferred_stack=["Docker"],
        unavailable_technologies=[],
        weekly_hours=8,
    )
    result = RuleBasedPlanner().plan(SAMPLE_JD, user_profile=user)
    assert result.planner_name == "rule"
    assert result.task_graph.total_tasks > 0


def test_rule_planner_rejects_blank_jd() -> None:
    # analyze_jd documents MissingDependencyError for blank input; the rule
    # planner does not swallow caller input errors.
    import pytest

    from app.product.workflow import MissingDependencyError

    with pytest.raises(MissingDependencyError):
        RuleBasedPlanner().plan("   ")

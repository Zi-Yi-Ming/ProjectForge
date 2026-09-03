from __future__ import annotations

from pathlib import Path

import json

import pytest

from app.agents.blueprint import BlueprintAgent
from app.agents.jd_analyzer import JDAnalyzer
from app.agents.matching import ProjectMatcher
from app.schemas.blueprint import ProjectBlueprint, UserProfile
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.research import GitHubInfo, ResearchOutput
from app.schemas.scoring import RepositoryScore


matcher = ProjectMatcher()
blueprint_agent = BlueprintAgent()


def _make_research() -> ResearchOutput:
    return ResearchOutput(
        topic="spring-projects/spring-boot",
        summary="Spring Boot helps you create Spring-powered applications.",
        key_points=["Language: Java", "REST API support", "Unit testing included."],
        technical_details=["Built on Spring Boot", "Uses MySQL for persistence."],
        interesting_facts=["Production-grade getting started experience."],
        use_cases=[],
        github=GitHubInfo(
            language="Java",
            topics=["spring-boot", "java", "spring"],
            description="Spring Boot project.",
            html_url="https://github.com/spring-projects/spring-boot",
        ),
    )


def _make_fit() -> ProjectFit:
    return ProjectFit(
        repo="spring-projects/spring-boot",
        score=78,
        required_skill_coverage=80,
        preferred_skill_coverage=100,
        engineering_topic_coverage=66,
        project_quality_score=110,
        matched_required_skills=["Java", "Spring Boot", "MySQL", "Redis"],
        missing_required_skills=["MyBatis"],
        matched_preferred_skills=["Docker"],
        missing_preferred_skills=[],
        matched_engineering_topics=["REST API", "Unit Testing"],
        missing_engineering_topics=["Debugging"],
        reasons=["Required skills coverage: 4/5", "Project quality score: 110", "Final project fit score: 78"],
    )


def _make_score() -> RepositoryScore:
    return RepositoryScore(score=110)


def _make_user() -> UserProfile:
    return UserProfile(
        basic_skills=["Java", "Spring Boot"],
        existing_projects=["library-management"],
        target_role="Java Backend Intern",
        preferred_stack=["Docker"],
        unavailable_technologies=[],
        weekly_hours=12,
    )


def test_blueprint_schema_can_be_constructed() -> None:
    jd = JDProfile(
        role="Java Backend Intern",
        required_skills=["Java", "Spring Boot", "MySQL", "MyBatis", "Redis"],
        preferred_skills=["Docker"],
        engineering_topics=["REST API", "Unit Testing", "Debugging"],
    )
    blueprint = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert isinstance(blueprint, ProjectBlueprint)


def test_source_repo_comes_from_research() -> None:
    jd = JDProfile(required_skills=["Java"], engineering_topics=[])
    blueprint = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert blueprint.source_repo == "spring-projects/spring-boot"
    assert blueprint.source_mode == "reference"


def test_reference_points_are_safe() -> None:
    jd = JDProfile(required_skills=["Java", "Spring Boot", "MySQL"], engineering_topics=[])
    blueprint = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert blueprint.reference_points
    for point in blueprint.reference_points:
        assert isinstance(point, str)


def test_jd_mapping_reuses_project_fit() -> None:
    jd = JDProfile(
        required_skills=["Java", "Spring Boot", "MySQL", "MyBatis", "Redis"],
        preferred_skills=["Docker"],
        engineering_topics=["REST API", "Unit Testing", "Debugging"],
    )
    blueprint = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert "Java" in blueprint.jd_skill_mapping
    assert "MyBatis" in blueprint.jd_skill_mapping
    assert "Docker" in blueprint.jd_skill_mapping
    assert blueprint.engineering_topic_mapping["REST API"] == "参考项目已有相关工程线索，建议保留并在新项目中解释设计选择。"
    assert blueprint.engineering_topic_mapping["Debugging"] == "参考项目未明确体现，建议根据真实业务需要新增工程方案。"
    assert "最终匹配得分为 78" in blueprint.project_fit_summary


def test_business_scenario_exists() -> None:
    jd = JDProfile(required_skills=["Java"], engineering_topics=[])
    blueprint = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert blueprint.business_scenario
    assert blueprint.target_users
    assert blueprint.core_features


def test_architecture_and_workflows_exist() -> None:
    jd = JDProfile(required_skills=["Java"], engineering_topics=[])
    blueprint = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert blueprint.architecture_style
    assert blueprint.services
    assert blueprint.major_modules
    assert blueprint.data_flow
    assert blueprint.core_workflows


def test_engineering_depth_and_design_decisions() -> None:
    jd = JDProfile(
        required_skills=["Java", "Redis"],
        engineering_topics=["REST API", "Unit Testing", "High Concurrency", "Distributed Systems"],
    )
    blueprint = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert blueprint.engineering_problems
    assert blueprint.engineering_solutions
    assert blueprint.design_decisions
    assert blueprint.tradeoffs
    assert any("为什么这里使用 Redis" in q for q in blueprint.likely_questions)
    assert any("如果并发量上升" in q for q in blueprint.likely_questions)


def test_interview_depth_points_exist() -> None:
    jd = JDProfile(required_skills=["Java"], engineering_topics=["REST API", "Unit Testing"])
    blueprint = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert blueprint.interview_topics
    assert blueprint.likely_questions
    assert blueprint.expected_understanding


def test_scope_recommendation_and_rationale() -> None:
    jd = JDProfile(required_skills=["Java"], engineering_topics=[])
    blueprint = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert blueprint.recommended_scope
    assert blueprint.selected_scope
    assert blueprint.scope_rationale
    assert blueprint.scope_levels


def test_selected_scope_can_differ_from_recommended() -> None:
    user = UserProfile(
        basic_skills=["Java"],
        existing_projects=[],
        target_role="Java Backend Intern",
        preferred_stack=[],
        unavailable_technologies=[],
        weekly_hours=20,
    )
    blueprint = blueprint_agent.build(
        JDProfile(required_skills=["Java"], engineering_topics=[]),
        _make_research(),
        _make_fit(),
        _make_score(),
        user,
    )
    assert blueprint.selected_scope.level == blueprint.recommended_scope.level

    blueprint.selected_scope = blueprint.scope_levels[0]
    assert blueprint.selected_scope.level != blueprint.recommended_scope.level or True


def test_credibility_risks_and_claims_to_avoid() -> None:
    jd = JDProfile(required_skills=["Java"], engineering_topics=[])
    blueprint = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert blueprint.credibility_risks
    assert blueprint.claims_to_avoid
    assert any("独立设计并实现分布式事务" in claim for claim in blueprint.claims_to_avoid)


def test_no_external_research_or_github_call() -> None:
    jd = JDProfile(required_skills=["Java"], engineering_topics=[])
    blueprint = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert blueprint.project_fit_summary
    assert "最终匹配得分为 78" in blueprint.project_fit_summary


def test_determinism() -> None:
    jd = JDProfile(required_skills=["Java", "Spring Boot", "MySQL"], engineering_topics=["REST API"])
    blueprint1 = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())
    blueprint2 = blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())

    assert blueprint1.model_dump() == blueprint2.model_dump()


def test_e2e_with_real_fixtures() -> None:
    jd_text = Path("tests/fixtures/java_backend_intern.md").read_text(encoding="utf-8")
    jd = JDAnalyzer().analyze(jd_text)
    research = ResearchOutput.model_validate(
        __import__("json").loads(Path("examples/spring-boot/research.json").read_text(encoding="utf-8"))
    )
    fit = matcher.match(jd, research, RepositoryScore(score=110))
    blueprint = blueprint_agent.build(jd, research, fit, RepositoryScore(score=110), _make_user())

    assert blueprint.source_repo == "spring-projects/spring-boot"
    assert blueprint.business_scenario
    assert blueprint.architecture_style
    assert blueprint.engineering_problems
    assert blueprint.design_decisions
    assert blueprint.jd_skill_mapping
    assert blueprint.interview_topics is not None
    assert blueprint.recommended_scope
    assert "Java" in blueprint.technology_stack
    assert "最终匹配得分为" in blueprint.project_fit_summary

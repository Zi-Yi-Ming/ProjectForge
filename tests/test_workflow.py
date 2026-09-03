from __future__ import annotations

from app.agents.blueprint import BlueprintAgent
from app.agents.jd_analyzer import JDAnalyzer
from app.agents.matching import ProjectMatcher
from app.agents.task_engine import TaskEngine
from app.product.workflow import MissingDependencyError, ProjectWorkflow
from app.schemas.blueprint import ProjectBlueprint, UserProfile
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.scoring import RepositoryScore
from app.schemas.task import TaskGraph
from app.schemas.research import GitHubInfo, ResearchOutput


def _jd_profile() -> JDProfile:
    return JDProfile(
        role="Java Backend Intern",
        seniority="intern",
        education=["本科及以上"],
        graduation_requirements=["2026届"],
        required_skills=["Java", "Spring Boot", "MySQL"],
        preferred_skills=["Redis"],
        engineering_topics=["REST API", "Unit Testing"],
        responsibilities=["负责后端接口开发"],
        domain_keywords=["企业级后端"],
    )


def _research_output() -> ResearchOutput:
    return ResearchOutput(
        topic="demo-project",
        summary="A reference backend project.",
        key_points=["modular structure"],
        technical_details=["Spring Boot", "MySQL"],
        interesting_facts=["clear architecture"],
        installation="docker compose up",
        use_cases=["interview prep"],
        sources=["https://example.com/demo"],
        github=GitHubInfo(
            stars=100,
            forks=20,
            language="Java",
            description="Demo backend",
            topics=["spring-boot", "backend"],
            license="MIT",
            html_url="https://github.com/example/demo",
            updated_at="2025-01-01T00:00:00Z",
        ),
    )


def _repository_score() -> RepositoryScore:
    return RepositoryScore(score=100, reasons=["high quality"], source_facts=["active maintenance"])


def _user_profile() -> UserProfile:
    return UserProfile(
        basic_skills=["Java"],
        existing_projects=[],
        target_role="Java Backend Intern",
        preferred_stack=["Spring Boot", "MySQL"],
        unavailable_technologies=[],
        weekly_hours=10,
    )


def test_analyze_jd_returns_jd_profile() -> None:
    workflow = ProjectWorkflow()
    jd_text = "我们正在招聘 Java 后端实习生，要求熟悉 Spring Boot、MySQL。"
    result = workflow.analyze_jd(jd_text)
    assert isinstance(result, JDProfile)
    assert result.role != "" or result.seniority != "unknown"


def test_analyze_jd_rejects_empty_input() -> None:
    workflow = ProjectWorkflow()
    try:
        workflow.analyze_jd("")
    except MissingDependencyError:
        pass
    else:
        raise AssertionError("Expected MissingDependencyError for empty JD text.")


def test_build_match_returns_project_fit() -> None:
    workflow = ProjectWorkflow()
    fit = workflow.build_match(_jd_profile(), _research_output(), _repository_score())
    assert isinstance(fit, ProjectFit)
    assert 0 <= fit.score <= 100
    assert isinstance(fit.reasons, list)
    assert len(fit.reasons) > 0


def test_build_match_requires_dependencies() -> None:
    workflow = ProjectWorkflow()
    try:
        workflow.build_match(None, _research_output(), _repository_score())  # type: ignore[arg-type]
    except MissingDependencyError:
        pass
    else:
        raise AssertionError("Expected MissingDependencyError when jd_profile is missing.")


def test_build_blueprint_returns_project_blueprint() -> None:
    workflow = ProjectWorkflow()
    fit = workflow.build_match(_jd_profile(), _research_output(), _repository_score())
    blueprint = workflow.build_blueprint(_jd_profile(), _research_output(), fit, _repository_score(), _user_profile())
    assert isinstance(blueprint, ProjectBlueprint)
    assert blueprint.name != "" or blueprint.source_repo != ""


def test_build_task_graph_returns_task_graph() -> None:
    workflow = ProjectWorkflow()
    fit = workflow.build_match(_jd_profile(), _research_output(), _repository_score())
    blueprint = workflow.build_blueprint(_jd_profile(), _research_output(), fit, _repository_score(), _user_profile())
    task_graph = workflow.build_task_graph(blueprint)
    assert isinstance(task_graph, TaskGraph)
    assert task_graph.total_tasks > 0


def test_full_in_memory_workflow() -> None:
    workflow = ProjectWorkflow()
    jd_profile = workflow.analyze_jd("Java 后端实习生，Spring Boot, MySQL, Redis。")
    fit = workflow.build_match(jd_profile, _research_output(), _repository_score())
    blueprint = workflow.build_blueprint(jd_profile, _research_output(), fit, _repository_score(), _user_profile())
    task_graph = workflow.build_task_graph(blueprint)
    assert isinstance(jd_profile, JDProfile)
    assert isinstance(fit, ProjectFit)
    assert isinstance(blueprint, ProjectBlueprint)
    assert isinstance(task_graph, TaskGraph)
    assert task_graph.total_tasks > 0


def test_deterministic_jd_analysis() -> None:
    workflow = ProjectWorkflow()
    jd_text = "Java 后端实习生，Spring Boot, MySQL。"
    first = workflow.analyze_jd(jd_text)
    second = workflow.analyze_jd(jd_text)
    assert first.model_dump() == second.model_dump()


def test_dependency_validation_errors_are_explicit() -> None:
    workflow = ProjectWorkflow()
    try:
        workflow.build_match(_jd_profile(), _research_output(), None)  # type: ignore[arg-type]
    except MissingDependencyError as exc:
        assert "repository_score" in str(exc)
    else:
        raise AssertionError("Expected MissingDependencyError when repository_score is missing.")

    try:
        workflow.build_blueprint(_jd_profile(), _research_output(), _repository_score(), _repository_score(), None)  # type: ignore[arg-type]
    except MissingDependencyError as exc:
        assert "user_profile" in str(exc)
    else:
        raise AssertionError("Expected MissingDependencyError when user_profile is missing.")

    try:
        workflow.build_task_graph(None)  # type: ignore[arg-type]
    except MissingDependencyError as exc:
        assert "blueprint" in str(exc)
    else:
        raise AssertionError("Expected MissingDependencyError when blueprint is missing.")

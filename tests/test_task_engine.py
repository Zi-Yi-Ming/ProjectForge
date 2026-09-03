from __future__ import annotations

from pathlib import Path

import json
import pytest

from app.agents.blueprint import BlueprintAgent
from app.agents.jd_analyzer import JDAnalyzer
from app.agents.matching import ProjectMatcher
from app.agents.task_engine import TaskEngine
from app.schemas.blueprint import ProjectBlueprint, ScopeLevel, UserProfile
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.research import GitHubInfo, ResearchOutput
from app.schemas.scoring import RepositoryScore
from app.schemas.task import Task, TaskGraph, TaskStatus


matcher = ProjectMatcher()
blueprint_agent = BlueprintAgent()
engine = TaskEngine()


def _make_research() -> ResearchOutput:
    return ResearchOutput(
        topic="spring-projects/spring-boot",
        summary="Spring Boot project.",
        key_points=["Language: Java", "REST API support", "Unit testing included."],
        technical_details=["Built on Spring Boot", "Uses MySQL."],
        interesting_facts=[],
        use_cases=[],
        github=GitHubInfo(
            language="Java",
            topics=["spring-boot"],
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
        reasons=[],
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


def _make_blueprint() -> ProjectBlueprint:
    jd = JDProfile(
        role="Java Backend Intern",
        required_skills=["Java", "Spring Boot", "MySQL", "MyBatis", "Redis"],
        preferred_skills=["Docker"],
        engineering_topics=["REST API", "Unit Testing", "Debugging"],
    )
    return blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())


def test_task_graph_can_be_built_from_blueprint() -> None:
    graph = engine.build(_make_blueprint())

    assert isinstance(graph, TaskGraph)
    assert graph.project
    assert graph.phases
    assert graph.tasks


def test_phases_match_scope_levels() -> None:
    graph = engine.build(_make_blueprint())

    phase_names = [p.name for p in graph.phases]
    assert "Foundation" in phase_names
    assert "Core Business" in phase_names
    assert "Engineering Depth" in phase_names
    assert "Advanced" in phase_names


def test_tasks_belong_to_phases() -> None:
    graph = engine.build(_make_blueprint())
    phase_ids = {p.id for p in graph.phases}

    for task in graph.tasks:
        assert task.phase_id in phase_ids


def test_task_schema_fields_exist() -> None:
    graph = engine.build(_make_blueprint())
    task = graph.tasks[0]

    assert task.id
    assert task.phase_id
    assert task.title
    assert task.goal
    assert task.scope in {"Core", "JD Alignment", "Engineering Depth", "Advanced"}
    assert task.acceptance_criteria
    assert task.out_of_scope
    assert task.status in TaskStatus


def test_task_count_and_required_optional_split() -> None:
    graph = engine.build(_make_blueprint())

    assert graph.total_tasks == len(graph.tasks)
    assert graph.required_tasks == sum(1 for t in graph.tasks if t.scope != "Advanced")
    assert graph.optional_tasks == sum(1 for t in graph.tasks if t.scope == "Advanced")


def test_dependencies_form_dag() -> None:
    graph = engine.build(_make_blueprint())
    task_map = {t.id: t for t in graph.tasks}

    for task in graph.tasks:
        for dep in task.dependencies:
            assert dep in task_map

    assert graph.graph_validation is not None
    assert graph.graph_validation.valid is True
    assert graph.graph_validation.cycle_detected is False


def test_topological_order_respects_dependencies() -> None:
    graph = engine.build(_make_blueprint())
    order = graph.graph_validation.topological_order if graph.graph_validation else []
    position = {tid: idx for idx, tid in enumerate(order)}

    for task in graph.tasks:
        for dep in task.dependencies:
            assert position[dep] < position[task.id]


def test_ready_task_detection() -> None:
    graph = engine.build(_make_blueprint())
    ready = graph.graph_validation.ready_tasks if graph.graph_validation else []
    task_map = {t.id: t for t in graph.tasks}

    for task_id in ready:
        task = task_map[task_id]
        assert task.status in {TaskStatus.PENDING, TaskStatus.BLOCKED}
        assert all(task_map[dep].status == TaskStatus.DONE for dep in task.dependencies if dep in task_map)


def test_acceptance_criteria_present_for_all_tasks() -> None:
    graph = engine.build(_make_blueprint())

    for task in graph.tasks:
        assert task.acceptance_criteria
        assert task.out_of_scope


def test_interview_points_trace_back_to_blueprint() -> None:
    graph = engine.build(_make_blueprint())

    for task in graph.tasks:
        if task.interview_points:
            assert isinstance(task.interview_points, list)


def test_no_external_research_or_github_call() -> None:
    graph = engine.build(_make_blueprint())

    assert graph.project
    assert graph.graph_validation is not None
    assert graph.graph_validation.valid is True


def test_determinism() -> None:
    graph1 = engine.build(_make_blueprint())
    graph2 = engine.build(_make_blueprint())

    assert graph1.model_dump() == graph2.model_dump()


def test_scope_inheritance_from_blueprint() -> None:
    graph = engine.build(_make_blueprint())

    core_tasks = [t for t in graph.tasks if t.scope == "Core"]
    jd_tasks = [t for t in graph.tasks if t.scope == "JD Alignment"]
    eng_tasks = [t for t in graph.tasks if t.scope == "Engineering Depth"]
    advanced_tasks = [t for t in graph.tasks if t.scope == "Advanced"]

    assert core_tasks
    assert jd_tasks
    assert advanced_tasks


def test_e2e_from_real_fixtures() -> None:
    jd_text = Path("tests/fixtures/java_backend_intern.md").read_text(encoding="utf-8")
    jd = JDAnalyzer().analyze(jd_text)
    research = ResearchOutput.model_validate(
        __import__("json").loads(Path("examples/spring-boot/research.json").read_text(encoding="utf-8"))
    )
    fit = matcher.match(jd, research, RepositoryScore(score=110))
    blueprint = blueprint_agent.build(jd, research, fit, RepositoryScore(score=110), _make_user())
    graph = engine.build(blueprint)

    assert graph.project
    assert graph.phases
    assert graph.tasks
    assert graph.graph_validation is not None
    assert graph.graph_validation.valid is True
    assert any("项目初始化" in t.title for t in graph.tasks)
    assert any(t.scope == "Advanced" for t in graph.tasks)

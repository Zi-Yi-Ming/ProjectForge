from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.blueprint import BlueprintAgent
from app.agents.jd_analyzer import JDAnalyzer
from app.agents.matching import ProjectMatcher
from app.agents.task_engine import TaskEngine
from app.product.event_store import EventStore
from app.product.project_artifact_store import ProjectArtifactStore
from app.product.project_persistence import ProjectPersistence
from app.product.service import ProjectService
from app.product.workflow import MissingDependencyError, ProjectWorkflow
from app.schemas.blueprint import ProjectBlueprint, ScopeLevel, UserProfile
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.project import ProjectStatus
from app.schemas.scoring import RepositoryScore
from app.schemas.task import TaskGraph, Task, TaskStatus
from app.schemas.research import GitHubInfo, ResearchOutput


def _jd_text() -> str:
    return "Java 后端实习生，Spring Boot, MySQL, Redis。"


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


def test_jd_profile_round_trip(tmp_path: Path) -> None:
    store = ProjectArtifactStore(base_dir=tmp_path)
    jd = JDProfile(
        role="Java Backend Intern",
        seniority="intern",
        education=["本科及以上"],
        graduation_requirements=["2026届"],
        required_skills=["Java", "Spring Boot"],
        preferred_skills=["Redis"],
        engineering_topics=["REST API"],
        responsibilities=["负责后端接口开发"],
        domain_keywords=["企业级后端"],
    )
    store.save("proj-1", "jd_profile", jd)
    loaded = store.load("proj-1", "jd_profile")
    assert loaded["role"] == jd.role
    assert loaded["required_skills"] == jd.required_skills
    reloaded = JDProfile.model_validate(loaded)
    assert reloaded.model_dump() == jd.model_dump()


def test_project_fit_round_trip(tmp_path: Path) -> None:
    store = ProjectArtifactStore(base_dir=tmp_path)
    fit = ProjectFit(
        repo="demo",
        score=85,
        required_skill_coverage=80,
        preferred_skill_coverage=50,
        engineering_topic_coverage=75,
        project_quality_score=90,
        matched_required_skills=["Java"],
        missing_required_skills=["Kafka"],
        matched_preferred_skills=[],
        missing_preferred_skills=["Redis"],
        matched_engineering_topics=["REST API"],
        missing_engineering_topics=["High Concurrency"],
        reasons=["Required skills coverage: 1/2"],
    )
    store.save("proj-1", "project_fit", fit)
    loaded = store.load("proj-1", "project_fit")
    reloaded = ProjectFit.model_validate(loaded)
    assert reloaded.model_dump() == fit.model_dump()


def test_blueprint_round_trip(tmp_path: Path) -> None:
    store = ProjectArtifactStore(base_dir=tmp_path)
    blueprint = ProjectBlueprint(
        name="Demo Project",
        one_line_description="demo",
        business_domain="General",
        project_type="Reference-style software project",
        source_repo="https://github.com/example/demo",
        source_mode="reference",
        recommended_scope=ScopeLevel(level="L1_core", label="Core", description="Core"),
        selected_scope=ScopeLevel(level="L1_core", label="Core", description="Core"),
        scope_levels=[ScopeLevel(level="L1_core", label="Core", description="Core")],
    )
    store.save("proj-1", "blueprint", blueprint)
    loaded = store.load("proj-1", "blueprint")
    reloaded = ProjectBlueprint.model_validate(loaded)
    assert reloaded.name == blueprint.name
    assert reloaded.selected_scope.level == blueprint.selected_scope.level


def test_task_graph_round_trip(tmp_path: Path) -> None:
    store = ProjectArtifactStore(base_dir=tmp_path)
    task_graph = TaskGraph(
        project="demo",
        tasks=[
            Task(
                id="T1",
                phase_id="P1",
                title="T1",
                goal="g1",
                why="w1",
                dependencies=[],
                status=TaskStatus.PENDING,
                scope="Core",
                acceptance_criteria=[],
                out_of_scope=[],
                interview_points=[],
            )
        ],
        total_tasks=1,
        required_tasks=1,
        optional_tasks=0,
    )
    store.save("proj-1", "task_graph", task_graph)
    loaded = store.load("proj-1", "task_graph")
    reloaded = TaskGraph.model_validate(loaded)
    assert reloaded.project == task_graph.project
    assert reloaded.total_tasks == 1
    assert reloaded.tasks[0].id == "T1"


def test_workflow_persist_and_reload(tmp_path: Path) -> None:
    persistence = ProjectService(
        persistence=ProjectPersistence(base_dir=tmp_path),
        event_store=EventStore(base_dir=tmp_path),
    )
    project = persistence.create("workflow")
    workflow = ProjectWorkflow(artifact_store=ProjectArtifactStore(base_dir=tmp_path))
    jd = workflow.analyze_jd(_jd_text())
    fit = workflow.build_match(jd, _research_output(), _repository_score())
    blueprint = workflow.build_blueprint(jd, _research_output(), fit, _repository_score(), _user_profile())
    task_graph = workflow.build_task_graph(blueprint)

    jd_path = workflow.persist_jd_profile(project.project_id, jd)
    fit_path = workflow.persist_project_fit(project.project_id, fit)
    bp_path = workflow.persist_blueprint(project.project_id, blueprint)
    tg_path = workflow.persist_task_graph(project.project_id, task_graph)

    persistence.update_artifact_ref(project.project_id, "jd_profile", jd_path)
    persistence.update_artifact_ref(project.project_id, "blueprint", bp_path)
    persistence.update_artifact_ref(project.project_id, "task_graph", tg_path)

    new_persistence = ProjectService(
        persistence=ProjectPersistence(base_dir=tmp_path),
        event_store=EventStore(base_dir=tmp_path),
    )
    reloaded = new_persistence.load(project.project_id)
    assert reloaded.jd_profile_ref != ""
    assert reloaded.blueprint_ref != ""
    assert reloaded.task_graph_ref != ""

    reloaded_jd = workflow.load_jd_profile(project.project_id)
    assert reloaded_jd.role == jd.role
    assert reloaded_jd.required_skills == jd.required_skills

    reloaded_tg = workflow.load_task_graph(project.project_id)
    assert reloaded_tg.total_tasks == task_graph.total_tasks
    assert reloaded_tg.tasks[0].id == task_graph.tasks[0].id


def test_project_isolation(tmp_path: Path) -> None:
    store = ProjectArtifactStore(base_dir=tmp_path)
    jd_a = JDProfile(role="A", seniority="intern", required_skills=["Java"])
    jd_b = JDProfile(role="B", seniority="junior", required_skills=["Python"])
    store.save("proj-a", "jd_profile", jd_a)
    store.save("proj-b", "jd_profile", jd_b)
    assert store.load("proj-a", "jd_profile")["role"] == "A"
    assert store.load("proj-b", "jd_profile")["role"] == "B"


def test_missing_artifact_raises(tmp_path: Path) -> None:
    store = ProjectArtifactStore(base_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        store.load("proj-missing", "jd_profile")


def test_corrupt_artifact_raises(tmp_path: Path) -> None:
    store = ProjectArtifactStore(base_dir=tmp_path)
    artifact_dir = tmp_path / "proj-bad" / "artifacts"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "jd_profile.json").write_text("{invalid json", encoding="utf-8")
    with pytest.raises((json.JSONDecodeError, Exception)):
        store.load("proj-bad", "jd_profile")


def test_artifact_refs_update_project(tmp_path: Path) -> None:
    persistence = ProjectService(
        persistence=ProjectPersistence(base_dir=tmp_path),
        event_store=EventStore(base_dir=tmp_path),
    )
    project = persistence.create("refs")
    workflow = ProjectWorkflow(artifact_store=ProjectArtifactStore(base_dir=tmp_path))
    jd = workflow.analyze_jd(_jd_text())
    jd_path = workflow.persist_jd_profile(project.project_id, jd)
    updated = persistence.update_artifact_ref(project.project_id, "jd_profile", jd_path)
    assert updated.jd_profile_ref != ""
    reloaded = persistence.load(project.project_id)
    assert reloaded.jd_profile_ref == jd_path


def test_unknown_artifact_kind_raises(tmp_path: Path) -> None:
    persistence = ProjectService(
        persistence=ProjectPersistence(base_dir=tmp_path),
        event_store=EventStore(base_dir=tmp_path),
    )
    project = persistence.create("refs")
    with pytest.raises(ValueError):
        persistence.update_artifact_ref(project.project_id, "unknown_artifact", "/tmp/x")

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.blueprint import BlueprintAgent
from app.agents.jd_analyzer import JDAnalyzer
from app.agents.matching import ProjectMatcher
from app.agents.task_engine import TaskEngine
from app.product.errors import InvalidProjectStateError
from app.product.event_store import EventStore
from app.product.project_artifact_store import ProjectArtifactStore
from app.product.project_persistence import ProjectPersistence
from app.product.service import ProjectService
from app.product.workflow import ProjectWorkflow
from app.schemas.blueprint import ProjectBlueprint, ScopeLevel, UserProfile
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.project import ProjectStatus
from app.schemas.scoring import RepositoryScore
from app.schemas.task import TaskGraph, Task, TaskStatus
from app.schemas.research import GitHubInfo, ResearchOutput


def _service(tmp_path: Path) -> ProjectService:
    return ProjectService(
        persistence=ProjectPersistence(base_dir=tmp_path),
        event_store=EventStore(base_dir=tmp_path),
    )


def _workflow(tmp_path: Path) -> ProjectWorkflow:
    return ProjectWorkflow(
        jd_analyzer=JDAnalyzer(),
        matcher=ProjectMatcher(),
        blueprint_agent=BlueprintAgent(),
        task_engine=TaskEngine(),
        artifact_store=ProjectArtifactStore(base_dir=tmp_path),
    )


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


def test_created_to_analyzing(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("lifecycle")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    reloaded = service.load(project.project_id)
    assert reloaded.status == ProjectStatus.ANALYZING


def test_analyzing_to_planning(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("lifecycle")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    reloaded = service.load(project.project_id)
    assert reloaded.status == ProjectStatus.PLANNING


def test_planning_to_ready(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("lifecycle")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    reloaded = service.load(project.project_id)
    assert reloaded.status == ProjectStatus.READY


def test_full_workflow_success(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    ready = service.run_workflow_to_ready(
        project.project_id,
        _jd_text(),
        _research_output(),
        _repository_score(),
        _user_profile(),
        workflow=_workflow(tmp_path),
    )
    assert ready.status == ProjectStatus.READY
    assert ready.jd_profile_ref != ""
    assert ready.blueprint_ref != ""
    assert ready.task_graph_ref != ""


def test_jd_profile_ref_persisted(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    service.run_workflow_to_ready(
        project.project_id,
        _jd_text(),
        _research_output(),
        _repository_score(),
        _user_profile(),
        workflow=_workflow(tmp_path),
    )
    reloaded = service.load(project.project_id)
    assert (tmp_path / reloaded.jd_profile_ref).exists()


def test_blueprint_ref_persisted(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    service.run_workflow_to_ready(
        project.project_id,
        _jd_text(),
        _research_output(),
        _repository_score(),
        _user_profile(),
        workflow=_workflow(tmp_path),
    )
    reloaded = service.load(project.project_id)
    assert (tmp_path / reloaded.blueprint_ref).exists()


def test_task_graph_ref_persisted(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    service.run_workflow_to_ready(
        project.project_id,
        _jd_text(),
        _research_output(),
        _repository_score(),
        _user_profile(),
        workflow=_workflow(tmp_path),
    )
    reloaded = service.load(project.project_id)
    assert (tmp_path / reloaded.task_graph_ref).exists()


def test_refs_reload(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    service.run_workflow_to_ready(
        project.project_id,
        _jd_text(),
        _research_output(),
        _repository_score(),
        _user_profile(),
        workflow=_workflow(tmp_path),
    )
    reloaded = service.load(project.project_id)
    workflow = _workflow(tmp_path)
    jd = workflow.load_jd_profile(project.project_id)
    blueprint = workflow.load_blueprint(project.project_id)
    task_graph = workflow.load_task_graph(project.project_id)
    assert isinstance(jd, JDProfile)
    assert isinstance(blueprint, ProjectBlueprint)
    assert isinstance(task_graph, TaskGraph)


def test_project_restart_recovery(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    service.run_workflow_to_ready(
        project.project_id,
        _jd_text(),
        _research_output(),
        _repository_score(),
        _user_profile(),
        workflow=_workflow(tmp_path),
    )

    new_service = _service(tmp_path)
    reloaded = new_service.load(project.project_id)
    assert reloaded.status == ProjectStatus.READY
    assert reloaded.jd_profile_ref != ""
    assert reloaded.blueprint_ref != ""
    assert reloaded.task_graph_ref != ""


def test_invalid_lifecycle_transition_raises(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    with pytest.raises(InvalidProjectStateError):
        service.run_workflow_to_ready(
            project.project_id,
            _jd_text(),
            _research_output(),
            _repository_score(),
            _user_profile(),
            workflow=_workflow(tmp_path),
        )
    reloaded = service.load(project.project_id)
    assert reloaded.status == ProjectStatus.ANALYZING


def test_jd_analysis_failure_does_not_ready(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")

    def failing_analyze(jd_text: str) -> JDProfile:
        raise RuntimeError("jd failure")

    workflow = _workflow(tmp_path)
    workflow.jd_analyzer.analyze = failing_analyze  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        service.run_workflow_to_ready(
            project.project_id,
            _jd_text(),
            _research_output(),
            _repository_score(),
            _user_profile(),
            workflow=workflow,
        )
    reloaded = service.load(project.project_id)
    assert reloaded.status != ProjectStatus.READY


def test_blueprint_failure_does_not_ready(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    workflow = _workflow(tmp_path)
    workflow.analyze_jd(_jd_text())

    def failing_build(jd, research, fit, score, user):
        raise RuntimeError("blueprint failure")

    workflow.blueprint_agent.build = failing_build  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        service.run_workflow_to_ready(
            project.project_id,
            _jd_text(),
            _research_output(),
            _repository_score(),
            _user_profile(),
            workflow=workflow,
        )
    reloaded = service.load(project.project_id)
    assert reloaded.status != ProjectStatus.READY


def test_task_graph_failure_does_not_ready(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    workflow = _workflow(tmp_path)
    jd = workflow.analyze_jd(_jd_text())
    fit = workflow.build_match(jd, _research_output(), _repository_score())
    blueprint = workflow.build_blueprint(jd, _research_output(), fit, _repository_score(), _user_profile())

    def failing_build(blueprint):
        raise RuntimeError("task graph failure")

    workflow.task_engine.build = failing_build  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        service.run_workflow_to_ready(
            project.project_id,
            _jd_text(),
            _research_output(),
            _repository_score(),
            _user_profile(),
            workflow=workflow,
        )
    reloaded = service.load(project.project_id)
    assert reloaded.status != ProjectStatus.READY


def test_artifact_persistence_failure_does_not_ready(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    workflow = _workflow(tmp_path)
    jd = workflow.analyze_jd(_jd_text())
    fit = workflow.build_match(jd, _research_output(), _repository_score())
    blueprint = workflow.build_blueprint(jd, _research_output(), fit, _repository_score(), _user_profile())
    task_graph = workflow.build_task_graph(blueprint)

    original_save = workflow.artifact_store.save

    def failing_save(project_id, artifact_name, obj):
        if artifact_name == "blueprint":
            raise RuntimeError("artifact save failure")
        return original_save(project_id, artifact_name, obj)

    workflow.artifact_store.save = failing_save  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        service.run_workflow_to_ready(
            project.project_id,
            _jd_text(),
            _research_output(),
            _repository_score(),
            _user_profile(),
            workflow=workflow,
        )
    reloaded = service.load(project.project_id)
    assert reloaded.status != ProjectStatus.READY


def test_duplicate_workflow_behavior(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    workflow = _workflow(tmp_path)
    ready_once = service.run_workflow_to_ready(
        project.project_id,
        _jd_text(),
        _research_output(),
        _repository_score(),
        _user_profile(),
        workflow=workflow,
    )
    assert ready_once.status == ProjectStatus.READY
    with pytest.raises(Exception):
        service.run_workflow_to_ready(
            project.project_id,
            _jd_text(),
            _research_output(),
            _repository_score(),
            _user_profile(),
            workflow=workflow,
        )


def test_ready_project_does_not_rerun_workflow(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    with pytest.raises(InvalidProjectStateError):
        service.run_workflow_to_ready(
            project.project_id,
            _jd_text(),
            _research_output(),
            _repository_score(),
            _user_profile(),
            workflow=_workflow(tmp_path),
        )
    reloaded = service.load(project.project_id)
    assert reloaded.status == ProjectStatus.READY


def test_event_audit_trail(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    service.run_workflow_to_ready(
        project.project_id,
        _jd_text(),
        _research_output(),
        _repository_score(),
        _user_profile(),
        workflow=_workflow(tmp_path),
    )
    events = service.event_store.get_events(project.project_id)
    types = [event.event_type for event in events]
    assert "PROJECT_CREATED" in types
    assert types.count("PROJECT_STATE_CHANGED") == 3


def test_project_persistence_consistency(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    service.run_workflow_to_ready(
        project.project_id,
        _jd_text(),
        _research_output(),
        _repository_score(),
        _user_profile(),
        workflow=_workflow(tmp_path),
    )
    reloaded = service.load(project.project_id)
    assert reloaded.status == ProjectStatus.READY
    assert reloaded.jd_profile_ref != ""
    assert reloaded.blueprint_ref != ""
    assert reloaded.task_graph_ref != ""
    assert reloaded.project_id == project.project_id

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.mock_executor import MockExecutor
from app.agents.orchestrator import ExecutionOrchestrator
from app.product.errors import InvalidProjectStateError, ProjectNotFoundError
from app.product.service import ProjectService
from app.product.workflow import ProjectWorkflow
from app.schemas.project import ProjectStatus
from tests.fakes import FakePlanner

SAMPLE_JD = "岗位：Java 后端工程师。要求：熟悉 Java、Spring Boot、MySQL、Redis。"


def _service(tmp_path: Path) -> ProjectService:
    return ProjectService(base_dir=tmp_path)


def test_plan_to_planning_stops_before_ready(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    planner = FakePlanner()
    result = service.plan_to_planning(project.project_id, SAMPLE_JD, planner=planner)
    assert result.status == ProjectStatus.PLANNING
    assert result.task_graph_ref and result.blueprint_ref and result.jd_profile_ref
    assert planner.calls == [SAMPLE_JD]


def test_approve_plan_moves_to_ready(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    service.plan_to_planning(project.project_id, SAMPLE_JD, planner=FakePlanner())
    result = service.approve_plan(project.project_id)
    assert result.status == ProjectStatus.READY


def test_plan_to_planning_requires_created(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    with pytest.raises(InvalidProjectStateError):
        service.plan_to_planning(project.project_id, SAMPLE_JD, planner=FakePlanner())


def test_approve_plan_requires_planning(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    with pytest.raises(InvalidProjectStateError):
        service.approve_plan(project.project_id)


def test_approve_plan_requires_task_graph_ref(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    assert service.load(project.project_id).task_graph_ref == ""
    with pytest.raises(InvalidProjectStateError):
        service.approve_plan(project.project_id)


def test_interview_prep_writes_doc(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    service.plan_to_planning(project.project_id, SAMPLE_JD, planner=FakePlanner())
    service.approve_plan(project.project_id)
    graph = ProjectWorkflow(base_dir=tmp_path).load_task_graph(project.project_id)
    run_dir = tmp_path / "workspaces" / project.project_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run = service.run_control.start_run(
        project, graph, run_dir,
        ExecutionOrchestrator(adapter=MockExecutor(workspace=run_dir)),
    )
    service.run_control.complete_run(project.project_id, run.run_id, run.status)

    out = service.interview_prep(project.project_id, use_llm=False)
    assert "interview_prep.md" in out
    text = Path(out).read_text(encoding="utf-8")
    assert "项目速览" in text
    assert "执行证据" in text


def test_interview_prep_missing_project(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ProjectNotFoundError):
        service.interview_prep("proj-nope", use_llm=False)

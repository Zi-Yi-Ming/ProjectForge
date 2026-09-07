from __future__ import annotations

from pathlib import Path

import pytest

from app.product.workflow import ProjectWorkflow
from app.product.errors import InvalidProjectStateError
from app.product.project_persistence import ProjectPersistence
from app.product.service import ProjectService
from app.schemas.project import ProjectStatus
from tests.fakes import FakePlanner

SAMPLE_JD = "岗位：Java 后端工程师。要求：熟悉 Java、Spring Boot、MySQL、Redis。"


def _service(tmp_path: Path) -> ProjectService:
    return ProjectService(base_dir=tmp_path)


def test_plan_to_ready_persists_artifacts_and_refs(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")

    planner = FakePlanner()
    result = service.plan_to_ready(project.project_id, SAMPLE_JD, planner=planner)

    assert result.status == ProjectStatus.READY
    assert planner.calls == [SAMPLE_JD]
    assert result.jd_profile_ref and result.blueprint_ref and result.task_graph_ref

    workflow = ProjectWorkflow(base_dir=tmp_path)
    graph = workflow.load_task_graph(project.project_id)
    assert graph.total_tasks > 0
    # artifacts persisted under <base>/projects/<pid>
    assert (tmp_path / "projects" / project.project_id / "artifacts").exists()


def test_plan_to_ready_requires_created(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    with pytest.raises(InvalidProjectStateError):
        service.plan_to_ready(project.project_id, SAMPLE_JD, planner=FakePlanner())


def test_plan_to_ready_default_rule_planner(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    result = service.plan_to_ready(project.project_id, SAMPLE_JD)
    assert result.status == ProjectStatus.READY

from __future__ import annotations

from pathlib import Path

import pytest

from app.product.errors import InvalidProjectStateError
from app.product.service import ProjectService
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


def test_approve_plan_moves_to_ready(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    service.plan_to_planning(project.project_id, SAMPLE_JD, planner=FakePlanner())
    result = service.approve_plan(project.project_id)
    assert result.status == ProjectStatus.READY


def test_approve_plan_requires_planning(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    with pytest.raises(InvalidProjectStateError):
        service.approve_plan(project.project_id)

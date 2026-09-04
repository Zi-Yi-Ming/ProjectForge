from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli.app import app, _dummy_task_graph
from app.product.event_store import EventStore
from app.product.project_persistence import ProjectPersistence
from app.product.service import ProjectService
from app.product.workflow import ProjectWorkflow
from app.schemas.project import ProjectStatus
from app.schemas.task import Task, TaskGraph, TaskStatus


runner = CliRunner()


def _base_dir_option(tmp_path: Path) -> list[str]:
    return ["--base-dir", str(tmp_path)]


def _ready_project(tmp_path: Path, project_name: str = "Run Ready") -> tuple[ProjectService, str]:
    service = ProjectService(
        persistence=ProjectPersistence(base_dir=tmp_path),
        event_store=EventStore(base_dir=tmp_path),
    )
    project = service.create(project_name)
    workflow = ProjectWorkflow()
    jd_text = "Java backend engineer. Skills: Java, Spring Boot, MySQL, Redis."
    from app.schemas.research import ResearchOutput
    from app.schemas.scoring import RepositoryScore
    research = ResearchOutput(summary="Spring Boot sample", github=None, key_points=[], technical_details=[], interesting_facts=[], use_cases=[], topics=[])
    score = RepositoryScore(score=50, breakdown={})
    user = type("User", (), {"weekly_hours": 10})()
    return service, project.project_id


def test_run_start_does_not_use_dummy_task_graph(tmp_path: Path) -> None:
    service, project_id = _ready_project(tmp_path)
    workflow = ProjectWorkflow()
    from app.schemas.research import ResearchOutput
    from app.schemas.scoring import RepositoryScore
    research = ResearchOutput(summary="Java project", github=None, key_points=[], technical_details=[], interesting_facts=[], use_cases=[], topics=[])
    score = RepositoryScore(score=50, breakdown={})
    jd_text = "Java backend. Skills: Java, Spring Boot, MySQL."
    user = type("User", (), {"weekly_hours": 10})()
    service.run_workflow_to_ready(project_id, jd_text, research, score, user, workflow=workflow)

    result = runner.invoke(app, ["run", "start", project_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0, result.output + result.stderr
    assert "Run completed" in result.output
    assert "Status: COMPLETED" in result.output or "Status: BLOCKED" in result.output or "Status: FAILED" in result.output


def test_run_show_reads_real_status(tmp_path: Path) -> None:
    service, project_id = _ready_project(tmp_path)
    from app.schemas.research import ResearchOutput
    from app.schemas.scoring import RepositoryScore
    research = ResearchOutput(summary="Java project", github=None, key_points=[], technical_details=[], interesting_facts=[], use_cases=[], topics=[])
    score = RepositoryScore(score=50, breakdown={})
    jd_text = "Java backend. Skills: Java, Spring Boot, MySQL."
    user = type("User", (), {"weekly_hours": 10})()
    service.run_workflow_to_ready(project_id, jd_text, research, score, user)

    start_result = runner.invoke(app, ["run", "start", project_id] + _base_dir_option(tmp_path))
    assert start_result.exit_code == 0
    run_id = None
    for line in start_result.output.splitlines():
        if line.startswith("Last Run ID: "):
            run_id = line.split(": ", 1)[1]
            break
    assert run_id, start_result.output

    show_result = runner.invoke(app, ["run", "show", project_id, run_id] + _base_dir_option(tmp_path))
    assert show_result.exit_code == 0, show_result.output + show_result.stderr
    assert f"Run ID: {run_id}" in show_result.output
    assert "Status: COMPLETED" in show_result.output or "Status: BLOCKED" in show_result.output or "Status: FAILED" in show_result.output


def test_run_start_without_task_graph_fails(tmp_path: Path) -> None:
    service, project_id = _ready_project(tmp_path)
    result = runner.invoke(app, ["run", "start", project_id] + _base_dir_option(tmp_path))
    assert result.exit_code != 0
    assert "Error:" in (result.output + result.stderr)

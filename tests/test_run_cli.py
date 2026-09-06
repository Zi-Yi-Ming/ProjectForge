from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.agents.persistence import JsonExecutionPersistence
from app.cli.app import app
from app.product.project_persistence import ProjectPersistence
from app.product.workflow import ProjectWorkflow
from app.schemas.execution import ExecutionRun, ExecutionStatus
from app.schemas.project import ProjectStatus
from app.schemas.task import Task, TaskGraph, TaskStatus
from tests.fakes import requires_hermes


runner = CliRunner()


def _base_dir_option(tmp_path: Path) -> list[str]:
    return ["--base-dir", str(tmp_path)]


def _create_project(tmp_path: Path, name: str = "CLI Run") -> str:
    result = runner.invoke(app, ["create", name] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    return [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]


def _transition_ready(tmp_path: Path, project_id: str) -> None:
    for status in [ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY]:
        result = runner.invoke(app, ["transition", project_id, status.value] + _base_dir_option(tmp_path))
        assert result.exit_code == 0


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # `run start` loads the task graph via a default ProjectWorkflow whose
    # artifact store is CWD-relative.
    monkeypatch.chdir(tmp_path)


@requires_hermes
def test_cli_run_start(tmp_path: Path) -> None:
    project_id = _create_project(tmp_path)
    _transition_ready(tmp_path, project_id)
    task_graph = TaskGraph(
        project=project_id,
        tasks=[
            Task(
                id="T1",
                phase_id="P1",
                title="hello",
                goal="Create hello.txt",
                status=TaskStatus.PENDING,
            )
        ],
        total_tasks=1,
        required_tasks=1,
        optional_tasks=0,
    )
    workflow = ProjectWorkflow()
    persistence = ProjectPersistence(base_dir=tmp_path)
    project = persistence.load_project(project_id)
    project.task_graph_ref = workflow.persist_task_graph(project_id, task_graph)
    persistence.save_project(project)
    result = runner.invoke(app, ["run", "start", project_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0, result.output + result.stderr
    assert "Run completed" in result.output
    assert "Status: COMPLETED" in result.output or "Status: BLOCKED" in result.output or "Status: FAILED" in result.output


def test_cli_run_start_requires_ready(tmp_path: Path) -> None:
    project_id = _create_project(tmp_path)
    result = runner.invoke(app, ["run", "start", project_id] + _base_dir_option(tmp_path))
    assert result.exit_code != 0
    assert "Error:" in result.stderr


def test_cli_run_show(tmp_path: Path) -> None:
    project_id = _create_project(tmp_path)
    run_id = f"run-{project_id}-20260101000000000000"
    run = ExecutionRun(run_id=run_id, project=project_id, status=ExecutionStatus.RUNNING, total_tasks=1, started_at="2026-01-01T00:00:00Z")
    JsonExecutionPersistence(base_dir=tmp_path).create_run(run)
    result = runner.invoke(app, ["run", "show", project_id, run_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    assert run_id in result.output


def test_cli_run_cancel(tmp_path: Path) -> None:
    project_id = _create_project(tmp_path)
    run_id = f"run-{project_id}-20260101000000000000"
    run = ExecutionRun(run_id=run_id, project=project_id, status=ExecutionStatus.RUNNING, total_tasks=1, started_at="2026-01-01T00:00:00Z")
    JsonExecutionPersistence(base_dir=tmp_path).create_run(run)
    result = runner.invoke(app, ["run", "cancel", project_id, run_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    assert run_id in result.output

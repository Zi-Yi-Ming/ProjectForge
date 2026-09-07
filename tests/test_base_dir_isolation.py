from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli.app import app
from app.product.errors import ProjectNotFoundError
from app.product.project_persistence import ProjectPersistence
from app.product.workflow import ProjectWorkflow
from app.schemas.project import ProjectStatus
from app.schemas.task import Task, TaskGraph, TaskStatus

runner = CliRunner()


def _graph(project_id: str) -> TaskGraph:
    return TaskGraph(
        project=project_id,
        tasks=[Task(id="T1", phase_id="P1", title="hello", goal="Create hello.txt", status=TaskStatus.PENDING)],
        total_tasks=1,
        required_tasks=1,
        optional_tasks=0,
    )


def _run_lifecycle(base: Path) -> str:
    result = runner.invoke(app, ["create", "Isolation"] + ["--base-dir", str(base)])
    assert result.exit_code == 0, result.output + result.stderr
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    for status in (ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY):
        result = runner.invoke(app, ["transition", project_id, status.value, "--base-dir", str(base)])
        assert result.exit_code == 0

    workflow = ProjectWorkflow(base_dir=base)
    persistence = ProjectPersistence(base_dir=base / "projects")
    project = persistence.load_project(project_id)
    project.task_graph_ref = workflow.persist_task_graph(project_id, _graph(project_id))
    persistence.save_project(project)

    result = runner.invoke(app, ["run", "start", project_id, "--base-dir", str(base), "--executor", "mock"])
    assert result.exit_code == 0, result.output + result.stderr
    assert "Status: COMPLETED" in result.output
    return project_id


def _service_for(base: Path):
    from app.product.service import ProjectService as _Service

    return _Service(persistence=ProjectPersistence(base_dir=base / "projects"), base_dir=base)


def test_base_dirs_are_fully_isolated(tmp_path: Path) -> None:
    base_a = tmp_path / "base-a"
    base_b = tmp_path / "base-b"
    project_a = _run_lifecycle(base_a)
    project_b = _run_lifecycle(base_b)

    # Each base holds its own projects, events, runs and workspaces.
    assert (base_a / "projects" / project_a).exists()
    assert (base_b / "projects" / project_b).exists()
    assert not (base_a / "projects" / project_b).exists()
    assert not (base_b / "projects" / project_a).exists()

    service_a = _service_for(base_a)
    service_b = _service_for(base_b)
    assert service_a.load(project_a).name == "Isolation"
    assert service_b.load(project_b).name == "Isolation"
    with pytest.raises(ProjectNotFoundError):
        service_b.load(project_a)
    with pytest.raises(ProjectNotFoundError):
        service_a.load(project_b)

    assert any((base_a / "runs").iterdir())
    assert any((base_b / "runs").iterdir())
    assert any((base_a / "workspaces").iterdir())
    assert any((base_b / "workspaces").iterdir())

    # Same default layout also works without an explicit --base-dir.
    default_service = ProjectPersistence(base_dir=Path(".runtime") / "projects")
    assert default_service.base_dir == Path(".runtime") / "projects"

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from app.agents.persistence import JsonExecutionPersistence
from app.cli.app import app
from app.product.project_persistence import ProjectPersistence
from app.product.run_control import RunControl
from app.product.service import ProjectService
from app.schemas.execution import ExecutionStatus
from app.schemas.project import ProjectStatus
from app.schemas.task import Task, TaskGraph, TaskStatus
from tests.fakes import FakeExecutor

runner = CliRunner()


def _base_dir_option(tmp_path: Path) -> list[str]:
    return ["--base-dir", str(tmp_path)]


def _graph_with_failed() -> TaskGraph:
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], status=TaskStatus.DONE, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g2", why="w2", dependencies=["T1"], status=TaskStatus.FAILED, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
    ]
    return TaskGraph(project="demo", tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


def _project_service(tmp_path: Path) -> ProjectService:
    persistence = ProjectPersistence(base_dir=tmp_path)
    execution_persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence)
    return ProjectService(persistence=persistence, run_control=run_control)


def _failed_run(service: ProjectService, project_id: str, task_graph: TaskGraph, run_dir: Path):
    run = service.start_run(project_id, task_graph, run_dir, FakeExecutor())
    run.status = ExecutionStatus.FAILED
    service.run_control.execution_persistence.save_run(run)
    service.run_control.complete_run(project_id, run.run_id, ExecutionStatus.FAILED)
    project = service.persistence.load_project(project_id)
    project.last_run_id = run.run_id
    service.persistence.save_project(project)
    return run


def test_cli_replan(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Replan"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    for status in [ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY]:
        result = runner.invoke(app, ["transition", project_id, status.value] + _base_dir_option(tmp_path))
        assert result.exit_code == 0
    run = _failed_run(_project_service(tmp_path), project_id, _graph_with_failed(), tmp_path)
    result = runner.invoke(app, ["replan", "create", project_id, run.run_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    assert "Proposal created" in result.output


def test_cli_replan_show(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Replan"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    for status in [ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY]:
        result = runner.invoke(app, ["transition", project_id, status.value] + _base_dir_option(tmp_path))
        assert result.exit_code == 0
    run = _failed_run(_project_service(tmp_path), project_id, _graph_with_failed(), tmp_path)
    result = runner.invoke(app, ["replan", "create", project_id, run.run_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    proposal_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("Proposal ID: ")][0]
    result = runner.invoke(app, ["replan", "show", project_id, proposal_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    assert proposal_id in result.output


def test_cli_replan_approve(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Replan"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    for status in [ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY]:
        result = runner.invoke(app, ["transition", project_id, status.value] + _base_dir_option(tmp_path))
        assert result.exit_code == 0
    run = _failed_run(_project_service(tmp_path), project_id, _graph_with_failed(), tmp_path)
    result = runner.invoke(app, ["replan", "create", project_id, run.run_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    proposal_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("Proposal ID: ")][0]
    result = runner.invoke(app, ["replan", "approve", project_id, proposal_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    assert "APPROVED" in result.output


def test_cli_replan_reject(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Replan"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    for status in [ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY]:
        result = runner.invoke(app, ["transition", project_id, status.value] + _base_dir_option(tmp_path))
        assert result.exit_code == 0
    run = _failed_run(_project_service(tmp_path), project_id, _graph_with_failed(), tmp_path)
    result = runner.invoke(app, ["replan", "create", project_id, run.run_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    proposal_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("Proposal ID: ")][0]
    result = runner.invoke(app, ["replan", "reject", project_id, proposal_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    assert "REJECTED" in result.output


def test_cli_run_resume(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Resume"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    for status in [ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY]:
        result = runner.invoke(app, ["transition", project_id, status.value] + _base_dir_option(tmp_path))
        assert result.exit_code == 0
    result = runner.invoke(app, ["run", "resume", project_id] + _base_dir_option(tmp_path))
    assert result.exit_code != 0
    assert "Error:" in result.stderr

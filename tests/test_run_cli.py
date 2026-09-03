from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from app.cli.app import app
from app.schemas.project import ProjectStatus


runner = CliRunner()


def _base_dir_option(tmp_path: Path) -> list[str]:
    return ["--base-dir", str(tmp_path)]


def test_cli_run_start(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Run"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    result = runner.invoke(app, ["transition", project_id, "ANALYZING"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    result = runner.invoke(app, ["transition", project_id, "PLANNING"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    result = runner.invoke(app, ["transition", project_id, "READY"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    result = runner.invoke(app, ["run", "start", project_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    assert "Run started" in result.output
    assert "Run ID: run-" in result.output


def test_cli_run_start_requires_ready(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Run"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    result = runner.invoke(app, ["run", "start", project_id] + _base_dir_option(tmp_path))
    assert result.exit_code != 0
    assert "Error:" in result.stderr


def test_cli_run_show(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Run"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    for status in [ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY]:
        result = runner.invoke(app, ["transition", project_id, status.value] + _base_dir_option(tmp_path))
        assert result.exit_code == 0
    run_id = f"run-{project_id}-20260101000000000000"
    result = runner.invoke(app, ["run", "show", project_id, run_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    assert run_id in result.output


def test_cli_run_cancel(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Run"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    for status in [ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY]:
        result = runner.invoke(app, ["transition", project_id, status.value] + _base_dir_option(tmp_path))
        assert result.exit_code == 0
    run_id = f"run-{project_id}-20260101000000000000"
    result = runner.invoke(app, ["run", "cancel", project_id, run_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    assert run_id in result.output

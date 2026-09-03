from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from app.cli.app import app
from app.product.errors import (
    ActiveRunExistsError,
    CommandNotAllowedError,
    InvalidStateTransitionError,
    ProjectNotFoundError,
)
from app.product.event_store import EventStore
from app.product.project_persistence import ProjectPersistence
from app.product.service import ProjectService
from app.schemas.project import ProjectStatus


runner = CliRunner()


def _base_dir_option(tmp_path: Path) -> list[str]:
    return ["--base-dir", str(tmp_path)]


def test_create_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Demo"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0, result.output + result.stderr
    assert "Project created" in result.output
    assert "ID: proj-" in result.output
    assert "Status: CREATED" in result.output


def test_show_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Demo"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    result = runner.invoke(app, ["show", project_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0, result.output + result.stderr
    assert project_id in result.output
    assert "Status: CREATED" in result.output


def test_show_missing_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["show", "proj-missing"] + _base_dir_option(tmp_path))
    assert result.exit_code != 0
    assert "Error:" in result.stderr


def test_valid_transition(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Demo"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    result = runner.invoke(app, ["transition", project_id, "ANALYZING"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0, result.output + result.stderr
    assert "Status: ANALYZING" in result.output


def test_invalid_transition(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Demo"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    result = runner.invoke(app, ["transition", project_id, "COMPLETED"] + _base_dir_option(tmp_path))
    assert result.exit_code != 0
    assert "Error:" in result.stderr


def test_events_command(tmp_path: Path) -> None:
    service = ProjectService(
        persistence=ProjectPersistence(base_dir=tmp_path),
        event_store=EventStore(base_dir=tmp_path),
    )
    project = service.create("CLI Event Demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    result = runner.invoke(app, ["events", project.project_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0, result.output + result.stderr
    assert "PROJECT_CREATED" in result.output
    assert "PROJECT_STATE_CHANGED" in result.output


def test_persistence_restart_via_cli(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "CLI Restart"] + _base_dir_option(tmp_path))
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    result = runner.invoke(app, ["show", project_id] + _base_dir_option(tmp_path))
    assert result.exit_code == 0, result.output + result.stderr
    assert "CLI Restart" in result.output

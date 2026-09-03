from __future__ import annotations

import pytest

from app.product.errors import (
    ActiveRunExistsError,
    CommandNotAllowedError,
    InvalidStateTransitionError,
    ProjectNotFoundError,
)
from app.product.service import ProjectService
from app.schemas.project import Project, ProjectStatus


def test_create_project_success() -> None:
    service = ProjectService()
    project = service.create("demo")
    assert project.name == "demo"
    assert project.status == ProjectStatus.CREATED
    assert project.project_id.startswith("proj-")


def test_create_project_unique_project_id() -> None:
    service = ProjectService()
    p1 = service.create("a")
    p2 = service.create("b")
    assert p1.project_id != p2.project_id


def test_create_project_initial_state() -> None:
    service = ProjectService()
    project = service.create("demo")
    assert project.current_stage == "CREATED"
    assert project.created_at is not None
    assert project.updated_at is not None


def test_load_existing_project() -> None:
    service = ProjectService()
    created = service.create("demo")
    loaded = service.load(created.project_id)
    assert loaded.project_id == created.project_id
    assert loaded.name == "demo"


def test_load_missing_project_raises() -> None:
    service = ProjectService()
    with pytest.raises(ProjectNotFoundError):
        service.load("proj-missing")


def test_valid_transitions() -> None:
    service = ProjectService()
    project = service.create("demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    service.transition_to(project.project_id, ProjectStatus.EXECUTING)
    service.transition_to(project.project_id, ProjectStatus.COMPLETED)
    loaded = service.load(project.project_id)
    assert loaded.status == ProjectStatus.COMPLETED


def test_invalid_transition_raises() -> None:
    service = ProjectService()
    project = service.create("demo")
    with pytest.raises(InvalidStateTransitionError):
        service.transition_to(project.project_id, ProjectStatus.READY)


def test_terminal_state_protection() -> None:
    service = ProjectService()
    project = service.create("demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    service.transition_to(project.project_id, ProjectStatus.EXECUTING)
    service.transition_to(project.project_id, ProjectStatus.COMPLETED)
    with pytest.raises(InvalidStateTransitionError):
        service.transition_to(project.project_id, ProjectStatus.ANALYZING)


def test_blocked_to_executing_resume() -> None:
    service = ProjectService()
    project = service.create("demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    service.transition_to(project.project_id, ProjectStatus.EXECUTING)
    service.transition_to(project.project_id, ProjectStatus.BLOCKED)
    service.transition_to(project.project_id, ProjectStatus.EXECUTING)
    loaded = service.load(project.project_id)
    assert loaded.status == ProjectStatus.EXECUTING


def test_blocked_to_failed_reject() -> None:
    service = ProjectService()
    project = service.create("demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    service.transition_to(project.project_id, ProjectStatus.EXECUTING)
    service.transition_to(project.project_id, ProjectStatus.BLOCKED)
    service.transition_to(project.project_id, ProjectStatus.FAILED)
    loaded = service.load(project.project_id)
    assert loaded.status == ProjectStatus.FAILED


def test_command_validation_allowed_state() -> None:
    service = ProjectService()
    project = service.create("demo")
    assert service.can_start_run(project.project_id) is False
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    assert service.can_start_run(project.project_id) is True


def test_active_run_invariant_no_active_run() -> None:
    service = ProjectService()
    project = service.create("demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    assert service.can_start_run(project.project_id) is True


def test_active_run_invariant_active_run_exists() -> None:
    service = ProjectService()
    project = service.create("demo")
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    service.register_active_run(project.project_id, "run-1")
    assert service.can_start_run(project.project_id) is False
    with pytest.raises(ActiveRunExistsError):
        service.register_active_run(project.project_id, "run-2")


def test_persistence_round_trip() -> None:
    service = ProjectService()
    created = service.create("demo")
    service.transition_to(created.project_id, ProjectStatus.ANALYZING)
    reloaded = service.load(created.project_id)
    assert reloaded.status == ProjectStatus.ANALYZING
    assert reloaded.project_id == created.project_id


def test_project_run_task_state_separation() -> None:
    service = ProjectService()
    project = service.create("demo")
    assert project.status == ProjectStatus.CREATED
    assert project.status != ProjectStatus.READY
    assert project.status != ProjectStatus.EXECUTING

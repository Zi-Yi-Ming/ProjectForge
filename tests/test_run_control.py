from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.persistence import JsonExecutionPersistence
from app.product.errors import (
    ActiveRunExistsError,
    CommandNotAllowedError,
    InvalidProjectStateError,
    InvalidStateTransitionError,
    ProjectNotFoundError,
)
from app.product.project_persistence import ProjectPersistence
from app.product.run_control import RunControl
from app.product.service import ProjectService
from app.schemas.execution import ExecutionRun, ExecutionStatus
from app.schemas.project import Project, ProjectStatus
from app.schemas.task import Task, TaskGraph, TaskStatus


class FakeExecutor:
    def __init__(self, run: ExecutionRun | None = None) -> None:
        self.run = run or ExecutionRun(
            run_id="run-fake",
            project="demo",
            status=ExecutionStatus.COMPLETED,
            total_tasks=1,
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:01:00Z",
            completed_tasks=["T1"],
            failed_tasks=[],
            blocked_tasks=[],
            ready_tasks=[],
        )

    def run(self, task_graph: TaskGraph, run_id: str, run_dir: Path) -> ExecutionRun:
        return self.run


def _graph() -> TaskGraph:
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], status=TaskStatus.READY),
    ]
    return TaskGraph(project="demo", tasks=tasks, total_tasks=1, required_tasks=1, optional_tasks=0)


def _ready_project(service: ProjectService, name: str) -> Project:
    project = service.create(name)
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.transition_to(project.project_id, ProjectStatus.READY)
    return service.load(project.project_id)


def test_start_run(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    run_control = RunControl()
    service = ProjectService(persistence=persistence, run_control=run_control)
    project = _ready_project(service, "run-demo")
    run = service.start_run(project.project_id, _graph(), tmp_path, FakeExecutor())
    assert run.status == ExecutionStatus.RUNNING
    assert run.project == project.project_id


def test_start_run_updates_project(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    run_control = RunControl()
    service = ProjectService(persistence=persistence, run_control=run_control)
    project = _ready_project(service, "run-demo")
    run = service.start_run(project.project_id, _graph(), tmp_path, FakeExecutor())
    loaded = service.load(project.project_id)
    assert loaded.last_run_id == run.run_id


def test_start_run_requires_ready(tmp_path: Path) -> None:
    service = ProjectService()
    project = service.create("not-ready")
    with pytest.raises(InvalidProjectStateError):
        service.start_run(project.project_id, _graph(), tmp_path, FakeExecutor())


def test_one_active_run_only(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    run_control = RunControl()
    service = ProjectService(persistence=persistence, run_control=run_control)
    project = _ready_project(service, "run-demo")
    service.start_run(project.project_id, _graph(), tmp_path, FakeExecutor())
    with pytest.raises(ActiveRunExistsError):
        service.start_run(project.project_id, _graph(), tmp_path, FakeExecutor())


def test_run_persists(tmp_path: Path) -> None:
    persistence = ProjectPersistence(base_dir=tmp_path)
    run_control = RunControl()
    service = ProjectService(persistence=persistence, run_control=run_control)
    project = _ready_project(service, "run-demo")
    run = service.start_run(project.project_id, _graph(), tmp_path, FakeExecutor())
    new_control = RunControl(execution_persistence=run_control.execution_persistence)
    assert new_control.load_run(project.project_id, run.run_id).run_id == run.run_id


def test_cancel_marks_run_blocked(tmp_path: Path) -> None:
    run_control = RunControl()
    project = Project(name="cancel-demo", status=ProjectStatus.READY, project_id="proj-cancel")
    run = run_control.start_run(project, _graph(), tmp_path, FakeExecutor())
    cancelled = run_control.cancel_run(project.project_id, run.run_id)
    assert cancelled.status == ExecutionStatus.BLOCKED
    assert cancelled.blocking_reason == "CANCELLED"
    assert run_control.cancel_requested(run.run_id)

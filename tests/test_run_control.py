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
        self._run = run or ExecutionRun(
            run_id="run-fake",
            project="demo",
            status=ExecutionStatus.RUNNING,
            total_tasks=1,
            started_at="2026-01-01T00:00:00Z",
        )

    def run(self, task_graph: TaskGraph, project_map=None, run_dir=None, run_id=None, cancel_check=None) -> ExecutionRun:
        return self._run


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


def test_complete_run_does_not_overwrite_cancelled(tmp_path: Path) -> None:
    run_control = RunControl()
    project = Project(name="cancel-demo", status=ProjectStatus.READY, project_id="proj-cancel")
    run = run_control.start_run(project, _graph(), tmp_path, FakeExecutor())
    run_control.cancel_run(project.project_id, run.run_id)
    final = run_control.complete_run(project.project_id, run.run_id, ExecutionStatus.COMPLETED)
    assert final.status == ExecutionStatus.BLOCKED
    assert final.blocking_reason == "CANCELLED"


def test_start_run_stops_on_persisted_cancellation(tmp_path: Path) -> None:
    from app.agents.mock_executor import MockExecutor
    from app.agents.orchestrator import ExecutionOrchestrator

    persistence = ProjectPersistence(base_dir=tmp_path)
    execution_persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence)
    service = ProjectService(persistence=persistence, run_control=run_control)
    project = _ready_project(service, "cancel-mid-run")

    class CancelAfterFirstTask(MockExecutor):
        def __init__(self, workspace: Path) -> None:
            super().__init__(workspace=workspace)
            self.calls = 0

        def execute(self, task_contract, project_map):
            result = super().execute(task_contract, project_map)
            self.calls += 1
            if self.calls >= 1:
                runs = execution_persistence.list_runs()
                if runs:
                    run = execution_persistence.load_run(runs[0].run_id)
                    run.cancel_requested = True
                    execution_persistence.create_run(run)
            return result

    graph = TaskGraph(
        project=project.project_id,
        tasks=[
            Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], status=TaskStatus.PENDING, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
            Task(id="T2", phase_id="P1", title="T2", goal="g2", why="w2", dependencies=["T1"], status=TaskStatus.PENDING, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
        ],
        total_tasks=2,
        required_tasks=2,
        optional_tasks=0,
    )
    run_dir = tmp_path / "ws"
    run_dir.mkdir(parents=True, exist_ok=True)
    run = run_control.start_run(project, graph, run_dir, ExecutionOrchestrator(adapter=CancelAfterFirstTask(run_dir)))
    assert run.status == ExecutionStatus.BLOCKED
    assert run.blocking_reason == "CANCELLED"
    assert run.cancel_requested is True
    done = [r for r in run.task_results if r.status == "DONE"]
    assert [r.task_id for r in done] == ["T1"]
    assert len(run.task_results) == 1
    assert graph.tasks[1].status == TaskStatus.BLOCKED
    loaded = execution_persistence.load_run(run.run_id)
    assert loaded.cancel_requested is True
    assert loaded.status == ExecutionStatus.BLOCKED

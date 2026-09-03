from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.product.errors import (
    ActiveRunExistsError,
    CommandNotAllowedError,
    InvalidProjectStateError,
    InvalidStateTransitionError,
    ProjectNotFoundError,
)
from app.product.event_store import EventStore
from app.product.lifecycle import ProjectLifecycle
from app.product.project_persistence import ProjectPersistence
from app.product.run_control import RunControl
from app.product.replan_control import ReplanControl
from app.schemas.event import Actor, ProductEvent
from app.schemas.project import Project, ProjectStatus
from app.schemas.task import TaskGraph


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_event_id() -> str:
    return f"evt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


class ProjectService:
    def __init__(self, persistence: ProjectPersistence | None = None, event_store: EventStore | None = None, run_control: RunControl | None = None, replan_control: Any = None) -> None:
        self.persistence = persistence or ProjectPersistence()
        self.event_store = event_store or EventStore()
        self._active_runs: dict[str, str] = {}
        self.run_control = run_control or RunControl()
        self.replan_control = replan_control or ReplanControl(persistence=self.persistence, run_control=self.run_control)

    def create(self, name: str) -> Project:
        project = Project(name=name)
        project.project_id = f"proj-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        project.created_at = _now_iso()
        project.updated_at = _now_iso()
        project.current_stage = ProjectStatus.CREATED.value
        self.persistence.save_project(project)
        self.event_store.append(
            ProductEvent(
                event_id=_new_event_id(),
                event_type="PROJECT_CREATED",
                project_id=project.project_id,
                timestamp=_now_iso(),
                actor=Actor.SYSTEM,
                payload={"name": name},
            )
        )
        return project

    def load(self, project_id: str) -> Project:
        try:
            return self.persistence.load_project(project_id)
        except FileNotFoundError as exc:
            raise ProjectNotFoundError(f"Project {project_id} not found") from exc

    def transition_to(self, project_id: str, target: ProjectStatus) -> Project:
        project = self.load(project_id)
        if not ProjectLifecycle.can_transition(project.status, target):
            raise InvalidStateTransitionError(
                f"Cannot transition project {project_id} from {project.status} to {target}"
            )
        previous = project.status
        project.status = target
        project.current_stage = target.value
        project.updated_at = _now_iso()
        self.persistence.save_project(project)
        self.event_store.append(
            ProductEvent(
                event_id=_new_event_id(),
                event_type="PROJECT_STATE_CHANGED",
                project_id=project_id,
                timestamp=_now_iso(),
                actor=Actor.SYSTEM,
                payload={"from": previous.value, "to": target.value},
            )
        )
        return project

    def can_start_run(self, project_id: str) -> bool:
        project = self.load(project_id)
        if project.status != ProjectStatus.READY:
            return False
        return self._active_runs.get(project_id) is None

    def register_active_run(self, project_id: str, run_id: str) -> None:
        project = self.load(project_id)
        if not self.can_start_run(project_id):
            raise ActiveRunExistsError(
                f"Project {project_id} already has an active run: {self._active_runs.get(project_id)}"
            )
        self._active_runs[project_id] = run_id
        project.last_run_id = run_id
        project.updated_at = _now_iso()
        self.persistence.save_project(project)

    def complete_run(self, project_id: str) -> None:
        self._active_runs.pop(project_id, None)

    def start_run(self, project_id: str, task_graph: Any = None, run_dir: Any = None, executor: Any = None) -> Any:
        project = self.load(project_id)
        if project.status != ProjectStatus.READY:
            raise InvalidProjectStateError(f"Project {project_id} is not READY: {project.status}")
        run = self.run_control.start_run(project, task_graph, run_dir, executor)
        self.register_active_run(project_id, run.run_id)
        self.event_store.append(
            ProductEvent(
                event_id=_new_event_id(),
                event_type="RUN_CREATED",
                project_id=project_id,
                timestamp=_now_iso(),
                actor=Actor.SYSTEM,
                payload={"run_id": run.run_id},
            )
        )
        return run

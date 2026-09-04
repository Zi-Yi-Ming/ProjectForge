from __future__ import annotations

import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.agents.persistence import JsonExecutionPersistence
from app.product.errors import (
    ActiveRunExistsError,
    CommandNotAllowedError,
    InvalidProjectStateError,
    InvalidStateTransitionError,
    ProjectNotFoundError,
)
from app.product.event_store import Actor, EventStore, ProductEvent
from app.product.project_persistence import ProjectPersistence
from app.schemas.execution import ExecutionRun, ExecutionStatus


class RunControl:
    def __init__(
        self,
        persistence: ProjectPersistence | None = None,
        execution_persistence: JsonExecutionPersistence | None = None,
        *,
        event_store: EventStore | None = None,
        on_run_started: Callable[..., Any] | None = None,
        on_run_completed: Callable[..., Any] | None = None,
        on_run_failed: Callable[..., Any] | None = None,
        on_run_cancelled: Callable[..., Any] | None = None,
        executor: Callable[..., Any] | None = None,
    ) -> None:
        self.persistence = persistence or ProjectPersistence()
        self.execution_persistence = execution_persistence or JsonExecutionPersistence()
        self.event_store = event_store
        self._on_run_started = on_run_started
        self._on_run_completed = on_run_completed
        self._on_run_failed = on_run_failed
        self._on_run_cancelled = on_run_cancelled
        self.executor = executor
        self._active_runs: dict[str, str] = {}
        self._lock = threading.Lock()
        self._cancellations: set[str] = set()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _event(self, event_type: str, project_id: str, run_id: str, payload: dict[str, Any] | None = None) -> None:
        if self.event_store is None:
            return
        event = ProductEvent(
            event_id=secrets.token_hex(16),
            event_type=event_type,
            project_id=project_id,
            run_id=run_id,
            actor=Actor.SYSTEM,
            timestamp=self._now(),
            payload=payload or {},
        )
        self.event_store.append(event)

    def start_run(self, project: Any, task_graph: Any = None, run_dir: Any = None, executor: Any = None) -> ExecutionRun:
        project_id = project.project_id if hasattr(project, "project_id") else str(project)
        with self._lock:
            if project_id in self._cancellations:
                self._cancellations.discard(project_id)
            active = self._active_runs.get(project_id)
            if active and self.execution_persistence.run_path(active).exists():
                run = self.execution_persistence.load_run(active)
                if run.status == ExecutionStatus.RUNNING:
                    raise ActiveRunExistsError(f"Project {project_id} already has an active run: {active}")

            run_id = f"run-{project_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
            run = ExecutionRun(
                run_id=run_id,
                project=project_id,
                status=ExecutionStatus.RUNNING,
                total_tasks=len(task_graph.tasks) if task_graph is not None else 0,
                started_at=self._now(),
            )
            self.execution_persistence.create_run(run)
            self._active_runs[project_id] = run_id
            self._event("RUN_STARTED", project_id, run_id)
            if self._on_run_started is not None:
                self._on_run_started(run)

            # Minimal bridge to execution engine.
            # Executor is expected to be ExecutionOrchestrator or compatible.
            # It may create its own run; we merge results into the Product Core run.
            if executor is not None and task_graph is not None:
                try:
                    from app.schemas.implementation import ProjectMap
                    execution_run = executor.run(
                        task_graph,
                        ProjectMap(architecture="", services=[], modules=[], technology=[], data_flow=""),
                        run_dir=run_dir,
                    )
                    if execution_run.task_results:
                        run.task_results = execution_run.task_results
                    if execution_run.status in {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.BLOCKED}:
                        run.status = execution_run.status
                        run.finished_at = execution_run.finished_at
                        run.completed_tasks = execution_run.completed_tasks
                        run.failed_tasks = execution_run.failed_tasks
                        run.blocked_tasks = execution_run.blocked_tasks
                        self.execution_persistence.create_run(run)
                        if run.status == ExecutionStatus.COMPLETED:
                            self._event("RUN_COMPLETED", project_id, run_id)
                        elif run.status == ExecutionStatus.FAILED:
                            self._event("RUN_FAILED", project_id, run_id)
                        elif run.status == ExecutionStatus.BLOCKED:
                            self._event("RUN_BLOCKED", project_id, run_id)
                except Exception as exc:
                    run.status = ExecutionStatus.FAILED
                    run.finished_at = self._now()
                    run.failed_tasks = [run.current_task_id] if run.current_task_id else []
                    run.blocking_reason = str(exc)
                    self.execution_persistence.create_run(run)
                    self._event("RUN_FAILED", project_id, run_id, {"blocking_reason": str(exc)})
                    raise

            return run

    def complete_run(self, project_id: str, run_id: str, status: ExecutionStatus = ExecutionStatus.COMPLETED) -> ExecutionRun:
        run = self.execution_persistence.load_run(run_id)
        was_terminal = run.status in {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.BLOCKED}
        if run.status != status:
            run.status = status
            run.finished_at = self._now()
            self.execution_persistence.create_run(run)
        if project_id in self._active_runs and self._active_runs[project_id] == run_id:
            self._active_runs.pop(project_id, None)
        if status == ExecutionStatus.COMPLETED and not was_terminal:
            self._event("RUN_COMPLETED", project_id, run_id)
            if self._on_run_completed is not None:
                self._on_run_completed(run)
        elif status == ExecutionStatus.FAILED and not was_terminal:
            self._event("RUN_FAILED", project_id, run_id)
            if self._on_run_failed is not None:
                self._on_run_failed(run)
        elif status == ExecutionStatus.BLOCKED and not was_terminal:
            self._event("RUN_BLOCKED", project_id, run_id)
        return run

    def request_cancel(self, project_id: str, run_id: str) -> None:
        run = self.execution_persistence.load_run(run_id)
        if run.status != ExecutionStatus.RUNNING:
            return
        self._cancellations.add(run_id)
        self._event("RUN_CANCEL_REQUESTED", project_id, run_id)

    def cancel_requested(self, run_id: str) -> bool:
        return run_id in self._cancellations

    def cancel_run(self, project_id: str, run_id: str) -> ExecutionRun:
        self.request_cancel(project_id, run_id)
        run = self.execution_persistence.load_run(run_id)
        run.status = ExecutionStatus.BLOCKED
        run.blocking_reason = "CANCELLED"
        run.finished_at = self._now()
        self.execution_persistence.create_run(run)
        if project_id in self._active_runs and self._active_runs[project_id] == run_id:
            self._active_runs.pop(project_id, None)
        self._event("RUN_CANCELLED", project_id, run_id)
        if self._on_run_cancelled is not None:
            self._on_run_cancelled(run)
        return run

    def load_run(self, project_id: str, run_id: str) -> ExecutionRun:
        return self.execution_persistence.load_run(run_id)

    def get_run(self, run_id: str) -> ExecutionRun:
        return self.execution_persistence.load_run(run_id)

    def active_run(self, project_id: str) -> ExecutionRun | None:
        run_id = self._active_runs.get(project_id)
        if not run_id:
            return None
        if self.execution_persistence.run_path(run_id).exists():
            return self.execution_persistence.load_run(run_id)
        return None

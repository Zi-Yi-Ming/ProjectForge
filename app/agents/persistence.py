from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from app.schemas.execution import ExecutionRun, ExecutionStatus
from app.schemas.persistence import Artifact, PersistedExecution


class JsonExecutionPersistence:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(".runtime")
        self.runs_dir = self.base_dir / "runs"

    def create_run(self, execution_run: ExecutionRun) -> PersistedExecution:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        persisted = PersistedExecution(
            run_id=execution_run.run_id,
            project=execution_run.project,
            status=execution_run.status.value,
            current_task_id=execution_run.current_task_id,
            completed_tasks=list(execution_run.completed_tasks),
            failed_tasks=list(execution_run.failed_tasks),
            blocked_tasks=list(execution_run.blocked_tasks),
            ready_tasks=list(execution_run.ready_tasks),
            total_tasks=execution_run.total_tasks,
            started_at=execution_run.started_at,
            finished_at=execution_run.finished_at,
            blocking_reason=execution_run.blocking_reason,
            version=1,
            task_records=list(execution_run.task_results),
        )
        self._write_json(self.runs_dir / execution_run.run_id / "execution.json", persisted.model_dump())
        return persisted

    def save_run(self, execution_run: ExecutionRun) -> PersistedExecution:
        return self.create_run(execution_run)

    def load_run(self, run_id: str) -> ExecutionRun:
        path = self.runs_dir / run_id / "execution.json"
        data = self._read_json(path)
        persisted = PersistedExecution.model_validate(data)
        return ExecutionRun(
            run_id=persisted.run_id,
            project=persisted.project,
            status=ExecutionStatus(persisted.status),
            current_task_id=persisted.current_task_id,
            completed_tasks=list(persisted.completed_tasks),
            failed_tasks=list(persisted.failed_tasks),
            blocked_tasks=list(persisted.blocked_tasks),
            ready_tasks=list(persisted.ready_tasks),
            total_tasks=persisted.total_tasks,
            started_at=persisted.started_at,
            finished_at=persisted.finished_at,
            blocking_reason=persisted.blocking_reason,
            task_results=list(persisted.task_records),
        )

    def save_task_record(self, run_id: str, record: Any) -> None:
        task_dir = self.runs_dir / run_id / "tasks"
        task_dir.mkdir(parents=True, exist_ok=True)
        payload = record.model_dump() if hasattr(record, "model_dump") else record
        self._write_json(task_dir / f"{record.task_id}.json", payload)

    def load_task_record(self, run_id: str, task_id: str) -> Any:
        path = self.runs_dir / run_id / "tasks" / f"{task_id}.json"
        return self._read_json(path)

    def list_runs(self) -> list[PersistedExecution]:
        if not self.runs_dir.exists():
            return []
        runs: list[PersistedExecution] = []
        for run_dir in self.runs_dir.iterdir():
            path = run_dir / "execution.json"
            if path.exists():
                data = self._read_json(path)
                runs.append(PersistedExecution.model_validate(data))
        runs.sort(key=lambda r: (r.started_at, r.run_id))
        return runs

    def exists(self, run_id: str) -> bool:
        return (self.runs_dir / run_id / "execution.json").exists()

    def run_path(self, run_id: str) -> Path:
        return self.runs_dir / run_id / "execution.json"

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(path))
        except Exception:
            if Path(tmp).exists():
                Path(tmp).unlink()
            raise

    def _read_json(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

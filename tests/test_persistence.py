from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.artifact_store import ArtifactStore
from app.schemas.execution import ExecutionRun, ExecutionStatus, TaskExecutionRecord
from app.schemas.persistence import Artifact, ArtifactType, PersistedExecution


def test_create_and_load_run(tmp_path: Path) -> None:
    from app.agents.persistence import JsonExecutionPersistence

    persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run = ExecutionRun(
        run_id="run-1",
        project="demo",
        status=ExecutionStatus.RUNNING,
        total_tasks=1,
        started_at="2026-01-01T00:00:00Z",
    )
    persisted = persistence.create_run(run)
    assert persisted.run_id == "run-1"
    assert persisted.version == 1
    assert persisted.status == "RUNNING"

    loaded = persistence.load_run("run-1")
    assert loaded.run_id == "run-1"
    assert loaded.status == ExecutionStatus.RUNNING
    assert loaded.project == "demo"
    assert loaded.total_tasks == 1


def test_save_run_updates_existing_run(tmp_path: Path) -> None:
    from app.agents.persistence import JsonExecutionPersistence

    persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run = ExecutionRun(
        run_id="run-2",
        project="demo",
        status=ExecutionStatus.RUNNING,
        total_tasks=1,
        started_at="2026-01-01T00:00:00Z",
    )
    persistence.create_run(run)
    run.status = ExecutionStatus.COMPLETED
    run.finished_at = "2026-01-01T00:01:00Z"
    persistence.save_run(run)

    loaded = persistence.load_run("run-2")
    assert loaded.status == ExecutionStatus.COMPLETED
    assert loaded.finished_at == "2026-01-01T00:01:00Z"


def test_save_and_load_task_record(tmp_path: Path) -> None:
    from app.agents.persistence import JsonExecutionPersistence

    persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run = ExecutionRun(
        run_id="run-3",
        project="demo",
        status=ExecutionStatus.RUNNING,
        total_tasks=1,
        started_at="2026-01-01T00:00:00Z",
    )
    persistence.create_run(run)
    record = TaskExecutionRecord(
        task_id="T1",
        phase="P1",
        title="Task 1",
        status="DONE",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:10Z",
    )
    persistence.save_task_record("run-3", record)
    loaded = persistence.load_task_record("run-3", "T1")
    assert loaded["task_id"] == "T1"
    assert loaded["status"] == "DONE"


def test_list_runs_sorted_by_started_at_and_run_id(tmp_path: Path) -> None:
    from app.agents.persistence import JsonExecutionPersistence

    persistence = JsonExecutionPersistence(base_dir=tmp_path)
    for run_id, started_at in [
        ("run-b", "2026-01-01T00:00:02Z"),
        ("run-a", "2026-01-01T00:00:01Z"),
        ("run-c", "2026-01-01T00:00:01Z"),
    ]:
        run = ExecutionRun(
            run_id=run_id,
            project="demo",
            status=ExecutionStatus.RUNNING,
            total_tasks=0,
            started_at=started_at,
        )
        persistence.create_run(run)

    runs = persistence.list_runs()
    assert [r.run_id for r in runs] == ["run-a", "run-c", "run-b"]


def test_exists(tmp_path: Path) -> None:
    from app.agents.persistence import JsonExecutionPersistence

    persistence = JsonExecutionPersistence(base_dir=tmp_path)
    assert not persistence.exists("missing")
    run = ExecutionRun(
        run_id="run-x",
        project="demo",
        status=ExecutionStatus.RUNNING,
        total_tasks=0,
        started_at="2026-01-01T00:00:00Z",
    )
    persistence.create_run(run)
    assert persistence.exists("run-x")


def test_atomic_write_does_not_leave_corrupt_json(tmp_path: Path) -> None:
    from app.agents.persistence import JsonExecutionPersistence

    persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run = ExecutionRun(
        run_id="run-atomic",
        project="demo",
        status=ExecutionStatus.RUNNING,
        total_tasks=0,
        started_at="2026-01-01T00:00:00Z",
    )
    persistence.create_run(run)
    path = tmp_path / "runs" / "run-atomic" / "execution.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["status"] == "RUNNING"


def test_load_missing_run_raises_error(tmp_path: Path) -> None:
    from app.agents.persistence import JsonExecutionPersistence

    persistence = JsonExecutionPersistence(base_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        persistence.load_run("missing")


def test_persisted_execution_version_is_one(tmp_path: Path) -> None:
    from app.agents.persistence import JsonExecutionPersistence

    persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run = ExecutionRun(
        run_id="run-ver",
        project="demo",
        status=ExecutionStatus.RUNNING,
        total_tasks=0,
        started_at="2026-01-01T00:00:00Z",
    )
    persisted = persistence.create_run(run)
    assert persisted.version == 1
    loaded = persistence.load_run("run-ver")
    # ExecutionRun itself does not carry version; persisted file does.
    path = tmp_path / "runs" / "run-ver" / "execution.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1

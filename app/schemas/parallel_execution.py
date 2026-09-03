from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class WorkerStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class WorkerRecord(BaseModel):
    worker_id: str = Field(default="", description="Worker identifier.")
    task_id: str = Field(default="", description="Dispatched task identifier.")
    status: WorkerStatus = Field(..., description="Current worker status.")
    started_at: str = Field(default="", description="Start timestamp.")
    finished_at: str = Field(default="", description="Finish timestamp.")
    error: str = Field(default="", description="Error detail when failed.")


class ParallelExecutionResult(BaseModel):
    run_id: str = Field(default="", description="Execution run identifier.")
    worker_count: int = Field(default=0, description="Configured max workers.")
    max_workers: int = Field(default=0, description="Configured max workers.")
    dispatched_tasks: list[str] = Field(default_factory=list, description="Dispatched task ids.")
    completed_tasks: list[str] = Field(default_factory=list, description="Completed task ids.")
    failed_tasks: list[str] = Field(default_factory=list, description="Failed task ids.")
    blocked_tasks: list[str] = Field(default_factory=list, description="Blocked task ids.")
    worker_results: list[WorkerRecord] = Field(default_factory=list, description="Per-worker results.")

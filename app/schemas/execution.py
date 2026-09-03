from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.implementation import AgentExecutionResult, TaskContract
from app.schemas.validation import ValidationResult


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class TaskExecutionRecord(BaseModel):
    task_id: str = Field(default="", description="Task identifier.")
    phase: str = Field(default="", description="Phase identifier.")
    title: str = Field(default="", description="Task title.")
    status: str = Field(default="", description="Final task status.")
    contract: TaskContract | None = Field(default=None, description="Task contract used.")
    execution_result: AgentExecutionResult | None = Field(default=None, description="Agent execution result.")
    validation_result: ValidationResult | None = Field(default=None, description="Validation result.")
    started_at: str = Field(default="", description="Start timestamp.")
    finished_at: str = Field(default="", description="Finish timestamp.")


class ExecutionRun(BaseModel):
    run_id: str = Field(default="", description="Execution run identifier.")
    project: str = Field(default="", description="Project name.")
    status: ExecutionStatus = Field(..., description="Overall execution status.")
    current_task_id: str = Field(default="", description="Currently executing task.")
    completed_tasks: list[str] = Field(default_factory=list, description="Completed task ids.")
    failed_tasks: list[str] = Field(default_factory=list, description="Failed task ids.")
    blocked_tasks: list[str] = Field(default_factory=list, description="Blocked task ids.")
    ready_tasks: list[str] = Field(default_factory=list, description="Ready task ids.")
    total_tasks: int = Field(default=0, description="Total task count.")
    started_at: str = Field(default="", description="Run start timestamp.")
    finished_at: str = Field(default="", description="Run finish timestamp.")
    task_results: list[TaskExecutionRecord] = Field(default_factory=list, description="Per-task execution records.")
    blocking_reason: str = Field(default="", description="Reason when blocked.")
    replan_count: int = Field(default=0, description="Number of replans applied.")
    active_proposal_id: str = Field(default="", description="Active replan proposal identifier.")

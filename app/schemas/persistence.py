from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.execution import ExecutionRun, TaskExecutionRecord
from app.schemas.implementation import AgentExecutionResult, GitCheckpoint
from app.schemas.validation import ValidationResult


class ArtifactType(str, Enum):
    AGENT_OUTPUT = "AGENT_OUTPUT"
    VALIDATION_RESULT = "VALIDATION_RESULT"
    GIT_CHECKPOINT = "GIT_CHECKPOINT"
    DIFF = "DIFF"
    TEST_RESULT = "TEST_RESULT"
    ERROR_LOG = "ERROR_LOG"


class Artifact(BaseModel):
    artifact_id: str = Field(default="", description="Artifact identifier.")
    task_id: str = Field(default="", description="Related task identifier.")
    artifact_type: ArtifactType = Field(..., description="Kind of artifact.")
    path: str = Field(default="", description="Relative path under run artifacts dir.")
    created_at: str = Field(default="", description="Creation timestamp.")
    metadata: list[str] = Field(default_factory=list, description="Structured metadata.")


class PersistedExecution(BaseModel):
    run_id: str = Field(default="", description="Execution run identifier.")
    project: str = Field(default="", description="Project name.")
    status: str = Field(default="", description="Execution status string.")
    current_task_id: str = Field(default="", description="Current task identifier.")
    completed_tasks: list[str] = Field(default_factory=list, description="Completed task ids.")
    failed_tasks: list[str] = Field(default_factory=list, description="Failed task ids.")
    blocked_tasks: list[str] = Field(default_factory=list, description="Blocked task ids.")
    ready_tasks: list[str] = Field(default_factory=list, description="Ready task ids.")
    total_tasks: int = Field(default=0, description="Total task count.")
    started_at: str = Field(default="", description="Run start timestamp.")
    finished_at: str = Field(default="", description="Run finish timestamp.")
    blocking_reason: str = Field(default="", description="Reason when blocked.")
    version: int = Field(default=1, description="Schema version.")
    task_records: list[TaskExecutionRecord] = Field(default_factory=list, description="Per-task execution records.")
    artifacts: list[Artifact] = Field(default_factory=list, description="Execution artifacts.")

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.task import Task


class ScopeStatus(str, Enum):
    WITHIN_SCOPE = "WITHIN_SCOPE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"


class AllowedTestAction(str, Enum):
    ADD_TEST = "ADD_TEST"
    MODIFY_RELEVANT_TEST = "MODIFY_RELEVANT_TEST"
    DELETE_TEST = "DELETE_TEST"
    WEAKEN_ASSERTION = "WEAKEN_ASSERTION"
    MODIFY_UNRELATED_TEST = "MODIFY_UNRELATED_TEST"


class ExecutionStatus(str, Enum):
    IMPLEMENTED = "IMPLEMENTED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


class ProjectMap(BaseModel):
    architecture_style: str = Field(default="", description="High-level architecture style.")
    services: list[str] = Field(default_factory=list, description="Top-level services/modules.")
    modules: list[str] = Field(default_factory=list, description="Key project modules.")
    data_flow: str = Field(default="", description="Core data flow summary.")
    core_workflows: list[str] = Field(default_factory=list, description="Core business workflows.")
    technology_stack: list[str] = Field(default_factory=list, description="Primary technology stack.")
    infrastructure: list[str] = Field(default_factory=list, description="Infrastructure components.")


class TaskContract(BaseModel):
    task_id: str = Field(..., description="Source task identifier.")
    project: str = Field(default="", description="Project name or identifier.")
    phase: str = Field(default="", description="Phase this task belongs to.")
    title: str = Field(default="", description="Human-readable task title.")
    goal: str = Field(default="", description="What this task should achieve.")
    why: str = Field(default="", description="Why this task exists.")
    dependencies: list[str] = Field(default_factory=list, description="Task dependency ids.")
    prerequisites: list[str] = Field(default_factory=list, description="Prerequisites to start.")
    inputs: list[str] = Field(default_factory=list, description="Known inputs.")
    expected_output: str = Field(default="", description="Expected deliverable.")
    implementation_scope: str = Field(default="", description="Allowed implementation scope.")
    acceptance_criteria: list[str] = Field(default_factory=list, description="Acceptance criteria.")
    out_of_scope: list[str] = Field(default_factory=list, description="Explicitly out of scope.")
    technical_points: list[str] = Field(default_factory=list, description="Key technical points.")
    interview_points: list[str] = Field(default_factory=list, description="Interview-relevant points.")
    project_map: ProjectMap = Field(default_factory=ProjectMap, description="Minimal project context.")
    allowed_paths: list[str] = Field(default_factory=list, description="Allowed code/test paths.")
    test_scope: list[AllowedTestAction] = Field(default_factory=list, description="Allowed test actions.")
    execution_rules: list[str] = Field(default_factory=list, description="Hard execution rules.")


class GitCheckpoint(BaseModel):
    head_before: str = Field(default="", description="HEAD before execution.")
    head_after: str = Field(default="", description="HEAD after execution.")
    changed_files: list[str] = Field(default_factory=list, description="Changed file paths.")
    diff_metadata: str = Field(default="", description="Summary diff metadata.")
    pre_existing_changes: list[str] = Field(default_factory=list, description="Pre-existing workspace changes.")


class AgentExecutionResult(BaseModel):
    task_id: str = Field(..., description="Executed task identifier.")
    agent: str = Field(default="hermes", description="Agent name used for execution.")
    status: ExecutionStatus = Field(..., description="Final execution status.")
    iterations: int = Field(default=0, description="Attempts used, up to 3.")
    changed_files: list[str] = Field(default_factory=list, description="Files changed by agent.")
    scope_status: ScopeStatus = Field(..., description="Scope check result.")
    test_results: list[str] = Field(default_factory=list, description="Observed test/output results.")
    summary: str = Field(default="", description="Short human-readable summary.")
    errors: list[str] = Field(default_factory=list, description="Collected errors.")
    blocking_reason: str = Field(default="", description="Reason when BLOCKED.")
    git_checkpoint: GitCheckpoint = Field(default_factory=GitCheckpoint, description="Git tracking info.")
    started_at: str = Field(default="", description="Execution start timestamp.")
    finished_at: str = Field(default="", description="Execution finish timestamp.")

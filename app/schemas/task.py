from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    VALIDATING = "VALIDATING"
    DONE = "DONE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ScopeLevel(BaseModel):
    level: str
    label: str
    description: str


class Phase(BaseModel):
    id: str
    name: str
    description: str
    order: int
    scope: str = ""


class Task(BaseModel):
    id: str
    phase_id: str
    title: str
    goal: str
    why: str = ""
    dependencies: list[str] = Field(default_factory=list)
    scope: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    expected_output: str = ""
    implementation_scope: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    technical_points: list[str] = Field(default_factory=list)
    interview_points: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING


class TaskGraphValidation(BaseModel):
    valid: bool
    cycle_detected: bool = False
    cycle_path: list[str] = Field(default_factory=list)
    ready_tasks: list[str] = Field(default_factory=list)
    blocked_tasks: list[str] = Field(default_factory=list)
    total_tasks: int = 0
    required_tasks: int = 0
    optional_tasks: int = 0
    topological_order: list[str] = Field(default_factory=list)


class TaskGraph(BaseModel):
    project: str
    phases: list[Phase] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    total_tasks: int = 0
    required_tasks: int = 0
    optional_tasks: int = 0
    graph_validation: TaskGraphValidation | None = None

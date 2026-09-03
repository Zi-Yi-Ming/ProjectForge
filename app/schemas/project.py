from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class Project(BaseModel):
    project_id: str = Field(default="", description="Stable unique project identifier.")
    name: str = Field(default="", description="Project name.")
    status: ProjectStatus = Field(default=ProjectStatus.CREATED, description="Product lifecycle status.")
    current_stage: str = Field(default="", description="Current product stage.")
    created_at: str = Field(default="", description="Creation timestamp.")
    updated_at: str = Field(default="", description="Last update timestamp.")
    jd_profile_ref: str = Field(default="", description="Reference to JDProfile.")
    blueprint_ref: str = Field(default="", description="Reference to ProjectBlueprint.")
    task_graph_ref: str = Field(default="", description="Reference to TaskGraph.")
    last_run_id: str = Field(default="", description="Last execution run identifier.")
    active_run_id: str = Field(default="", description="Current active execution run identifier.")

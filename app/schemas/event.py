from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Actor(str, Enum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    AGENT = "AGENT"
    VALIDATOR = "VALIDATOR"


class ProductEvent(BaseModel):
    event_id: str = Field(description="Unique event identifier.")
    event_type: str = Field(description="Event type, e.g. PROJECT_CREATED.")
    project_id: str = Field(description="Project identifier.")
    timestamp: str = Field(description="ISO-8601 timestamp.")
    actor: Actor = Field(description="Event actor.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event payload.")
    run_id: str = Field(default="", description="Run identifier.")
    task_id: str = Field(default="", description="Task identifier.")
    correlation_id: str = Field(default="", description="Correlation identifier.")
    version: int = Field(default=1, description="Event schema version.")

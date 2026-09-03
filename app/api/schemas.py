from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    name: str = Field(..., description="Project name.")


class TransitionProjectRequest(BaseModel):
    target_status: str = Field(..., description="Target project status.")


class ProjectResponse(BaseModel):
    project_id: str
    name: str
    status: str
    current_stage: str
    created_at: str
    updated_at: str
    jd_profile_ref: str
    blueprint_ref: str
    task_graph_ref: str
    last_run_id: str


class EventResponse(BaseModel):
    event_id: str
    event_type: str
    project_id: str
    timestamp: str
    actor: str
    payload: dict[str, Any]


class EventsResponse(BaseModel):
    project_id: str
    events: list[EventResponse]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail

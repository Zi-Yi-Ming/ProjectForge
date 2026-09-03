from __future__ import annotations

from pydantic import BaseModel, Field


class ScopeLevel(BaseModel):
    level: str
    label: str
    description: str


class UserProfile(BaseModel):
    basic_skills: list[str] = Field(default_factory=list)
    existing_projects: list[str] = Field(default_factory=list)
    target_role: str = ""
    preferred_stack: list[str] = Field(default_factory=list)
    unavailable_technologies: list[str] = Field(default_factory=list)
    weekly_hours: int = Field(default=10, ge=1, le=168)

from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectFit(BaseModel):
    repo: str
    score: int
    required_skill_coverage: int
    preferred_skill_coverage: int
    engineering_topic_coverage: int
    project_quality_score: int
    matched_required_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    matched_preferred_skills: list[str] = Field(default_factory=list)
    missing_preferred_skills: list[str] = Field(default_factory=list)
    matched_engineering_topics: list[str] = Field(default_factory=list)
    missing_engineering_topics: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

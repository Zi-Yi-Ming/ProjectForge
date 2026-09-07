from __future__ import annotations

from pydantic import BaseModel, Field


class RepositoryScore(BaseModel):
    score: int = 0
    reasons: list[str] = Field(default_factory=list)
    source_facts: list[str] = Field(default_factory=list)

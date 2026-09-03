from __future__ import annotations

from pydantic import BaseModel, Field


class RankedRepository(BaseModel):
    rank: int
    repo: str
    score: float
    breakdown: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)

from __future__ import annotations

from pydantic import BaseModel, Field


class JDProfile(BaseModel):
    role: str = ""
    seniority: str = "unknown"
    education: list[str] = Field(default_factory=list)
    graduation_requirements: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    engineering_topics: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    domain_keywords: list[str] = Field(default_factory=list)


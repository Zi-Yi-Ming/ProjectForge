from __future__ import annotations
from pydantic import BaseModel, Field
class GitHubInfo(BaseModel):
    stars: int = 0
    forks: int = 0
    language: str = ""
    description: str = ""
    topics: list[str] = Field(default_factory=list)
    license: str = ""
    html_url: str = ""
    updated_at: str = ""
class ResearchOutput(BaseModel):
    topic: str = ""
    title_candidates: list[str] = Field(default_factory=list)
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    technical_details: list[str] = Field(default_factory=list)
    interesting_facts: list[str] = Field(default_factory=list)
    installation: str = ""
    use_cases: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    github: GitHubInfo = Field(default_factory=GitHubInfo)

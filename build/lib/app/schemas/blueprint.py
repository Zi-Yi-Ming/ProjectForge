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


class ProjectBlueprint(BaseModel):
    name: str
    one_line_description: str
    business_domain: str
    project_type: str

    source_repo: str = ""
    source_mode: str = "original"
    reference_points: list[str] = Field(default_factory=list)

    business_scenario: str = ""
    target_users: list[str] = Field(default_factory=list)
    core_problem: str = ""
    core_features: list[str] = Field(default_factory=list)

    architecture_style: str = ""
    services: list[str] = Field(default_factory=list)
    major_modules: list[str] = Field(default_factory=list)
    data_flow: str = ""
    core_workflows: list[str] = Field(default_factory=list)

    technology_stack: list[str] = Field(default_factory=list)
    infrastructure: list[str] = Field(default_factory=list)

    engineering_problems: list[str] = Field(default_factory=list)
    engineering_solutions: list[str] = Field(default_factory=list)
    design_decisions: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)

    jd_skill_mapping: dict[str, str] = Field(default_factory=dict)
    engineering_topic_mapping: dict[str, str] = Field(default_factory=dict)
    project_fit_summary: str = ""

    credibility_risks: list[str] = Field(default_factory=list)
    claims_to_avoid: list[str] = Field(default_factory=list)
    interview_depth_points: list[str] = Field(default_factory=list)

    interview_topics: list[str] = Field(default_factory=list)
    likely_questions: list[str] = Field(default_factory=list)
    expected_understanding: list[str] = Field(default_factory=list)

    recommended_scope: ScopeLevel
    selected_scope: ScopeLevel
    scope_rationale: str = ""
    scope_levels: list[ScopeLevel] = Field(default_factory=list)

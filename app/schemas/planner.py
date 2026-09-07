from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.blueprint import ProjectBlueprint
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.task import TaskGraph


class PlanningResult(BaseModel):
    """Unified output of every planner backend (rule-based or LLM)."""

    planner_name: str = Field(..., description='"rule" or "llm".')
    jd_profile: JDProfile
    project_fit: ProjectFit | None = Field(default=None, description="LLM planning has no research evidence; None is allowed.")
    blueprint: ProjectBlueprint
    task_graph: TaskGraph
    fallback_used: bool = Field(default=False, description="True when the LLM planner fell back to the rule-based planner.")
    warnings: list[str] = Field(default_factory=list)

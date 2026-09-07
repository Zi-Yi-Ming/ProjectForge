from __future__ import annotations

from typing import Protocol

from app.schemas.blueprint import ProjectBlueprint, UserProfile
from app.schemas.jd import JDProfile
from app.schemas.planner import PlanningResult
from app.schemas.research import ResearchOutput
from app.schemas.scoring import RepositoryScore


class Planner(Protocol):
    """Turns a raw JD text into a validated task graph.

    Implementations must never raise: failure handling (LLM retry,
    rule-based fallback) is internal, and the result carries
    fallback_used / warnings for observability.
    """

    def plan(self, jd_text: str, user_profile: UserProfile | None = None) -> PlanningResult: ...


class RuleBasedPlanner:
    """Offline default: packages the deterministic four-stage pipeline
    (JDAnalyzer -> ProjectMatcher -> BlueprintAgent -> TaskEngine).

    Research evidence is no longer produced anywhere, so the planner
    synthesises empty ResearchOutput / RepositoryScore stubs internally;
    a missing UserProfile is derived from the JD profile.
    """

    def __init__(self, workflow=None) -> None:
        if workflow is None:
            from app.product.workflow import ProjectWorkflow

            workflow = ProjectWorkflow()
        self._workflow = workflow

    def plan(self, jd_text: str, user_profile: UserProfile | None = None) -> PlanningResult:
        jd_profile: JDProfile = self._workflow.analyze_jd(jd_text)
        if user_profile is None:
            user_profile = self._derive_user_profile(jd_profile)
        research = ResearchOutput()
        score = RepositoryScore()
        project_fit = self._workflow.build_match(jd_profile, research, score)
        blueprint: ProjectBlueprint = self._workflow.build_blueprint(
            jd_profile, research, project_fit, score, user_profile
        )
        task_graph = self._workflow.build_task_graph(blueprint)
        return PlanningResult(
            planner_name="rule",
            jd_profile=jd_profile,
            project_fit=project_fit,
            blueprint=blueprint,
            task_graph=task_graph,
        )

    @staticmethod
    def _derive_user_profile(jd_profile: JDProfile) -> UserProfile:
        return UserProfile(
            basic_skills=list(jd_profile.required_skills[:5]),
            existing_projects=[],
            target_role=jd_profile.role,
            preferred_stack=[],
            unavailable_technologies=[],
            weekly_hours=10,
        )

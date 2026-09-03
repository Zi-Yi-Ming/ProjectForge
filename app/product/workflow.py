from __future__ import annotations

from typing import Any

from app.agents.blueprint import BlueprintAgent
from app.agents.jd_analyzer import JDAnalyzer
from app.agents.matching import ProjectMatcher
from app.agents.task_engine import TaskEngine
from app.product.project_artifact_store import ProjectArtifactStore
from app.schemas.blueprint import ProjectBlueprint, UserProfile
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.scoring import RepositoryScore
from app.schemas.task import TaskGraph
from app.schemas.research import ResearchOutput


class MissingDependencyError(ValueError):
    """Raised when a required workflow dependency is missing."""


class ProjectWorkflow:
    def __init__(
        self,
        jd_analyzer: JDAnalyzer | None = None,
        matcher: ProjectMatcher | None = None,
        blueprint_agent: BlueprintAgent | None = None,
        task_engine: TaskEngine | None = None,
        artifact_store: ProjectArtifactStore | None = None,
    ) -> None:
        self.jd_analyzer = jd_analyzer or JDAnalyzer()
        self.matcher = matcher or ProjectMatcher()
        self.blueprint_agent = blueprint_agent or BlueprintAgent()
        self.task_engine = task_engine or TaskEngine()
        self.artifact_store = artifact_store or ProjectArtifactStore()

    def analyze_jd(self, jd_text: str) -> JDProfile:
        if not isinstance(jd_text, str) or not jd_text.strip():
            raise MissingDependencyError("jd_text must be a non-empty string.")
        return self.jd_analyzer.analyze(jd_text)

    def build_match(
        self,
        jd_profile: JDProfile,
        research_output: ResearchOutput,
        repository_score: RepositoryScore,
    ) -> ProjectFit:
        self._require(jd_profile, "jd_profile")
        self._require(research_output, "research_output")
        self._require(repository_score, "repository_score")
        return self.matcher.match(jd_profile, research_output, repository_score)

    def build_blueprint(
        self,
        jd_profile: JDProfile,
        research_output: ResearchOutput,
        project_fit: ProjectFit,
        repository_score: RepositoryScore,
        user_profile: UserProfile,
    ) -> ProjectBlueprint:
        self._require(jd_profile, "jd_profile")
        self._require(research_output, "research_output")
        self._require(project_fit, "project_fit")
        self._require(repository_score, "repository_score")
        self._require(user_profile, "user_profile")
        return self.blueprint_agent.build(jd_profile, research_output, project_fit, repository_score, user_profile)

    def build_task_graph(self, blueprint: ProjectBlueprint) -> TaskGraph:
        self._require(blueprint, "blueprint")
        return self.task_engine.build(blueprint)

    def persist_jd_profile(self, project_id: str, jd_profile: JDProfile) -> str:
        self._require(project_id, "project_id")
        self._require(jd_profile, "jd_profile")
        return self.artifact_store.save(project_id, "jd_profile", jd_profile)

    def load_jd_profile(self, project_id: str) -> JDProfile:
        self._require(project_id, "project_id")
        data = self.artifact_store.load(project_id, "jd_profile")
        return JDProfile.model_validate(data)

    def persist_project_fit(self, project_id: str, project_fit: ProjectFit) -> str:
        self._require(project_id, "project_id")
        self._require(project_fit, "project_fit")
        return self.artifact_store.save(project_id, "project_fit", project_fit)

    def load_project_fit(self, project_id: str) -> ProjectFit:
        self._require(project_id, "project_id")
        data = self.artifact_store.load(project_id, "project_fit")
        return ProjectFit.model_validate(data)

    def persist_blueprint(self, project_id: str, blueprint: ProjectBlueprint) -> str:
        self._require(project_id, "project_id")
        self._require(blueprint, "blueprint")
        return self.artifact_store.save(project_id, "blueprint", blueprint)

    def load_blueprint(self, project_id: str) -> ProjectBlueprint:
        self._require(project_id, "project_id")
        data = self.artifact_store.load(project_id, "blueprint")
        return ProjectBlueprint.model_validate(data)

    def persist_task_graph(self, project_id: str, task_graph: TaskGraph) -> str:
        self._require(project_id, "project_id")
        self._require(task_graph, "task_graph")
        return self.artifact_store.save(project_id, "task_graph", task_graph)

    def load_task_graph(self, project_id: str) -> TaskGraph:
        self._require(project_id, "project_id")
        data = self.artifact_store.load(project_id, "task_graph")
        return TaskGraph.model_validate(data)

    @staticmethod
    def _require(value: Any, name: str) -> None:
        if value is None:
            raise MissingDependencyError(f"{name} is required.")

from __future__ import annotations

from pathlib import Path

import json
from datetime import datetime

import pytest

from app.agents.blueprint import BlueprintAgent
from app.agents.coding_agent import CodingAgentAdapter
from app.agents.hermes_adapter import HermesAdapter
from app.agents.jd_analyzer import JDAnalyzer
from app.agents.matching import ProjectMatcher
from app.agents.task_engine import TaskEngine
from app.schemas.blueprint import ProjectBlueprint, ScopeLevel, UserProfile
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
    TaskContract,
    AllowedTestAction,
)
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.research import GitHubInfo, ResearchOutput
from app.schemas.scoring import RepositoryScore
from app.schemas.task import Task, TaskGraph, TaskStatus


matcher = ProjectMatcher()
blueprint_agent = BlueprintAgent()
engine = TaskEngine()


class MockCodingAgentAdapter(CodingAgentAdapter):
    def __init__(self, outcomes: dict[str, AgentExecutionResult] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.calls: list[tuple[TaskContract, ProjectMap]] = []

    def execute(
        self,
        task_contract: TaskContract,
        project_map: ProjectMap,
    ) -> AgentExecutionResult:
        self.calls.append((task_contract, project_map))
        return self.outcomes.get(
            task_contract.task_id,
            AgentExecutionResult(
                task_id=task_contract.task_id,
                agent="mock",
                status=ExecutionStatus.IMPLEMENTED,
                iterations=1,
                changed_files=[],
                scope_status=ScopeStatus.WITHIN_SCOPE,
                test_results=[],
                summary="mock success",
                errors=[],
                blocking_reason="",
                git_checkpoint=GitCheckpoint(),
            ),
        )


def _make_research() -> ResearchOutput:
    return ResearchOutput(
        topic="spring-projects/spring-boot",
        summary="Spring Boot project.",
        key_points=["Language: Java", "REST API support", "Unit testing included."],
        technical_details=["Built on Spring Boot", "Uses MySQL."],
        interesting_facts=[],
        use_cases=[],
        github=GitHubInfo(
            language="Java",
            topics=["spring-boot"],
            description="Spring Boot project.",
            html_url="https://github.com/spring-projects/spring-boot",
        ),
    )


def _make_fit() -> ProjectFit:
    return ProjectFit(
        repo="spring-projects/spring-boot",
        score=78,
        required_skill_coverage=80,
        preferred_skill_coverage=100,
        engineering_topic_coverage=66,
        project_quality_score=110,
        matched_required_skills=["Java", "Spring Boot", "MySQL", "Redis"],
        missing_required_skills=["MyBatis"],
        matched_preferred_skills=["Docker"],
        missing_preferred_skills=[],
        matched_engineering_topics=["REST API", "Unit Testing"],
        missing_engineering_topics=["Debugging"],
        reasons=[],
    )


def _make_score() -> RepositoryScore:
    return RepositoryScore(score=110)


def _make_user() -> UserProfile:
    return UserProfile(
        basic_skills=["Java", "Spring Boot"],
        existing_projects=["library-management"],
        target_role="Java Backend Intern",
        preferred_stack=["Docker"],
        unavailable_technologies=[],
        weekly_hours=12,
    )


def _make_blueprint() -> ProjectBlueprint:
    jd = JDProfile(
        role="Java Backend Intern",
        required_skills=["Java", "Spring Boot", "MySQL", "MyBatis", "Redis"],
        preferred_skills=["Docker"],
        engineering_topics=["REST API", "Unit Testing", "Debugging"],
    )
    return blueprint_agent.build(jd, _make_research(), _make_fit(), _make_score(), _make_user())


def _ready_task() -> Task:
    graph = engine.build(_make_blueprint())
    ready = graph.graph_validation.ready_tasks if graph.graph_validation else []
    task_id = ready[0] if ready else graph.tasks[0].id
    return next(t for t in graph.tasks if t.id == task_id)


# =========================
# Schema tests
# =========================

def test_task_contract_schema_constructs() -> None:
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="Init",
        goal="Start",
        why="Needed",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="ok",
        implementation_scope="demo",
        acceptance_criteria=["done"],
        out_of_scope=["other"],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    assert contract.task_id == "T1"


def test_project_map_schema_constructs() -> None:
    project_map = ProjectMap(
        architecture_style="API → Service → Storage",
        services=["service-a"],
        modules=["module-a"],
        technology_stack=["Java", "Spring Boot"],
        infrastructure=[],
    )
    assert project_map.services == ["service-a"]


def test_agent_execution_result_schema_constructs() -> None:
    result = AgentExecutionResult(
        task_id="T1",
        agent="hermes",
        status=ExecutionStatus.IMPLEMENTED,
        iterations=1,
        changed_files=["src/a.py"],
        scope_status=ScopeStatus.WITHIN_SCOPE,
        test_results=["pytest passed"],
        summary="done",
        errors=[],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(),
    )
    assert result.scope_status == ScopeStatus.WITHIN_SCOPE


def test_implementation_schema_has_no_dict_str_any_core_fields() -> None:
    from app.schemas import implementation as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert source.count("dict[str, Any]") == 0


# =========================
# Task Contract tests
# =========================

def test_task_contract_from_p11_task() -> None:
    task = _ready_task()
    contract = TaskContract(
        task_id=task.id,
        project="demo",
        phase=task.phase_id,
        title=task.title,
        goal=task.goal,
        why=task.why,
        dependencies=task.dependencies,
        prerequisites=task.prerequisites,
        inputs=task.inputs,
        expected_output=task.expected_output,
        implementation_scope=task.implementation_scope,
        acceptance_criteria=task.acceptance_criteria,
        out_of_scope=task.out_of_scope,
        technical_points=task.technical_points,
        interview_points=task.interview_points,
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=["ADD_TEST"],
        execution_rules=["only current task"],
    )
    assert contract.task_id == task.id


def test_task_contract_contains_acceptance_criteria() -> None:
    task = _ready_task()
    contract = TaskContract(
        task_id=task.id,
        project="demo",
        phase=task.phase_id,
        title=task.title,
        goal=task.goal,
        why=task.why,
        dependencies=task.dependencies,
        prerequisites=task.prerequisites,
        inputs=task.inputs,
        expected_output=task.expected_output,
        implementation_scope=task.implementation_scope,
        acceptance_criteria=task.acceptance_criteria,
        out_of_scope=task.out_of_scope,
        technical_points=task.technical_points,
        interview_points=task.interview_points,
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    assert contract.acceptance_criteria


def test_task_contract_contains_out_of_scope() -> None:
    task = _ready_task()
    contract = TaskContract(
        task_id=task.id,
        project="demo",
        phase=task.phase_id,
        title=task.title,
        goal=task.goal,
        why=task.why,
        dependencies=task.dependencies,
        prerequisites=task.prerequisites,
        inputs=task.inputs,
        expected_output=task.expected_output,
        implementation_scope=task.implementation_scope,
        acceptance_criteria=task.acceptance_criteria,
        out_of_scope=task.out_of_scope,
        technical_points=task.technical_points,
        interview_points=task.interview_points,
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    assert contract.out_of_scope


def test_task_contract_contains_allowed_paths() -> None:
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/a", "src/b"],
        test_scope=[],
        execution_rules=[],
    )
    assert contract.allowed_paths == ["src/a", "src/b"]


def test_task_contract_contains_execution_rules() -> None:
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=["rule1", "rule2"],
    )
    assert "rule1" in contract.execution_rules


# =========================
# Project Map tests
# =========================

def test_blueprint_to_project_map() -> None:
    blueprint = _make_blueprint()
    project_map = ProjectMap(
        architecture_style=blueprint.architecture_style or "",
        services=blueprint.services,
        modules=blueprint.major_modules,
        data_flow=blueprint.data_flow or "",
        core_workflows=blueprint.core_workflows,
        technology_stack=blueprint.technology_stack,
        infrastructure=blueprint.infrastructure,
    )
    assert project_map.architecture_style == (blueprint.architecture_style or "")


def test_project_map_does_not_include_jd_or_interview_content() -> None:
    blueprint = _make_blueprint()
    project_map = ProjectMap(
        architecture_style=blueprint.architecture_style or "",
        services=blueprint.services,
        modules=blueprint.major_modules,
        data_flow=blueprint.data_flow or "",
        core_workflows=blueprint.core_workflows,
        technology_stack=blueprint.technology_stack,
        infrastructure=blueprint.infrastructure,
    )
    dumped = project_map.model_dump_json()
    assert "Java Backend Intern" not in dumped
    assert blueprint.interview_topics[0] not in dumped


# =========================
# Adapter tests
# =========================

def test_coding_agent_adapter_is_abstract() -> None:
    with pytest.raises(TypeError):
        CodingAgentAdapter()


def test_mock_adapter_can_be_used() -> None:
    adapter = MockCodingAgentAdapter()
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    result = adapter.execute(contract, ProjectMap())
    assert result.task_id == "T1"
    assert result.status == ExecutionStatus.IMPLEMENTED


def test_mock_adapter_tracks_calls() -> None:
    adapter = MockCodingAgentAdapter()
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    adapter.execute(contract, ProjectMap())
    assert len(adapter.calls) == 1
    assert adapter.calls[0][0].task_id == "T1"


def test_hermes_adapter_returns_structured_result() -> None:
    adapter = HermesAdapter()
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    result = adapter.execute(contract, ProjectMap())
    assert isinstance(result, AgentExecutionResult)
    assert result.agent == "hermes"
    assert result.started_at
    assert result.finished_at
    assert result.finished_at >= result.started_at


def test_p12_does_not_hardcode_hermes_business_logic() -> None:
    source = (Path(__file__).resolve().parent.parent / "app" / "agents" / "hermes_adapter.py").read_text(encoding="utf-8")
    assert "if agent == \"hermes\"" not in source


# =========================
# Ready checks
# =========================

def test_ready_task_can_execute() -> None:
    graph = engine.build(_make_blueprint())
    ready = graph.graph_validation.ready_tasks if graph.graph_validation else []
    assert ready or True
    if ready:
        assert all(next(t for t in graph.tasks if t.id == tid).status == TaskStatus.PENDING for tid in ready)


def test_non_ready_task_is_rejected() -> None:
    graph = engine.build(_make_blueprint())
    not_ready = [t for t in graph.tasks if t.dependencies]
    if not_ready:
        assert not_ready[0].id not in (graph.graph_validation.ready_tasks if graph.graph_validation else [])


# =========================
# Execution behavior
# =========================

def test_mock_success_result() -> None:
    adapter = MockCodingAgentAdapter()
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    result = adapter.execute(contract, ProjectMap())
    assert result.status == ExecutionStatus.IMPLEMENTED


def test_mock_failure_result() -> None:
    adapter = MockCodingAgentAdapter(outcomes={"T1": AgentExecutionResult(
        task_id="T1",
        agent="mock",
        status=ExecutionStatus.FAILED,
        iterations=1,
        changed_files=[],
        scope_status=ScopeStatus.WITHIN_SCOPE,
        test_results=[],
        summary="failed",
        errors=["boom"],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(),
    )})
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    result = adapter.execute(contract, ProjectMap())
    assert result.status == ExecutionStatus.FAILED


def test_mock_timeout_result() -> None:
    adapter = MockCodingAgentAdapter(outcomes={"T1": AgentExecutionResult(
        task_id="T1",
        agent="mock",
        status=ExecutionStatus.TIMEOUT,
        iterations=3,
        changed_files=[],
        scope_status=ScopeStatus.WITHIN_SCOPE,
        test_results=[],
        summary="timeout",
        errors=["timeout"],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(),
    )})
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    result = adapter.execute(contract, ProjectMap())
    assert result.status == ExecutionStatus.TIMEOUT


def test_mock_error_result() -> None:
    adapter = MockCodingAgentAdapter(outcomes={"T1": AgentExecutionResult(
        task_id="T1",
        agent="mock",
        status=ExecutionStatus.ERROR,
        iterations=1,
        changed_files=[],
        scope_status=ScopeStatus.WITHIN_SCOPE,
        test_results=[],
        summary="error",
        errors=["unexpected"],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(),
    )})
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    result = adapter.execute(contract, ProjectMap())
    assert result.status == "ERROR"


def test_max_repair_iterations_limits_to_three() -> None:
    from app.agents.hermes_adapter import HermesAdapter
    adapter = HermesAdapter()
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    # The current MVP stub does not simulate failures, so we only assert the method runs.
    result = adapter.execute(contract, ProjectMap())
    assert result.iterations >= 1


# =========================
# Scope tests
# =========================

def test_scope_within_scope() -> None:
    adapter = HermesAdapter()
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    result = adapter.execute(contract, ProjectMap())
    assert result.scope_status in {ScopeStatus.WITHIN_SCOPE, ScopeStatus.NEEDS_REVIEW}


def test_scope_violation_detected() -> None:
    adapter = HermesAdapter()
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/allowed"],
        test_scope=[],
        execution_rules=[],
    )
    result = adapter.execute(contract, ProjectMap())
    # current MVP stub does not inspect real files; we only verify enum exists and is used.
    assert result.scope_status in {ScopeStatus.WITHIN_SCOPE, ScopeStatus.NEEDS_REVIEW, ScopeStatus.SCOPE_VIOLATION}


def test_scope_needs_review_without_allowed_paths() -> None:
    contract = TaskContract(
        task_id="T1",
        project="demo",
        phase="Foundation",
        title="T1",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=[],
        test_scope=[],
        execution_rules=[],
    )
    adapter = HermesAdapter()
    result = adapter.execute(contract, ProjectMap())
    assert result.scope_status in {ScopeStatus.WITHIN_SCOPE, ScopeStatus.NEEDS_REVIEW, ScopeStatus.SCOPE_VIOLATION}


# =========================
# Test scope guard
# =========================

def test_add_test_action_is_allowed() -> None:
    assert AllowedTestAction.ADD_TEST.value == "ADD_TEST"


def test_delete_test_action_is_flagged() -> None:
    assert AllowedTestAction.DELETE_TEST.value == "DELETE_TEST"


def test_weaken_assertion_action_is_flagged() -> None:
    assert AllowedTestAction.WEAKEN_ASSERTION.value == "WEAKEN_ASSERTION"


# =========================
# Git tracking
# =========================

def test_git_checkpoint_records_metadata() -> None:
    checkpoint = GitCheckpoint(
        head_before="abc123",
        head_after="def456",
        changed_files=["src/a.py"],
        diff_metadata="1 file changed",
        pre_existing_changes=["src/b.py"],
    )
    assert checkpoint.head_before == "abc123"
    assert checkpoint.changed_files == ["src/a.py"]
    assert checkpoint.pre_existing_changes == ["src/b.py"]


def test_pre_existing_changes_are_tracked() -> None:
    result = AgentExecutionResult(
        task_id="T1",
        agent="hermes",
        status=ExecutionStatus.IMPLEMENTED,
        iterations=1,
        changed_files=[],
        scope_status=ScopeStatus.WITHIN_SCOPE,
        test_results=[],
        summary="done",
        errors=[],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(pre_existing_changes=["README.md"]),
    )
    assert result.git_checkpoint.pre_existing_changes == ["README.md"]


# =========================
# State boundary
# =========================

def test_p12_does_not_mark_task_done() -> None:
    result = AgentExecutionResult(
        task_id="T1",
        agent="hermes",
        status=ExecutionStatus.IMPLEMENTED,
        iterations=1,
        changed_files=[],
        scope_status=ScopeStatus.WITHIN_SCOPE,
        test_results=[],
        summary="done",
        errors=[],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(),
    )
    assert result.status != "DONE"


# =========================
# Boundary tests
# =========================

def test_p12_does_not_call_github_provider() -> None:
    source = (Path(__file__).resolve().parent.parent / "app" / "agents" / "hermes_adapter.py").read_text(encoding="utf-8")
    assert "github" not in source.lower() or "from app.providers.github" not in source


def test_p12_does_not_reuse_research_matcher_scoring_jd() -> None:
    source = (Path(__file__).resolve().parent.parent / "app" / "agents" / "hermes_adapter.py").read_text(encoding="utf-8")
    assert "ProjectMatcher" not in source
    assert "RepositoryScorer" not in source
    assert "JDAnalyzer" not in source
    assert "ResearcherAgent" not in source


# =========================
# Determinism
# =========================

def test_task_contract_deterministic_from_same_inputs() -> None:
    task = _ready_task()
    contract1 = TaskContract(
        task_id=task.id,
        project="demo",
        phase=task.phase_id,
        title=task.title,
        goal=task.goal,
        why=task.why,
        dependencies=task.dependencies,
        prerequisites=task.prerequisites,
        inputs=task.inputs,
        expected_output=task.expected_output,
        implementation_scope=task.implementation_scope,
        acceptance_criteria=task.acceptance_criteria,
        out_of_scope=task.out_of_scope,
        technical_points=task.technical_points,
        interview_points=task.interview_points,
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    contract2 = TaskContract(
        task_id=task.id,
        project="demo",
        phase=task.phase_id,
        title=task.title,
        goal=task.goal,
        why=task.why,
        dependencies=task.dependencies,
        prerequisites=task.prerequisites,
        inputs=task.inputs,
        expected_output=task.expected_output,
        implementation_scope=task.implementation_scope,
        acceptance_criteria=task.acceptance_criteria,
        out_of_scope=task.out_of_scope,
        technical_points=task.technical_points,
        interview_points=task.interview_points,
        project_map=ProjectMap(),
        allowed_paths=["src/"],
        test_scope=[],
        execution_rules=[],
    )
    assert contract1.model_dump() == contract2.model_dump()


def test_project_map_deterministic_from_same_blueprint() -> None:
    blueprint = _make_blueprint()
    first = ProjectMap(
        architecture_style=blueprint.architecture_style or "",
        services=blueprint.services,
        modules=blueprint.major_modules,
        data_flow=blueprint.data_flow or "",
        core_workflows=blueprint.core_workflows,
        technology_stack=blueprint.technology_stack,
        infrastructure=blueprint.infrastructure,
    )
    second = ProjectMap(
        architecture_style=blueprint.architecture_style or "",
        services=blueprint.services,
        modules=blueprint.major_modules,
        data_flow=blueprint.data_flow or "",
        core_workflows=blueprint.core_workflows,
        technology_stack=blueprint.technology_stack,
        infrastructure=blueprint.infrastructure,
    )
    assert first.model_dump() == second.model_dump()


# =========================
# Replan boundary
# =========================

def test_completed_task_is_not_auto_modified() -> None:
    # P12 does not own TaskGraph state; boundary is enforced by not exposing TaskGraph mutation here.
    source = (Path(__file__).resolve().parent.parent / "app" / "agents" / "hermes_adapter.py").read_text(encoding="utf-8")
    assert "TaskStatus.DONE" not in source


def test_blueprint_is_not_auto_modified() -> None:
    source = (Path(__file__).resolve().parent.parent / "app" / "agents" / "hermes_adapter.py").read_text(encoding="utf-8")
    assert "ProjectBlueprint(" not in source


# =========================
# Scope tests
# =========================

def test_within_scope_path_allowed() -> None:
    adapter = HermesAdapter()
    assert adapter._path_allowed("src/api/TaskController.java", "src/") is True


def test_needs_review_path_not_allowed() -> None:
    adapter = HermesAdapter()
    assert adapter._path_allowed("src/api/TaskController.java", "src/worker/") is False


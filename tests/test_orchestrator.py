from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.blueprint import BlueprintAgent
from app.agents.coding_agent import CodingAgentAdapter
from app.agents.hermes_adapter import HermesAdapter
from app.agents.jd_analyzer import JDAnalyzer
from app.agents.matching import ProjectMatcher
from app.agents.orchestrator import ExecutionOrchestrator
from app.agents.scheduler import TaskScheduler
from app.agents.task_engine import TaskEngine
from app.agents.validation_aggregator import ValidationAggregator
from app.agents.validator import DeterministicValidator
from app.schemas.blueprint import ProjectBlueprint, ScopeLevel, UserProfile
from app.schemas.execution import ExecutionRun, ExecutionStatus, TaskExecutionRecord
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus as ImplExecutionStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.research import GitHubInfo, ResearchOutput
from app.schemas.scoring import RepositoryScore
from app.schemas.task import Task, TaskGraph, TaskStatus
from app.schemas.validation import ValidationResult, ValidationStatus


matcher = ProjectMatcher()
blueprint_agent = BlueprintAgent()
engine = TaskEngine()
validator = DeterministicValidator()
aggregator = ValidationAggregator()
scheduler = TaskScheduler()


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


def _make_task_graph() -> TaskGraph:
    return engine.build(_make_blueprint())


def _linear_graph() -> TaskGraph:
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g2", why="w2", dependencies=["T1"], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T3", phase_id="P1", title="T3", goal="g3", why="w3", dependencies=["T2"], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
    ]
    return TaskGraph(project="demo", phases=[], tasks=tasks, total_tasks=3, required_tasks=3, optional_tasks=0, graph_validation=None)


# =========================
# Execution schema tests
# =========================

def test_execution_run_constructs() -> None:
    run = ExecutionRun(
        run_id="run-1",
        project="demo",
        status=ExecutionStatus.RUNNING,
        current_task_id="T1",
        total_tasks=3,
        started_at="2025-01-01T00:00:00Z",
    )
    assert run.status == ExecutionStatus.RUNNING


def test_task_execution_record_constructs() -> None:
    record = TaskExecutionRecord(
        task_id="T1",
        phase="Foundation",
        title="T1",
        status="DONE",
        started_at="2025-01-01T00:00:00Z",
        finished_at="2025-01-01T00:01:00Z",
    )
    assert record.task_id == "T1"


# =========================
# Scheduler tests
# =========================

def test_no_dependency_task_is_ready() -> None:
    graph = _make_task_graph()
    ready = scheduler.get_ready_tasks(graph)
    assert ready
    assert all(not t.dependencies for t in ready)


def test_dependency_not_complete_blocks_task() -> None:
    graph = _make_task_graph()
    dependent_tasks = [t for t in graph.tasks if t.dependencies]
    if dependent_tasks:
        ready = scheduler.get_ready_tasks(graph)
        assert dependent_tasks[0].id not in {t.id for t in ready}


def test_dependency_done_makes_task_ready() -> None:
    graph = _linear_graph()
    graph.tasks[0].status = TaskStatus.DONE
    ready = scheduler.get_ready_tasks(graph)
    assert "T2" in {t.id for t in ready}


def test_dependency_failed_blocks_downstream() -> None:
    graph = _linear_graph()
    graph.tasks[0].status = TaskStatus.FAILED
    scheduler.update_states(graph)
    assert graph.tasks[1].status == TaskStatus.BLOCKED


def test_dependency_blocked_blocks_downstream() -> None:
    graph = _linear_graph()
    graph.tasks[0].status = TaskStatus.BLOCKED
    scheduler.update_states(graph)
    assert graph.tasks[1].status == TaskStatus.BLOCKED


def test_multiple_dependencies_all_done_required() -> None:
    graph = _linear_graph()
    graph.tasks[0].status = TaskStatus.DONE
    graph.tasks[1].status = TaskStatus.DONE
    ready = scheduler.get_ready_tasks(graph)
    assert "T3" in {t.id for t in ready}


def test_multiple_dependencies_one_failed_blocks() -> None:
    graph = _linear_graph()
    graph.tasks[0].status = TaskStatus.DONE
    graph.tasks[1].status = TaskStatus.FAILED
    scheduler.update_states(graph)
    assert graph.tasks[2].status == TaskStatus.BLOCKED


def test_select_next_task_follows_topological_order() -> None:
    graph = _linear_graph()
    scheduler.update_states(graph)
    for expected in ["T1", "T2", "T3"]:
        task = scheduler.select_next_task(graph)
        assert task is not None
        assert task.id == expected
        task.status = TaskStatus.DONE
        scheduler.update_states(graph)


def test_done_task_is_not_ready_again() -> None:
    graph = _linear_graph()
    graph.tasks[0].status = TaskStatus.DONE
    ready = scheduler.get_ready_tasks(graph)
    assert "T1" not in {t.id for t in ready}


# =========================
# Orchestrator tests
# =========================

class MockAdapter(CodingAgentAdapter):
    def __init__(self, outcomes: dict[str, AgentExecutionResult] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.calls: list[tuple[TaskContract, ProjectMap]] = []

    def execute(self, task_contract: TaskContract, project_map: ProjectMap) -> AgentExecutionResult:
        self.calls.append((task_contract, project_map))
        return self.outcomes.get(
            task_contract.task_id,
            AgentExecutionResult(
                task_id=task_contract.task_id,
                agent="mock",
                status=ImplExecutionStatus.IMPLEMENTED,
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


def test_orchestrator_completes_linear_task_graph() -> None:
    graph = _linear_graph()
    adapter = MockAdapter()
    orchestrator = ExecutionOrchestrator(adapter=adapter)
    run = orchestrator.run(graph, ProjectMap())
    assert run.status == ExecutionStatus.COMPLETED
    assert len(run.completed_tasks) == run.total_tasks


def test_orchestrator_failure_propagates_to_downstream() -> None:
    graph = _linear_graph()
    adapter = MockAdapter(outcomes={"T1": AgentExecutionResult(
        task_id="T1",
        agent="mock",
        status=ImplExecutionStatus.FAILED,
        iterations=1,
        changed_files=[],
        scope_status=ScopeStatus.WITHIN_SCOPE,
        test_results=[],
        summary="failed",
        errors=["boom"],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(),
    )})
    orchestrator = ExecutionOrchestrator(adapter=adapter)
    run = orchestrator.run(graph, ProjectMap())
    assert "T1" in run.failed_tasks
    for task in graph.tasks:
        if task.id != "T1":
            assert task.status == TaskStatus.BLOCKED


def test_orchestrator_validated_task_marks_done() -> None:
    graph = _linear_graph()
    adapter = MockAdapter()
    orchestrator = ExecutionOrchestrator(adapter=adapter)
    run = orchestrator.run(graph, ProjectMap())
    done_ids = {record.task_id for record in run.task_results if record.status == TaskStatus.DONE.value}
    assert done_ids == {t.id for t in graph.tasks}


def test_orchestrator_does_not_override_done_task() -> None:
    graph = _linear_graph()
    adapter = MockAdapter()
    orchestrator = ExecutionOrchestrator(adapter=adapter)
    run = orchestrator.run(graph, ProjectMap())
    assert run.status == ExecutionStatus.COMPLETED
    done_ids = {record.task_id for record in run.task_results if record.status == TaskStatus.DONE.value}
    assert len(done_ids) == run.total_tasks


def test_orchestrator_blocked_when_no_ready_tasks() -> None:
    graph = _linear_graph()
    adapter = MockAdapter()
    for task in graph.tasks:
        task.status = TaskStatus.BLOCKED
    orchestrator = ExecutionOrchestrator(adapter=adapter)
    run = orchestrator.run(graph, ProjectMap())
    assert run.status == ExecutionStatus.BLOCKED


def test_orchestrator_rejects_invalid_task_graph() -> None:
    graph = _linear_graph()
    adapter = MockAdapter()
    graph.graph_validation = None
    orchestrator = ExecutionOrchestrator(adapter=adapter)
    run = orchestrator.run(graph, ProjectMap())
    assert run.status == ExecutionStatus.BLOCKED
    assert "invalid" in run.blocking_reason.lower()


def test_orchestrator_execution_run_progress() -> None:
    graph = _linear_graph()
    adapter = MockAdapter()
    orchestrator = ExecutionOrchestrator(adapter=adapter)
    run = orchestrator.run(graph, ProjectMap())
    assert run.total_tasks == len(graph.tasks)
    assert len(run.completed_tasks) + len(run.failed_tasks) + len(run.blocked_tasks) == run.total_tasks


def test_orchestrator_e2e_with_real_task_graph() -> None:
    graph = _make_task_graph()
    adapter = MockAdapter()
    orchestrator = ExecutionOrchestrator(adapter=adapter)
    run = orchestrator.run(graph, ProjectMap())
    assert run.status == ExecutionStatus.COMPLETED
    assert len(run.completed_tasks) == run.total_tasks

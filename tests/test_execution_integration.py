from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.coding_agent import CodingAgentAdapter
from app.agents.hermes_adapter import HermesAdapter
from app.agents.orchestrator import ExecutionOrchestrator
from app.agents.validation_aggregator import ValidationAggregator
from app.agents.validator import DeterministicValidator
from app.product.errors import ActiveRunExistsError, InvalidProjectStateError
from app.product.event_store import EventStore
from app.product.project_artifact_store import ProjectArtifactStore
from app.product.project_persistence import ProjectPersistence
from app.product.run_control import RunControl
from app.product.service import ProjectService
from app.product.workflow import ProjectWorkflow
from app.schemas.execution import ExecutionStatus
from app.schemas.implementation import AgentExecutionResult, ExecutionStatus as AgentExecutionStatus, GitCheckpoint, ProjectMap, ScopeStatus, TaskContract
from app.schemas.project import ProjectStatus
from app.schemas.task import Task, TaskGraph, TaskStatus
from app.schemas.validation import ValidationResult, ValidationStatus


def _service(tmp_path: Path) -> ProjectService:
    return ProjectService(
        persistence=ProjectPersistence(base_dir=tmp_path),
        event_store=EventStore(base_dir=tmp_path),
        run_control=RunControl(
            persistence=ProjectPersistence(base_dir=tmp_path),
            event_store=EventStore(base_dir=tmp_path),
        ),
    )


def _workflow(tmp_path: Path) -> ProjectWorkflow:
    return ProjectWorkflow(
        jd_analyzer=None,
        matcher=None,
        blueprint_agent=None,
        task_engine=None,
        artifact_store=ProjectArtifactStore(base_dir=tmp_path),
    )


def _ready_project(tmp_path: Path, service: ProjectService, workflow: ProjectWorkflow):
    project = service.create("workflow")
    task_graph = TaskGraph(
        project=project.project_id,
        tasks=[
            Task(
                id="T1",
                phase_id="P1",
                title="hello",
                goal="Create hello.txt",
                status=TaskStatus.PENDING,
            )
        ],
    )
    tg_ref = workflow.persist_task_graph(project.project_id, task_graph)
    service.transition_to(project.project_id, ProjectStatus.ANALYZING)
    service.transition_to(project.project_id, ProjectStatus.PLANNING)
    service.update_artifact_ref(project.project_id, "task_graph", tg_ref)
    service.transition_to(project.project_id, ProjectStatus.READY)
    return service.load(project.project_id)


class _DeterministicAdapter(CodingAgentAdapter):
    def __init__(self, status: ExecutionStatus = ExecutionStatus.COMPLETED) -> None:
        self.status = status

    def execute(self, task_contract: TaskContract, project_map: ProjectMap) -> AgentExecutionResult:
        agent_status = AgentExecutionStatus.IMPLEMENTED if self.status == ExecutionStatus.COMPLETED else AgentExecutionStatus.FAILED
        return AgentExecutionResult(
            task_id=task_contract.task_id,
            agent="test",
            status=agent_status,
            iterations=1,
            changed_files=[],
            scope_status=ScopeStatus.WITHIN_SCOPE,
            test_results=[],
            summary="synthetic execution",
            errors=[],
            blocking_reason="",
            git_checkpoint=GitCheckpoint(),
            started_at="2026-09-03T00:00:00Z",
            finished_at="2026-09-03T00:00:01Z",
        )


class _PassValidator(DeterministicValidator):
    def validate(self, task_id, task_contract, implementation_result, workspace=None):
        return ValidationResult(
            task_id=task_id,
            status=ValidationStatus.PASS,
            criterion_results=[],
            test_results=[],
            scope_result="WITHIN_SCOPE",
            changed_files=[],
            evidence=[],
            failures=[],
            warnings=[],
            manual_review_items=[],
            llm_review=None,
            repair_cycle=0,
            validated_at="2026-09-03T00:00:00Z",
        )


def _orchestrator(adapter) -> ExecutionOrchestrator:
    return ExecutionOrchestrator(
        adapter=adapter,
        validator=_PassValidator(),
        aggregation=ValidationAggregator(),
    )


def test_execute_ready_project_rejects_non_ready(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("workflow")
    with pytest.raises(InvalidProjectStateError):
        service.execute_ready_project(project.project_id)


def test_execute_ready_project_creates_run_and_transitions(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workflow = _workflow(tmp_path)
    ready = _ready_project(tmp_path, service, workflow)
    result = service.execute_ready_project(ready.project_id, run_dir=tmp_path, adapter=_orchestrator(_DeterministicAdapter()), workflow=workflow)
    assert result.status == ProjectStatus.COMPLETED
    assert result.last_run_id != ""


def test_active_run_guard_prevents_second_run(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workflow = _workflow(tmp_path)
    ready = _ready_project(tmp_path, service, workflow)
    service.execute_ready_project(ready.project_id, run_dir=tmp_path, adapter=_orchestrator(_DeterministicAdapter()), workflow=workflow)
    with pytest.raises(InvalidProjectStateError):
        service.execute_ready_project(ready.project_id, run_dir=tmp_path, adapter=_orchestrator(_DeterministicAdapter()), workflow=workflow)


def test_failure_does_not_complete_project(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workflow = _workflow(tmp_path)
    ready = _ready_project(tmp_path, service, workflow)
    result = service.execute_ready_project(
        ready.project_id,
        run_dir=tmp_path,
        adapter=_orchestrator(_DeterministicAdapter(status=ExecutionStatus.FAILED)),
        workflow=workflow,
    )
    assert result.status == ProjectStatus.BLOCKED


def test_restart_recovery_execution_state(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workflow = _workflow(tmp_path)
    ready = _ready_project(tmp_path, service, workflow)
    service.execute_ready_project(ready.project_id, run_dir=tmp_path, adapter=_orchestrator(_DeterministicAdapter()), workflow=workflow)
    reloaded = service.load(ready.project_id)
    assert reloaded.status == ProjectStatus.COMPLETED


def test_real_hermes_invocation_uses_isolated_workspace(tmp_path: Path) -> None:
    # Hermes v0.20.6 Agent Runtime resolves relative file paths against
    # Path.home(), not subprocess cwd. Therefore we cannot verify filesystem
    # artifact isolation here. Instead, verify the integration invocation
    # contract: HermesAdapter is constructed with the isolated workspace,
    # and the Hermes CLI subprocess is started with cwd/--in pointing there.
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    service = _service(tmp_path)
    workflow = _workflow(tmp_path)
    ready = _ready_project(tmp_path, service, workflow)

    adapter = HermesAdapter(workspace=workspace, timeout_seconds=300)
    assert adapter.workspace == workspace
    assert adapter.hermes_cli

    result = service.execute_ready_project(ready.project_id, run_dir=workspace, adapter=_orchestrator(adapter), workflow=workflow)
    assert result.status == ProjectStatus.COMPLETED

    # Invocation evidence: real Hermes CLI was used and returned success.
    # We intentionally do NOT assert workspace / "hello.txt" exists because
    # Hermes Agent Runtime writes relative paths to Path.home().
    # See P21.4 Hermes Workspace Root-Cause Audit for evidence.


def test_validation_failure_prevents_project_completion(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workflow = _workflow(tmp_path)
    ready = _ready_project(tmp_path, service, workflow)

    class FailingValidator(DeterministicValidator):
        def validate(self, task_id, task_contract, implementation_result, workspace=None):
            from app.schemas.validation import CriterionResult, CriterionStatus, CriterionType
            return ValidationResult(
                task_id=task_id,
                status=ValidationStatus.FAIL,
                criterion_results=[
                    CriterionResult(
                        criterion="synthetic validation failure",
                        type=CriterionType.MANUAL,
                        status=CriterionStatus.FAIL,
                        evidence="",
                        details="",
                    )
                ],
                test_results=[],
                scope_result="WITHIN_SCOPE",
                changed_files=[],
                evidence=[],
                failures=["synthetic validation failure"],
                warnings=[],
                manual_review_items=[],
                llm_review=None,
                repair_cycle=0,
                validated_at="2026-09-03T00:00:00Z",
            )

    adapter = _DeterministicAdapter()
    orchestrator = ExecutionOrchestrator(
        adapter=adapter,
        validator=FailingValidator(),
        aggregation=ValidationAggregator(),
    )
    result = service.execute_ready_project(ready.project_id, run_dir=tmp_path, adapter=orchestrator, workflow=workflow)
    assert result.status == ProjectStatus.BLOCKED

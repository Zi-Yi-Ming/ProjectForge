from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.agents.coding_agent import CodingAgentAdapter
from app.schemas.execution import ExecutionRun, ExecutionStatus, TaskExecutionRecord
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus as ImplExecutionStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)
from app.schemas.task import Task, TaskGraph, TaskStatus
from app.schemas.validation import ValidationResult, ValidationStatus


def hermes_runtime_available() -> bool:
    if shutil.which("bwrap") is None:
        return False
    return any(shutil.which(name) for name in ("hermes", "hermes-agent", "hermes_cli"))


requires_hermes = pytest.mark.skipif(
    not hermes_runtime_available(),
    reason="hermes CLI and bwrap sandbox are not available on this host",
)


class FakeExecutor:
    def __init__(self, outcomes: dict[str, AgentExecutionResult] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.cancelled = False

    def run(self, task_graph: TaskGraph, project_map: ProjectMap | None = None, run_dir: Path | None = None) -> ExecutionRun:
        self.cancelled = False
        run = ExecutionRun(
            run_id=f"run-fake-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            project=task_graph.project,
            status=ExecutionStatus.RUNNING,
            total_tasks=len(task_graph.tasks),
            started_at=self._now(),
            ready_tasks=[t.id for t in task_graph.tasks if t.status == TaskStatus.READY],
            completed_tasks=[t.id for t in task_graph.tasks if t.status == TaskStatus.DONE],
            failed_tasks=[t.id for t in task_graph.tasks if t.status == TaskStatus.FAILED],
            blocked_tasks=[t.id for t in task_graph.tasks if t.status == TaskStatus.BLOCKED],
        )

        task_map = {task.id: task for task in task_graph.tasks}
        outcomes = self.outcomes

        class _Adapter(CodingAgentAdapter):
            def execute(self, task_contract: TaskContract, project_map: ProjectMap) -> AgentExecutionResult:
                return outcomes.get(
                    task_contract.task_id,
                    AgentExecutionResult(
                        task_id=task_contract.task_id,
                        agent="fake",
                        status=ImplExecutionStatus.IMPLEMENTED,
                        iterations=1,
                        changed_files=[],
                        scope_status=ScopeStatus.WITHIN_SCOPE,
                        test_results=[],
                        summary="fake",
                        errors=[],
                        blocking_reason="",
                        git_checkpoint=GitCheckpoint(),
                    ),
                )

        adapter = _Adapter()

        for task in task_graph.tasks:
            if self.cancelled:
                break
            # ReplanControl expects failed runs to carry execution/validation
            # records for the failed task, as the real orchestrator produces.
            if task.status == TaskStatus.FAILED:
                run.task_results.append(self._failed_record(task))
                continue
            if task.status in {TaskStatus.DONE, TaskStatus.BLOCKED}:
                continue
            if any(task_map[dependency].status != TaskStatus.DONE for dependency in task.dependencies if dependency in task_map):
                continue

            task.status = TaskStatus.IN_PROGRESS
            contract = TaskContract(
                task_id=task.id,
                project="",
                phase=task.phase_id,
                title=task.title,
                goal=task.goal,
                why=task.why,
                dependencies=list(task.dependencies),
                prerequisites=list(task.prerequisites),
                inputs=list(task.inputs),
                expected_output=task.expected_output,
                implementation_scope=task.implementation_scope,
                acceptance_criteria=list(task.acceptance_criteria),
                out_of_scope=list(task.out_of_scope),
                technical_points=list(task.technical_points),
                interview_points=list(task.interview_points),
                project_map=ProjectMap(),
                allowed_paths=[],
                test_scope=[],
                execution_rules=[],
            )
            result = adapter.execute(contract, ProjectMap())
            validation = ValidationResult(
                task_id=task.id,
                status=ValidationStatus.PASS,
                criterion_results=[],
                test_results=[],
                scope_result="",
                changed_files=[],
                evidence=[],
                failures=[],
                warnings=[],
                manual_review_items=[],
                llm_review=None,
                repair_cycle=0,
                validated_at=self._now(),
            )
            if result.status == ImplExecutionStatus.IMPLEMENTED and validation.status == ValidationStatus.PASS:
                task.status = TaskStatus.DONE
                run.completed_tasks.append(task.id)
            else:
                task.status = TaskStatus.FAILED
                run.failed_tasks.append(task.id)
            run.task_results.append(TaskExecutionRecord(task_id=task.id, status=task.status.value))

        if self.cancelled:
            run.status = ExecutionStatus.BLOCKED
            run.blocking_reason = "CANCELLED"
        elif all(t.status == TaskStatus.DONE for t in task_graph.tasks):
            run.status = ExecutionStatus.COMPLETED
        else:
            run.status = ExecutionStatus.FAILED if run.failed_tasks else ExecutionStatus.BLOCKED
        run.finished_at = self._now()
        return run

    @staticmethod
    def _failed_record(task: Task) -> TaskExecutionRecord:
        return TaskExecutionRecord(
            task_id=task.id,
            phase=task.phase_id,
            title=task.title,
            status="FAILED",
            execution_result=AgentExecutionResult(
                task_id=task.id,
                agent="fake",
                status=ImplExecutionStatus.FAILED,
                iterations=1,
                changed_files=[],
                scope_status=ScopeStatus.WITHIN_SCOPE,
                test_results=[],
                summary="fake failure",
                errors=["fake failure"],
                blocking_reason="",
                git_checkpoint=GitCheckpoint(),
            ),
            validation_result=ValidationResult(
                task_id=task.id,
                status=ValidationStatus.FAIL,
                criterion_results=[],
                test_results=[],
                scope_result="WITHIN_SCOPE",
                changed_files=[],
                evidence=[],
                failures=["fake failure"],
                warnings=[],
                manual_review_items=[],
                llm_review=None,
                repair_cycle=0,
                validated_at="",
            ),
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

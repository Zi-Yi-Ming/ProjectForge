from __future__ import annotations

import concurrent.futures
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.agents.artifact_store import ArtifactStore
from app.agents.coding_agent import CodingAgentAdapter
from app.agents.failure_analyzer import FailureAnalyzer
from app.agents.orchestrator import ExecutionOrchestrator
from app.agents.persistence import JsonExecutionPersistence
from app.agents.replanner import Replanner
from app.agents.replan_persistence import ReplanPersistence
from app.agents.scheduler import TaskScheduler
from app.agents.validator import DeterministicValidator
from app.agents.worker import Worker, WorkerResult
from app.agents.worker_pool import WorkerPool
from app.schemas.execution import ExecutionRun, ExecutionStatus, TaskExecutionRecord
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus as ImplExecutionStatus,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)
from app.schemas.replan import ReplanAction, ReplanProposal, ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus
from app.schemas.validation import ValidationResult, ValidationStatus


class ParallelExecutionOrchestrator:
    def __init__(
        self,
        adapter: CodingAgentAdapter,
        project_map: ProjectMap,
        base_dir: Path | None = None,
        max_workers: int = 1,
        validator: DeterministicValidator | None = None,
        workspace_factory: Callable[[str], Path] | None = None,
    ) -> None:
        self.adapter = adapter
        self.project_map = project_map
        self.base_dir = base_dir or Path(".runtime")
        self.max_workers = max_workers
        self.validator = validator or DeterministicValidator()
        self.workspace_factory = workspace_factory
        self.scheduler = TaskScheduler()
        self.persistence = JsonExecutionPersistence(self.base_dir)
        self.replan_persistence = ReplanPersistence(self.base_dir)
        self.failure_analyzer = FailureAnalyzer()
        self.replanner = Replanner()
        self._state_lock = threading.Lock()

    def run(self, task_graph: TaskGraph, run_id: str, run_dir: Path) -> ExecutionRun:
        run_dir.mkdir(parents=True, exist_ok=True)
        run = ExecutionRun(
            run_id=run_id,
            project=task_graph.project,
            status=ExecutionStatus.RUNNING,
            total_tasks=len(task_graph.tasks),
            started_at=self._now(),
            ready_tasks=[t.id for t in task_graph.tasks if t.status == TaskStatus.READY],
            completed_tasks=[t.id for t in task_graph.tasks if t.status == TaskStatus.DONE],
            failed_tasks=[t.id for t in task_graph.tasks if t.status == TaskStatus.FAILED],
            blocked_tasks=[t.id for t in task_graph.tasks if t.status == TaskStatus.BLOCKED],
        )
        self.persistence.create_run(run)

        worker = Worker(
            adapter=self.adapter,
            validator=self.validator,
            workspace_factory=self.workspace_factory,
        )
        pool = WorkerPool(max_workers=self.max_workers)

        while True:
            if run.status == ExecutionStatus.COMPLETED:
                break
            if run.status in {ExecutionStatus.FAILED, ExecutionStatus.BLOCKED}:
                break

            self.scheduler.update_states(task_graph)
            ready = self._select_ready_by_order(task_graph)
            ready = [task for task in ready if task.status == TaskStatus.READY]
            if not ready:
                if self._has_active_or_pending(task_graph):
                    with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                        pass
                    continue
                final_status = ExecutionStatus.COMPLETED if all(t.status == TaskStatus.DONE for t in task_graph.tasks if t.id in run.completed_tasks) else ExecutionStatus.BLOCKED
                run.status = final_status
                run.finished_at = self._now()
                self.persistence.save_run(run)
                break

            worker_results = pool.execute(ready, lambda task: worker.execute(self._contract_for(task), self.project_map))
            with self._state_lock:
                for result in worker_results:
                    self._apply_worker_result(run, task_graph, result, run_dir)

            if run.active_proposal_id:
                run.status = ExecutionStatus.BLOCKED
                run.finished_at = self._now()
                self.persistence.save_run(run)
                break

        return run

    def _apply_worker_result(self, run: ExecutionRun, task_graph: TaskGraph, result: WorkerResult, run_dir: Path) -> None:
        task = next((t for t in task_graph.tasks if t.id == result.task_id), None)
        if task is None:
            return

        if result.agent_result.status == ImplExecutionStatus.IMPLEMENTED and result.validation_result and result.validation_result.status == "PASS":
            task.status = TaskStatus.DONE
            run.completed_tasks.append(result.task_id)
        elif result.agent_result.status == ImplExecutionStatus.IMPLEMENTED:
            task.status = TaskStatus.FAILED
            run.failed_tasks.append(result.task_id)
            proposal = self._build_proposal(run, task, result)
            self.replan_persistence.save_proposal(proposal)
            run.active_proposal_id = proposal.proposal_id
            run.replan_count += 1
        elif result.agent_result.status == ImplExecutionStatus.ERROR:
            task.status = TaskStatus.FAILED
            run.failed_tasks.append(result.task_id)
        elif result.agent_result.status == ImplExecutionStatus.TIMEOUT:
            task.status = TaskStatus.FAILED
            run.failed_tasks.append(result.task_id)
        else:
            task.status = TaskStatus.FAILED
            run.failed_tasks.append(result.task_id)

        run.task_results.append(TaskExecutionRecord(task_id=result.task_id, status=task.status.value))
        run.completed_tasks = [tid for tid in run.completed_tasks if tid not in run.failed_tasks and tid not in run.blocked_tasks]
        run.failed_tasks = [tid for tid in run.failed_tasks if tid not in run.completed_tasks and tid not in run.blocked_tasks]
        run.blocked_tasks = [tid for tid in run.blocked_tasks if tid not in run.completed_tasks and tid not in run.failed_tasks]
        self.persistence.save_task_record(run.run_id, TaskExecutionRecord(task_id=result.task_id, status=task.status.value))
        self.persistence.save_run(run)

    def _build_proposal(self, run: ExecutionRun, task: Task, result: WorkerResult) -> ReplanProposal:
        return ReplanProposal(
            proposal_id=f"rp-{run.run_id}-{task.id}-{run.replan_count + 1}",
            run_id=run.run_id,
            task_id=task.id,
            action=ReplanAction.RETRY,
            reason="Validation failed after execution.",
            evidence=[f"validation_status={result.validation_result.status if result.validation_result else 'NONE'}"],
            affected_task_ids=[task.id],
            proposed_changes=[],
            forbidden_changes=["MODIFY_BLUEPRINT", "MODIFY_ARCHITECTURE", "DELETE_DONE_TASK", "REWRITE_PROJECT"],
            requires_user_approval=True,
            status=ReplanProposalStatus.PROPOSED,
            created_at=self._now(),
        )

    def _contract_for(self, task: Task) -> TaskContract:
        return TaskContract(
            task_id=task.id,
            project=task.phase_id,
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
            project_map=self.project_map,
            allowed_paths=[],
            test_scope=[],
            execution_rules=[],
        )

    def _select_ready_by_order(self, task_graph: TaskGraph) -> list[Task]:
        order = list(task_graph.graph_validation.topological_order) if task_graph.graph_validation and task_graph.graph_validation.topological_order else [t.id for t in task_graph.tasks]
        position = {task_id: idx for idx, task_id in enumerate(order)}
        ready = [task for task in task_graph.tasks if task.status == TaskStatus.READY]
        ready.sort(key=lambda task: position.get(task.id, len(order)))
        return ready

    def _has_active_or_pending(self, task_graph: TaskGraph) -> bool:
        return any(task.status in {TaskStatus.IN_PROGRESS, TaskStatus.VALIDATING} for task in task_graph.tasks)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

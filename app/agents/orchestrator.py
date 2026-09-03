from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.artifact_store import ArtifactStore
from app.agents.coding_agent import CodingAgentAdapter
from app.agents.failure_analyzer import FailureAnalyzer
from app.agents.persistence import JsonExecutionPersistence
from app.agents.replanner import Replanner
from app.agents.replan_applier import ReplanApplier
from app.agents.replan_persistence import ReplanPersistence
from app.agents.scheduler import TaskScheduler
from app.agents.validation_aggregator import ValidationAggregator
from app.agents.validator import DeterministicValidator
from app.schemas.execution import ExecutionRun, ExecutionStatus, TaskExecutionRecord
from app.schemas.implementation import ProjectMap, TaskContract
from app.schemas.persistence import Artifact, ArtifactType
from app.schemas.replan import ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus
from app.schemas.validation import ValidationResult, ValidationStatus


class ExecutionOrchestrator:
    def __init__(
        self,
        adapter: CodingAgentAdapter,
        validator: DeterministicValidator | None = None,
        aggregation: ValidationAggregator | None = None,
        persistence: JsonExecutionPersistence | None = None,
        artifact_store: ArtifactStore | None = None,
        failure_analyzer: Any | None = None,
        replanner: Any | None = None,
        replan_persistence: Any | None = None,
        replan_applier: Any | None = None,
    ) -> None:
        self.adapter = adapter
        self.validator = validator or DeterministicValidator()
        self.aggregation = aggregation or ValidationAggregator()
        self.scheduler = TaskScheduler()
        self.persistence = persistence
        self.artifact_store = artifact_store
        self.failure_analyzer = failure_analyzer
        self.replanner = replanner
        self.replan_persistence = replan_persistence
        self.replan_applier = replan_applier

    def run(self, task_graph: TaskGraph, project_map: ProjectMap, run_dir: Path | None = None) -> ExecutionRun:
        run = ExecutionRun(
            run_id=self._run_id(task_graph),
            project=task_graph.project,
            status=ExecutionStatus.RUNNING,
            total_tasks=len(task_graph.tasks),
            started_at=self._now(),
        )
        artifact_store = self.artifact_store or (ArtifactStore(run_dir) if run_dir else None)
        if self.persistence is not None and run_dir is not None:
            self.persistence.create_run(run)

        if task_graph.graph_validation is not None and not task_graph.graph_validation.valid:
            run.status = ExecutionStatus.BLOCKED
            run.blocking_reason = "TaskGraph validation failed; cannot execute invalid graph."
            run.finished_at = self._now()
            if self.persistence is not None:
                self.persistence.save_run(run)
            return run

        self.scheduler.update_states(task_graph)

        while True:
            ready = self.scheduler.get_ready_tasks(task_graph)
            run.ready_tasks = [t.id for t in ready]
            run.completed_tasks = [t.id for t in task_graph.tasks if t.status == TaskStatus.DONE]
            run.failed_tasks = [t.id for t in task_graph.tasks if t.status == TaskStatus.FAILED]
            run.blocked_tasks = [t.id for t in task_graph.tasks if t.status == TaskStatus.BLOCKED]

            if all(t.status == TaskStatus.DONE for t in task_graph.tasks):
                run.status = ExecutionStatus.COMPLETED
                run.finished_at = self._now()
                if self.persistence is not None:
                    self.persistence.save_run(run)
                return run

            next_task = self.scheduler.select_next_task(task_graph)
            if next_task is None:
                if not run.active_proposal_id:
                    run.status = ExecutionStatus.BLOCKED
                    run.blocking_reason = self._blocking_reason(task_graph)
                run.finished_at = self._now()
                if self.persistence is not None:
                    self.persistence.save_run(run)
                return run

            contract = self._build_contract(next_task, project_map)
            run.current_task_id = next_task.id
            next_task.status = TaskStatus.IN_PROGRESS
            if self.persistence is not None:
                self._persist_task_state(run, next_task, started_at=None)
            started_at = self._now()

            try:
                execution_result = self.adapter.execute(contract, project_map)
            except Exception as exc:
                next_task.status = TaskStatus.FAILED
                run.task_results.append(
                    TaskExecutionRecord(
                        task_id=next_task.id,
                        phase=next_task.phase_id,
                        title=next_task.title,
                        status=next_task.status.value,
                        contract=contract,
                        started_at=started_at,
                        finished_at=self._now(),
                    )
                )
                if artifact_store is not None:
                    artifact_store.save(
                        Artifact(
                            artifact_id=f"{next_task.id}_error",
                            task_id=next_task.id,
                            artifact_type=ArtifactType.ERROR_LOG,
                            created_at=self._now(),
                            metadata=[str(exc)],
                        ),
                        str(exc),
                    )
                self.scheduler.update_states(task_graph)
                if self.persistence is not None:
                    self.persistence.save_run(run)
                if self._replan_enabled():
                    self._maybe_generate_replan(run, next_task, task_graph, contract, None, None)
                continue

            if execution_result.status not in {"IMPLEMENTED"}:
                next_task.status = TaskStatus.FAILED if execution_result.status in {"FAILED", "ERROR", "TIMEOUT"} else TaskStatus.BLOCKED
                record = TaskExecutionRecord(
                    task_id=next_task.id,
                    phase=next_task.phase_id,
                    title=next_task.title,
                    status=next_task.status.value,
                    contract=contract,
                    execution_result=execution_result,
                    started_at=started_at,
                    finished_at=self._now(),
                )
                run.task_results.append(record)
                if self.persistence is not None:
                    self.persistence.save_task_record(run.run_id, record)
                if artifact_store is not None:
                    artifact_store.save(
                        Artifact(
                            artifact_id=f"{next_task.id}_output",
                            task_id=next_task.id,
                            artifact_type=ArtifactType.AGENT_OUTPUT,
                            created_at=self._now(),
                            metadata=[execution_result.status],
                        ),
                        json.dumps(execution_result.model_dump(), ensure_ascii=False, indent=2),
                    )
                self.scheduler.update_states(task_graph)
                if self.persistence is not None:
                    self.persistence.save_run(run)
                if self._replan_enabled():
                    self._maybe_generate_replan(run, next_task, task_graph, contract, execution_result, None)
                continue

            next_task.status = TaskStatus.VALIDATING
            if self.persistence is not None:
                self._persist_task_state(run, next_task, started_at)

            deterministic_result = self.validator.validate(next_task.id, contract, execution_result)
            validation_result, feedback = self.aggregation.aggregate(contract, execution_result, deterministic_result)

            if validation_result.status == ValidationStatus.PASS:
                next_task.status = TaskStatus.DONE
            elif validation_result.status == ValidationStatus.FAIL:
                next_task.status = TaskStatus.FAILED
            else:
                next_task.status = TaskStatus.BLOCKED

            record = TaskExecutionRecord(
                task_id=next_task.id,
                phase=next_task.phase_id,
                title=next_task.title,
                status=next_task.status.value,
                contract=contract,
                execution_result=execution_result,
                validation_result=validation_result,
                started_at=started_at,
                finished_at=self._now(),
            )
            run.task_results.append(record)
            if self.persistence is not None:
                self.persistence.save_task_record(run.run_id, record)
            if artifact_store is not None:
                artifact_store.save(
                    Artifact(
                        artifact_id=f"{next_task.id}_validation",
                        task_id=next_task.id,
                        artifact_type=ArtifactType.VALIDATION_RESULT,
                        created_at=self._now(),
                        metadata=[validation_result.status.value],
                    ),
                    json.dumps(validation_result.model_dump(), ensure_ascii=False, indent=2),
                )
                if execution_result.git_checkpoint is not None:
                    artifact_store.save(
                        Artifact(
                            artifact_id=f"{next_task.id}_git",
                            task_id=next_task.id,
                            artifact_type=ArtifactType.GIT_CHECKPOINT,
                            created_at=self._now(),
                            metadata=list(execution_result.git_checkpoint.changed_files or []),
                        ),
                        json.dumps(execution_result.git_checkpoint.model_dump(), ensure_ascii=False, indent=2),
                    )
            self.scheduler.update_states(task_graph)
            if self.persistence is not None:
                self.persistence.save_run(run)
            if next_task.status == TaskStatus.FAILED and self._replan_enabled():
                self._maybe_generate_replan(run, next_task, task_graph, contract, execution_result, validation_result)

        return run

    def resume(self, run_id: str, task_graph: TaskGraph, project_map: ProjectMap, run_dir: Path) -> ExecutionRun:
        if self.persistence is None:
            raise RuntimeError("persistence is required for resume")
        persisted_run = self.persistence.load_run(run_id)
        for record in persisted_run.task_results:
            task = next((t for t in task_graph.tasks if t.id == record.task_id), None)
            if task is None:
                continue
            if record.status == "DONE":
                task.status = TaskStatus.DONE
            elif record.status == "FAILED":
                task.status = TaskStatus.FAILED
            elif record.status == "BLOCKED":
                task.status = TaskStatus.BLOCKED
            else:
                task.status = TaskStatus.PENDING
        self.scheduler.update_states(task_graph)
        return self.run(task_graph, project_map, run_dir=run_dir)

    def approve_and_apply(self, proposal: Any, task_graph: TaskGraph) -> Any:
        proposal.status = ReplanProposalStatus.APPROVED
        if self.replan_persistence is not None:
            self.replan_persistence.save_proposal(proposal)
        if self.replan_applier is None:
            raise RuntimeError("replan_applier is required")
        return self.replan_applier.apply(proposal, task_graph)

    def _replan_enabled(self) -> bool:
        return self.failure_analyzer is not None and self.replanner is not None and self.replan_persistence is not None

    def _maybe_generate_replan(
        self,
        run: ExecutionRun,
        task: Task,
        task_graph: TaskGraph,
        contract: Any,
        execution_result: Any,
        validation_result: Any,
    ) -> None:
        if not self._replan_enabled():
            return
        artifacts: list[Any] = []
        if self.artifact_store is not None and run.run_id:
            try:
                artifacts = self.artifact_store.list_for_task(task.id)
            except FileNotFoundError:
                artifacts = []
        attempt_count = sum(1 for r in run.task_results if r.task_id == task.id)
        analysis = self.failure_analyzer.analyze(
            task_contract=contract,
            implementation_result=execution_result,
            validation_result=validation_result,
            artifacts=artifacts,
            attempt_count=attempt_count,
        )
        proposal = self.replanner.propose(run, task_graph, analysis, attempt_counts={task.id: attempt_count})
        if proposal is None:
            return
        run.status = ExecutionStatus.BLOCKED
        run.blocking_reason = "NEEDS_USER_REPLAN_APPROVAL"
        run.active_proposal_id = proposal.proposal_id
        proposal.status = ReplanProposalStatus.PROPOSED
        self.replan_persistence.save_proposal(proposal)
        if self.persistence is not None:
            self.persistence.save_run(run)

    def _persist_task_state(self, run: ExecutionRun, task: Task, started_at: str | None) -> None:
        if self.persistence is None:
            return
        record = TaskExecutionRecord(
            task_id=task.id,
            phase=task.phase_id,
            title=task.title,
            status=task.status.value,
            started_at=started_at or self._now(),
        )
        self.persistence.save_task_record(run.run_id, record)
        self.persistence.save_run(run)

    def _build_contract(self, task: Task, project_map: ProjectMap) -> TaskContract:
        return TaskContract(
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
            project_map=project_map,
            allowed_paths=[],
            test_scope=[],
            execution_rules=[],
        )

    def _blocking_reason(self, task_graph: TaskGraph) -> str:
        pending = [t for t in task_graph.tasks if t.status == TaskStatus.PENDING]
        if pending:
            return "no executable task remains; unresolved dependency chain"
        return "execution stopped"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _run_id(task_graph: TaskGraph) -> str:
        return f"run-{task_graph.project}-{abs(hash(str([t.id for t in task_graph.tasks])))}"

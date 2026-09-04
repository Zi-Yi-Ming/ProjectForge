from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.agents.failure_analyzer import FailureAnalyzer
from app.agents.replanner import Replanner
from app.agents.replan_applier import ReplanApplier
from app.product.replan_applier import ProductReplanApplier
from app.agents.replan_persistence import ReplanPersistence
from app.product.errors import (
    InvalidProjectStateError,
    ProjectNotFoundError,
)
from app.product.event_store import Actor, EventStore, ProductEvent
from app.product.project_persistence import ProjectPersistence
from app.product.run_control import RunControl
from app.schemas.execution import ExecutionRun, ExecutionStatus
from app.schemas.project import ProjectStatus
from app.schemas.replan import ReplanAction, ReplanProposal, ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus


class ReplanControl:
    def __init__(
        self,
        persistence: ProjectPersistence | None = None,
        run_control: RunControl | None = None,
        *,
        event_store: EventStore | None = None,
        execution_persistence: Any = None,
        failure_analyzer: FailureAnalyzer | None = None,
        replanner: Replanner | None = None,
        replan_applier: ReplanApplier | None = None,
        replan_persistence: ReplanPersistence | None = None,
        on_proposal_created: Callable[..., Any] | None = None,
        on_proposal_approved: Callable[..., Any] | None = None,
        on_proposal_applied: Callable[..., Any] | None = None,
        on_proposal_rejected: Callable[..., Any] | None = None,
    ) -> None:
        self.persistence = persistence or ProjectPersistence()
        self.run_control = run_control or RunControl()
        self.event_store = event_store
        self.execution_persistence = execution_persistence
        self.failure_analyzer = failure_analyzer or FailureAnalyzer()
        self.replanner = replanner or Replanner()
        self.replan_applier = replan_applier or ProductReplanApplier()
        self.replan_persistence = replan_persistence or ReplanPersistence()
        self._on_proposal_created = on_proposal_created
        self._on_proposal_approved = on_proposal_approved
        self._on_proposal_applied = on_proposal_applied
        self._on_proposal_rejected = on_proposal_rejected

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _event(self, event_type: str, project_id: str, run_id: str, payload: dict[str, Any] | None = None) -> None:
        if self.event_store is None:
            return
        event = ProductEvent(
            event_id=f"evt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            event_type=event_type,
            project_id=project_id,
            run_id=run_id,
            actor=Actor.SYSTEM,
            timestamp=self._now(),
            payload=payload or {},
        )
        self.event_store.append(event)

    def create_proposal(self, project_id: str, run_id: str, task_graph: TaskGraph) -> ReplanProposal:
        project = self.persistence.load_project(project_id)
        if project.status in {ProjectStatus.COMPLETED, ProjectStatus.FAILED}:
            raise InvalidProjectStateError(f"Cannot create replan proposal for project in state: {project.status}")
        run = self.run_control.load_run(project_id, run_id)
        if run.status not in {ExecutionStatus.FAILED, ExecutionStatus.BLOCKED}:
            raise InvalidProjectStateError(f"Run {run_id} is not in FAILED/BLOCKED state: {run.status}")
        failed_task_id = self._failed_task_id(run, task_graph)
        if failed_task_id is None:
            raise InvalidProjectStateError("No failed task found for replan.")
        task = next((t for t in task_graph.tasks if t.id == failed_task_id), None)
        if task is None:
            raise InvalidProjectStateError(f"Failed task {failed_task_id} not found in task graph.")
        if task.status == TaskStatus.DONE:
            raise InvalidProjectStateError("Cannot create replan proposal for DONE task.")
        contract = self._build_contract(task)
        execution_result = self._execution_result(run, failed_task_id)
        validation_result = self._validation_result(run, failed_task_id)
        artifacts = []
        attempt_count = sum(1 for r in run.task_results if r.task_id == failed_task_id)
        analysis = self.failure_analyzer.analyze(
            task_contract=contract,
            implementation_result=execution_result,
            validation_result=validation_result,
            artifacts=artifacts,
            attempt_count=attempt_count,
        )
        proposal = self.replanner.propose(run, task_graph, analysis, attempt_counts={failed_task_id: attempt_count})
        if proposal is None:
            raise InvalidProjectStateError("Replanner could not generate a proposal.")
        proposal.run_id = run_id
        proposal.created_at = self._now()
        proposal.status = ReplanProposalStatus.PROPOSED
        self.replan_persistence.save_proposal(proposal)
        run.status = ExecutionStatus.BLOCKED
        run.blocking_reason = "NEEDS_USER_REPLAN_APPROVAL"
        run.active_proposal_id = proposal.proposal_id
        if self.execution_persistence is not None:
            self.execution_persistence.save_run(run)
        self._event("REPLAN_PROPOSED", project_id, run_id, {"proposal_id": proposal.proposal_id, "task_id": failed_task_id})
        if self._on_proposal_created is not None:
            self._on_proposal_created(proposal)
        return proposal

    def approve_proposal(self, project_id: str, run_id: str, proposal_id: str) -> ReplanProposal:
        proposal = self.replan_persistence.load_proposal(run_id, proposal_id)
        if proposal.status != ReplanProposalStatus.PROPOSED:
            raise InvalidProjectStateError(f"Proposal {proposal_id} is not PENDING_APPROVAL: {proposal.status}")
        proposal.status = ReplanProposalStatus.APPROVED
        proposal.approved_at = self._now()
        self.replan_persistence.save_proposal(proposal)
        self._event("REPLAN_APPROVED", project_id, run_id, {"proposal_id": proposal_id})
        if self._on_proposal_approved is not None:
            self._on_proposal_approved(proposal)
        return proposal

    def apply_proposal(self, project_id: str, proposal_id: str, task_graph: TaskGraph, run_id: str = "") -> ReplanProposal:
        if not run_id and self.replan_persistence:
            run_id = self._run_id_from_proposal(proposal_id)
        proposal = self.replan_persistence.load_proposal(run_id, proposal_id)
        if proposal.status != ReplanProposalStatus.APPROVED:
            raise InvalidProjectStateError(f"Proposal {proposal_id} is not APPROVED: {proposal.status}")
        result = self.replan_applier.apply(proposal, task_graph)
        if not result.success:
            raise InvalidProjectStateError(f"Failed to apply proposal: {result.message}")
        proposal.status = ReplanProposalStatus.APPLIED
        proposal.applied_at = self._now()
        self.replan_persistence.save_proposal(proposal)
        self._event("REPLAN_APPLIED", project_id, run_id, {"proposal_id": proposal_id})
        if self._on_proposal_applied is not None:
            self._on_proposal_applied(proposal)
        return proposal

    def reject_proposal(self, project_id: str, run_id: str, proposal_id: str) -> ReplanProposal:
        proposal = self.replan_persistence.load_proposal(run_id, proposal_id)
        if proposal.status != ReplanProposalStatus.PROPOSED:
            raise InvalidProjectStateError(f"Proposal {proposal_id} is not PENDING_APPROVAL: {proposal.status}")
        proposal.status = ReplanProposalStatus.REJECTED
        self.replan_persistence.save_proposal(proposal)
        self._event("REPLAN_REJECTED", project_id, run_id, {"proposal_id": proposal_id})
        if self._on_proposal_rejected is not None:
            self._on_proposal_rejected(proposal)
        return proposal

    def get_proposal(self, run_id: str, proposal_id: str) -> ReplanProposal:
        return self.replan_persistence.load_proposal(run_id, proposal_id)

    def list_proposals(self, run_id: str) -> list[ReplanProposal]:
        return self.replan_persistence.list_proposals(run_id)

    def resume_project(self, project_id: str, task_graph: TaskGraph, run_dir: Path, executor: Any = None) -> ExecutionRun:
        project = self.persistence.load_project(project_id)
        if project.status not in {ProjectStatus.FAILED, ProjectStatus.BLOCKED, ProjectStatus.EXECUTING}:
            raise InvalidProjectStateError(f"Project {project_id} is not in a resumable state: {project.status}")
        active = self.run_control.active_run(project_id)
        if active is not None:
            raise InvalidProjectStateError(f"Project {project_id} already has an active run: {active.run_id}")
        proposals = self.replan_persistence.list_proposals(project.last_run_id) if project.last_run_id else []
        applied_proposal = next((p for p in proposals if p.status == ReplanProposalStatus.APPLIED), None)
        if applied_proposal is None:
            raise InvalidProjectStateError("No APPLIED proposal found for resume.")
        project.status = ProjectStatus.EXECUTING
        project.updated_at = self._now()
        self.persistence.save_project(project)
        run = self.run_control.start_run(project, task_graph, run_dir, executor)
        self._event("RUN_RESUMED", project_id, run.run_id, {"previous_run_id": project.last_run_id})
        return run

    def _run_id_from_proposal(self, proposal_id: str) -> str:
        if self.execution_persistence is None:
            return ""
        for run_dir in self.execution_persistence.runs_dir.iterdir():
            path = run_dir / "replans" / f"{proposal_id}.json"
            if path.exists():
                return run_dir.name
        return ""

    def _failed_task_id(self, run: ExecutionRun, task_graph: TaskGraph) -> str | None:
        for record in run.task_results:
            if record.status == "FAILED":
                return record.task_id
        for task in task_graph.tasks:
            if task.status == TaskStatus.FAILED:
                return task.id
        return None

    def _build_contract(self, task: Task) -> Any:
        from app.schemas.implementation import ProjectMap, TaskContract
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
            project_map=ProjectMap(),
            allowed_paths=[],
            test_scope=[],
            execution_rules=[],
        )

    def _execution_result(self, run: ExecutionRun, task_id: str) -> Any:
        for record in run.task_results:
            if record.task_id == task_id and record.execution_result is not None:
                return record.execution_result
        raise InvalidProjectStateError(
            f"Missing execution result for task {task_id} in run {run.run_id}."
        )

    def _validation_result(self, run: ExecutionRun, task_id: str) -> Any:
        for record in run.task_results:
            if record.task_id == task_id and record.validation_result is not None:
                return record.validation_result
        raise InvalidProjectStateError(
            f"Missing validation result for task {task_id} in run {run.run_id}."
        )

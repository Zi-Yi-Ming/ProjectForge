from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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
from app.schemas.validation import CriterionResult, CriterionStatus, CriterionType, ValidationResult, ValidationStatus


@dataclass
class _WaveOutcome:
    """Per-task result produced inside a parallel wave, before the dispatcher
    merges it back and records it on the single-threaded path."""

    task: Task
    branch: str
    worktree: Path
    contract: TaskContract
    execution_result: Any | None
    validation_result: Any | None
    status: TaskStatus
    started_at: str
    finished_at: str
    error: str = ""


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
        artifacts_root: Path | None = None,
        max_run_seconds: float | None = None,
        rollback_on_failure: bool = False,
        parallel_enabled: bool = False,
        max_parallel_workers: int | None = None,
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
        self.artifacts_root = artifacts_root
        # ⑥g: global wall-clock budget for a run. 12 tasks x 3 retries x 300s is
        # worst-case ~3h with no gate. None keeps the previous unbounded behavior,
        # so opting in is required.
        self.max_run_seconds = max_run_seconds
        # P2 checkpoint rollback: discarding a failed task's partial work is
        # destructive (git reset --hard + clean), so it is opt-in. When off, a
        # failed task leaves its half-finished changes in the workspace and the
        # next task builds on a dirty foundation — the historical behavior.
        self.rollback_on_failure = rollback_on_failure
        # P3 parallel workers: opt-in. Off by default so the serial loop stays
        # exactly as before; only a ready wave of >1 independent task is fanned
        # out, each on its own git worktree, when enabled.
        self.parallel_enabled = parallel_enabled
        self.max_parallel_workers = max_parallel_workers

    def _artifact_store_for(self, run_dir: Path | None, run_id: str | None) -> ArtifactStore | None:
        """Pick where audit artifacts live.

        Preference order keeps artifacts *out of the executor workspace* when
        possible: an in-workspace ``artifacts/`` directory would be swept into
        the per-task git checkpoint and corrupt the audit trail. Falls back to
        the workspace only when no run root is known.
        """
        if self.artifact_store is not None:
            return self.artifact_store
        if self.artifacts_root is not None and run_id:
            return ArtifactStore(self.artifacts_root / run_id)
        if self.persistence is not None and run_id:
            return ArtifactStore(self.persistence.runs_dir / run_id)
        return ArtifactStore(run_dir) if run_dir else None

    def run(
        self,
        task_graph: TaskGraph,
        project_map: ProjectMap,
        run_dir: Path | None = None,
        run_id: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ExecutionRun:
        run = ExecutionRun(
            run_id=run_id or self._run_id(task_graph),
            project=task_graph.project,
            status=ExecutionStatus.RUNNING,
            total_tasks=len(task_graph.tasks),
            started_at=self._now(),
        )
        artifact_store = self._artifact_store_for(run_dir, run.run_id)
        if self.persistence is not None and run_dir is not None:
            self.persistence.create_run(run)

        if run_dir is not None:
            self._ensure_git_baseline(run_dir)

        if task_graph.graph_validation is not None and not task_graph.graph_validation.valid:
            run.status = ExecutionStatus.BLOCKED
            run.blocking_reason = "TaskGraph validation failed; cannot execute invalid graph."
            run.finished_at = self._now()
            if self.persistence is not None:
                self.persistence.save_run(run)
            return run

        self.scheduler.update_states(task_graph)
        budget_start = time.monotonic()

        while True:
            over_budget = self._is_over_budget(budget_start)
            if over_budget or (cancel_check is not None and cancel_check()):
                # A budget stop is not a user cancellation; keep the two distinct.
                run.cancel_requested = not over_budget
                run.status = ExecutionStatus.BLOCKED
                run.blocking_reason = "TIME_BUDGET_EXCEEDED" if over_budget else "CANCELLED"
                for task in task_graph.tasks:
                    if task.status not in {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.BLOCKED}:
                        task.status = TaskStatus.BLOCKED
                run.blocked_tasks = [t.id for t in task_graph.tasks if t.status == TaskStatus.BLOCKED]
                run.current_task_id = ""
                run.finished_at = self._now()
                if self.persistence is not None:
                    self.persistence.save_run(run)
                return run

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

            # Serial dispatch takes the head of the ready wave; this is the seam
            # a later workspace_provider fans the whole wave out over.
            wave = self.scheduler.ready_wave(task_graph)
            next_task = wave[0] if wave else None
            if next_task is None:
                if not run.active_proposal_id:
                    run.status = ExecutionStatus.BLOCKED
                    run.blocking_reason = self._blocking_reason(task_graph)
                run.finished_at = self._now()
                if self.persistence is not None:
                    self.persistence.save_run(run)
                return run

            if self.parallel_enabled and len(wave) > 1:
                handled = self._run_wave_parallel(
                    run, wave, task_graph, project_map, run_dir, artifact_store
                )
                if handled:
                    continue

            contract = self._build_contract(next_task, project_map, run_dir=run_dir)
            run.current_task_id = next_task.id
            next_task.status = TaskStatus.IN_PROGRESS
            if self.persistence is not None:
                self._persist_task_state(run, next_task, started_at=None)
            started_at = self._now()
            # Snapshot the workspace before the task runs so a failure can be
            # rolled back to it (only when rollback is enabled).
            head_before_task = self._git_head(run_dir)

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
                            artifact_id=self._unique_artifact_id(next_task.id, "error"),
                            task_id=next_task.id,
                            artifact_type=ArtifactType.ERROR_LOG,
                            created_at=self._now(),
                            metadata=[str(exc)],
                        ),
                        str(exc),
                    )
                self._maybe_rollback(run_dir, head_before_task, next_task.status)
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
                            artifact_id=self._unique_artifact_id(next_task.id, "output"),
                            task_id=next_task.id,
                            artifact_type=ArtifactType.AGENT_OUTPUT,
                            created_at=self._now(),
                            metadata=[execution_result.status],
                        ),
                        json.dumps(execution_result.model_dump(), ensure_ascii=False, indent=2),
                    )
                self._maybe_rollback(run_dir, head_before_task, next_task.status)
                self.scheduler.update_states(task_graph)
                if self.persistence is not None:
                    self.persistence.save_run(run)
                if self._replan_enabled():
                    self._maybe_generate_replan(run, next_task, task_graph, contract, execution_result, None)
                continue

            next_task.status = TaskStatus.VALIDATING
            if self.persistence is not None:
                self._persist_task_state(run, next_task, started_at)

            deterministic_result = self.validator.validate(next_task.id, contract, execution_result, workspace=run_dir)
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
                        artifact_id=self._unique_artifact_id(next_task.id, "validation"),
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
                            artifact_id=self._unique_artifact_id(next_task.id, "git"),
                            task_id=next_task.id,
                            artifact_type=ArtifactType.GIT_CHECKPOINT,
                            created_at=self._now(),
                            metadata=list(execution_result.git_checkpoint.changed_files or []),
                        ),
                        json.dumps(execution_result.git_checkpoint.model_dump(), ensure_ascii=False, indent=2),
                    )
            self._maybe_rollback(run_dir, head_before_task, next_task.status)
            self.scheduler.update_states(task_graph)
            if self.persistence is not None:
                self.persistence.save_run(run)
            if next_task.status == TaskStatus.FAILED and self._replan_enabled():
                self._maybe_generate_replan(run, next_task, task_graph, contract, execution_result, validation_result)

        return run

    def _run_wave_parallel(
        self,
        run: ExecutionRun,
        wave: list[Task],
        task_graph: TaskGraph,
        project_map: ProjectMap,
        run_dir: Path | None,
        artifact_store: ArtifactStore | None,
    ) -> bool:
        """Fan a ready wave of independent tasks out over git worktrees.

        Workers only ever touch their own worktree (execute + validate), so the
        isolation is real. Every shared mutation — merge, records, artifacts,
        persistence, replan — runs single-threaded after the barrier. Returns
        False (the caller then runs the untouched serial body for wave[0]) when
        the run cannot be branched, e.g. no usable git history yet.
        """
        from concurrent.futures import ThreadPoolExecutor

        from app.agents.worktree import WorktreeError, WorktreeManager
        from app.agents.workspace_provider import WorktreeWorkspaceProvider

        if run_dir is None:
            return False
        original_provider = getattr(self.adapter, "workspace_provider", None)
        if original_provider is None:
            return False  # adapter has no provider seam -> cannot isolate branches

        mgr = WorktreeManager(run_dir)
        base_head = mgr.head()
        if not base_head:
            return False  # nothing to branch from yet -> stay serial

        provider = WorktreeWorkspaceProvider(run_dir)
        worktrees_root = run_dir.parent / ".pf-worktrees" / run.run_id
        plans: list[tuple[Task, str, Path]] = []

        self.adapter.workspace_provider = provider
        try:
            try:
                for task in wave:
                    branch = f"pf/{run.run_id}/{task.id}"
                    worktree = worktrees_root / task.id
                    worktree.parent.mkdir(parents=True, exist_ok=True)
                    mgr.create(branch, worktree, base=base_head)
                    provider.bind(task.id, worktree)
                    task.status = TaskStatus.IN_PROGRESS
                    plans.append((task, branch, worktree))
            except WorktreeError:
                for task, branch, worktree in plans:
                    mgr.remove(worktree, branch)
                    provider.unbind(task.id)
                    task.status = TaskStatus.PENDING
                return False

            def work(entry: tuple[Task, str, Path]) -> _WaveOutcome:
                task, branch, worktree = entry
                contract = self._build_contract(task, project_map, run_dir=worktree)
                started_at = self._now()
                try:
                    execution_result = self.adapter.execute(contract, project_map)
                except Exception as exc:
                    return _WaveOutcome(task, branch, worktree, contract, None, None,
                                        TaskStatus.FAILED, started_at, self._now(), str(exc))
                if execution_result.status != "IMPLEMENTED":
                    failed = execution_result.status in {"FAILED", "ERROR", "TIMEOUT"}
                    return _WaveOutcome(
                        task, branch, worktree, contract, execution_result, None,
                        TaskStatus.FAILED if failed else TaskStatus.BLOCKED, started_at, self._now(), "",
                    )
                deterministic = self.validator.validate(task.id, contract, execution_result, workspace=worktree)
                validation_result, _feedback = self.aggregation.aggregate(contract, execution_result, deterministic)
                if validation_result.status == ValidationStatus.PASS:
                    status = TaskStatus.DONE
                elif validation_result.status == ValidationStatus.FAIL:
                    status = TaskStatus.FAILED
                else:
                    status = TaskStatus.BLOCKED
                return _WaveOutcome(
                    task, branch, worktree, contract, execution_result, validation_result,
                    status, started_at, self._now(), "",
                )

            workers = max(1, min(self.max_parallel_workers or len(plans), len(plans)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                outcomes = list(pool.map(work, plans))
        finally:
            self.adapter.workspace_provider = original_provider

        # Phase 1: merge every branch that validated in isolation back into the
        # shared workspace. A conflict is a real failure even though the task
        # passed alone. Worktrees are reclaimed here; run_dir now holds the
        # integrated tree. Records are finalized later so re-validation can see
        # every sibling's merge.
        for outcome in outcomes:
            task = outcome.task
            if outcome.status == TaskStatus.DONE:
                merge = mgr.merge(outcome.branch)
                if merge.ok:
                    if (
                        artifact_store is not None
                        and outcome.execution_result is not None
                        and outcome.execution_result.git_checkpoint is not None
                    ):
                        artifact_store.save(
                            Artifact(
                                artifact_id=self._unique_artifact_id(task.id, "git"),
                                task_id=task.id,
                                artifact_type=ArtifactType.GIT_CHECKPOINT,
                                created_at=self._now(),
                                metadata=list(outcome.execution_result.git_checkpoint.changed_files or []),
                            ),
                            json.dumps(outcome.execution_result.git_checkpoint.model_dump(), ensure_ascii=False, indent=2),
                        )
                else:
                    outcome.status = TaskStatus.FAILED
                    outcome.validation_result = self._merge_conflict_result(
                        outcome.validation_result, task.id, merge.conflicted_files
                    )
                    if artifact_store is not None:
                        artifact_store.save(
                            Artifact(
                                artifact_id=self._unique_artifact_id(task.id, "conflict"),
                                task_id=task.id,
                                artifact_type=ArtifactType.ERROR_LOG,
                                created_at=self._now(),
                                metadata=["MERGE_CONFLICT", *merge.conflicted_files],
                            ),
                            json.dumps({"conflicted_files": merge.conflicted_files}, ensure_ascii=False, indent=2),
                        )
            mgr.remove(outcome.worktree, outcome.branch)
            provider.unbind(task.id)

        # Phase 2: re-validate merged tasks against the *integrated* workspace.
        # Each branch only proved its own tests against base_head in isolation;
        # a sibling's change — or the combination — can still break them. This
        # is what serial gets implicitly (later validations run on cumulative
        # state) and the parallel path must do explicitly after the merge.
        for outcome in outcomes:
            if outcome.status != TaskStatus.DONE or outcome.execution_result is None:
                continue
            integrated_contract = self._build_contract(outcome.task, project_map, run_dir=run_dir)
            integrated = self.validator.validate(
                outcome.task.id, integrated_contract, outcome.execution_result, workspace=run_dir
            )
            if integrated.status == ValidationStatus.FAIL:
                outcome.status = TaskStatus.FAILED
                outcome.validation_result = self._post_merge_integration_result(
                    outcome.validation_result, outcome.task.id, integrated
                )
                if artifact_store is not None:
                    artifact_store.save(
                        Artifact(
                            artifact_id=self._unique_artifact_id(outcome.task.id, "integration"),
                            task_id=outcome.task.id,
                            artifact_type=ArtifactType.ERROR_LOG,
                            created_at=self._now(),
                            metadata=["POST_MERGE_INTEGRATION_FAIL"],
                        ),
                        json.dumps(integrated.model_dump(), ensure_ascii=False, indent=2),
                    )

        # Phase 3: finalize each outcome (status, record, persistence,
        # artifacts, replan) once its integration verdict is settled.
        for outcome in outcomes:
            task = outcome.task
            status = outcome.status
            task.status = status

            record = TaskExecutionRecord(
                task_id=task.id,
                phase=task.phase_id,
                title=task.title,
                status=status.value,
                contract=outcome.contract,
                execution_result=outcome.execution_result,
                validation_result=outcome.validation_result,
                started_at=outcome.started_at,
                finished_at=outcome.finished_at,
            )
            run.task_results.append(record)
            if self.persistence is not None:
                self.persistence.save_task_record(run.run_id, record)

            if artifact_store is not None and outcome.execution_result is not None and status != TaskStatus.DONE:
                artifact_store.save(
                    Artifact(
                        artifact_id=self._unique_artifact_id(task.id, "output"),
                        task_id=task.id,
                        artifact_type=ArtifactType.AGENT_OUTPUT,
                        created_at=self._now(),
                        metadata=[outcome.execution_result.status],
                    ),
                    json.dumps(outcome.execution_result.model_dump(), ensure_ascii=False, indent=2),
                )
            if artifact_store is not None and outcome.validation_result is not None:
                artifact_store.save(
                    Artifact(
                        artifact_id=self._unique_artifact_id(task.id, "validation"),
                        task_id=task.id,
                        artifact_type=ArtifactType.VALIDATION_RESULT,
                        created_at=self._now(),
                        metadata=[outcome.validation_result.status.value],
                    ),
                    json.dumps(outcome.validation_result.model_dump(), ensure_ascii=False, indent=2),
                )

            if status == TaskStatus.FAILED and self._replan_enabled():
                self._maybe_generate_replan(run, task, task_graph, outcome.contract, outcome.execution_result, outcome.validation_result)

        run.current_task_id = ""
        return True

    def _merge_conflict_result(
        self, base: ValidationResult | None, task_id: str, conflicted_files: list[str]
    ) -> ValidationResult:
        """Stamp a wave task's validation as FAIL for a merge conflict.

        The task validated cleanly in isolation; the conflict only surfaces when
        its branch merges back. This rewrites the result to FAIL with the
        conflicted files as evidence while keeping the original criterion
        history, so both the persisted record and the replan analyzer see the
        real reason instead of a stale PASS.
        """
        files = list(conflicted_files)
        evidence = "parallel merge conflict in: " + (", ".join(files) if files else "unknown paths")
        if base is not None:
            result = base.model_copy(deep=True)
        else:
            result = ValidationResult(task_id=task_id, status=ValidationStatus.FAIL)
        result.task_id = result.task_id or task_id
        result.status = ValidationStatus.FAIL
        result.criterion_results.append(
            CriterionResult(
                criterion="Concurrent branch merges cleanly back to the shared workspace",
                type=CriterionType.GIT,
                status=CriterionStatus.FAIL,
                evidence=evidence,
                details="Task validated in isolation; failure arose from merging its worktree branch.",
            )
        )
        result.changed_files = list(dict.fromkeys([*result.changed_files, *files]))
        result.evidence.append(evidence)
        result.failures.append(evidence)
        return result

    def _post_merge_integration_result(
        self, base: ValidationResult | None, task_id: str, integrated: ValidationResult
    ) -> ValidationResult:
        """Stamp a wave task's validation as FAIL for a post-merge break.

        The task validated cleanly in its own worktree, but re-running its
        checks against the integrated workspace (after every sibling branch
        merged back) failed. Keep the isolation-passed criteria and append the
        integration failure so the record and replan analyzer see the real
        reason. The passed-in ``base`` is deep-copied, never mutated.
        """
        if base is not None:
            result = base.model_copy(deep=True)
        else:
            result = ValidationResult(task_id=task_id, status=ValidationStatus.FAIL)
        result.task_id = result.task_id or task_id
        result.status = ValidationStatus.FAIL
        detail = "; ".join(integrated.failures[:3]) if integrated.failures else "validation failed after merge"
        evidence = (
            "passed in isolation but failed validation against the integrated workspace: "
            + detail
        )
        result.criterion_results.append(
            CriterionResult(
                criterion="Merged task still passes validation against the integrated workspace",
                type=CriterionType.TEST,
                status=CriterionStatus.FAIL,
                evidence=evidence,
                details="Validated cleanly in its own worktree; failure surfaced only after merging into the shared workspace.",
            )
        )
        result.changed_files = list(dict.fromkeys([*result.changed_files, *(integrated.changed_files or [])]))
        result.evidence.append(evidence)
        result.failures.append(evidence)
        return result

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

    def _is_over_budget(self, started: float) -> bool:
        if self.max_run_seconds is None:
            return False
        return (time.monotonic() - started) >= self.max_run_seconds

    @staticmethod
    def _git_head(run_dir: Path | None) -> str:
        """Current workspace HEAD, or "" when unavailable (no git / no commits)."""
        import subprocess

        if run_dir is None:
            return ""
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(run_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            if proc.returncode != 0:
                return ""
            return proc.stdout.decode("utf-8", "replace").strip()
        except Exception:
            return ""

    def _rollback_workspace(self, run_dir: Path | None, head_before: str) -> None:
        """Return the workspace to its pre-task state after a failure.

        Best-effort and never raises: a git-less workspace simply keeps its dirty
        state. Untracked files are removed so the next task does not build on a
        half-finished attempt — except ``artifacts/``, which holds audit data and
        may legitimately live inside the workspace.
        """
        import subprocess

        if run_dir is None or not head_before:
            return
        try:
            subprocess.run(
                ["git", "reset", "--hard", head_before],
                cwd=str(run_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            subprocess.run(
                ["git", "clean", "-fd", "-e", "artifacts"],
                cwd=str(run_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
        except Exception:
            return

    def _maybe_rollback(self, run_dir: Path | None, head_before: str, task_status: TaskStatus) -> None:
        """Discard a failed task's partial work when rollback is enabled."""
        if self.rollback_on_failure and task_status == TaskStatus.FAILED:
            self._rollback_workspace(run_dir, head_before)

    @staticmethod
    def _unique_artifact_id(task_id: str, kind: str) -> str:
        # ⑥d: artifact ids used to be deterministic (`{task_id}_output`), so a
        # retry overwrote the previous attempt's artifact and the history was
        # lost. A short random suffix keeps the `{task_id}_` prefix (still matched
        # by ArtifactStore.list_for_task) while making each attempt distinct.
        return f"{task_id}_{kind}_{secrets.token_hex(4)}"

    def _build_contract(self, task: Task, project_map: ProjectMap, run_dir: Path | None = None) -> TaskContract:
        # Scope resolution has three cases:
        #   1. the task declared usable paths -> enforce them (+ shared files)
        #   2. the task declared paths we cannot trust -> leave the list empty,
        #      which the scope policy reports as NEEDS_REVIEW (never a false
        #      violation)
        #   3. the task declared nothing -> historical behaviour: the workspace
        #      root is the only boundary
        from app.agents.scope_policy import normalize_declared_paths, shared_paths_for
        from app.schemas.implementation import AllowedTestAction

        declared = normalize_declared_paths(list(task.allowed_paths), run_dir)
        if declared:
            allowed_paths = declared + shared_paths_for(run_dir)
        elif task.allowed_paths:
            allowed_paths = []
        else:
            allowed_paths = [str(Path(run_dir).resolve())] if run_dir is not None else []

        test_scope = (
            [AllowedTestAction.ADD_TEST, AllowedTestAction.MODIFY_RELEVANT_TEST]
            if task.test_paths
            else []
        )
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
            allowed_paths=allowed_paths,
            test_paths=list(task.test_paths),
            test_command=task.test_command,
            test_scope=test_scope,
            execution_rules=[],
        )

    def _blocking_reason(self, task_graph: TaskGraph) -> str:
        pending = [t for t in task_graph.tasks if t.status == TaskStatus.PENDING]
        if pending:
            return "no executable task remains; unresolved dependency chain"
        return "execution stopped"

    def _ensure_git_baseline(self, run_dir: Path) -> None:
        """Make the workspace auditable: when it is not its own git
        repository, initialise one and commit a baseline so adapters can
        capture real checkpoints. Never raises — a git-less host only
        loses auditability.

        The workspace must own its repository. A run dir merely nested
        inside an unrelated parent repository (e.g. a workspace under a
        checked-out source tree) must NOT reuse that parent: committing
        task artifacts there would pollute the host repo's history and
        make the per-task checkpoint diff span unrelated files.
        """
        import subprocess

        def _git(args: list[str], check: bool = False) -> subprocess.CompletedProcess:
            return subprocess.run(
                ["git", *args],
                cwd=str(run_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                check=check,
            )

        try:
            run_dir_resolved = Path(run_dir).resolve()
            toplevel = _git(["rev-parse", "--show-toplevel"])
            if toplevel.returncode != 0:
                # Not inside any repository — safe to create our own.
                _git(["init", "-q"], check=True)
            elif Path(toplevel.stdout.decode("utf-8", "replace").strip()).resolve() != run_dir_resolved:
                # Nested inside a foreign repository: detach by creating a
                # nested, self-contained repo owned by the workspace.
                _git(["init", "-q"], check=True)

            head = _git(["rev-parse", "HEAD"])
            if head.returncode == 0:
                return  # existing repo with commits: leave dirty state untouched

            for key, value in (("user.name", "ProjectForge"), ("user.email", "projectforge@local")):
                if _git(["config", key]).returncode != 0:
                    _git(["config", key, value], check=True)
            _git(["add", "-A"], check=True)
            _git(["commit", "-q", "-m", "projectforge baseline", "--allow-empty"], check=True)
        except Exception:
            return

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _run_id(task_graph: TaskGraph) -> str:
        return f"run-{task_graph.project}-{abs(hash(str([t.id for t in task_graph.tasks])))}"

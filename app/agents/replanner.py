from __future__ import annotations

import uuid
from typing import Any

from app.schemas.execution import ExecutionRun
from app.schemas.replan import FailureAnalysis, ReplanAction, ReplanChange, ReplanChangeType, ReplanProposal, ReplanProposalStatus, RecommendedAction
from app.schemas.task import Task, TaskGraph


class Replanner:
    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    def propose(
        self,
        run: ExecutionRun,
        task_graph: TaskGraph,
        failure_analysis: FailureAnalysis,
        attempt_counts: dict[str, int] | None = None,
    ) -> ReplanProposal | None:
        attempt_counts = attempt_counts or {}
        proposal_id = f"proposal-{failure_analysis.task_id}-{uuid.uuid4().hex[:8]}"
        affected = [failure_analysis.task_id]
        changes: list[ReplanChange] = []

        if failure_analysis.recommended_action == RecommendedAction.RETRY and attempt_counts.get(failure_analysis.task_id, 0) < self.max_retries:
            return ReplanProposal(
                proposal_id=proposal_id,
                run_id=run.run_id,
                task_id=failure_analysis.task_id,
                action=ReplanAction.RETRY,
                reason=failure_analysis.root_cause_hypothesis,
                evidence=failure_analysis.evidence,
                affected_task_ids=affected,
                proposed_changes=[ReplanChange(change_type=ReplanChangeType.RETRY_TASK, task_id=failure_analysis.task_id, target_task_id=failure_analysis.task_id, title="Retry task", description="Retry task execution.")],
                forbidden_changes=["MODIFY_BLUEPRINT", "MODIFY_ARCHITECTURE", "DELETE_DONE_TASK", "REWRITE_PROJECT"],
                requires_user_approval=True,
                status=ReplanProposalStatus.PROPOSED,
                created_at="",
            )

        if failure_analysis.recommended_action == RecommendedAction.SPLIT:
            task = next((t for t in task_graph.tasks if t.id == failure_analysis.task_id), None)
            if task is None:
                return None
            new_ids = [f"{task.id}a", f"{task.id}b"]
            affected.extend(new_ids)
            return ReplanProposal(
                proposal_id=proposal_id,
                run_id=run.run_id,
                task_id=failure_analysis.task_id,
                action=ReplanAction.SPLIT,
                reason=failure_analysis.root_cause_hypothesis,
                evidence=failure_analysis.evidence,
                affected_task_ids=affected,
                proposed_changes=[
                    ReplanChange(change_type=ReplanChangeType.ADD_TASK, task_id=task.id, target_task_id=new_ids[0], title=task.title + " (a)", description=task.goal + " split part a."),
                    ReplanChange(change_type=ReplanChangeType.ADD_TASK, task_id=task.id, target_task_id=new_ids[1], title=task.title + " (b)", description=task.goal + " split part b."),
                ],
                forbidden_changes=["MODIFY_BLUEPRINT", "MODIFY_ARCHITECTURE", "DELETE_DONE_TASK", "REWRITE_PROJECT"],
                requires_user_approval=True,
                status=ReplanProposalStatus.PROPOSED,
                created_at="",
            )

        return ReplanProposal(
            proposal_id=proposal_id,
            run_id=run.run_id,
            task_id=failure_analysis.task_id,
            action=ReplanAction.BLOCK,
            reason=failure_analysis.root_cause_hypothesis,
            evidence=failure_analysis.evidence,
            affected_task_ids=affected,
            proposed_changes=[ReplanChange(change_type="BLOCK_TASK", task_id=failure_analysis.task_id, target_task_id=failure_analysis.task_id, title="Block task", description="Block task until user intervention.")],
            forbidden_changes=["MODIFY_BLUEPRINT", "MODIFY_ARCHITECTURE", "DELETE_DONE_TASK", "REWRITE_PROJECT"],
            requires_user_approval=True,
            status=ReplanProposalStatus.PROPOSED,
            created_at="",
        )

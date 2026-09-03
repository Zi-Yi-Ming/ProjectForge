from __future__ import annotations

from typing import Any

from app.agents.replan_applier import ReplanApplier
from app.schemas.replan import ReplanProposal, ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus


class ProductReplanApplier(ReplanApplier):
    def apply(self, proposal: ReplanProposal, task_graph: TaskGraph) -> Any:
        if proposal.status != ReplanProposalStatus.APPROVED:
            return self._build_result(False, proposal.proposal_id, [], ["Proposal must be APPROVED; current status={}".format(proposal.status.value)])
        failures = self._product_validate_proposal(proposal, task_graph)
        if failures:
            return self._build_result(False, proposal.proposal_id, [], failures)
        task_map = {t.id: t for t in task_graph.tasks}
        applied_changes: list[Any] = []

        if proposal.action == "RETRY":
            task = task_map[proposal.task_id]
            if task.status == TaskStatus.FAILED:
                task.status = TaskStatus.PENDING
            applied_changes = list(proposal.proposed_changes)
        elif proposal.action == "SPLIT":
            failed_task = task_map[proposal.task_id]
            if failed_task.status == TaskStatus.DONE:
                return self._build_result(False, proposal.proposal_id, [], ["Cannot split DONE task."])
            failed_task.status = TaskStatus.BLOCKED
            new_ids = [c.target_task_id for c in proposal.proposed_changes if c.change_type == "ADD_TASK"]
            for new_id in new_ids:
                if new_id in task_map:
                    return self._build_result(False, proposal.proposal_id, [], ["Duplicate task id: {}".format(new_id)])
            for change in proposal.proposed_changes:
                if change.change_type == "ADD_TASK":
                    new_task = Task(
                        id=change.target_task_id,
                        phase_id=failed_task.phase_id,
                        title=change.title,
                        goal=failed_task.goal,
                        why=failed_task.why,
                        dependencies=list(failed_task.dependencies),
                        scope=failed_task.scope,
                        prerequisites=list(failed_task.prerequisites),
                        inputs=list(failed_task.inputs),
                        expected_output=failed_task.expected_output,
                        implementation_scope=failed_task.implementation_scope,
                        acceptance_criteria=list(failed_task.acceptance_criteria),
                        out_of_scope=list(failed_task.out_of_scope),
                        technical_points=list(failed_task.technical_points),
                        interview_points=list(failed_task.interview_points),
                        status=TaskStatus.PENDING,
                    )
                    task_graph.tasks.append(new_task)
                    applied_changes.append(change)
            task_graph.total_tasks = len(task_graph.tasks)
        elif proposal.action == "ADD_DEPENDENCY":
            target_id = proposal.proposed_changes[0].target_task_id if proposal.proposed_changes else proposal.task_id
            target = task_map.get(target_id)
            if target is None:
                return self._build_result(False, proposal.proposal_id, [], ["Target task not found: {}".format(target_id)])
            if target.status == TaskStatus.DONE:
                return self._build_result(False, proposal.proposal_id, [], ["Cannot modify DONE task dependencies."])
            new_dep = proposal.proposed_changes[0].task_id
            if new_dep not in target.dependencies:
                target.dependencies.append(new_dep)
            applied_changes = list(proposal.proposed_changes)
        elif proposal.action == "BLOCK":
            task = task_map[proposal.task_id]
            if task.status == TaskStatus.DONE:
                return self._build_result(False, proposal.proposal_id, [], ["Cannot block DONE task."])
            task.status = TaskStatus.BLOCKED
            applied_changes = list(proposal.proposed_changes)
        else:
            return self._build_result(False, proposal.proposal_id, [], ["Unknown action: {}".format(proposal.action)])

        validation = self._validate_task_graph(task_graph)
        if not validation.valid:
            return self._build_result(False, proposal.proposal_id, [], ["Post-apply DAG validation failed."])
        return self._build_result(True, proposal.proposal_id, applied_changes, [])

    def _product_validate_proposal(self, proposal: ReplanProposal, task_graph: TaskGraph) -> list[str]:
        task_map = {t.id: t for t in task_graph.tasks}
        if proposal.task_id not in task_map:
            return ["Task not found: {}".format(proposal.task_id)]
        for affected_id in proposal.affected_task_ids:
            if affected_id not in task_map and affected_id not in [c.target_task_id for c in proposal.proposed_changes]:
                return ["Affected task not found: {}".format(affected_id)]
        for change in proposal.proposed_changes:
            if change.change_type == "ADD_TASK":
                if change.target_task_id in task_map:
                    return ["Duplicate new task id: {}".format(change.target_task_id)]
            if change.change_type == "ADD_DEPENDENCY":
                target = task_map.get(change.target_task_id)
                if target is None or target.status == TaskStatus.DONE:
                    return ["Cannot modify dependencies for DONE or missing task: {}".format(change.target_task_id)]
        if any(t.status == TaskStatus.DONE for t in task_graph.tasks if t.id in proposal.affected_task_ids and t.id != proposal.task_id):
            return ["Proposal affects DONE task."]
        return []

    @staticmethod
    def _build_result(success: bool, proposal_id: str, applied_changes: list[Any], failures: list[str]) -> Any:
        from app.schemas.replan import ReplanApplyResult
        return ReplanApplyResult(success=success, proposal_id=proposal_id, applied_changes=applied_changes, failures=failures, message="Replan applied successfully." if success else "Replan apply failed.")

from __future__ import annotations

import uuid
from typing import Any

from app.schemas.replan import ReplanAction, ReplanApplyResult, ReplanChange, ReplanProposal, ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskGraphValidation, TaskStatus


class ReplanApplier:
    def apply(self, proposal: ReplanProposal, task_graph: TaskGraph) -> ReplanApplyResult:
        failures = self._validate_proposal(proposal, task_graph)
        if failures:
            return ReplanApplyResult(success=False, proposal_id=proposal.proposal_id, failures=failures, message="Proposal validation failed.")

        task_map = {t.id: t for t in task_graph.tasks}
        applied_changes: list[ReplanChange] = []

        if proposal.action == ReplanAction.RETRY:
            task = task_map[proposal.task_id]
            if task.status == TaskStatus.FAILED:
                task.status = TaskStatus.PENDING
            applied_changes = list(proposal.proposed_changes)

        elif proposal.action == ReplanAction.SPLIT:
            failed_task = task_map[proposal.task_id]
            if failed_task.status == TaskStatus.DONE:
                return ReplanApplyResult(success=False, proposal_id=proposal.proposal_id, failures=["Cannot split DONE task."], message="DONE task immutable.")
            failed_task.status = TaskStatus.BLOCKED
            new_ids = [c.target_task_id for c in proposal.proposed_changes if c.change_type == "ADD_TASK"]
            for new_id in new_ids:
                if new_id in task_map:
                    return ReplanApplyResult(success=False, proposal_id=proposal.proposal_id, failures=[f"Duplicate task id: {new_id}"], message="New task id already exists.")
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

        elif proposal.action == ReplanAction.ADD_DEPENDENCY:
            target_id = proposal.proposed_changes[0].target_task_id if proposal.proposed_changes else proposal.task_id
            target = task_map.get(target_id)
            if target is None:
                return ReplanApplyResult(success=False, proposal_id=proposal.proposal_id, failures=[f"Target task not found: {target_id}"], message="Target task missing.")
            if target.status == TaskStatus.DONE:
                return ReplanApplyResult(success=False, proposal_id=proposal.proposal_id, failures=["Cannot modify DONE task dependencies."], message="DONE task immutable.")
            new_dep = proposal.proposed_changes[0].task_id
            if new_dep not in target.dependencies:
                target.dependencies.append(new_dep)
            applied_changes = list(proposal.proposed_changes)

        elif proposal.action == ReplanAction.BLOCK:
            task = task_map[proposal.task_id]
            if task.status == TaskStatus.DONE:
                return ReplanApplyResult(success=False, proposal_id=proposal.proposal_id, failures=["Cannot block DONE task."], message="DONE task immutable.")
            task.status = TaskStatus.BLOCKED
            applied_changes = list(proposal.proposed_changes)

        validation = self._validate_task_graph(task_graph)
        if not validation.valid:
            return ReplanApplyResult(success=False, proposal_id=proposal.proposal_id, failures=["Post-apply DAG validation failed."], message="DAG invalid after apply.")

        return ReplanApplyResult(success=True, proposal_id=proposal.proposal_id, applied_changes=applied_changes, message="Replan applied successfully.")

    def _validate_proposal(self, proposal: ReplanProposal, task_graph: TaskGraph) -> list[str]:
        if proposal.status != ReplanProposalStatus.APPROVED:
            return [f"Proposal must be APPROVED; current status={proposal.status.value}"]
        if proposal.requires_user_approval and proposal.status != ReplanProposalStatus.APPROVED:
            return ["Proposal requires user approval."]
        task_map = {t.id: t for t in task_graph.tasks}
        if proposal.task_id not in task_map:
            return [f"Task not found: {proposal.task_id}"]
        for affected_id in proposal.affected_task_ids:
            if affected_id not in task_map and affected_id not in [c.target_task_id for c in proposal.proposed_changes]:
                return [f"Affected task not found: {affected_id}"]
        for change in proposal.proposed_changes:
            if change.change_type == "ADD_TASK":
                if change.target_task_id in task_map:
                    return [f"Duplicate new task id: {change.target_task_id}"]
            if change.change_type == "ADD_DEPENDENCY":
                target = task_map.get(change.target_task_id)
                if target is None or target.status == TaskStatus.DONE:
                    return [f"Cannot modify dependencies for DONE or missing task: {change.target_task_id}"]
        if any(t.status == TaskStatus.DONE for t in task_graph.tasks if t.id in proposal.affected_task_ids and t.id != proposal.task_id):
            return ["Proposal affects DONE task."]
        forbidden = {"MODIFY_BLUEPRINT", "MODIFY_ARCHITECTURE", "DELETE_DONE_TASK", "REWRITE_PROJECT"}
        if any(f in forbidden for f in proposal.forbidden_changes):
            return ["Proposal requests forbidden changes."]
        return []

    def _validate_task_graph(self, task_graph: TaskGraph) -> TaskGraphValidation:
        in_degree = {t.id: 0 for t in task_graph.tasks}
        adjacency = {t.id: [] for t in task_graph.tasks}
        for task in task_graph.tasks:
            for dep in task.dependencies:
                if dep in adjacency:
                    adjacency[dep].append(task.id)
                    in_degree[task.id] += 1
        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        valid = len(order) == len(task_graph.tasks)
        return TaskGraphValidation(valid=valid, cycle_detected=not valid, topological_order=order, ready_tasks=[], blocked_tasks=[], total_tasks=task_graph.total_tasks, required_tasks=task_graph.required_tasks, optional_tasks=task_graph.optional_tasks)

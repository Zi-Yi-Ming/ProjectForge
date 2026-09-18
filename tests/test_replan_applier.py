from __future__ import annotations

import pytest

from app.agents.replan_applier import ReplanApplier
from app.schemas.replan import ReplanAction, ReplanProposal, ReplanProposalStatus, ReplanChange, ReplanChangeType
from app.schemas.task import Task, TaskGraph, TaskStatus


def _base_graph():
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], scope="Core", status=TaskStatus.DONE, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g", why="w", dependencies=["T1"], scope="Core", status=TaskStatus.FAILED, acceptance_criteria=[], out_of_scope=[]),
    ]
    return TaskGraph(project="demo", phases=[], tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


def _proposed(action, task_id="T2", target_task_id="T2"):
    return ReplanProposal(proposal_id="p1", run_id="run-1", task_id=task_id, action=action, status=ReplanProposalStatus.APPROVED, proposed_changes=[ReplanChange(change_type=ReplanChangeType.RETRY_TASK, task_id=task_id, target_task_id=target_task_id, title="", description="")])


def test_proposed_status_rejects_apply():
    applier = ReplanApplier()
    proposal = _proposed(ReplanAction.RETRY)
    proposal.status = ReplanProposalStatus.PROPOSED
    result = applier.apply(proposal, _base_graph())
    assert result.success is False


def test_approved_retry_apply():
    applier = ReplanApplier()
    proposal = _proposed(ReplanAction.RETRY)
    graph = _base_graph()
    result = applier.apply(proposal, graph)
    assert result.success is True
    assert graph.tasks[1].status == TaskStatus.PENDING


def test_modify_done_task_rejected():
    applier = ReplanApplier()
    proposal = _proposed(ReplanAction.BLOCK, task_id="T1", target_task_id="T1")
    proposal.status = ReplanProposalStatus.APPROVED
    result = applier.apply(proposal, _base_graph())
    assert result.success is False


def test_missing_task_rejected():
    applier = ReplanApplier()
    proposal = _proposed(ReplanAction.RETRY, task_id="T9", target_task_id="T9")
    proposal.status = ReplanProposalStatus.APPROVED
    result = applier.apply(proposal, _base_graph())
    assert result.success is False


def test_cycle_proposal_rejected():
    applier = ReplanApplier()
    proposal = ReplanProposal(proposal_id="p2", run_id="run-1", task_id="T2", action=ReplanAction.ADD_DEPENDENCY, status=ReplanProposalStatus.APPROVED, proposed_changes=[ReplanChange(change_type=ReplanChangeType.ADD_DEPENDENCY, task_id="T2", target_task_id="T1", title="", description="")])
    result = applier.apply(proposal, _base_graph())
    assert result.success is False


def test_apply_failure_does_not_mutate_graph():
    applier = ReplanApplier()
    proposal = _proposed(ReplanAction.RETRY)
    proposal.status = ReplanProposalStatus.PROPOSED
    graph = _base_graph()
    applier.apply(proposal, graph)
    assert graph.tasks[1].status == TaskStatus.FAILED


def test_standard_forbidden_changes_list_does_not_block_apply():
    # Replanner stamps every proposal with the "must not touch" guard list; that
    # is declarative metadata, not a request to perform those actions, so a
    # legitimate approved RETRY carrying it must still apply.
    applier = ReplanApplier()
    proposal = _proposed(ReplanAction.RETRY)
    proposal.forbidden_changes = ["MODIFY_BLUEPRINT", "MODIFY_ARCHITECTURE", "DELETE_DONE_TASK", "REWRITE_PROJECT"]
    proposal.requires_user_approval = True
    graph = _base_graph()
    result = applier.apply(proposal, graph)
    assert result.success is True
    assert graph.tasks[1].status == TaskStatus.PENDING


def _split_graph():
    parent = Task(
        id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], scope="Core",
        status=TaskStatus.FAILED, acceptance_criteria=[], out_of_scope=[],
        test_command="pytest -q tests/unit", test_paths=["tests/unit"], allowed_paths=["src/app"],
    )
    return TaskGraph(project="demo", phases=[], tasks=[parent], total_tasks=1, required_tasks=1, optional_tasks=0)


def _split_proposal():
    return ReplanProposal(
        proposal_id="p-split", run_id="run-1", task_id="T1", action=ReplanAction.SPLIT,
        status=ReplanProposalStatus.APPROVED, affected_task_ids=["T1", "T1a", "T1b"],
        proposed_changes=[
            ReplanChange(change_type=ReplanChangeType.ADD_TASK, task_id="T1", target_task_id="T1a", title="T1 (a)", description="part a"),
            ReplanChange(change_type=ReplanChangeType.ADD_TASK, task_id="T1", target_task_id="T1b", title="T1 (b)", description="part b"),
        ],
    )


def test_split_children_inherit_test_and_scope_fields():
    applier = ReplanApplier()
    graph = _split_graph()
    result = applier.apply(_split_proposal(), graph)
    assert result.success is True

    parent = next(t for t in graph.tasks if t.id == "T1")
    children = [t for t in graph.tasks if t.id in {"T1a", "T1b"}]
    assert len(children) == 2
    for child in children:
        assert child.test_command == "pytest -q tests/unit"
        assert child.test_paths == ["tests/unit"]
        assert child.allowed_paths == ["src/app"]
    # independent copies, not shared mutable references to the parent's lists
    children[0].test_paths.append("extra")
    assert parent.test_paths == ["tests/unit"]

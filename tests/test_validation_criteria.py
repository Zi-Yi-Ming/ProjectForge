from __future__ import annotations

from pathlib import Path

from app.agents.replanner import Replanner
from app.product.replan_applier import ProductReplanApplier
from app.schemas.execution import ExecutionRun, ExecutionStatus as RunExecutionStatus
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)
from app.schemas.replan import (
    FailureAnalysis,
    FailureType,
    ReplanAction,
    RecommendedAction,
    ReplanProposalStatus,
    Recoverability,
)
from app.schemas.task import Task, TaskGraph, TaskStatus


def _contract(task_id: str, tmp_path: Path, test_paths: list[str], test_scope: list[str], criteria: list[str]) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        project="demo",
        phase="P1",
        title=task_id,
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="o",
        implementation_scope="s",
        acceptance_criteria=criteria,
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=[str(tmp_path)],
        test_paths=test_paths,
        test_command="",
        test_scope=test_scope,
        execution_rules=[],
    )


def _result(task_id: str, changed: list[str]) -> AgentExecutionResult:
    return AgentExecutionResult(
        task_id=task_id,
        agent="mock",
        status=ExecutionStatus.IMPLEMENTED,
        iterations=1,
        changed_files=changed,
        scope_status=ScopeStatus.WITHIN_SCOPE,
        test_results=[],
        summary="",
        errors=[],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(),
    )


def _graph() -> TaskGraph:
    return TaskGraph(
        project="demo",
        tasks=[Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", status=TaskStatus.FAILED, scope="Core")],
        total_tasks=1,
        required_tasks=1,
        optional_tasks=0,
    )


def _validator():
    from app.agents.validator import DeterministicValidator

    return DeterministicValidator()


def test_passing_self_test_defers_manual_criteria(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    contract = _contract("T1", tmp_path, ["tests"], ["ADD_TEST"], ["deliverable works"])
    result = _validator().validate("T1", contract, _result("T1", ["t1_impl.txt"]), workspace=tmp_path)
    assert result.status.value == "PASS"
    assert result.manual_review_items == ["deliverable works"]
    assert all(c.status.value != "NEEDS_REVIEW" for c in result.criterion_results)


def test_failing_self_test_hard_fails_and_keeps_criteria_blocking(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_bad.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    contract = _contract("T1", tmp_path, ["tests"], ["ADD_TEST"], ["deliverable works"])
    result = _validator().validate("T1", contract, _result("T1", ["t1_impl.txt"]), workspace=tmp_path)
    # A declared test suite that fails is a hard failure, not a review item.
    assert result.status.value == "FAIL"
    assert any(c.status.value == "NEEDS_REVIEW" and c.type.value == "MANUAL" for c in result.criterion_results)


def test_missing_test_scope_keeps_criteria_blocking(tmp_path: Path) -> None:
    contract = _contract("T1", tmp_path, [], [], ["deliverable works"])
    result = _validator().validate("T1", contract, _result("T1", ["t1_impl.txt"]), workspace=tmp_path)
    assert result.status.value == "NEEDS_REVIEW"


def test_relative_changed_file_matches_absolute_allowed_path(tmp_path: Path) -> None:
    contract = _contract("T1", tmp_path, [], [], [])
    result = _validator().validate("T1", contract, _result("T1", ["t1_impl.txt"]), workspace=tmp_path)
    assert result.scope_result == "WITHIN_SCOPE"


def _proposal(action: RecommendedAction, graph: TaskGraph):
    run = ExecutionRun(
        run_id="run-test",
        project="demo",
        status=RunExecutionStatus.RUNNING,
        total_tasks=len(graph.tasks),
        started_at="2026-01-01T00:00:00Z",
    )
    analysis = FailureAnalysis(
        task_id="T1",
        failure_type=FailureType.AGENT_FAILURE,
        root_cause_hypothesis="hypothesis",
        evidence=[],
        affected_scope="s",
        recoverability=Recoverability.RETRYABLE,
        recommended_action=action,
    )
    return Replanner().propose(run, graph, analysis, attempt_counts={"T1": 1})


def test_product_applier_applies_split_proposal() -> None:
    graph = _graph()
    proposal = _proposal(RecommendedAction.SPLIT, graph)
    assert proposal is not None and proposal.action == ReplanAction.SPLIT
    proposal.status = ReplanProposalStatus.APPROVED
    result = ProductReplanApplier().apply(proposal, graph)
    assert result.success
    ids = [t.id for t in graph.tasks]
    assert "T1a" in ids and "T1b" in ids
    assert graph.tasks[0].status == TaskStatus.BLOCKED
    assert graph.total_tasks == 3


def test_product_applier_applies_block_proposal() -> None:
    graph = _graph()
    proposal = _proposal(RecommendedAction.BLOCK, graph)
    assert proposal is not None and proposal.action == ReplanAction.BLOCK
    proposal.status = ReplanProposalStatus.APPROVED
    result = ProductReplanApplier().apply(proposal, graph)
    assert result.success
    assert graph.tasks[0].status == TaskStatus.BLOCKED


def test_product_applier_rejects_duplicate_split_ids() -> None:
    graph = _graph()
    graph.tasks.append(Task(id="T1a", phase_id="P1", title="dup", goal="g", why="w", status=TaskStatus.PENDING, scope="Core"))
    proposal = _proposal(RecommendedAction.SPLIT, graph)
    proposal.status = ReplanProposalStatus.APPROVED
    result = ProductReplanApplier().apply(proposal, graph)
    assert not result.success
    assert any("Duplicate" in f for f in result.failures)

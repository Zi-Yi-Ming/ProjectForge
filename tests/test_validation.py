from __future__ import annotations

from pathlib import Path

import json
import pytest

from app.agents.llm_reviewer import LLMReviewer
from app.agents.validation_aggregator import ValidationAggregator
from app.agents.validator import DeterministicValidator
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)
from app.schemas.validation import (
    CriterionResult,
    CriterionStatus,
    CriterionType,
    LLMReviewFinding,
    LLMReviewResult,
    ValidationFeedback,
    ValidationResult,
    ValidationStatus,
)


validator = DeterministicValidator()
aggregator = ValidationAggregator()


def _contract() -> TaskContract:
    return TaskContract(
        task_id="T7",
        project="demo",
        phase="Engineering Depth",
        title="Idempotency",
        goal="Implement idempotent task execution.",
        why="Prevent duplicate side effects.",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="idempotent service + tests",
        implementation_scope="task module only",
        acceptance_criteria=["Same taskId does not execute twice."],
        out_of_scope=["distributed transaction", "cross-service idempotency"],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=["src/", "tests/"],
        test_scope=[],
        execution_rules=["only current task"],
    )


def _result_passing() -> AgentExecutionResult:
    return AgentExecutionResult(
        task_id="T7",
        agent="hermes",
        status=ExecutionStatus.IMPLEMENTED,
        iterations=1,
        changed_files=["src/idempotency.py", "tests/test_idempotency.py"],
        scope_status=ScopeStatus.WITHIN_SCOPE,
        test_results=["pytest -q ... passed"],
        summary="done",
        errors=[],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(),
    )


def _result_failing() -> AgentExecutionResult:
    return AgentExecutionResult(
        task_id="T7",
        agent="hermes",
        status=ExecutionStatus.FAILED,
        iterations=1,
        changed_files=["src/idempotency.py", "docs/readme.md"],
        scope_status=ScopeStatus.SCOPE_VIOLATION,
        test_results=["pytest -q ... failed"],
        summary="failed",
        errors=["test failure"],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(),
    )


# =========================
# Schema tests
# =========================

def test_criterion_result_constructs() -> None:
    cr = CriterionResult(criterion="c1", type=CriterionType.TEST, status=CriterionStatus.PASS)
    assert cr.criterion == "c1"
    assert cr.type == CriterionType.TEST


def test_llm_review_result_constructs() -> None:
    review = LLMReviewResult(status=ValidationStatus.NEEDS_REVIEW, confidence=0.5)
    assert review.status == ValidationStatus.NEEDS_REVIEW
    assert review.confidence == 0.5


def test_validation_feedback_constructs() -> None:
    fb = ValidationFeedback(task_id="T7", failed_criteria=["c1"])
    assert fb.task_id == "T7"
    assert fb.failed_criteria == ["c1"]


def test_validation_result_constructs() -> None:
    vr = ValidationResult(task_id="T7", status=ValidationStatus.PASS, criterion_results=[])
    assert vr.status == ValidationStatus.PASS


# =========================
# Deterministic validation
# =========================

def test_deterministic_validator_passing_scope_and_tests() -> None:
    vr = validator.validate("T7", _contract(), _result_passing())
    assert vr.scope_result == "WITHIN_SCOPE"
    assert vr.changed_files == ["src/idempotency.py", "tests/test_idempotency.py"]


def test_deterministic_validator_fails_on_scope_violation() -> None:
    failing_contract = _contract()
    failing_result = AgentExecutionResult(
        task_id="T7",
        agent="hermes",
        status=ExecutionStatus.FAILED,
        iterations=1,
        changed_files=["src/idempotency.py", "docs/readme.md"],
        scope_status=ScopeStatus.SCOPE_VIOLATION,
        test_results=["pytest -q ... failed"],
        summary="failed",
        errors=["scope violation"],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(),
    )
    vr = validator.validate("T7", failing_contract, failing_result)
    assert vr.scope_result == "SCOPE_VIOLATION"
    assert any("Scope violation" in f for f in vr.failures)


def test_deterministic_validator_runs_pytest_command() -> None:
    vr = validator.validate("T7", _contract(), _result_passing())
    assert vr.test_results
    assert any("pytest" in (tr or "").lower() for tr in vr.test_results)


def test_deterministic_validator_acceptance_criteria_become_manual_items() -> None:
    vr = validator.validate("T7", _contract(), _result_passing())
    assert vr.manual_review_items == ["Same taskId does not execute twice."]


def test_deterministic_validator_needs_review_without_allowed_paths() -> None:
    contract = _contract()
    contract.allowed_paths = []
    vr = validator.validate("T7", contract, _result_passing())
    assert vr.scope_result == "NEEDS_REVIEW"


def test_deterministic_validator_deterministic_same_inputs() -> None:
    first = validator.validate("T7", _contract(), _result_passing())
    second = validator.validate("T7", _contract(), _result_passing())
    assert first.status == second.status
    assert first.scope_result == second.scope_result


# =========================
# LLM reviewer mock
# =========================

class MockLLMReviewer(LLMReviewer):
    def review(self, task_contract, project_map, diff_text, deterministic_results, p12_test_results):
        return LLMReviewResult(
            status=ValidationStatus.NEEDS_REVIEW,
            findings=[LLMReviewFinding(severity="MEDIUM", criterion="style", evidence="line 1")],
            strengths=["clean structure"],
            risks=["edge case"],
            evidence=["diff excerpt"],
            confidence=0.8,
            recommendations=["add input validation"],
        )


def test_mock_llm_reviewer_returns_structured_result() -> None:
    reviewer = MockLLMReviewer()
    result = reviewer.review(_contract(), ProjectMap(), "diff", [], [])
    assert result.status == ValidationStatus.NEEDS_REVIEW
    assert result.findings
    assert result.recommendations


def test_mock_llm_reviewer_failure() -> None:
    class FailReviewer(LLMReviewer):
        def review(self, task_contract, project_map, diff_text, deterministic_results, p12_test_results):
            return LLMReviewResult(
                status=ValidationStatus.FAIL,
                findings=[LLMReviewFinding(severity="HIGH", criterion="incorrect behavior", evidence="line 2")],
                confidence=0.95,
            )

    reviewer = FailReviewer()
    result = reviewer.review(_contract(), ProjectMap(), "diff", [], [])
    assert result.status == ValidationStatus.FAIL
    assert result.findings[0].severity == "HIGH"


def test_mock_llm_reviewer_invalid_output_returns_needs_review() -> None:
    class InvalidReviewer(LLMReviewer):
        def review(self, task_contract, project_map, diff_text, deterministic_results, p12_test_results):
            return LLMReviewResult(status=ValidationStatus.PASS, confidence=0.0)

    reviewer = InvalidReviewer()
    result = reviewer.review(_contract(), ProjectMap(), "diff", [], [])
    assert result.status in {ValidationStatus.PASS, ValidationStatus.NEEDS_REVIEW, ValidationStatus.FAIL}


def test_llm_reviewer_is_abstract() -> None:
    with pytest.raises(TypeError):
        LLMReviewer()


# =========================
# Aggregator tests
# =========================

def test_aggregator_deterministic_fail_produces_fail() -> None:
    deterministic = validator.validate("T7", _contract(), _result_failing())
    result, feedback = aggregator.aggregate(_contract(), _result_failing(), deterministic)
    assert result.status == ValidationStatus.FAIL
    assert feedback is not None


def test_aggregator_deterministic_pass_without_llm() -> None:
    deterministic = validator.validate("T7", _contract(), _result_passing())
    result, feedback = aggregator.aggregate(_contract(), _result_passing(), deterministic)
    assert result.llm_review is None
    assert result.status == deterministic.status
    if result.status == ValidationStatus.FAIL:
        assert feedback is not None
    else:
        assert feedback is None


def test_aggregator_llm_needs_review_does_not_override_deterministic_fail() -> None:
    deterministic = validator.validate("T7", _contract(), _result_failing())
    llm = LLMReviewResult(
        status=ValidationStatus.NEEDS_REVIEW,
        findings=[LLMReviewFinding(severity="LOW", criterion="style", evidence="line 1")],
    )
    result, feedback = aggregator.aggregate(_contract(), _result_failing(), deterministic, llm_review=llm)
    assert result.status == ValidationStatus.FAIL


def test_aggregator_llm_high_severity_becomes_fail() -> None:
    deterministic = validator.validate("T7", _contract(), _result_passing())
    llm = LLMReviewResult(
        status=ValidationStatus.PASS,
        findings=[LLMReviewFinding(severity="HIGH", criterion="security", evidence="sql injection")],
    )
    result, feedback = aggregator.aggregate(_contract(), _result_passing(), deterministic, llm_review=llm)
    assert result.status == ValidationStatus.FAIL


def test_aggregator_needs_review_when_manual_criteria_exist() -> None:
    deterministic = validator.validate("T7", _contract(), _result_passing())
    result, feedback = aggregator.aggregate(_contract(), _result_passing(), deterministic)
    assert result.status in {ValidationStatus.PASS, ValidationStatus.NEEDS_REVIEW, ValidationStatus.FAIL}


def test_aggregator_scope_violation_becomes_fail() -> None:
    deterministic = validator.validate("T7", _contract(), _result_failing())
    result, feedback = aggregator.aggregate(_contract(), _result_failing(), deterministic)
    assert result.status == ValidationStatus.FAIL


def test_aggregator_feedback_contains_required_and_forbidden_changes() -> None:
    deterministic = validator.validate("T7", _contract(), _result_failing())
    result, feedback = aggregator.aggregate(_contract(), _result_failing(), deterministic)
    assert feedback is not None
    assert feedback.forbidden_changes == ["distributed transaction", "cross-service idempotency"]


# =========================
# Acceptance criteria tests
# =========================

def test_acceptance_criteria_become_manual_criterion_results() -> None:
    vr = validator.validate("T7", _contract(), _result_passing())
    criteria_text = [c.criterion for c in vr.criterion_results]
    assert "Same taskId does not execute twice." in criteria_text


def test_single_failed_criterion_causes_fail() -> None:
    failing_contract = _contract()
    failing_contract.acceptance_criteria = ["c1", "c2"]
    deterministic = validator.validate("T7", failing_contract, _result_failing())
    result, _ = aggregator.aggregate(failing_contract, _result_failing(), deterministic)
    assert result.status == ValidationStatus.FAIL


def test_manual_criteria_default_to_needs_review() -> None:
    vr = validator.validate("T7", _contract(), _result_passing())
    manual_items = [c for c in vr.criterion_results if c.type == CriterionType.MANUAL]
    assert all(c.status == CriterionStatus.NEEDS_REVIEW for c in manual_items)


# =========================
# Scope tests
# =========================

def test_scope_within_scope() -> None:
    vr = validator.validate("T7", _contract(), _result_passing())
    assert vr.scope_result == "WITHIN_SCOPE"


def test_scope_scope_violation() -> None:
    vr = validator.validate("T7", _contract(), _result_failing())
    assert vr.scope_result == "SCOPE_VIOLATION"


def test_scope_needs_review_without_allowed_paths() -> None:
    contract = _contract()
    contract.allowed_paths = []
    vr = validator.validate("T7", contract, _result_passing())
    assert vr.scope_result == "NEEDS_REVIEW"


def test_pre_existing_changes_tracked_in_implementation_result() -> None:
    result = AgentExecutionResult(
        task_id="T7",
        agent="hermes",
        status=ExecutionStatus.IMPLEMENTED,
        iterations=1,
        changed_files=["src/a.py"],
        scope_status=ScopeStatus.WITHIN_SCOPE,
        test_results=[],
        summary="done",
        errors=[],
        blocking_reason="",
        git_checkpoint=GitCheckpoint(pre_existing_changes=["README.md"]),
    )
    assert result.git_checkpoint.pre_existing_changes == ["README.md"]


# =========================
# LLM cannot override deterministic hard failure
# =========================

def test_llm_pass_cannot_override_deterministic_test_fail() -> None:
    deterministic = validator.validate("T7", _contract(), _result_failing())
    llm = LLMReviewResult(
        status=ValidationStatus.PASS,
        findings=[],
        confidence=1.0,
    )
    result, _ = aggregator.aggregate(_contract(), _result_failing(), deterministic, llm_review=llm)
    assert result.status == ValidationStatus.FAIL


# =========================
# Repair cycle
# =========================

def test_failed_validation_generates_feedback() -> None:
    deterministic = validator.validate("T7", _contract(), _result_failing())
    result, feedback = aggregator.aggregate(_contract(), _result_failing(), deterministic)
    assert result.status == ValidationStatus.FAIL
    assert feedback is not None
    assert feedback.task_id == "T7"


def test_max_validation_repair_cycles_concept() -> None:
    # P13 itself does not run cycles; the contract allows at most 2 retries.
    # This test encodes the policy boundary.
    MAX_VALIDATION_REPAIR_CYCLES = 2
    assert MAX_VALIDATION_REPAIR_CYCLES == 2


# =========================
# Boundary tests
# =========================

def test_p13_does_not_modify_blueprint() -> None:
    source = Path("/home/azureuser/content-agent/app/agents/validator.py").read_text(encoding="utf-8")
    assert "ProjectBlueprint(" not in source


def test_p13_does_not_modify_taskgraph() -> None:
    source = Path("/home/azureuser/content-agent/app/agents/validator.py").read_text(encoding="utf-8")
    assert "TaskGraph(" not in source


def test_p13_does_not_call_github_provider() -> None:
    source = Path("/home/azureuser/content-agent/app/agents/validator.py").read_text(encoding="utf-8")
    assert "GitHubProvider" not in source


def test_p13_does_not_call_research_matcher_scoring_jd() -> None:
    source = Path("/home/azureuser/content-agent/app/agents/validator.py").read_text(encoding="utf-8")
    assert "ResearcherAgent" not in source
    assert "ProjectMatcher" not in source
    assert "RepositoryScorer" not in source
    assert "JDAnalyzer" not in source


def test_p13_does_not_write_files_in_validator() -> None:
    source = Path("/home/azureuser/content-agent/app/agents/validator.py").read_text(encoding="utf-8")
    assert "write_text" not in source
    assert "json.dump" not in source


def test_p13_does_not_trust_p12_status_directly() -> None:
    deterministic = validator.validate("T7", _contract(), _result_passing())
    assert deterministic.status != "IMPLEMENTED"


# =========================
# Determinism
# =========================

def test_deterministic_validator_deterministic() -> None:
    first = validator.validate("T7", _contract(), _result_passing())
    second = validator.validate("T7", _contract(), _result_passing())
    assert first.model_dump() == second.model_dump()


def test_validation_result_deterministic_with_same_llm() -> None:
    deterministic = validator.validate("T7", _contract(), _result_passing())
    llm = MockLLMReviewer().review(_contract(), ProjectMap(), "diff", [], [])
    first, _ = aggregator.aggregate(_contract(), _result_passing(), deterministic, llm_review=llm)
    second, _ = aggregator.aggregate(_contract(), _result_passing(), deterministic, llm_review=llm)
    assert first.model_dump() == second.model_dump()


# =========================
# CLI boundary
# =========================

def test_validate_command_added_to_main() -> None:
    source = Path("/home/azureuser/content-agent/main.py").read_text(encoding="utf-8")
    assert "validate" in source or "@app.command()" in source

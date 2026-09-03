from __future__ import annotations

import pytest

from app.agents.failure_analyzer import FailureAnalyzer
from app.schemas.implementation import AgentExecutionResult, ExecutionStatus as AgentExecutionStatus, ScopeStatus
from app.schemas.replan import FailureType
from app.schemas.implementation import TaskContract
from app.schemas.validation import CriterionResult, CriterionStatus, CriterionType, ValidationResult, ValidationStatus


def _base_contract():
    return TaskContract(task_id="T1", project="demo", phase="P1", title="T1", goal="g", why="w", implementation_scope="Core", acceptance_criteria=[])


def _base_agent_result(status=AgentExecutionStatus.FAILED):
    return AgentExecutionResult(task_id="T1", agent="mock", status=status, scope_status=ScopeStatus.WITHIN_SCOPE)


def _validation_result(status=ValidationStatus.FAIL, scope_result="WITHIN_SCOPE", criterion_type=CriterionType.TEST, criterion_status=CriterionStatus.FAIL):
    return ValidationResult(
        task_id="T1",
        status=status,
        criterion_results=[CriterionResult(criterion="c", type=criterion_type, status=criterion_status, evidence="", details="")],
        test_results=[],
        scope_result=scope_result,
        changed_files=[],
        evidence=[],
        failures=[],
        warnings=[],
        manual_review_items=[],
        llm_review=None,
        repair_cycle=0,
    )


def test_test_failure_classification():
    analyzer = FailureAnalyzer()
    result = analyzer.analyze(_base_contract(), _base_agent_result(AgentExecutionStatus.FAILED), _validation_result(), [])
    assert result.failure_type == FailureType.TEST_FAILURE


def test_timeout_classification():
    analyzer = FailureAnalyzer()
    result = analyzer.analyze(_base_contract(), _base_agent_result(AgentExecutionStatus.TIMEOUT), _validation_result(ValidationStatus.PASS), [])
    assert result.failure_type == FailureType.TIMEOUT


def test_agent_failure_classification():
    analyzer = FailureAnalyzer()
    result = analyzer.analyze(_base_contract(), _base_agent_result(AgentExecutionStatus.FAILED), _validation_result(ValidationStatus.FAIL, "WITHIN_SCOPE", CriterionType.MANUAL, CriterionStatus.NEEDS_REVIEW), [])
    assert result.failure_type == FailureType.AGENT_FAILURE


def test_scope_violation_classification():
    analyzer = FailureAnalyzer()
    result = analyzer.analyze(_base_contract(), _base_agent_result(AgentExecutionStatus.FAILED), _validation_result(ValidationStatus.FAIL, "SCOPE_VIOLATION", CriterionType.MANUAL, CriterionStatus.NEEDS_REVIEW), [])
    assert result.failure_type == FailureType.SCOPE_VIOLATION


def test_evidence_from_validation_failures():
    analyzer = FailureAnalyzer()
    validation = _validation_result(ValidationStatus.FAIL, "WITHIN_SCOPE", CriterionType.TEST, CriterionStatus.FAIL)
    validation.failures = ["failure"]
    result = analyzer.analyze(_base_contract(), _base_agent_result(AgentExecutionStatus.FAILED), validation, [])
    assert "failure" in result.evidence


def test_deterministic_output():
    analyzer = FailureAnalyzer()
    result1 = analyzer.analyze(_base_contract(), _base_agent_result(AgentExecutionStatus.FAILED), _validation_result(), [])
    result2 = analyzer.analyze(_base_contract(), _base_agent_result(AgentExecutionStatus.FAILED), _validation_result(), [])
    assert result1 == result2

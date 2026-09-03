from __future__ import annotations

from typing import Any

from app.schemas.implementation import AgentExecutionResult, GitCheckpoint
from app.schemas.replan import FailureAnalysis, FailureType, RecommendedAction, Recoverability
from app.schemas.validation import ValidationResult


class FailureAnalyzer:
    def analyze(
        self,
        task_contract: Any,
        implementation_result: AgentExecutionResult,
        validation_result: ValidationResult,
        artifacts: list[Any],
        attempt_count: int = 0,
    ) -> FailureAnalysis:
        evidence: list[str] = []
        if validation_result is not None:
            if validation_result.failures:
                evidence.extend(validation_result.failures)
        if implementation_result.errors:
            evidence.extend(implementation_result.errors)
        if implementation_result.git_checkpoint is not None:
            evidence.extend(implementation_result.git_checkpoint.changed_files or [])
        if artifacts:
            evidence.extend([a.metadata[0] for a in artifacts if a.metadata])

        if validation_result is not None and validation_result.status == "FAIL":
            test_failures = [c for c in validation_result.criterion_results if c.type == "TEST" and c.status == "FAIL"]
            if test_failures:
                return FailureAnalysis(
                    task_id=implementation_result.task_id,
                    failure_type=FailureType.TEST_FAILURE,
                    root_cause_hypothesis="Deterministic validation detected test failures.",
                    evidence=evidence,
                    affected_scope=task_contract.implementation_scope,
                    recoverability=Recoverability.RETRYABLE if attempt_count < 2 else Recoverability.BLOCKED,
                    recommended_action=RecommendedAction.RETRY if attempt_count < 2 else RecommendedAction.BLOCK,
                )
            if validation_result.scope_result == "SCOPE_VIOLATION":
                return FailureAnalysis(
                    task_id=implementation_result.task_id,
                    failure_type=FailureType.SCOPE_VIOLATION,
                    root_cause_hypothesis="Changed files are outside allowed paths.",
                    evidence=evidence,
                    affected_scope=task_contract.implementation_scope,
                    recoverability=Recoverability.NEEDS_USER,
                    recommended_action=RecommendedAction.BLOCK,
                )
            if not evidence:
                evidence.extend(validation_result.failures or [])

        if implementation_result.status == "TIMEOUT":
            return FailureAnalysis(
                task_id=implementation_result.task_id,
                failure_type=FailureType.TIMEOUT,
                root_cause_hypothesis="Agent execution exceeded timeout.",
                evidence=evidence,
                affected_scope=task_contract.implementation_scope,
                recoverability=Recoverability.RETRYABLE if attempt_count < 2 else Recoverability.BLOCKED,
                recommended_action=RecommendedAction.RETRY if attempt_count < 2 else RecommendedAction.BLOCK,
            )

        if implementation_result.status == "FAILED":
            return FailureAnalysis(
                task_id=implementation_result.task_id,
                failure_type=FailureType.AGENT_FAILURE,
                root_cause_hypothesis="Agent reported failure without more specific cause.",
                evidence=evidence,
                affected_scope=task_contract.implementation_scope,
                recoverability=Recoverability.RETRYABLE if attempt_count < 2 else Recoverability.BLOCKED,
                recommended_action=RecommendedAction.RETRY if attempt_count < 2 else RecommendedAction.BLOCK,
            )

        if implementation_result.status == "BLOCKED":
            return FailureAnalysis(
                task_id=implementation_result.task_id,
                failure_type=FailureType.DEPENDENCY_FAILURE,
                root_cause_hypothesis="Agent execution blocked.",
                evidence=evidence,
                affected_scope=task_contract.implementation_scope,
                recoverability=Recoverability.BLOCKED,
                recommended_action=RecommendedAction.BLOCK,
            )

        if validation_result is not None and validation_result.status == "FAIL":
            return FailureAnalysis(
                task_id=implementation_result.task_id,
                failure_type=FailureType.VALIDATION_FAILURE,
                root_cause_hypothesis="Validation failed without more specific cause.",
                evidence=evidence,
                affected_scope=task_contract.implementation_scope,
                recoverability=Recoverability.REPLAN_REQUIRED,
                recommended_action=RecommendedAction.BLOCK,
            )

        return FailureAnalysis(
            task_id=implementation_result.task_id,
            failure_type=FailureType.UNKNOWN,
            root_cause_hypothesis="Unable to classify failure from available evidence.",
            evidence=evidence,
            affected_scope=task_contract.implementation_scope,
            recoverability=Recoverability.NEEDS_USER,
            recommended_action=RecommendedAction.BLOCK,
        )

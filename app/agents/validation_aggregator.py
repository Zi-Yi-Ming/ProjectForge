from __future__ import annotations

from typing import Sequence

from app.schemas.implementation import AgentExecutionResult, TaskContract
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


class ValidationAggregator:
    def aggregate(
        self,
        task_contract: TaskContract,
        implementation_result: AgentExecutionResult,
        deterministic_result: ValidationResult,
        llm_review: LLMReviewResult | None = None,
    ) -> tuple[ValidationResult, ValidationFeedback | None]:
        merged_criteria = list(deterministic_result.criterion_results)
        merged_evidence = list(deterministic_result.evidence)
        merged_failures = list(deterministic_result.failures)
        merged_warnings = list(deterministic_result.warnings)
        merged_manual = list(deterministic_result.manual_review_items)

        if llm_review:
            merged_evidence.extend(llm_review.evidence)
            merged_warnings.extend(llm_review.risks)
            for finding in llm_review.findings:
                review_status = (
                    CriterionStatus.FAIL
                    if finding.severity.upper() == "HIGH"
                    else CriterionStatus.NEEDS_REVIEW
                )
                merged_criteria.append(
                    CriterionResult(
                        criterion=f"LLM:{finding.criterion or finding.severity}",
                        type=CriterionType.LLM_REVIEW,
                        status=review_status,
                        evidence=finding.evidence,
                        details=",".join(llm_review.recommendations),
                    )
                )

        # The criteria are the single source of truth for the verdict. Scope in
        # particular is *not* re-derived from `scope_result` here: the validator
        # owns that decision (it knows PROJECTFORGE_SCOPE_MODE) and already
        # emits a FAIL criterion when enforcement is on. Re-deriving it here
        # silently overrode warn mode and failed tasks it was meant to spare.
        hard_failure = any(c.status == "FAIL" for c in merged_criteria)
        needs_review = any(c.status == "NEEDS_REVIEW" for c in merged_criteria)

        if hard_failure:
            status = ValidationStatus.FAIL
        elif needs_review:
            status = ValidationStatus.NEEDS_REVIEW
        else:
            status = ValidationStatus.PASS

        result = ValidationResult(
            task_id=deterministic_result.task_id,
            status=status,
            criterion_results=merged_criteria,
            test_results=deterministic_result.test_results,
            scope_result=deterministic_result.scope_result,
            changed_files=deterministic_result.changed_files,
            evidence=merged_evidence,
            failures=merged_failures,
            warnings=merged_warnings,
            manual_review_items=merged_manual,
            llm_review=llm_review,
            repair_cycle=deterministic_result.repair_cycle,
            validated_at=deterministic_result.validated_at,
        )

        feedback: ValidationFeedback | None = None
        if status == ValidationStatus.FAIL:
            feedback = ValidationFeedback(
                task_id=result.task_id,
                failed_criteria=[c.criterion for c in merged_criteria if c.status == "FAIL"],
                deterministic_failures=merged_failures,
                llm_findings=[f.criterion for f in (llm_review.findings if llm_review else [])],
                evidence=merged_evidence,
                required_changes=llm_review.recommendations if llm_review else [],
                forbidden_changes=list(task_contract.out_of_scope),
                retry_context=f"repair_cycle={result.repair_cycle}",
            )
        return result, feedback

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.implementation import TaskContract


class CriterionType(str, Enum):
    TEST = "TEST"
    COMMAND = "COMMAND"
    FILE = "FILE"
    PATTERN = "PATTERN"
    LLM_REVIEW = "LLM_REVIEW"
    MANUAL = "MANUAL"


class CriterionStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"


class ValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"


class CriterionResult(BaseModel):
    criterion: str = Field(default="", description="What is being checked.")
    type: CriterionType = Field(..., description="Kind of validation.")
    status: CriterionStatus = Field(..., description="Result of this criterion.")
    evidence: str = Field(default="", description="Concrete evidence for this result.")
    details: str = Field(default="", description="Additional context.")


class LLMReviewFinding(BaseModel):
    severity: str = Field(default="MEDIUM", description="Finding severity.")
    criterion: str = Field(default="", description="Related criterion or concern.")
    evidence: str = Field(default="", description="Supporting evidence.")


class LLMReviewResult(BaseModel):
    status: ValidationStatus = Field(..., description="Overall LLM review result.")
    findings: list[LLMReviewFinding] = Field(default_factory=list, description="Findings from review.")
    strengths: list[str] = Field(default_factory=list, description="Observed strengths.")
    risks: list[str] = Field(default_factory=list, description="Observed risks.")
    evidence: list[str] = Field(default_factory=list, description="Collected evidence.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Review confidence.")
    recommendations: list[str] = Field(default_factory=list, description="Review recommendations.")


class ValidationFeedback(BaseModel):
    task_id: str = Field(default="", description="Task being validated.")
    failed_criteria: list[str] = Field(default_factory=list, description="Failed criterion summaries.")
    deterministic_failures: list[str] = Field(default_factory=list, description="Deterministic failure descriptions.")
    llm_findings: list[str] = Field(default_factory=list, description="LLM finding summaries.")
    evidence: list[str] = Field(default_factory=list, description="Supporting evidence.")
    required_changes: list[str] = Field(default_factory=list, description="Required changes.")
    forbidden_changes: list[str] = Field(default_factory=list, description="Forbidden changes.")
    retry_context: str = Field(default="", description="Context for retry.")


class ValidationResult(BaseModel):
    task_id: str = Field(default="", description="Validated task identifier.")
    status: ValidationStatus = Field(..., description="Final validation status.")
    criterion_results: list[CriterionResult] = Field(default_factory=list, description="Per-criterion results.")
    test_results: list[str] = Field(default_factory=list, description="Test execution outputs.")
    scope_result: str = Field(default="", description="Scope validation result string.")
    changed_files: list[str] = Field(default_factory=list, description="Files observed as changed.")
    evidence: list[str] = Field(default_factory=list, description="Validation evidence.")
    failures: list[str] = Field(default_factory=list, description="Failure summaries.")
    warnings: list[str] = Field(default_factory=list, description="Warning summaries.")
    manual_review_items: list[str] = Field(default_factory=list, description="Items needing manual review.")
    llm_review: LLMReviewResult | None = Field(default=None, description="Optional LLM review.")
    repair_cycle: int = Field(default=0, ge=0, description="Validation repair cycle count.")
    validated_at: str = Field(default="", description="Validation timestamp.")

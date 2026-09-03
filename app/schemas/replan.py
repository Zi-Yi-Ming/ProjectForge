from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.execution import ExecutionRun


class FailureType(str, Enum):
    TEST_FAILURE = "TEST_FAILURE"
    ACCEPTANCE_CRITERIA_FAILURE = "ACCEPTANCE_CRITERIA_FAILURE"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    AGENT_FAILURE = "AGENT_FAILURE"
    TIMEOUT = "TIMEOUT"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    UNKNOWN = "UNKNOWN"


class Recoverability(str, Enum):
    RETRYABLE = "RETRYABLE"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    BLOCKED = "BLOCKED"
    NEEDS_USER = "NEEDS_USER"


class RecommendedAction(str, Enum):
    RETRY = "RETRY"
    SPLIT = "SPLIT"
    ADD_DEPENDENCY = "ADD_DEPENDENCY"
    BLOCK = "BLOCK"


class FailureAnalysis(BaseModel):
    task_id: str = Field(default="", description="Failed task identifier.")
    failure_type: FailureType = Field(..., description="Classified failure type.")
    root_cause_hypothesis: str = Field(default="", description="Hypothesis about root cause.")
    evidence: list[str] = Field(default_factory=list, description="Evidence references.")
    affected_scope: str = Field(default="", description="Scope impact summary.")
    recoverability: Recoverability = Field(..., description="Recoverability assessment.")
    recommended_action: RecommendedAction = Field(..., description="Recommended action.")


class ReplanChangeType(str, Enum):
    RETRY_TASK = "RETRY_TASK"
    ADD_TASK = "ADD_TASK"
    ADD_DEPENDENCY = "ADD_DEPENDENCY"
    BLOCK_TASK = "BLOCK_TASK"


class ReplanChange(BaseModel):
    change_type: ReplanChangeType = Field(..., description="Type of replan change.")
    task_id: str = Field(default="", description="Source task identifier.")
    target_task_id: str = Field(default="", description="Target task identifier.")
    title: str = Field(default="", description="Change title.")
    description: str = Field(default="", description="Change description.")


class ReplanAction(str, Enum):
    RETRY = "RETRY"
    SPLIT = "SPLIT"
    ADD_DEPENDENCY = "ADD_DEPENDENCY"
    BLOCK = "BLOCK"


class ReplanProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    EXPIRED = "EXPIRED"


class ReplanProposal(BaseModel):
    proposal_id: str = Field(default="", description="Proposal identifier.")
    run_id: str = Field(default="", description="Related execution run identifier.")
    task_id: str = Field(default="", description="Failed task identifier.")
    action: ReplanAction = Field(..., description="Proposed replan action.")
    reason: str = Field(default="", description="Reason for the proposal.")
    evidence: list[str] = Field(default_factory=list, description="Supporting evidence.")
    affected_task_ids: list[str] = Field(default_factory=list, description="Task ids affected by this proposal.")
    proposed_changes: list[ReplanChange] = Field(default_factory=list, description="Proposed changes.")
    forbidden_changes: list[str] = Field(default_factory=list, description="Forbidden change descriptions.")
    requires_user_approval: bool = Field(default=True, description="Whether user approval is required.")
    status: ReplanProposalStatus = Field(default=ReplanProposalStatus.PROPOSED, description="Proposal status.")
    created_at: str = Field(default="", description="Creation timestamp.")
    approved_at: str = Field(default="", description="Approval timestamp.")
    applied_at: str = Field(default="", description="Applied timestamp.")


class ReplanApplyResult(BaseModel):
    success: bool = Field(default=False, description="Whether apply succeeded.")
    proposal_id: str = Field(default="", description="Applied proposal identifier.")
    applied_changes: list[ReplanChange] = Field(default_factory=list, description="Changes that were applied.")
    failures: list[str] = Field(default_factory=list, description="Validation failures if any.")
    message: str = Field(default="", description="Result message.")

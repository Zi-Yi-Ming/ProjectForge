from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.coding_agent import CodingAgentAdapter
from app.agents.validator import DeterministicValidator
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)
from app.schemas.validation import ValidationResult, ValidationStatus


@dataclass
class WorkerResult:
    task_id: str
    agent_result: AgentExecutionResult
    validation_result: ValidationResult | None = None
    error: str | None = None
    workspace: Path | None = None


class Worker:
    def __init__(
        self,
        adapter: CodingAgentAdapter,
        validator: DeterministicValidator | None = None,
        workspace_factory: Any = None,
    ) -> None:
        self.adapter = adapter
        self.validator = validator or DeterministicValidator()
        self.workspace_factory = workspace_factory

    def execute(self, task_contract: TaskContract, project_map: ProjectMap) -> WorkerResult:
        workspace = self._workspace_for(task_contract.task_id)
        try:
            agent_result = self.adapter.execute(task_contract, project_map)
        except Exception as exc:
            agent_result = AgentExecutionResult(
                task_id=task_contract.task_id,
                agent=getattr(self.adapter, "__class__", type("UnknownAdapter", (), {})).__name__,
                status=ExecutionStatus.ERROR,
                iterations=0,
                changed_files=[],
                scope_status=ScopeStatus.NEEDS_REVIEW,
                test_results=[],
                summary="",
                errors=[f"{exc}"],
                blocking_reason=str(exc),
            )

        validation_result = None
        if agent_result.status == ExecutionStatus.IMPLEMENTED:
            try:
                validation_result = self.validator.validate(
                    task_id=task_contract.task_id,
                    task_contract=task_contract,
                    implementation_result=agent_result,
                    workspace=workspace,
                )
            except Exception as exc:
                validation_result = ValidationResult(
                    task_id=task_contract.task_id,
                    status=ValidationStatus.FAIL,
                    failures=[f"Validator exception: {exc}"],
                    evidence=[traceback.format_exc()],
                )

        return WorkerResult(
            task_id=task_contract.task_id,
            agent_result=agent_result,
            validation_result=validation_result,
            workspace=workspace,
        )

    def _workspace_for(self, task_id: str) -> Path:
        if self.workspace_factory is not None:
            return self.workspace_factory(task_id)
        return Path(".")

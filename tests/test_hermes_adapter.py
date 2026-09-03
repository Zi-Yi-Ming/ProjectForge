from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.hermes_adapter import HermesAdapter
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)


PROJECT_ROOT = Path("/home/azureuser/content-agent")


def _contract() -> TaskContract:
    return TaskContract(
        task_id="T_REAL",
        project="demo",
        phase="Foundation",
        title="Echo probe",
        goal="Echo probe only",
        why="Verify HermesAdapter can launch real Hermes.",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="echo",
        implementation_scope="workspace only",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=[],
        test_scope=[],
        execution_rules=[],
    )


def test_hermes_adapter_real_cli_is_discovered() -> None:
    adapter = HermesAdapter()
    assert adapter.hermes_cli
    assert Path(adapter.hermes_cli).exists() or adapter.hermes_cli in {"hermes", "hermes-agent", "hermes_cli"}


def test_hermes_adapter_real_execution_captures_output() -> None:
    adapter = HermesAdapter(workspace=PROJECT_ROOT)
    contract = _contract()
    result = adapter.execute(contract, ProjectMap())
    assert isinstance(result, AgentExecutionResult)
    assert result.agent == "hermes"
    assert result.started_at
    assert result.finished_at >= result.started_at
    assert result.task_id == "T_REAL"
    assert result.git_checkpoint is not None


def test_hermes_adapter_timeout_status() -> None:
    adapter = HermesAdapter(workspace=PROJECT_ROOT, timeout_seconds=1)
    contract = _contract()
    result = adapter.execute(contract, ProjectMap())
    assert result.status in {ExecutionStatus.TIMEOUT, ExecutionStatus.IMPLEMENTED, ExecutionStatus.ERROR}


def test_hermes_adapter_workspace_missing_returns_error() -> None:
    adapter = HermesAdapter(workspace=Path("/tmp/nonexistent_content_agent_workspace_xyz"))
    contract = _contract()
    result = adapter.execute(contract, ProjectMap())
    assert result.status == ExecutionStatus.ERROR
    assert result.blocking_reason


def test_hermes_adapter_git_checkpoint_preserves_metadata() -> None:
    adapter = HermesAdapter(workspace=PROJECT_ROOT)
    contract = _contract()
    result = adapter.execute(contract, ProjectMap())
    assert result.git_checkpoint is not None
    assert result.git_checkpoint.head_before
    assert result.git_checkpoint.pre_existing_changes is not None


def test_hermes_adapter_prompt_contains_task_contract_fields() -> None:
    adapter = HermesAdapter()
    contract = _contract()
    prompt = adapter._build_prompt(contract, ProjectMap())
    assert "T_REAL" in prompt
    assert "Echo probe" in prompt
    assert "Goal:" in prompt
    assert "Acceptance Criteria:" in prompt
    assert "Execution Rules:" in prompt


def test_hermes_adapter_scope_status_is_not_done() -> None:
    adapter = HermesAdapter(workspace=PROJECT_ROOT)
    contract = _contract()
    result = adapter.execute(contract, ProjectMap())
    assert result.status != "DONE"

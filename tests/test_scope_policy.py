"""Regression tests for task-level path scope.

Background (2026-09-15): the scope plane was tautological. ``_build_contract``
set ``allowed_paths = [<workspace root>]``, so every file inside the workspace
was "allowed" and the check could only ever return WITHIN_SCOPE — the README's
"restricts which files may be modified" claim never fired in a real run.

This adds an opt-in mechanism plus a staged rollout:

- A task that declares ``allowed_paths`` gets them enforced (plus shared
  cross-cutting files); a task that declares nothing keeps the old behaviour.
- ``PROJECTFORGE_SCOPE_MODE`` gates whether a violation actually fails the task
  (``warn``, the default) or not (``enforce``).
- A declaration that cannot be trusted (absolute, ``..``) is treated as
  unverifiable -> NEEDS_REVIEW, never as a violation.

The verdict logic itself now lives once in ``app.agents.scope_policy``; the
validator and the CLI adapter both delegate to it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.scope_policy import (
    NEEDS_REVIEW,
    SCOPE_MODE_ENFORCE,
    SCOPE_MODE_WARN,
    SCOPE_VIOLATION,
    WITHIN_SCOPE,
    evaluate_scope,
    normalize_declared_paths,
    path_allowed,
    resolve_scope_mode,
    shared_paths_for,
)
from app.agents.validator import DeterministicValidator
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)
from app.schemas.validation import ValidationStatus


# --- mode resolution ---


def test_scope_mode_defaults_to_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROJECTFORGE_SCOPE_MODE", raising=False)
    assert resolve_scope_mode() == SCOPE_MODE_WARN


def test_scope_mode_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECTFORGE_SCOPE_MODE", "enforce")
    assert resolve_scope_mode() == SCOPE_MODE_ENFORCE


def test_scope_mode_explicit_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECTFORGE_SCOPE_MODE", "enforce")
    assert resolve_scope_mode("warn") == SCOPE_MODE_WARN


def test_scope_mode_unknown_value_falls_back_to_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo must not silently enable enforcement."""
    monkeypatch.setenv("PROJECTFORGE_SCOPE_MODE", "ENFORCED")
    assert resolve_scope_mode() == SCOPE_MODE_WARN


# --- path matching ---


def test_path_allowed_prefix_semantics() -> None:
    assert path_allowed("src/api/Handler.java", "src/") is True
    assert path_allowed("src/worker/Handler.java", "src/api/") is False


def test_path_allowed_exact_match() -> None:
    assert path_allowed("requirements.txt", "requirements.txt") is True


def test_path_allowed_shared_basename_at_any_depth() -> None:
    """Package markers appear at arbitrary depths and cannot be prefix-matched."""
    assert path_allowed("src/pkg/__init__.py", "src/") is True
    assert path_allowed("deep/nested/__init__.py", "src/") is True


# --- declaration normalization ---


def test_normalize_rejects_absolute_and_escaping_paths(tmp_path: Path) -> None:
    declared = ["src/", "/etc/passwd", "../outside/", "tests/"]
    resolved = normalize_declared_paths(declared, tmp_path)
    assert len(resolved) == 2
    assert all(str(tmp_path.resolve()) in item for item in resolved)


def test_normalize_returns_empty_for_unusable_declaration(tmp_path: Path) -> None:
    """Nothing trustworthy left -> caller must see 'unverifiable', not 'ok'."""
    assert normalize_declared_paths(["../escape/", "/abs/path"], tmp_path) == []


def test_normalize_empty_input_stays_empty(tmp_path: Path) -> None:
    assert normalize_declared_paths([], tmp_path) == []
    assert normalize_declared_paths(None, tmp_path) == []


# --- verdict ---


def test_evaluate_scope_without_declaration_is_unverifiable() -> None:
    assert evaluate_scope(["anything.py"], []) == NEEDS_REVIEW


def test_evaluate_scope_flags_outside_path(tmp_path: Path) -> None:
    allowed = [str((tmp_path / "src").resolve())]
    assert evaluate_scope(["src/a.py"], allowed, workspace=tmp_path) == WITHIN_SCOPE
    assert evaluate_scope(["docs/a.py"], allowed, workspace=tmp_path) == SCOPE_VIOLATION


def test_evaluate_scope_allows_shared_files(tmp_path: Path) -> None:
    allowed = [str((tmp_path / "src").resolve())] + shared_paths_for(tmp_path)
    assert evaluate_scope(["requirements.txt"], allowed, workspace=tmp_path) == WITHIN_SCOPE


# --- validator integration ---


def _contract(allowed_paths: list[str]) -> TaskContract:
    return TaskContract(
        task_id="T1",
        project="demo",
        phase="Core",
        title="t",
        goal="g",
        why="w",
        dependencies=[],
        prerequisites=[],
        inputs=[],
        expected_output="",
        implementation_scope="",
        acceptance_criteria=[],
        out_of_scope=[],
        technical_points=[],
        interview_points=[],
        project_map=ProjectMap(),
        allowed_paths=allowed_paths,
        test_scope=[],
        execution_rules=[],
    )


def _result(changed: list[str]) -> AgentExecutionResult:
    return AgentExecutionResult(
        task_id="T1",
        agent="test",
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


def test_enforce_mode_fails_task_on_violation(tmp_path: Path) -> None:
    validator = DeterministicValidator(scope_mode=SCOPE_MODE_ENFORCE)
    contract = _contract([str((tmp_path / "src").resolve())])
    result = validator.validate("T1", contract, _result(["docs/readme.md"]), workspace=tmp_path)
    assert result.scope_result == SCOPE_VIOLATION
    assert result.status == ValidationStatus.FAIL
    assert any("Scope violation" in item for item in result.failures)


def test_warn_mode_records_violation_without_failing(tmp_path: Path) -> None:
    """The whole point of the staged rollout: observe, do not kill."""
    validator = DeterministicValidator(scope_mode=SCOPE_MODE_WARN)
    contract = _contract([str((tmp_path / "src").resolve())])
    result = validator.validate("T1", contract, _result(["docs/readme.md"]), workspace=tmp_path)
    assert result.scope_result == SCOPE_VIOLATION
    assert result.status != ValidationStatus.FAIL
    assert not any("Scope violation" in item for item in result.failures)
    assert any("not enforced" in item for item in result.warnings)


def test_undeclared_paths_keep_historical_behaviour(tmp_path: Path) -> None:
    """No declaration -> workspace root boundary, still WITHIN_SCOPE."""
    validator = DeterministicValidator(scope_mode=SCOPE_MODE_ENFORCE)
    contract = _contract([str(tmp_path.resolve())])
    result = validator.validate("T1", contract, _result(["anything/at/all.py"]), workspace=tmp_path)
    assert result.scope_result == WITHIN_SCOPE
    assert result.status != ValidationStatus.FAIL


def test_unverifiable_declaration_never_becomes_a_violation(tmp_path: Path) -> None:
    """Conservative semantics: unusable declaration -> NEEDS_REVIEW."""
    validator = DeterministicValidator(scope_mode=SCOPE_MODE_ENFORCE)
    contract = _contract([])  # contract carries nothing usable
    result = validator.validate("T1", contract, _result(["src/a.py"]), workspace=tmp_path)
    assert result.scope_result == NEEDS_REVIEW
    assert result.status != ValidationStatus.FAIL


# --- orchestrator contract routing ---


def _task(allowed_paths: list[str]):
    from app.schemas.task import Task, TaskStatus

    return Task(
        id="T1",
        phase_id="P1",
        title="t",
        goal="g",
        why="w",
        dependencies=[],
        status=TaskStatus.PENDING,
        scope="Core",
        acceptance_criteria=[],
        out_of_scope=[],
        interview_points=[],
        allowed_paths=allowed_paths,
    )


def _orchestrator():
    from app.agents.orchestrator import ExecutionOrchestrator

    class _NoopAdapter:
        pass

    return ExecutionOrchestrator(adapter=_NoopAdapter())  # type: ignore[arg-type]


def test_contract_enforces_declared_paths_plus_shared(tmp_path: Path) -> None:
    orchestrator = _orchestrator()
    contract = orchestrator._build_contract(_task(["src/", "tests/"]), ProjectMap(), run_dir=tmp_path)
    assert str((tmp_path / "src").resolve()) in contract.allowed_paths
    assert str((tmp_path / "tests").resolve()) in contract.allowed_paths
    # shared cross-cutting files come along automatically
    assert str((tmp_path / "requirements.txt").resolve()) in contract.allowed_paths


def test_contract_leaves_list_empty_for_unusable_declaration(tmp_path: Path) -> None:
    """Declared but untrustworthy -> empty -> NEEDS_REVIEW, never a violation."""
    orchestrator = _orchestrator()
    contract = orchestrator._build_contract(_task(["../escape/"]), ProjectMap(), run_dir=tmp_path)
    assert contract.allowed_paths == []


def test_contract_keeps_workspace_root_when_nothing_declared(tmp_path: Path) -> None:
    """Historical behaviour must be untouched for undeclared tasks."""
    orchestrator = _orchestrator()
    contract = orchestrator._build_contract(_task([]), ProjectMap(), run_dir=tmp_path)
    assert contract.allowed_paths == [str(tmp_path.resolve())]


# --- the two callers must agree ---


def test_validator_and_adapter_share_one_policy(tmp_path: Path) -> None:
    from app.agents.cli_adapter import CliAgentAdapter

    allowed = [str((tmp_path / "src").resolve())]
    changed = ["docs/a.md"]

    class _Adapter(CliAgentAdapter):
        def agent_name(self) -> str:  # pragma: no cover
            return "probe"

        def find_binary(self) -> str:  # pragma: no cover
            return "probe"

        def build_argv(self, prompt: str) -> list[str]:  # pragma: no cover
            return []

        def _run(self, task_contract, project_map):  # pragma: no cover
            raise NotImplementedError

    adapter = _Adapter(workspace=tmp_path)
    assert adapter._evaluate_scope_from_files(changed, allowed) == ScopeStatus.SCOPE_VIOLATION
    assert evaluate_scope(changed, allowed, workspace=tmp_path) == SCOPE_VIOLATION

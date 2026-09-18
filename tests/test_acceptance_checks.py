from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.mock_executor import MockExecutor
from app.agents.orchestrator import ExecutionOrchestrator
from app.agents.validator import DeterministicValidator
from app.product.service import ProjectService, resolve_criteria_mode
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)
from app.schemas.task import AcceptanceCheck, Task, TaskGraph, TaskStatus
from app.schemas.validation import (
    CriterionStatus,
    CriterionType,
    ValidationStatus,
)


class _FakeProcResult:
    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code
        self.stdout = ""
        self.stderr = ""


def _contract(ws: Path, checks: list[AcceptanceCheck]) -> TaskContract:
    # acceptance_criteria empty + a matching allowed_path keeps the verdict
    # driven purely by the criterion_checks under test (no manual/scope noise).
    return TaskContract(
        task_id="T1",
        goal="g",
        acceptance_criteria=[],
        criterion_checks=checks,
        allowed_paths=[str(ws.resolve())],
        test_scope=[],
    )


def _impl() -> AgentExecutionResult:
    return AgentExecutionResult(
        task_id="T1",
        agent="mock",
        status=ExecutionStatus.IMPLEMENTED,
        changed_files=[],
        scope_status=ScopeStatus.WITHIN_SCOPE,
        git_checkpoint=GitCheckpoint(),
    )


def _criteria_of(result, label):
    return [c for c in result.criterion_results if c.criterion == label]


# --- observe: never changes the verdict ---

def test_observe_failing_check_does_not_fail_task(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    validator = DeterministicValidator()  # default observe
    contract = _contract(ws, [AcceptanceCheck(criterion="missing file", kind="FILE", target="nope.py")])

    result = validator.validate("T1", contract, _impl(), workspace=ws)

    assert result.status != ValidationStatus.FAIL
    assert not [c for c in result.criterion_results if c.status == CriterionStatus.FAIL]
    assert any("observe" in w and "missing file" in w for w in result.warnings)


def test_observe_passing_check_records_pass_criterion(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "report.txt").write_text("hello", encoding="utf-8")
    validator = DeterministicValidator()
    contract = _contract(ws, [AcceptanceCheck(criterion="report exists", kind="FILE", target="report.txt")])

    result = validator.validate("T1", contract, _impl(), workspace=ws)

    crit = _criteria_of(result, "report exists")
    assert crit and crit[0].status == CriterionStatus.PASS
    assert crit[0].type == CriterionType.FILE


# --- require: a failed check blocks DONE ---

def test_require_failing_check_blocks_done(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    validator = DeterministicValidator(criteria_mode="require")
    contract = _contract(ws, [AcceptanceCheck(criterion="must exist", kind="FILE", target="absent.py")])

    result = validator.validate("T1", contract, _impl(), workspace=ws)

    assert result.status == ValidationStatus.FAIL
    crit = _criteria_of(result, "must exist")
    assert crit and crit[0].status == CriterionStatus.FAIL


def test_require_all_passing_reaches_pass(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("x", encoding="utf-8")
    validator = DeterministicValidator(criteria_mode="require")
    contract = _contract(ws, [
        AcceptanceCheck(criterion="a exists", kind="FILE", target="a.txt"),
        AcceptanceCheck(criterion="a mentions x", kind="PATTERN", target="a.txt:x"),
    ])

    result = validator.validate("T1", contract, _impl(), workspace=ws)

    assert result.status == ValidationStatus.PASS


# --- PATTERN semantics ---

def test_pattern_check_match_and_mismatch(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "svc.py").write_text("class Service: pass", encoding="utf-8")
    validator = DeterministicValidator(criteria_mode="require")
    ok = validator.validate("T1", _contract(ws, [AcceptanceCheck(criterion="has class", kind="PATTERN", target="svc.py:class\\s+Service")]), _impl(), workspace=ws)
    assert _criteria_of(ok, "has class")[0].status == CriterionStatus.PASS
    bad = validator.validate("T1", _contract(ws, [AcceptanceCheck(criterion="nope", kind="PATTERN", target="svc.py:doesnotexist")]), _impl(), workspace=ws)
    assert bad.status == ValidationStatus.FAIL


# --- TEST / COMMAND go through _run_command (and thus the sandbox); fake it ---

def test_test_kind_uses_run_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake(cmd, workspace=None):
        seen["cmd"] = cmd
        return _FakeProcResult(0)

    monkeypatch.setattr(DeterministicValidator, "_run_command", lambda self, cmd, workspace=None: fake(cmd, workspace))
    validator = DeterministicValidator(criteria_mode="require")
    res = validator.validate("T1", _contract(tmp_path, [AcceptanceCheck(criterion="unit", kind="TEST", target="tests/test_u.py")]), _impl(), workspace=tmp_path)
    assert _criteria_of(res, "unit")[0].status == CriterionStatus.PASS
    assert "tests/test_u.py" in seen["cmd"]  # type: ignore[index]


def test_command_kind_failure_blocks_in_require(tmp_path: Path) -> None:
    validator = DeterministicValidator(criteria_mode="require")
    # a command that certainly exits non-zero
    monkey = validator
    monkey._run_command = lambda cmd, workspace=None: _FakeProcResult(2)  # type: ignore[assignment]
    res = monkey.validate("T1", _contract(tmp_path, [AcceptanceCheck(criterion="lint", kind="COMMAND", target="pytest -q")]), _impl(), workspace=tmp_path)
    assert res.status == ValidationStatus.FAIL
    assert _criteria_of(res, "lint")[0].type == CriterionType.COMMAND


# --- MANUAL stays a manual review item ---

def test_manual_check_goes_to_manual_items(tmp_path: Path) -> None:
    validator = DeterministicValidator(criteria_mode="require")
    res = validator.validate("T1", _contract(tmp_path, [AcceptanceCheck(criterion="needs human", kind="MANUAL", target="")]), _impl(), workspace=tmp_path)
    assert "needs human" in res.manual_review_items


# --- backward compat: no criterion_checks changes nothing ---

def test_no_checks_preserves_prior_behavior(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    validator = DeterministicValidator()
    contract = _contract(ws, [])
    res = validator.validate("T1", contract, _impl(), workspace=ws)
    assert not any(
        c.details.startswith("acceptance check") for c in res.criterion_results
    ), "empty criterion_checks must add no check criteria"
    assert not any("acceptance check" in w for w in res.warnings), "empty criterion_checks must add no check warnings"


# --- contract plumbing: _build_contract carries criterion_checks ---

def test_build_contract_propagates_criterion_checks(tmp_path: Path) -> None:
    orch = ExecutionOrchestrator(adapter=object())  # adapter unused by _build_contract
    task = Task(
        id="T1", phase_id="P1", title="t", goal="g",
        acceptance_criteria=["c"],
        criterion_checks=[AcceptanceCheck(criterion="c", kind="FILE", target="x.txt")],
        status=TaskStatus.PENDING,
    )
    contract = orch._build_contract(task, ProjectMap(), run_dir=tmp_path)
    assert len(contract.criterion_checks) == 1
    assert contract.criterion_checks[0].kind == "FILE"


# --- PR2: env resolver + service wiring + end-to-end gating ---

@pytest.mark.parametrize("value,expected", [
    ("", "observe"), ("require", "require"), ("REQUIRE", "require"),
    ("observe", "observe"), ("bogus", "observe"),
])
def test_resolve_criteria_mode(monkeypatch: pytest.MonkeyPatch, value: str, expected: str) -> None:
    monkeypatch.setenv("PROJECTFORGE_CRITERIA_MODE", value)
    assert resolve_criteria_mode() == expected


def test_build_executor_threads_criteria_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECTFORGE_CRITERIA_MODE", "require")
    service = ProjectService(
        base_dir=tmp_path,
        executor_factory=lambda run_dir, timeout: MockExecutor(workspace=run_dir),
    )
    orch = service._build_executor(tmp_path / "ws")
    assert orch.validator.criteria_mode == "require"


def _run_serial_with_failing_check(tmp_path: Path, mode: str) -> str:
    run_dir = tmp_path / "ws"
    run_dir.mkdir()
    orch = ExecutionOrchestrator(
        adapter=MockExecutor(workspace=run_dir),
        validator=DeterministicValidator(criteria_mode=mode),
        parallel_enabled=False,
    )
    task = Task(
        id="T1", phase_id="P1", title="t", goal="g", status=TaskStatus.PENDING,
        acceptance_criteria=["delivered"], test_paths=["tests"],
        criterion_checks=[AcceptanceCheck(criterion="marker", kind="FILE", target="does_not_exist.txt")],
    )
    graph = TaskGraph(project="p", tasks=[task], total_tasks=1, required_tasks=1, optional_tasks=0)
    run = orch.run(graph, ProjectMap(), run_dir=run_dir)
    return run.task_results[0].status


def test_observe_failing_check_still_reaches_done(tmp_path: Path) -> None:
    assert _run_serial_with_failing_check(tmp_path, "observe") == TaskStatus.DONE.value


def test_require_failing_check_blocks_done(tmp_path: Path) -> None:
    assert _run_serial_with_failing_check(tmp_path, "require") == TaskStatus.FAILED.value

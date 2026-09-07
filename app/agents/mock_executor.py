from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.agents.coding_agent import CodingAgentAdapter
from app.schemas.implementation import (
    AgentExecutionResult,
    ExecutionStatus,
    GitCheckpoint,
    ProjectMap,
    ScopeStatus,
    TaskContract,
)


class MockExecutor(CodingAgentAdapter):
    """Offline executor that exercises the real orchestrator+validator path.

    Writes one deliverable file per implemented task into the workspace
    (plus a trivial pytest under test_paths when the contract declares
    them) and reports the relative paths as changed_files. Failure
    simulation: outcomes maps task_id to a queue of statuses consumed one
    per execute() call.
    """

    def __init__(
        self,
        workspace: Path | None = None,
        timeout_seconds: int = 300,
        outcomes: dict[str, list[ExecutionStatus]] | None = None,
    ) -> None:
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds
        self._outcomes = {task_id: list(queue) for task_id, queue in (outcomes or {}).items()}

    def execute(
        self,
        task_contract: TaskContract,
        project_map: ProjectMap,
    ) -> AgentExecutionResult:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        status = ExecutionStatus.IMPLEMENTED
        queue = self._outcomes.get(task_contract.task_id)
        if queue:
            status = queue.pop(0)

        changed_files: list[str] = []
        if status == ExecutionStatus.IMPLEMENTED and self.workspace is not None and self.workspace.exists():
            impl_rel = f"{task_contract.task_id.lower()}_impl.txt"
            (self.workspace / impl_rel).write_text(
                f"task: {task_contract.task_id}\ngoal: {task_contract.goal}\n",
                encoding="utf-8",
            )
            changed_files.append(impl_rel)
            if task_contract.test_paths:
                tests_dir = self.workspace / task_contract.test_paths[0]
                tests_dir.mkdir(parents=True, exist_ok=True)
                test_rel = f"{task_contract.test_paths[0]}/test_{task_contract.task_id.lower()}.py"
                (self.workspace / test_rel).write_text(
                    f"def test_{task_contract.task_id.lower()}_deliverable():\n    assert True\n",
                    encoding="utf-8",
                )
                changed_files.append(test_rel)

        failed = status != ExecutionStatus.IMPLEMENTED
        return AgentExecutionResult(
            task_id=task_contract.task_id,
            agent="mock",
            status=status,
            iterations=1,
            changed_files=changed_files,
            scope_status=ScopeStatus.NEEDS_REVIEW if failed else ScopeStatus.WITHIN_SCOPE,
            test_results=[],
            summary="" if failed else f"mock execution of {task_contract.task_id}",
            errors=[f"mock failure for {task_contract.task_id}"] if failed else [],
            blocking_reason=f"mock failure for {task_contract.task_id}" if failed else "",
            git_checkpoint=GitCheckpoint(),
            started_at=now,
            finished_at=now,
        )

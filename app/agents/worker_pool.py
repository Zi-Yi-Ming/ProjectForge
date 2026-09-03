from __future__ import annotations

import concurrent.futures
import threading
from dataclasses import dataclass
from typing import Any, Callable

from app.agents.worker import WorkerResult
from app.schemas.implementation import AgentExecutionResult, ExecutionStatus, ScopeStatus


@dataclass
class DispatchedTask:
    task_id: str
    payload: Any


class WorkerPool:
    def __init__(self, max_workers: int = 2) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self.max_workers = max_workers
        self._lock = threading.Lock()
        self._claimed: set[str] = set()

    def claim_task(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._claimed:
                return False
            self._claimed.add(task_id)
            return True

    def execute(self, tasks: list[Any], worker_fn: Callable[[Any], WorkerResult]) -> list[WorkerResult]:
        claimed: list[Any] = []
        for task in tasks:
            task_id = getattr(task, "id", None)
            if task_id is None:
                continue
            if self.claim_task(task_id):
                claimed.append(task)

        if not claimed:
            return []

        results: list[WorkerResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(worker_fn, task): getattr(task, "id", "") for task in claimed}
            for future in concurrent.futures.as_completed(futures):
                task_id = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = WorkerResult(
                        task_id=task_id,
                        agent_result=AgentExecutionResult(
                            task_id=task_id,
                            agent="worker-pool",
                            status=ExecutionStatus.ERROR,
                            iterations=0,
                            changed_files=[],
                            scope_status=ScopeStatus.NEEDS_REVIEW,
                            test_results=[],
                            summary="",
                            errors=[f"Worker exception: {exc}"],
                            blocking_reason=str(exc),
                        ),
                        error=str(exc),
                    )
                results.append(result)
        return results

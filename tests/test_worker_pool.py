from __future__ import annotations

import pytest

from app.agents.worker_pool import WorkerPool


def test_max_workers_zero_raises() -> None:
    with pytest.raises(ValueError):
        WorkerPool(max_workers=0)


def test_max_workers_negative_raises() -> None:
    with pytest.raises(ValueError):
        WorkerPool(max_workers=-1)


def test_claim_same_task_twice_rejected() -> None:
    pool = WorkerPool(max_workers=1)
    assert pool.claim_task("T1") is True
    assert pool.claim_task("T1") is False


def test_claim_different_tasks_allowed() -> None:
    pool = WorkerPool(max_workers=2)
    assert pool.claim_task("T1") is True
    assert pool.claim_task("T2") is True

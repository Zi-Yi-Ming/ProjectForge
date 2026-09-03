from __future__ import annotations

import pytest

from app.agents.scheduler import TaskScheduler
from app.agents.task_engine import TaskEngine
from app.schemas.task import Task, TaskGraph, TaskStatus


def _graph_with_dependencies() -> TaskGraph:
    engine = TaskEngine()
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g2", why="w2", dependencies=["T1"], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T3", phase_id="P1", title="T3", goal="g3", why="w3", dependencies=["T1", "T2"], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
    ]
    return TaskGraph(project="demo", phases=[], tasks=tasks, total_tasks=3, required_tasks=3, optional_tasks=0)


def test_no_dependency_task_is_ready() -> None:
    graph = _graph_with_dependencies()
    ready = TaskScheduler().get_ready_tasks(graph)
    assert [t.id for t in ready] == ["T1"]


def test_dependency_not_complete_blocks_task() -> None:
    graph = _graph_with_dependencies()
    ready = TaskScheduler().get_ready_tasks(graph)
    assert "T2" not in {t.id for t in ready}
    assert "T3" not in {t.id for t in ready}


def test_dependency_done_makes_task_ready() -> None:
    graph = _graph_with_dependencies()
    graph.tasks[0].status = TaskStatus.DONE
    ready = TaskScheduler().get_ready_tasks(graph)
    assert "T2" in {t.id for t in ready}


def test_dependency_failed_blocks_downstream() -> None:
    graph = _graph_with_dependencies()
    graph.tasks[0].status = TaskStatus.FAILED
    TaskScheduler().update_states(graph)
    assert graph.tasks[1].status == TaskStatus.BLOCKED


def test_dependency_blocked_blocks_downstream() -> None:
    graph = _graph_with_dependencies()
    graph.tasks[0].status = TaskStatus.BLOCKED
    TaskScheduler().update_states(graph)
    assert graph.tasks[1].status == TaskStatus.BLOCKED


def test_multiple_dependencies_all_done_required() -> None:
    graph = _graph_with_dependencies()
    graph.tasks[0].status = TaskStatus.DONE
    graph.tasks[1].status = TaskStatus.DONE
    ready = TaskScheduler().get_ready_tasks(graph)
    assert "T3" in {t.id for t in ready}


def test_multiple_dependencies_one_failed_blocks() -> None:
    graph = _graph_with_dependencies()
    graph.tasks[0].status = TaskStatus.DONE
    graph.tasks[1].status = TaskStatus.FAILED
    TaskScheduler().update_states(graph)
    assert graph.tasks[2].status == TaskStatus.BLOCKED


def test_select_next_task_follows_topological_order() -> None:
    graph = _graph_with_dependencies()
    graph.tasks[0].status = TaskStatus.DONE
    TaskScheduler().update_states(graph)
    ready = TaskScheduler().get_ready_tasks(graph)
    assert [t.id for t in ready] == ["T2"]


def test_done_task_is_not_ready_again() -> None:
    graph = _graph_with_dependencies()
    graph.tasks[0].status = TaskStatus.DONE
    ready = TaskScheduler().get_ready_tasks(graph)
    assert "T1" not in {t.id for t in ready}

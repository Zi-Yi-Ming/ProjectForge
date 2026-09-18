from __future__ import annotations

import pytest

from app.agents.scheduler import TaskScheduler
from app.agents.task_engine import TaskEngine
from app.schemas.task import Task, TaskGraph, TaskGraphValidation, TaskStatus


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


def _diamond_graph() -> TaskGraph:
    # T1 -> {T2, T3} -> T4. With T1 DONE both T2 and T3 are ready at once.
    # Insertion order (T2, T3) differs from the declared topological order
    # (T3 before T2) so the two orderings can be told apart.
    tasks = [
        Task(id="T2", phase_id="P1", title="T2", goal="g", why="w", dependencies=["T1"], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T3", phase_id="P1", title="T3", goal="g", why="w", dependencies=["T1"], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T1", phase_id="P1", title="T1", goal="g", why="w", dependencies=[], scope="Core", status=TaskStatus.DONE, acceptance_criteria=[], out_of_scope=[]),
        Task(id="T4", phase_id="P1", title="T4", goal="g", why="w", dependencies=["T2", "T3"], scope="Core", status=TaskStatus.PENDING, acceptance_criteria=[], out_of_scope=[]),
    ]
    gv = TaskGraphValidation(valid=True, topological_order=["T1", "T3", "T2", "T4"])
    return TaskGraph(project="demo", phases=[], tasks=tasks, total_tasks=4, required_tasks=4, optional_tasks=0, graph_validation=gv)


def test_ready_wave_is_a_permutation_of_ready_tasks() -> None:
    scheduler = TaskScheduler()
    graph = _diamond_graph()
    wave = scheduler.ready_wave(graph)
    assert {t.id for t in wave} == {t.id for t in scheduler.get_ready_tasks(graph)}


def test_ready_wave_orders_by_topology_not_insertion() -> None:
    graph = _diamond_graph()
    wave = TaskScheduler().ready_wave(graph)
    assert [t.id for t in wave] == ["T3", "T2"]


def test_select_next_task_is_head_of_ready_wave() -> None:
    scheduler = TaskScheduler()
    graph = _diamond_graph()
    wave = scheduler.ready_wave(graph)
    nxt = scheduler.select_next_task(graph)
    assert nxt is not None
    assert nxt.id == wave[0].id


def test_select_next_task_none_when_no_ready_wave() -> None:
    scheduler = TaskScheduler()
    graph = _diamond_graph()
    for task in graph.tasks:
        task.status = TaskStatus.DONE
    assert scheduler.ready_wave(graph) == []
    assert scheduler.select_next_task(graph) is None

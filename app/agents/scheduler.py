from __future__ import annotations

from typing import Any

from app.schemas.task import Task, TaskGraph, TaskStatus


class TaskScheduler:
    def get_ready_tasks(self, task_graph: TaskGraph) -> list[Task]:
        task_map = {t.id: t for t in task_graph.tasks}
        ready: list[Task] = []
        for task in task_graph.tasks:
            if self._is_ready(task, task_map):
                ready.append(task)
        return ready

    def select_next_task(self, task_graph: TaskGraph) -> Task | None:
        ready = self.get_ready_tasks(task_graph)
        if not ready:
            return None
        order = list(task_graph.graph_validation.topological_order) if task_graph.graph_validation and task_graph.graph_validation.topological_order else [t.id for t in task_graph.tasks]
        position = {task_id: idx for idx, task_id in enumerate(order)}
        ready.sort(key=lambda t: position.get(t.id, len(order)))
        return ready[0]

    def update_states(self, task_graph: TaskGraph) -> None:
        task_map = {t.id: t for t in task_graph.tasks}
        for task in task_graph.tasks:
            if task.status in {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.IN_PROGRESS, TaskStatus.VALIDATING}:
                continue
            if self._is_ready(task, task_map):
                task.status = TaskStatus.READY
            elif self._is_blocked_by_dependency(task, task_map):
                task.status = TaskStatus.BLOCKED

    def _is_ready(self, task: Task, task_map: dict[str, Task]) -> bool:
        if task.status in {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.BLOCKED}:
            return False
        for dep_id in task.dependencies:
            dep = task_map.get(dep_id)
            if dep is None or dep.status != TaskStatus.DONE:
                return False
        return True

    def _is_blocked_by_dependency(self, task: Task, task_map: dict[str, Task]) -> bool:
        for dep_id in task.dependencies:
            dep = task_map.get(dep_id)
            if dep is None:
                continue
            if dep.status in {TaskStatus.FAILED, TaskStatus.BLOCKED}:
                return True
        return False

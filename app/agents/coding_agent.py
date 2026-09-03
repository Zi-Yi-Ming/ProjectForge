from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.implementation import AgentExecutionResult, ProjectMap, TaskContract


class CodingAgentAdapter(ABC):
    @abstractmethod
    def execute(
        self,
        task_contract: TaskContract,
        project_map: ProjectMap,
    ) -> AgentExecutionResult:
        ...

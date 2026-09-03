from __future__ import annotations

from enum import Enum

from app.schemas.project import ProjectStatus


class ProjectLifecycle:
    _ALLOWED_TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
        ProjectStatus.CREATED: {ProjectStatus.ANALYZING},
        ProjectStatus.ANALYZING: {ProjectStatus.PLANNING},
        ProjectStatus.PLANNING: {ProjectStatus.READY},
        ProjectStatus.READY: {ProjectStatus.EXECUTING},
        ProjectStatus.EXECUTING: {ProjectStatus.COMPLETED, ProjectStatus.FAILED, ProjectStatus.BLOCKED},
        ProjectStatus.BLOCKED: {ProjectStatus.EXECUTING, ProjectStatus.FAILED},
        ProjectStatus.COMPLETED: set(),
        ProjectStatus.FAILED: set(),
    }

    @classmethod
    def can_transition(cls, current: ProjectStatus, target: ProjectStatus) -> bool:
        return target in cls._ALLOWED_TRANSITIONS.get(current, set())

    @classmethod
    def terminal_states(cls) -> set[ProjectStatus]:
        return {ProjectStatus.COMPLETED, ProjectStatus.FAILED}

    @classmethod
    def is_terminal(cls, status: ProjectStatus) -> bool:
        return status in cls.terminal_states()

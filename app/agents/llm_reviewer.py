from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from app.schemas.implementation import ProjectMap, TaskContract
from app.schemas.validation import LLMReviewResult


class LLMReviewer(ABC):
    @abstractmethod
    def review(
        self,
        task_contract: TaskContract,
        project_map: ProjectMap,
        diff_text: str,
        deterministic_results: Sequence[str],
        p12_test_results: Sequence[str],
    ) -> LLMReviewResult:
        ...

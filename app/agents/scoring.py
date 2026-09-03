from __future__ import annotations

from app.schemas.research import ResearchOutput
from app.schemas.scoring import RepositoryScore


class RepositoryScorer:
    def __init__(self) -> None:
        self.reasons: list[str] = []
        self.source_facts: list[str] = []

    def run(self, research: ResearchOutput) -> RepositoryScore:
        self.reasons = []
        self.source_facts = []
        score = 0

        score += self._stars(research.github.stars)
        score += self._forks(research.github.forks)
        score += self._completeness(research)
        score += self._depth(research)

        return RepositoryScore(
            score=score,
            reasons=list(self.reasons),
            source_facts=list(self.source_facts),
        )

    def _stars(self, stars: int) -> int:
        if stars >= 10000:
            self.reasons.append("Very high GitHub star count")
            self.source_facts.append(f"stars: {stars}")
            return 50
        if stars >= 1000:
            self.reasons.append("High GitHub star count")
            self.source_facts.append(f"stars: {stars}")
            return 30
        if stars >= 100:
            self.reasons.append("Moderate GitHub star count")
            self.source_facts.append(f"stars: {stars}")
            return 20
        if stars > 0:
            self.reasons.append("Some GitHub stars")
            self.source_facts.append(f"stars: {stars}")
            return 10
        return 0

    def _forks(self, forks: int) -> int:
        if forks >= 500:
            self.reasons.append("Strong fork activity")
            self.source_facts.append(f"forks: {forks}")
            return 20
        if forks >= 50:
            self.reasons.append("Moderate fork activity")
            self.source_facts.append(f"forks: {forks}")
            return 10
        if forks > 0:
            self.source_facts.append(f"forks: {forks}")
            return 5
        return 0

    def _completeness(self, research: ResearchOutput) -> int:
        score = 0
        if research.github.description:
            self.reasons.append("Complete project metadata")
            self.source_facts.append(f"description: {research.github.description}")
            score += 5
        if research.github.language:
            self.source_facts.append(f"language: {research.github.language}")
            score += 5
        topics = research.github.topics or []
        if topics:
            self.source_facts.append(f"topics: {', '.join(topics[:5])}")
            score += min(len(topics) * 2, 10)
        if research.github.license:
            self.source_facts.append(f"license: {research.github.license}")
            score += 5
        if research.github.updated_at:
            self.reasons.append("Repository has recent update metadata")
            self.source_facts.append(f"updated_at: {research.github.updated_at}")
            score += 5
        return score

    def _depth(self, research: ResearchOutput) -> int:
        score = 0
        if research.summary:
            self.source_facts.append(f"summary: {research.summary}")
            score += 5
        key_points = research.key_points or []
        if key_points:
            score += min(len(key_points) * 2, 6)
            for kp in key_points[:3]:
                self.source_facts.append(f"key_point: {kp}")
        technical_details = research.technical_details or []
        if technical_details:
            score += min(len(technical_details) * 2, 4)
            for td in technical_details[:2]:
                self.source_facts.append(f"technical_detail: {td}")
        interesting_facts = research.interesting_facts or []
        if interesting_facts:
            score += min(len(interesting_facts) * 2, 4)
            for if_ in interesting_facts[:2]:
                self.source_facts.append(f"interesting_fact: {if_}")
        use_cases = research.use_cases or []
        if use_cases:
            score += min(len(use_cases) * 2, 4)
            for uc in use_cases[:2]:
                self.source_facts.append(f"use_case: {uc}")
        return score

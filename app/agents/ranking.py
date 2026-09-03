from __future__ import annotations

from app.schemas.research import ResearchOutput
from app.schemas.scoring import RepositoryScore
from app.schemas.ranking import RankedRepository


class RepositoryRanker:
    def __init__(self, top_n: int = 10) -> None:
        self.top_n = top_n

    def rank(self, items: list[tuple[ResearchOutput, RepositoryScore]]) -> list[RankedRepository]:
        if not items:
            return []

        scored: list[tuple[float, str, dict[str, float], list[str], ResearchOutput]] = []
        for research, repository_score in items:
            breakdown, reasons = self._score(research, repository_score)
            total = sum(breakdown.values())
            scored.append((total, research.topic, breakdown, reasons, research))

        scored.sort(key=lambda x: (-x[0], x[1]))

        results = []
        for idx, (total, topic, breakdown, reasons, research) in enumerate(scored[: self.top_n], start=1):
            results.append(
                RankedRepository(
                    rank=idx,
                    repo=topic,
                    score=round(total, 2),
                    breakdown=breakdown,
                    reasons=reasons,
                )
            )
        return results

    def _score(self, research: ResearchOutput, repository_score: RepositoryScore) -> tuple[dict[str, float], list[str]]:
        breakdown: dict[str, float] = {}
        reasons: list[str] = []

        popularity = self._popularity(research)
        breakdown["popularity"] = popularity
        if popularity >= 80:
            reasons.append("Strong community popularity")
        elif popularity >= 50:
            reasons.append("Moderate community popularity")

        activity = self._activity(research)
        breakdown["activity"] = activity
        if activity >= 80:
            reasons.append("Active repository signals")
        elif activity >= 50:
            reasons.append("Moderate repository activity")

        completeness = self._completeness(research)
        breakdown["completeness"] = completeness
        if completeness >= 80:
            reasons.append("Complete project metadata")

        discovery = self._discovery(popularity, activity, completeness, research)
        breakdown["discovery"] = discovery
        if discovery >= 70:
            reasons.append("High discovery priority among current candidates")

        return breakdown, reasons

    def _popularity(self, research: ResearchOutput) -> float:
        stars = research.github.stars or 0
        forks = research.github.forks or 0

        if stars >= 1000000:
            star_score = 150.0
        elif stars >= 100000:
            star_score = 100.0 + (stars - 100000) / (1000000 - 100000) * 50.0
        elif stars >= 10000:
            star_score = 60.0 + (stars - 10000) / (100000 - 10000) * 40.0
        elif stars >= 1000:
            star_score = 30.0 + (stars - 1000) / (10000 - 1000) * 30.0
        elif stars >= 100:
            star_score = 10.0 + (stars - 100) / (1000 - 100) * 20.0
        elif stars > 0:
            star_score = stars / 100.0 * 10.0
        else:
            star_score = 0.0

        if forks >= 100000:
            fork_score = 150.0
        elif forks >= 50000:
            fork_score = 100.0 + (forks - 50000) / (100000 - 50000) * 50.0
        elif forks >= 10000:
            fork_score = 60.0 + (forks - 10000) / (50000 - 10000) * 40.0
        elif forks >= 1000:
            fork_score = 30.0 + (forks - 1000) / (10000 - 1000) * 30.0
        elif forks >= 100:
            fork_score = 10.0 + (forks - 100) / (1000 - 100) * 20.0
        elif forks > 0:
            fork_score = forks / 100.0 * 10.0
        else:
            fork_score = 0.0

        return round(star_score * 0.7 + fork_score * 0.3, 2)

    def _activity(self, research: ResearchOutput) -> float:
        score = 0.0
        if research.github.updated_at:
            score += 40.0

        key_points = research.key_points or []
        if key_points:
            score += min(len(key_points) * 10.0, 20.0)

        technical_details = research.technical_details or []
        if technical_details:
            score += min(len(technical_details) * 10.0, 20.0)

        interesting_facts = research.interesting_facts or []
        if interesting_facts:
            score += min(len(interesting_facts) * 10.0, 20.0)

        return min(score, 100.0)

    def _completeness(self, research: ResearchOutput) -> float:
        score = 0.0
        if research.github.description:
            score += 25.0
        if research.github.language:
            score += 20.0
        topics = research.github.topics or []
        if topics:
            score += min(len(topics) * 5.0, 25.0)
        if research.github.license:
            score += 15.0
        if research.github.updated_at:
            score += 15.0
        return min(score, 100.0)

    def _discovery(self, popularity: float, activity: float, completeness: float, research: ResearchOutput) -> float:
        score = popularity * 0.30 + activity * 0.35 + completeness * 0.35

        key_points = research.key_points or []
        if key_points:
            score += min(len(key_points) * 2.0, 10.0)

        if research.use_cases:
            score += min(len(research.use_cases) * 2.0, 10.0)

        if research.interesting_facts:
            score += min(len(research.interesting_facts) * 2.0, 10.0)

        return min(score, 100.0)

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.content import ContentPackage
from app.schemas.research import ResearchOutput


class QualityResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class QualityGate:
    EXPECTED_PLATFORMS = {"overview", "blog", "x", "reddit"}

    def run(self, package: ContentPackage, research: ResearchOutput) -> QualityResult:
        reasons: list[str] = []

        platform_result = self._check_platforms(package)
        if not platform_result:
            reasons.append("Missing expected platform content")
        content_result = self._check_non_empty_content(package)
        if not content_result:
            reasons.append("Empty content detected")
        facts_result = self._check_source_facts(package, research)
        if not facts_result:
            reasons.append("Source facts do not trace back to research")

        return QualityResult(passed=not reasons, reasons=reasons)

    def _check_platforms(self, package: ContentPackage) -> bool:
        return set(package.contents.keys()) == self.EXPECTED_PLATFORMS

    def _check_non_empty_content(self, package: ContentPackage) -> bool:
        for platform, content in package.contents.items():
            if not content.content or not content.content.strip():
                return False
        return True

    def _check_source_facts(self, package: ContentPackage, research: ResearchOutput) -> bool:
        for platform, content in package.contents.items():
            if not content.source_facts:
                return False
            for fact in content.source_facts:
                if not _fact_traces_to_research(fact, research):
                    return False
        return True


def _fact_traces_to_research(fact: str, research: ResearchOutput) -> bool:
    if fact.startswith("stars: "):
        return research.github.stars == int(fact.split(": ", 1)[1])
    if fact.startswith("forks: "):
        return research.github.forks == int(fact.split(": ", 1)[1])
    if fact.startswith("language: "):
        return research.github.language == fact.split(": ", 1)[1]
    if fact.startswith("description: "):
        return research.github.description == fact.split(": ", 1)[1]
    if fact.startswith("license: "):
        return research.github.license == fact.split(": ", 1)[1]
    if fact.startswith("updated_at: "):
        return bool(research.github.updated_at) and research.github.updated_at == fact.split(": ", 1)[1]
    if fact.startswith("topic: "):
        return research.topic == fact.split(": ", 1)[1]
    if fact.startswith("summary: "):
        return research.summary == fact.split(": ", 1)[1]
    if fact.startswith("topics: "):
        raw = fact.split(": ", 1)[1]
        fact_topics = [t.strip() for t in raw.split(",") if t.strip()]
        return all(topic in (research.github.topics or []) for topic in fact_topics) and len(fact_topics) > 0
    if fact.startswith("key_point: "):
        return fact.split(": ", 1)[1] in (research.key_points or [])
    if fact.startswith("technical_detail: "):
        return fact.split(": ", 1)[1] in (research.technical_details or [])
    if fact.startswith("interesting_fact: "):
        return fact.split(": ", 1)[1] in (research.interesting_facts or [])
    if fact.startswith("use_case: "):
        return fact.split(": ", 1)[1] in (research.use_cases or [])
    return False

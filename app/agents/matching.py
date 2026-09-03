from __future__ import annotations

import re
from typing import Iterable

from app.agents.jd_analyzer import _ENGINEERING_TOPIC_MAP, _normalize_skill
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.research import ResearchOutput
from app.schemas.scoring import RepositoryScore


_MAX_REPOSITORY_SCORE = 123


def _collect_research_text(research: ResearchOutput) -> str:
    parts: list[str] = []
    if research.github.language:
        parts.append(research.github.language)
    if research.summary:
        parts.append(research.summary)
    if research.github.topics:
        parts.extend(research.github.topics)
    if research.key_points:
        parts.extend(research.key_points)
    if research.technical_details:
        parts.extend(research.technical_details)
    if research.interesting_facts:
        parts.extend(research.interesting_facts)
    if research.use_cases:
        parts.extend(research.use_cases)
    return "\n".join(parts)


def _is_evidence_present(evidence_text: str, canonical_skill: str) -> bool:
    pattern = re.compile(re.escape(canonical_skill), re.IGNORECASE)
    for match in pattern.finditer(evidence_text):
        start, end = match.start(), match.end()
        if start > 0 and evidence_text[start - 1].isalnum():
            continue
        if end < len(evidence_text) and evidence_text[end].isalnum():
            continue
        return True
    return False


def _coverage(total: int, matched: int) -> int:
    if total <= 0:
        return 0
    return round(matched / total * 100)


class ProjectMatcher:
    def match(self, jd: JDProfile, research: ResearchOutput, score: RepositoryScore) -> ProjectFit:
        evidence_text = _collect_research_text(research)

        matched_required: list[str] = []
        missing_required: list[str] = []
        for skill in jd.required_skills:
            canonical = _normalize_skill(skill)
            if _is_evidence_present(evidence_text, canonical):
                matched_required.append(canonical)
            else:
                missing_required.append(canonical)

        matched_preferred: list[str] = []
        missing_preferred: list[str] = []
        for skill in jd.preferred_skills:
            canonical = _normalize_skill(skill)
            if _is_evidence_present(evidence_text, canonical):
                matched_preferred.append(canonical)
            else:
                missing_preferred.append(canonical)

        matched_topics: list[str] = []
        missing_topics: list[str] = []
        for topic in jd.engineering_topics:
            if _is_evidence_present(evidence_text, topic):
                matched_topics.append(topic)
            else:
                missing_topics.append(topic)

        required_coverage = _coverage(len(jd.required_skills), len(matched_required))
        preferred_coverage = _coverage(len(jd.preferred_skills), len(matched_preferred))
        topic_coverage = _coverage(len(jd.engineering_topics), len(matched_topics))

        raw_quality = score.score
        normalized_quality = min(round(raw_quality / _MAX_REPOSITORY_SCORE * 100), 100)

        final_score = int(
            round(
                required_coverage * 0.40
                + topic_coverage * 0.25
                + preferred_coverage * 0.10
                + normalized_quality * 0.25
            )
        )
        final_score = max(0, min(100, final_score))

        reasons: list[str] = []
        reasons.append(f"Required skills coverage: {len(matched_required)}/{len(jd.required_skills)}")
        if matched_required:
            reasons.append(f"Matched required skills: {', '.join(matched_required)}")
        if missing_required:
            reasons.append(f"Missing required skills: {', '.join(missing_required)}")
        reasons.append(f"Engineering topic coverage: {len(matched_topics)}/{len(jd.engineering_topics)}")
        if matched_topics:
            reasons.append(f"Matched engineering topics: {', '.join(matched_topics)}")
        if missing_topics:
            reasons.append(f"Missing engineering topics: {', '.join(missing_topics)}")
        if jd.preferred_skills:
            reasons.append(f"Preferred skills coverage: {len(matched_preferred)}/{len(jd.preferred_skills)}")
            if matched_preferred:
                reasons.append(f"Matched preferred skills: {', '.join(matched_preferred)}")
            if missing_preferred:
                reasons.append(f"Missing preferred skills: {', '.join(missing_preferred)}")
        reasons.append(f"Project quality score: {raw_quality}")
        reasons.append(f"Final project fit score: {final_score}")

        return ProjectFit(
            repo=research.topic or research.github.html_url or "",
            score=final_score,
            required_skill_coverage=required_coverage,
            preferred_skill_coverage=preferred_coverage,
            engineering_topic_coverage=topic_coverage,
            project_quality_score=raw_quality,
            matched_required_skills=matched_required,
            missing_required_skills=missing_required,
            matched_preferred_skills=matched_preferred,
            missing_preferred_skills=missing_preferred,
            matched_engineering_topics=matched_topics,
            missing_engineering_topics=missing_topics,
            reasons=reasons,
        )

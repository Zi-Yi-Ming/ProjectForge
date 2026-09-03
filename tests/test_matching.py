from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.jd_analyzer import JDAnalyzer
from app.agents.matching import ProjectMatcher
from app.schemas.jd import JDProfile
from app.schemas.research import ResearchOutput, GitHubInfo
from app.schemas.scoring import RepositoryScore


analyzer = JDAnalyzer()
matcher = ProjectMatcher()


def _make_research(
    topic: str = "example/project",
    language: str = "",
    summary: str = "",
    topics: list[str] | None = None,
    key_points: list[str] | None = None,
    technical_details: list[str] | None = None,
    interesting_facts: list[str] | None = None,
    use_cases: list[str] | None = None,
    description: str = "",
) -> ResearchOutput:
    return ResearchOutput(
        topic=topic,
        summary=summary,
        key_points=key_points or [],
        technical_details=technical_details or [],
        interesting_facts=interesting_facts or [],
        use_cases=use_cases or [],
        github=GitHubInfo(
            language=language,
            topics=topics or [],
            description=description,
        ),
    )


def _make_score(score: int = 0) -> RepositoryScore:
    return RepositoryScore(score=score)


def test_full_required_match() -> None:
    jd = JDProfile(
        role="Backend Engineer",
        required_skills=["Java", "Spring Boot", "MySQL"],
        engineering_topics=["REST API", "Unit Testing"],
    )
    research = _make_research(
        language="Java",
        summary="Spring Boot project with REST API and MySQL database.",
        technical_details=["Built on Spring Boot", "Uses MySQL for persistence."],
        key_points=["Language: Java", "REST API support", "Unit testing included."],
    )
    fit = matcher.match(jd, research, _make_score(90))

    assert fit.required_skill_coverage == 100
    assert fit.matched_required_skills == ["Java", "Spring Boot", "MySQL"]
    assert fit.missing_required_skills == []


def test_partial_required_match() -> None:
    jd = JDProfile(
        role="Backend Engineer",
        required_skills=["Java", "Spring Boot", "MySQL", "Redis"],
        engineering_topics=[],
    )
    research = _make_research(
        language="Java",
        summary="Spring Boot project.",
        technical_details=["Built on Spring Boot", "Uses MySQL."],
    )
    fit = matcher.match(jd, research, _make_score(90))

    assert fit.required_skill_coverage == 75
    assert fit.matched_required_skills == ["Java", "Spring Boot", "MySQL"]
    assert fit.missing_required_skills == ["Redis"]


def test_preferred_coverage() -> None:
    jd = JDProfile(
        role="Backend Engineer",
        required_skills=["Java"],
        preferred_skills=["Docker", "Redis"],
        engineering_topics=[],
    )
    research = _make_research(
        language="Java",
        summary="Java project with Docker support.",
        technical_details=["Built with Java.", "Containerized with Docker."],
    )
    fit = matcher.match(jd, research, _make_score(90))

    assert fit.required_skill_coverage == 100
    assert fit.preferred_skill_coverage == 50
    assert fit.matched_preferred_skills == ["Docker"]
    assert fit.missing_preferred_skills == ["Redis"]


def test_strict_spring_cloud_not_matched_by_spring_boot() -> None:
    jd = JDProfile(
        role="Cloud Engineer",
        required_skills=["Spring Cloud"],
        engineering_topics=[],
    )
    research = _make_research(
        language="Java",
        summary="Spring Boot project.",
        technical_details=["Built on Spring Boot."],
    )
    fit = matcher.match(jd, research, _make_score(90))

    assert fit.matched_required_skills == []
    assert fit.missing_required_skills == ["Spring Cloud"]


def test_strict_kafka_not_matched_by_rabbitmq() -> None:
    jd = JDProfile(
        role="Messaging Engineer",
        required_skills=["Kafka"],
        engineering_topics=[],
    )
    research = _make_research(
        language="Java",
        summary="Messaging project.",
        technical_details=["Uses RabbitMQ for messaging."],
    )
    fit = matcher.match(jd, research, _make_score(90))

    assert fit.matched_required_skills == []
    assert fit.missing_required_skills == ["Kafka"]


def test_engineering_topic_exact_match_only() -> None:
    jd = JDProfile(
        role="Backend Engineer",
        required_skills=["Java"],
        engineering_topics=["REST API", "Unit Testing", "High Concurrency"],
    )
    research = _make_research(
        language="Java",
        summary="Java backend.",
        technical_details=["REST API design", "Unit testing coverage."],
    )
    fit = matcher.match(jd, research, _make_score(90))

    assert fit.matched_engineering_topics == ["REST API", "Unit Testing"]
    assert fit.missing_engineering_topics == ["High Concurrency"]
    assert fit.engineering_topic_coverage == round(2 / 3 * 100)


def test_no_inference_from_tech_stack() -> None:
    jd = JDProfile(
        role="Backend Engineer",
        required_skills=["Java"],
        engineering_topics=["High Concurrency"],
    )
    research = _make_research(
        language="Java",
        summary="Java and Redis project.",
        technical_details=["Uses Java and Redis."],
    )
    fit = matcher.match(jd, research, _make_score(90))

    assert fit.matched_engineering_topics == []
    assert fit.missing_engineering_topics == ["High Concurrency"]


def test_repository_score_reused() -> None:
    jd = JDProfile(
        role="Backend Engineer",
        required_skills=["Java"],
        engineering_topics=[],
    )
    research = _make_research(language="Java", summary="Java project.")
    fit = matcher.match(jd, research, _make_score(110))

    assert fit.project_quality_score == 110


def test_reasons_non_empty_and_explainable() -> None:
    jd = JDProfile(
        role="Backend Engineer",
        required_skills=["Java", "MySQL"],
        preferred_skills=["Docker"],
        engineering_topics=["REST API", "Debugging"],
    )
    research = _make_research(
        language="Java",
        summary="Java backend.",
        technical_details=["REST API support."],
    )
    fit = matcher.match(jd, research, _make_score(100))

    assert fit.reasons
    assert any("Required skills coverage:" in reason for reason in fit.reasons)
    assert any("Matched required skills:" in reason for reason in fit.reasons)
    assert any("Missing required skills:" in reason for reason in fit.reasons)
    assert any("Engineering topic coverage:" in reason for reason in fit.reasons)
    assert any("Project quality score:" in reason for reason in fit.reasons)
    assert any("Final project fit score:" in reason for reason in fit.reasons)


def test_determinism() -> None:
    jd = JDProfile(
        role="Backend Engineer",
        required_skills=["Java", "Spring Boot", "MySQL"],
        preferred_skills=["Docker"],
        engineering_topics=["REST API", "Debugging"],
    )
    research = _make_research(
        language="Java",
        summary="Spring Boot project.",
        technical_details=["REST API and MySQL."],
    )
    score = _make_score(90)

    first = matcher.match(jd, research, score)
    second = matcher.match(jd, research, score)

    assert first.model_dump() == second.model_dump()


def test_empty_required_skills() -> None:
    jd = JDProfile(
        role="Engineer",
        required_skills=[],
        engineering_topics=["REST API"],
    )
    research = _make_research(
        language="Python",
        summary="Python project.",
        technical_details=["REST API support."],
    )
    fit = matcher.match(jd, research, _make_score(50))

    assert fit.required_skill_coverage == 0
    assert fit.matched_required_skills == []
    assert fit.missing_required_skills == []


def test_empty_preferred_skills() -> None:
    jd = JDProfile(
        role="Engineer",
        required_skills=["Python"],
        preferred_skills=[],
        engineering_topics=[],
    )
    research = _make_research(language="Python", summary="Python project.")
    fit = matcher.match(jd, research, _make_score(50))

    assert fit.preferred_skill_coverage == 0
    assert fit.matched_preferred_skills == []
    assert fit.missing_preferred_skills == []


def test_real_fixture_spring_boot() -> None:
    jd_text = Path("tests/fixtures/java_backend_intern.md").read_text(encoding="utf-8")
    jd = analyzer.analyze(jd_text)
    research = ResearchOutput.model_validate(
        __import__("json").loads(Path("examples/spring-boot/research.json").read_text(encoding="utf-8"))
    )
    fit = matcher.match(jd, research, RepositoryScore(score=110))

    assert fit.repo == "spring-projects/spring-boot"
    assert "Java" in fit.matched_required_skills
    assert "MyBatis" in fit.missing_required_skills
    assert fit.project_quality_score == 110
    assert 0 <= fit.score <= 100

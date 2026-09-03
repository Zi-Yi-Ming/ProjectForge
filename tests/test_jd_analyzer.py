from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.jd_analyzer import JDAnalyzer
from app.schemas.jd import JDProfile


analyzer = JDAnalyzer()


def test_basic_java_jd() -> None:
    text = "2027届毕业生，计算机相关专业，熟悉 Java、Spring Boot、MySQL、MyBatis，了解 Redis。"
    profile = analyzer.analyze(text)

    assert profile.role == "Unknown"
    assert profile.seniority == "intern"
    assert profile.graduation_requirements == ["2027"]
    required = set(profile.required_skills)
    assert {"Java", "Spring Boot", "MySQL", "MyBatis", "Redis"}.issubset(required)


def test_preferred_skills_only_go_to_preferred() -> None:
    text = "熟悉 Java、Spring Boot、MySQL，有 Docker、Redis 使用经验者优先。"
    profile = analyzer.analyze(text)

    assert set(profile.required_skills) == {"Java", "Spring Boot", "MySQL"}
    assert set(profile.preferred_skills) == {"Docker", "Redis"}


def test_engineering_topics_extracted() -> None:
    text = "负责 RESTful API 开发、单元测试、问题排查和技术文档编写。"
    profile = analyzer.analyze(text)

    assert "REST API" in profile.engineering_topics
    assert "Unit Testing" in profile.engineering_topics
    assert "Debugging" in profile.engineering_topics
    assert "Documentation" in profile.engineering_topics


def test_skill_normalization() -> None:
    text = "JAVA、SpringBoot、Mysql、Mybatis、Redis。"
    profile = analyzer.analyze(text)

    assert set(profile.required_skills) == {"Java", "Spring Boot", "MySQL", "MyBatis", "Redis"}


def test_skill_deduplication() -> None:
    text = "Java java JAVA"
    profile = analyzer.analyze(text)

    assert profile.required_skills == ["Java"]
    assert profile.preferred_skills == []


def test_empty_jd_returns_valid_profile() -> None:
    profile = analyzer.analyze("")

    assert isinstance(profile, JDProfile)
    assert profile.role == "Unknown"
    assert profile.graduation_requirements == []
    assert profile.required_skills == []
    assert profile.preferred_skills == []
    assert profile.engineering_topics == []
    assert profile.domain_keywords == []


def test_no_graduation_requirement() -> None:
    text = "负责后端模块开发，熟悉 Java、MySQL。"
    profile = analyzer.analyze(text)

    assert profile.graduation_requirements == []


def test_no_preferred_skills() -> None:
    text = "2027届毕业生，熟悉 Java、Spring Boot、MySQL、MyBatis、Redis。"
    profile = analyzer.analyze(text)

    assert profile.preferred_skills == []


def test_domain_keywords_extracted() -> None:
    text = "参与公司 AI Agent 平台和 RAG 知识库系统研发。"
    profile = analyzer.analyze(text)

    assert "AI Agent" in profile.domain_keywords
    assert "RAG" in profile.domain_keywords


def test_determinism() -> None:
    text = Path("tests/fixtures/java_backend_intern.md").read_text(encoding="utf-8")
    first = analyzer.analyze(text)
    second = analyzer.analyze(text)

    assert first.model_dump() == second.model_dump()


def test_real_fixture_java_backend_intern_2() -> None:
    text = Path("tests/fixtures/java_backend_intern_2.md").read_text(encoding="utf-8")
    profile = analyzer.analyze(text)

    assert "Java" in profile.required_skills
    assert "Spring Boot" in profile.required_skills
    assert "MySQL" in profile.required_skills
    assert "MyBatis" in profile.required_skills
    assert "Redis" in profile.required_skills
    assert "REST API" in profile.engineering_topics
    assert "Unit Testing" in profile.engineering_topics
    assert profile.graduation_requirements == ["2027"]
    assert profile.seniority == "intern"


def test_real_fixture_ai_agent_backend() -> None:
    text = Path("tests/fixtures/ai_agent_backend.md").read_text(encoding="utf-8")
    profile = analyzer.analyze(text)

    assert "Python" in profile.required_skills
    assert "LangChain" in profile.required_skills
    assert "LangGraph" in profile.required_skills
    assert "Dify" in profile.required_skills
    assert "Milvus" in profile.required_skills or "PGVector" in profile.required_skills
    assert "REST API" in profile.required_skills
    assert "Docker" in profile.required_skills
    assert "Kafka" in profile.preferred_skills or "Function Calling" in profile.preferred_skills
    assert "AI Agent" in profile.domain_keywords
    assert "RAG" in profile.domain_keywords
    assert "High Concurrency" in profile.engineering_topics or "Distributed Systems" in profile.engineering_topics

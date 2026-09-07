from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from app.schemas.jd import JDProfile


_SKILL_NORMALIZATION: dict[str, str] = {
    "java": "Java",
    "spring": "Spring",
    "spring mvc": "Spring MVC",
    "springboot": "Spring Boot",
    "spring boot": "Spring Boot",
    "springcloud": "Spring Cloud",
    "spring cloud": "Spring Cloud",
    "mybatis": "MyBatis",
    "mysql": "MySQL",
    "mssql": "SQL Server",
    "sql server": "SQL Server",
    "postgresql": "PostgreSQL",
    "oracle": "Oracle",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "rabbitmq": "RabbitMQ",
    "kafka": "Kafka",
    "docker": "Docker",
    "linux": "Linux",
    "git": "Git",
    "python": "Python",
    "go": "Go",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "rag": "RAG",
    "ai agent": "AI Agent",
    "ai agents": "AI Agent",
    "function calling": "Function Calling",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "dify": "Dify",
    "milvus": "Milvus",
    "pgvector": "PGVector",
    "rest api": "REST API",
    "restful api": "REST API",
    "restful": "REST API",
    "rest": "REST API",
    "微服务": "微服务",
    "分布式系统": "Distributed Systems",
    "高并发": "High Concurrency",
    "单元测试": "Unit Testing",
    "问题排查": "Debugging",
    "性能优化": "Performance Optimization",
    "系统设计": "System Design",
    "架构设计": "System Design",
    "代码走查": "Code Review",
    "技术文档": "Documentation",
    "数据库设计": "Database Design",
}


_ENGINEERING_TOPIC_MAP: dict[str, str] = {
    "restful api": "REST API",
    "rest api": "REST API",
    "restful": "REST API",
    "rest": "REST API",
    "单元测试": "Unit Testing",
    "问题排查": "Debugging",
    "故障排查": "Debugging",
    "性能优化": "Performance Optimization",
    "高并发": "High Concurrency",
    "分布式系统": "Distributed Systems",
    "系统设计": "System Design",
    "架构设计": "System Design",
    "代码走查": "Code Review",
    "code review": "Code Review",
    "技术文档": "Documentation",
    "数据库设计": "Database Design",
    "api设计": "REST API",
    "接口设计": "REST API",
    "debugging": "Debugging",
    "unit testing": "Unit Testing",
    "documentation": "Documentation",
    "system design": "System Design",
    "database design": "Database Design",
}


_DOMAIN_PHRASES: tuple[str, ...] = (
    "ai agent",
    "agents",
    "rag",
    "知识库",
    "知识图谱",
    "大模型",
    "llm",
    "multimodal",
    "多模态",
    "nlp",
    "cv",
    "saaS",
    "供应链",
    "电商",
    "e-commerce",
    "金融",
    "fintech",
    "自动驾驶",
    "游戏",
    "游戏引擎",
    "云原生",
    "kubernetes",
    "k8s",
    "infra",
    "基础架构",
    "数据平台",
    "数据仓库",
    "推荐系统",
    "搜索",
    "广告",
    "支付",
    "物流",
    "工业",
    "cad",
    "医疗",
    "教育",
    "物联网",
    "iot",
    "安全",
    "安全测试",
    "渗透测试",
)


_GRADUATION_YEAR_RE = re.compile(r"\b(20\d{2})\s*(?:届|级|年毕业|届毕业生|graduate)?\b")
_INTERN_YEAR_RE = re.compile(r"\b(20\d{2})\s*(?:届|级)\b")


@dataclass(frozen=True)
class _Extracted:
    graduation_years: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)


def _dedupe_preserve(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item:
            continue
        key = item.strip()
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _normalize_skill(token: str) -> str:
    normalized = _SKILL_NORMALIZATION.get(token.lower().strip(), token.strip())
    return normalized


def _normalize_skills(tokens: Iterable[str]) -> list[str]:
    return _dedupe_preserve(_normalize_skill(t) for t in tokens)


def _chunk_windows(text: str, center: int, window: int = 40) -> str:
    start = max(0, center - window)
    end = min(len(text), center + window)
    return text[start:end]


def _extract_graduation_years(text: str) -> list[str]:
    years = _GRADUATION_YEAR_RE.findall(text)
    if not years:
        m = _INTERN_YEAR_RE.search(text)
        if m:
            years = [m.group(1)]
    return _dedupe_preserve(years)


def _split_clauses(text: str) -> list[str]:
    clauses = re.split(r"[，,。；;]+", text)
    return [clause.strip() for clause in clauses if clause.strip()]


def _clause_label(clause: str) -> str:
    lower_clause = clause.lower()
    if re.search(r"(?:plus|bonus|优先|优先考虑|有.*经验者优先|有.*经验优先|加分项|了解.*优先|了解.*者优先|preferred)", lower_clause):
        return "preferred"
    if re.search(r"(?:熟悉|精通|掌握|具备|要求|必须|熟练)", lower_clause):
        return "required"
    return "required"


def _classify_skill_mentions(text: str) -> _Extracted:
    lower_text = text.lower()
    extracted = _Extracted()

    skill_tokens = sorted(_SKILL_NORMALIZATION.keys(), key=len, reverse=True)
    clauses = _split_clauses(text)

    consumed: list[tuple[int, int]] = []

    def _is_consumed(start: int, end: int) -> bool:
        for c_start, c_end in consumed:
            if start >= c_start and end <= c_end:
                return True
            if start < c_end and end > c_start:
                return True
        return False

    for clause in clauses:
        label = _clause_label(clause)
        lower_clause = clause.lower()
        clause_start = lower_text.find(lower_clause)
        if clause_start == -1:
            clause_start = 0

        for token in skill_tokens:
            for match in re.finditer(re.escape(token), lower_clause, re.IGNORECASE):
                start = clause_start + match.start()
                end = clause_start + match.end()
                if _is_consumed(start, end):
                    continue
                if start > 0 and lower_text[start - 1].isalnum():
                    continue
                if end < len(lower_text) and lower_text[end].isalnum():
                    continue
                consumed.append((start, end))
                normalized_token = _normalize_skill(lower_text[start:end])
                if label == "preferred":
                    extracted.preferred_skills.append(normalized_token)
                else:
                    extracted.required_skills.append(normalized_token)

    return extracted


def _extract_engineering_topics(text: str) -> list[str]:
    lower_text = text.lower()
    hits: list[str] = []
    for phrase, canonical in _ENGINEERING_TOPIC_MAP.items():
        if phrase in lower_text and canonical not in hits:
            hits.append(canonical)
    return hits


def _extract_domain_keywords(text: str) -> list[str]:
    lower_text = text.lower()
    hits: list[str] = []
    for phrase in _DOMAIN_PHRASES:
        if phrase in lower_text:
            canonical = _SKILL_NORMALIZATION.get(phrase, phrase.title() if phrase.islower() else phrase)
            if canonical not in hits:
                hits.append(canonical)
    return hits


def _extract_responsibilities(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    results: list[str] = []
    for line in lines:
        normalized = re.sub(r"^[\-\*\•]\s*", "", line)
        normalized = re.sub(r"^(\d+[\.\)]\s*)", "", normalized).strip()
        if len(normalized) < 4:
            continue
        if re.search(r"(?:负责|参与|开发|设计|实现|维护|编写|推进|支持|构建|搭建|优化|负责)", normalized):
            results.append(normalized)
    return _dedupe_preserve(results[:20])


def _guess_role(text: str) -> str:
    lower_text = text.lower()
    role_hints = []
    for pattern in [
        r"(java\s*backend\s*intern)",
        r"(java\s*后端\s*开发\s*实习生)",
        r"(ai\s*agent\s*后端\s*开发\s*工程师)",
        r"(ai\s*agent\s*后端)",
        r"(java\s*后端)",
        r"(python\s*后端)",
        r"(go\s*后端)",
        r"(前端\s*开发)",
        r"(react\s*开发)",
        r"(vue\s*开发)",
        r"(算法\s*工程师)",
        r"(测试\s*工程师)",
        r"(devops)",
        r"(sre)",
        r"(后端\s*开发)",
        r"(后端\s*实习生)",
        r"(java\s*后端\s*实习生)",
        r"(ai\s*agent\s*后端\s*工程师)",
    ]:
        m = re.search(pattern, lower_text)
        if m:
            role_hints.append(m.group(1).strip())

    if role_hints:
        return " ".join(word.capitalize() if word.isalpha() else word for word in role_hints[0].split())
    return "Unknown"


def _guess_seniority(text: str, graduation_years: list[str]) -> str:
    lower_text = text.lower()
    if re.search(r"\bintern\b|实习生|实习", lower_text) or graduation_years:
        return "intern"
    if re.search(r"\bentry\b|初级|入门", lower_text):
        return "entry"
    if re.search(r"\bjunior\b|应届", lower_text):
        return "junior"
    if re.search(r"\bsenior\b|高级", lower_text):
        return "senior"
    return "unknown"


_EDUCATION_TOKENS = (
    "本科及以上",
    "本科",
    "硕士及以上",
    "硕士",
    "博士",
    "大专",
    "专科",
    "研究生",
    "计算机相关专业",
)


def _extract_education(text: str) -> list[str]:
    lower_text = text.lower()
    hits: list[str] = []
    for token in _EDUCATION_TOKENS:
        if token in lower_text and token not in hits:
            hits.append(token)
    return hits


class JDAnalyzer:
    def analyze(self, jd_text: str) -> JDProfile:
        cleaned = jd_text.strip()
        lower_text = cleaned.lower()

        extracted = _classify_skill_mentions(cleaned)
        graduation_years = _extract_graduation_years(cleaned)

        required_skills = _normalize_skills(extracted.required_skills)
        preferred_skills = _normalize_skills(extracted.preferred_skills)
        responsibilities = _extract_responsibilities(cleaned)
        engineering_topics = _extract_engineering_topics(cleaned)
        domain_keywords = _extract_domain_keywords(cleaned)
        role = _guess_role(cleaned)
        seniority = _guess_seniority(cleaned, graduation_years)

        education_hints = _extract_education(cleaned)

        return JDProfile(
            role=role,
            seniority=seniority,
            education=education_hints,
            graduation_requirements=graduation_years,
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            engineering_topics=engineering_topics,
            responsibilities=responsibilities,
            domain_keywords=domain_keywords,
        )

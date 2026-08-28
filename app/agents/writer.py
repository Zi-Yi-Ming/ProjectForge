from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.providers.base import ChatProvider
from app.providers.cache import cache_get, cache_set
from app.schemas.research import ResearchOutput
from app.schemas.script import ScriptOutput

logger = logging.getLogger(__name__)
settings = get_settings()

_GENERIC_SCENE4_PATTERNS = [
    "what makes",
    "solves real problems",
    "stand out",
    "key theme of this project",
    "project strength",
    "another strength",
    "one notable aspect is",
    "projects often emphasize",
    "clean integration into real developer workflows",
    "fits into real",
    "fits on github",
    "built for real-world use",
    "designed for real-world use",
    "real-world use",
    "codebase designed for real-world use",
    "codebase designed for",
]
_GENERIC_SCENE3_PATTERNS = [
    "achieves this through",
    "at its core",
    "a defining characteristic is",
    "codebase designed for real-world use",
    "projects often emphasize",
    "codebase designed for",
    "designed for real-world use",
    "clean integration into real developer workflows",
    "fits into real",
    "fits on github",
    "built for real-world use",
    "real-world use",
]
_GENERIC_SCENE5_PATTERNS = [
    "whether you're building or learning",
    "follow for more tech content",
    "if this looks useful, explore this project",
    "fits into real",
    "fits on github",
    "if you're interested in",
    "see how",
    "explore this project",
    "projects often emphasize",
    "clean integration into real developer workflows",
    "built for real-world use",
    "designed for real-world use",
    "real-world use",
]
_MARKDOWN_PATTERNS = ["**", "__", "`", "```", "* next,", "* first,", "* provide a", "* be opinionated"]
_URL_PATTERN = re.compile(r"https?://\S+")
_PATH_PATTERN = re.compile(r"(?i)(?:^|/)(?:readme|docs?|src|lib|examples?|scripts?|config|assets?)/[\w./-]+")
_CODE_EXT_PATTERN = re.compile(r"(?i)\b\w+\.(?:py|js|ts|java|cpp|c|h|md|txt|json|yaml|yml|toml|ini|cfg)\b")


def _is_generic(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(p in lowered for p in patterns)


def _has_markdown(text: str) -> bool:
    lowered = text.lower()
    return any(p in lowered for p in _MARKDOWN_PATTERNS)


def _clean_bullet(text: str) -> str:
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"__", "", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"^\s*[-*]\s+", "", text)
    text = re.sub(r"^\s*#+\s+", "", text)
    return text.strip()


def _clean_research_text(text: str, max_chars: int = 180) -> str:
    if not text:
        return ""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\*\*[^*]*\*\*", lambda m: m.group(0).strip("*"), text)
    text = re.sub(r"\*[^*]*\*", lambda m: m.group(0).strip("*"), text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.M)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?i)(?:^|/)(?:readme|docs?|src|lib|examples?|scripts?|config|assets?)/[\w./-]+", "", text)
    text = re.sub(r"(?i)(?:\b\w+)?\.(?:py|js|ts|java|cpp|c|h|md|txt|json|yaml|yml|toml|ini|cfg)\b", "", text)
    text = re.sub(r"(?<!\w)\.{2,}(?!\w)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        for sep in [". ", "! ", "? "]:
            idx = text.rfind(sep, 0, max_chars + 1)
            if idx != -1 and idx >= 20:
                text = text[: idx + len(sep)].strip()
                break
    return text.strip()


def _sentence_safe_trim(text: str, max_chars: int = 160) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    for sep in [". ", "! ", "? "]:
        idx = text.rfind(sep, 0, max_chars + 1)
        if idx != -1 and idx >= 20:
            return text[: idx + len(sep)].strip()
    # Fallback: cut at last space before max_chars to avoid fragment
    if " " in text[:max_chars]:
        return text[:max_chars].rsplit(" ", 1)[0].strip()
    return text[:max_chars].strip()


def _fact_words(text: str) -> str:
    """Extract a few content words from a fact for prompt/visual subject."""
    words = re.findall(r"[A-Za-z]{3,}", text or "")
    stop = {"the", "and", "for", "with", "from", "this", "that", "have", "has", "been", "were", "was", "are", "not", "but", "can", "may", "will", "its", "into", "than", "when", "what", "which", "their", "there", "would", "could", "should"}
    keep = [w for w in words if w.lower() not in stop]
    seen = set()
    out = []
    for w in keep:
        low = w.lower()
        if low not in seen:
            seen.add(low)
            out.append(w)
        if len(out) >= 4:
            break
    return ", ".join(out)


def _similarity(a: str, b: str) -> float:
    a_tokens = set(re.findall(r"[a-z0-9]+", a.lower()))
    b_tokens = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = a_tokens & b_tokens
    return len(intersection) / max(len(a_tokens | b_tokens), 1)


def _is_readme_like(text: str, research: ResearchOutput, index: int = -1) -> bool:
    """Reject voiceover that closely mirrors a research raw fact."""
    if not text or not research:
        return False
    candidates = [
        *(research.technical_details or []),
        *(research.interesting_facts or []),
        *(research.use_cases or []),
        research.summary or "",
        research.github.description or "",
    ]
    text_norm = re.sub(r"\s+", " ", text.lower()).strip()
    for raw in candidates:
        if not raw:
            continue
        raw_norm = re.sub(r"\s+", " ", raw.lower()).strip()
        if not raw_norm:
            continue
        # Allow exact matches for Scene 1 (description-based hook) and Scene 3 (tech facts)
        if index in (0, 2) and text_norm == raw_norm:
            continue
        if text_norm == raw_norm:
            return True
        if len(raw_norm) > 40 and raw_norm in text_norm:
            return True
    return False


def _strip_topic_prefix(text: str, topic: str) -> str:
    """Remove redundant topic prefix from a fact to avoid repetition in voiceover."""
    if not text or not topic:
        return text
    lowered = text.lower()
    topic_lower = topic.lower()
    if lowered.startswith(topic_lower):
        rest = text[len(topic):].lstrip(" ,.:;-")
        if rest:
            text = rest
            lowered = text.lower()
    # Also try base names from topic (e.g., "django" from "django/django")
    base_names = [p for p in topic.split("/") if len(p) > 2]
    for name in base_names:
        if lowered.startswith(name.lower()):
            rest = text[len(name):].lstrip(" ,.:;-")
            if rest:
                text = rest
                lowered = text.lower()
            break
    # Strip leading "is a", "is an", "is the" to avoid grammar issues
    for prefix in ["is a ", "is an ", "is the "]:
        if lowered.startswith(prefix):
            text = text[len(prefix):].lstrip(" ,.:;-")
            break
    return text.strip()


def _is_project_definition(text: str, topic: str) -> bool:
    """Check if text contains a project definition pattern near the topic."""
    if not text or not topic:
        return False
    text_lower = text.lower()
    topic_lower = topic.lower()
    # Check for pattern: topic/base-name followed by "is a/an/the" within a short distance
    base_names = [topic_lower] + [p.lower() for p in topic.split("/") if len(p) > 2]
    normalized_names = [name.replace("-", " ").replace("_", " ") for name in base_names]
    for name in list(dict.fromkeys(base_names + normalized_names)):
        idx = text_lower.find(name)
        if idx != -1:
            after = text_lower[idx + len(name):]
            if after.startswith(" is a ") or after.startswith(" is an ") or after.startswith(" is the "):
                return True
    return False


def _is_sentence_fragment(text: str) -> bool:
    """Check if text is a sentence fragment rather than a complete statement."""
    if not text:
        return True
    lowered = text.lower().strip()
    # Fragments starting with conjunctions or lowercase continuations
    fragment_starters = ("and ", "or ", "but ", "nor ", "for ", "so ", "yet ", "thanks ", "thank you ")
    return lowered.startswith(fragment_starters)


def _normalize_topic_name(topic: str) -> str:
    """Normalize a repo/topic name for display, preserving known tech proper nouns."""
    if not topic:
        return topic
    if "/" in topic:
        parts = topic.split("/")
        return "/".join(_canonical_name(p) for p in parts)
    return _canonical_name(topic)


def _canonical_name(name: str) -> str:
    """Return canonical casing for a single project/owner name."""
    lower = name.lower()
    # Compound names with separators
    compound = {
        "spring-boot": "Spring Boot",
        "spring_boot": "Spring Boot",
        "spring boot": "Spring Boot",
        "next.js": "Next.js",
        "next-js": "Next.js",
        "next js": "Next.js",
        "nestjs": "NestJS",
        "nest-js": "NestJS",
        "nest js": "NestJS",
        "django-rest-framework": "Django REST Framework",
        "django_rest_framework": "Django REST Framework",
        "django rest framework": "Django REST Framework",
        "react-native": "React Native",
        "react_native": "React Native",
        "react native": "React Native",
        "type-script": "TypeScript",
        "type_script": "TypeScript",
        "type script": "TypeScript",
        "java-script": "JavaScript",
        "java_script": "JavaScript",
        "java script": "JavaScript",
        "node-js": "Node.js",
        "node_js": "Node.js",
        "node js": "Node.js",
        "vue-js": "Vue.js",
        "vue_js": "Vue.js",
        "vue js": "Vue.js",
        "tensor-flow": "TensorFlow",
        "tensor_flow": "TensorFlow",
        "tensor flow": "TensorFlow",
        "py-torch": "PyTorch",
        "py_torch": "PyTorch",
        "py torch": "PyTorch",
    }
    if lower in compound:
        return compound[lower]
    # Single-word known proper nouns
    single = {
        "javascript": "JavaScript",
        "typescript": "TypeScript",
        "python": "Python",
        "github": "GitHub",
        "django": "Django",
        "react": "React",
        "spring": "Spring",
        "node": "Node",
        "vue": "Vue",
        "angular": "Angular",
        "express": "Express",
        "laravel": "Laravel",
        "rails": "Rails",
        "flask": "Flask",
        "fastapi": "FastAPI",
        "pytorch": "PyTorch",
        "tensorflow": "TensorFlow",
        "kubernetes": "Kubernetes",
        "docker": "Docker",
        "aws": "AWS",
        "azure": "Azure",
        "gcp": "GCP",
        "linux": "Linux",
        "windows": "Windows",
        "macos": "macOS",
        "ios": "iOS",
        "android": "Android",
        "sqlite": "SQLite",
        "postgresql": "PostgreSQL",
        "mysql": "MySQL",
        "mongodb": "MongoDB",
        "redis": "Redis",
        "nginx": "Nginx",
        "npm": "npm",
        "yarn": "Yarn",
        "pip": "pip",
        "conda": "Conda",
    }
    if lower in single:
        return single[lower]
    # Preserve original casing for unknown terms, normalizing separators
    return name.replace("-", " ").replace("_", " ")


def _is_scene5_template(text: str, topic: str) -> bool:
    """Detect banned Scene 5 template phrases."""
    if not text:
        return False
    lowered = text.lower()
    topic_parts = [p.lower() for p in topic.replace("-", " ").replace("_", " ").split("/") if p]
    checks = [
        "if you're interested in",
        "see how",
        "explore this project",
        "if this looks useful, explore this project",
        "fits on github",
        "fits into real",
        "projects often emphasize",
        "clean integration into real developer workflows",
        "built for real-world use",
        "designed for real-world use",
        "real-world use",
    ]
    for part in topic_parts:
        checks.extend([
            f"see how {part} fits",
            f"{part} offers",
            f"{part} is built for",
        ])
    return any(c in lowered for c in checks)


def _topic_label(research: ResearchOutput) -> str:
    return research.topic or research.github.description or research.summary or "this project"


def _pick_best_fact(research: ResearchOutput, prefer: str | None = None) -> str:
    """Pick the best repo-specific fact for a scene, cleaned and sentence-safe."""
    candidates: list[str] = []
    if prefer == "interesting":
        candidates = research.interesting_facts or []
    elif prefer == "use_case":
        candidates = research.use_cases or []
    elif prefer == "tech":
        candidates = research.technical_details or []
    else:
        candidates = (
            research.interesting_facts or research.use_cases or research.technical_details or []
        )
    for raw in candidates:
        cleaned = _clean_research_text(raw, max_chars=180)
        if cleaned and len(cleaned) >= 25:
            return cleaned
    return ""


def _pick_scene3_fact(research: ResearchOutput, topic: str = "") -> str:
    """Scene 3 priority: technical_details > interesting_facts > use_cases > summary.
    Last resort: short repo-specific sentence derived from metadata."""
    topic = topic or research.topic or ""
    candidates = (
        *(research.technical_details or []),
        *(research.interesting_facts or []),
        *(research.use_cases or []),
    )
    language = research.github.language or ""
    summary = research.summary or research.github.description or ""
    for raw in candidates:
        cleaned = _clean_research_text(raw, max_chars=180)
        if (
            cleaned
            and len(cleaned) >= 25
            and not _is_project_definition(cleaned, topic)
            and not _is_sentence_fragment(cleaned)
            and not _is_generic(cleaned, _GENERIC_SCENE3_PATTERNS)
            and cleaned[0].isupper()
            and not cleaned.endswith((":", ",", ";", "-"))
            and not _has_markdown(cleaned)
            and not _URL_PATTERN.search(cleaned)
            and not _PATH_PATTERN.search(cleaned)
            and not _CODE_EXT_PATTERN.search(cleaned)
            and _is_valid_fact_after_clean(cleaned)
        ):
            return cleaned
    # Fallback: use summary/description if it looks like a concrete tech/use fact
    if summary:
        cleaned_summary = _clean_research_text(summary, max_chars=180)
        if (
            cleaned_summary
            and len(cleaned_summary) >= 25
            and not _is_project_definition(cleaned_summary, topic)
            and not _is_sentence_fragment(cleaned_summary)
            and not _is_generic(cleaned_summary, _GENERIC_SCENE3_PATTERNS)
            and cleaned_summary[0].isupper()
            and not cleaned_summary.endswith((":", ",", ";", "-"))
        ):
            return cleaned_summary
    # Last resort: repo-specific sentence from metadata, never generic filler
    if language:
        return f"A {language} repository hosted on GitHub for developers."
    return "A repository available on GitHub for developers."


def _pick_scene4_fact(research: ResearchOutput, scene3_fact: str = "", topic: str = "") -> str:
    """Scene 4 priority: interesting_facts > use_cases > technical_details (excluding scene3).
    Deterministic dedup against scene3_fact."""
    topic = topic or research.topic or ""
    scene3_norm = _clean_research_text(scene3_fact, max_chars=180).lower().strip().rstrip(".") if scene3_fact else ""
    description_norm = (research.summary or research.github.description or "").lower().strip().rstrip(".")
    topic_norm = topic.lower().strip()
    # Priority: interesting_facts > use_cases > technical_details
    candidates = (
        *(research.interesting_facts or []),
        *(research.use_cases or []),
        *(research.technical_details or []),
    )
    for raw in candidates:
        cleaned = _clean_research_text(raw, max_chars=180)
        if (
            cleaned
            and len(cleaned) >= 25
            and not _is_project_definition(cleaned, topic)
            and not _is_sentence_fragment(cleaned)
            and not _is_generic(cleaned, _GENERIC_SCENE4_PATTERNS)
            and not _is_readme_like(cleaned, research)
            and cleaned[0].isupper()
            and not cleaned.endswith((":", ",", ";", "-"))
        ):
            cleaned_norm = cleaned.lower().strip().rstrip(".")
            # Deterministic dedup against scene3
            if scene3_norm:
                if cleaned_norm == scene3_norm:
                    continue
                if scene3_norm and scene3_norm in cleaned_norm:
                    continue
                if cleaned_norm and cleaned_norm in scene3_norm:
                    continue
                if _similarity(cleaned_norm, scene3_norm) > 0.7:
                    continue
            # Dedup against description
            if description_norm:
                if _similarity(cleaned_norm, description_norm) > 0.6:
                    continue
                if description_norm in cleaned_norm:
                    continue
            # Dedup against topic prefix
            if topic_norm and cleaned_norm.startswith(topic_norm):
                continue
            return cleaned
    # If scene3 fell back to summary, try interesting/use/tech that were skipped earlier
    for raw in candidates:
        cleaned = _clean_research_text(raw, max_chars=180)
        if (
            cleaned
            and len(cleaned) >= 25
            and not _is_project_definition(cleaned, topic)
            and not _is_sentence_fragment(cleaned)
            and cleaned[0].isupper()
            and not cleaned.endswith((":", ",", ";", "-"))
        ):
            cleaned_norm = cleaned.lower().strip().rstrip(".")
            if scene3_norm and _similarity(cleaned_norm, scene3_norm) > 0.7:
                continue
            if description_norm and _similarity(cleaned_norm, description_norm) > 0.6:
                continue
            if topic_norm and cleaned_norm.startswith(topic_norm):
                continue
            return cleaned
    return ""


def _title_case_fact(text: str) -> str:
    """Title-case a fact for voiceover, preserving known proper nouns."""
    proper_nouns = {
        "javascript",
        "typescript",
        "python",
        "java",
        "github",
        "django",
        "react",
        "spring",
        "api",
        "rest",
        "graphql",
        "cli",
        "orm",
        "sql",
        "html",
        "css",
        "json",
        "yaml",
        "docker",
        "kubernetes",
        "aws",
        "azure",
        "gcp",
        "linux",
        "windows",
        "macos",
        "ios",
        "android",
        "sqlite",
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "nginx",
        "node",
        "npm",
        "yarn",
        "pip",
        "conda",
        "venv",
        "url",
        "uri",
        "jwt",
        "oauth",
        "saml",
        "tls",
        "ssl",
        "jvm",
        "v8",
    }
    text = text.rstrip(".,;:!? ").strip()
    if not text:
        return "."
    words = text.split()
    out = []
    for i, w in enumerate(words):
        core = re.sub(r"[^a-zA-Z0-9]+", "", w).lower()
        # preserve possessives like github's -> github in lookup, then reattach 's after casing
        if core.endswith("s") and len(core) > 3 and core[:-1] in proper_nouns:
            base = core[:-1]
            possessive = True
        else:
            base = core
            possessive = False
        if i == 0:
            out.append(w[0].upper() + w[1:] if w else w)
        elif base in proper_nouns:
            # keep original punctuation/case for known proper noun stems; normalize known forms below
            out.append(w)
        else:
            out.append(w.lower())
    result = " ".join(out) + "."
    # normalize known proper noun phrases and possessive forms
    result = re.sub(r"\bmodel-template-views\b", "Model-Template-Views", result, flags=re.IGNORECASE)
    result = re.sub(r"\bmvt\b", "MVT", result, flags=re.IGNORECASE)
    result = re.sub(r"\bvirtual dom\b", "Virtual DOM", result, flags=re.IGNORECASE)
    result = re.sub(r"\bmodel view controller\b", "Model View Controller", result, flags=re.IGNORECASE)
    result = re.sub(r"\bmvc\b", "MVC", result, flags=re.IGNORECASE)
    result = re.sub(r"\bcommand line interface\b", "Command Line Interface", result, flags=re.IGNORECASE)
    standalone = {
        "javascript": "JavaScript",
        "typescript": "TypeScript",
        "python": "Python",
        "java": "Java",
        "django": "Django",
        "react": "React",
        "spring": "Spring",
        "api": "API",
        "rest": "REST",
        "graphql": "GraphQL",
        "cli": "CLI",
        "orm": "ORM",
        "sql": "SQL",
        "html": "HTML",
        "css": "CSS",
        "json": "JSON",
        "yaml": "YAML",
        "docker": "Docker",
        "kubernetes": "Kubernetes",
        "aws": "AWS",
        "azure": "Azure",
        "gcp": "GCP",
        "linux": "Linux",
        "windows": "Windows",
        "macos": "macOS",
        "ios": "iOS",
        "android": "Android",
        "sqlite": "SQLite",
        "postgresql": "PostgreSQL",
        "mysql": "MySQL",
        "mongodb": "MongoDB",
        "redis": "Redis",
        "nginx": "Nginx",
        "node": "Node",
        "npm": "npm",
        "yarn": "Yarn",
        "pip": "pip",
        "conda": "Conda",
        "venv": "venv",
        "url": "URL",
        "uri": "URI",
        "jwt": "JWT",
        "oauth": "OAuth",
        "saml": "SAML",
        "tls": "TLS",
        "ssl": "SSL",
        "jvm": "JVM",
    }
    for word, repl in standalone.items():
        result = re.sub(r"\b" + word + r"\b", repl, result, flags=re.IGNORECASE)
    return result


def _normalize_proper_nouns(text: str) -> str:
    """Title-case a fact and normalize compound tech proper nouns (Spring Boot, Node.js, etc.)."""
    text = _title_case_fact(text)
    text = re.sub(r"\bspring[\s.\-]?boot\b", "Spring Boot", text, flags=re.IGNORECASE)
    text = re.sub(r"\bspring[\s.\-]?framework\b", "Spring Framework", text, flags=re.IGNORECASE)
    text = re.sub(r"\bdjango[\s]?rest[\s]?framework\b", "Django REST Framework", text, flags=re.IGNORECASE)
    text = re.sub(r"\breact[\s.\-]?native\b", "React Native", text, flags=re.IGNORECASE)
    text = re.sub(r"\bnext[.\s\-]?js\b", "Next.js", text, flags=re.IGNORECASE)
    text = re.sub(r"\bnode[.\s\-]?js\b", "Node.js", text, flags=re.IGNORECASE)
    text = re.sub(r"\bvue[.\s\-]?js\b", "Vue.js", text, flags=re.IGNORECASE)
    text = re.sub(r"\btype[\s.\-]?script\b", "TypeScript", text, flags=re.IGNORECASE)
    text = re.sub(r"\bjava[\s.\-]?script\b", "JavaScript", text, flags=re.IGNORECASE)
    text = re.sub(r"\btensor[\s.\-]?flow\b", "TensorFlow", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpy[\s.\-]?torch\b", "PyTorch", text, flags=re.IGNORECASE)
    text = re.sub(r"\bgithub'?s\b", "GitHub's", text, flags=re.IGNORECASE)
    text = re.sub(r"\bgithub\b", "GitHub", text, flags=re.IGNORECASE)
    return text


def _scene2_voiceover(research: ResearchOutput) -> tuple[str, str, str]:
    topic = _topic_label(research)
    # Normalize topic for display without breaking tech proper nouns
    topic_display = _normalize_topic_name(topic.split("/")[-1]) if "/" in topic else _normalize_topic_name(topic)
    topic_sentence = topic_display.rstrip(".") if topic_display else topic
    stars = research.github.stars or 0
    forks = research.github.forks or 0
    language = research.github.language or "code"
    text = f"{stars:,} Stars\n{forks:,} Forks"
    if stars >= 100_000:
        voiceover = f"{topic_sentence} has more than {stars:,} stars on GitHub, which puts it among the most widely followed {language} projects."
    elif stars >= 50_000:
        voiceover = f"With {stars:,} stars and {forks:,} forks, {topic_sentence} has clearly found strong adoption among {language} developers."
    elif stars >= 10_000:
        voiceover = f"The numbers back up its influence: {topic_sentence} has {stars:,} stars and {forks:,} forks, showing real developer adoption."
    else:
        voiceover = f"{topic_sentence} continues to grow, with {stars:,} stars and {forks:,} forks showing genuine developer interest."
    return voiceover, text, f"GitHub repository dashboard for {topic_display} with star and fork metrics highlighted, dark UI"


def _scene3_voiceover(research: ResearchOutput, tech_fact_clean: str) -> tuple[str, str, str]:
    topic = _topic_label(research)
    language = research.github.language or "code"
    subject = _fact_words(tech_fact_clean) or language
    fact_base = tech_fact_clean.rstrip(".: ").strip() or tech_fact_clean.strip()
    if fact_base:
        voiceover = _normalize_proper_nouns(fact_base)
    else:
        voiceover = f"A {language} repository hosted on GitHub for developers."
    text = f"Tech: {language}\n{_sentence_safe_trim(tech_fact_clean, max_chars=90)}"
    visual = f"{language} architecture diagram showing {subject}, terminal/code editor aesthetic, dark theme"
    return voiceover, text, visual


def _scene4_voiceover(research: ResearchOutput, scene4_fact_clean: str, topics: list[str]) -> tuple[str, str, str]:
    topic = _topic_label(research)
    language = research.github.language or "code"
    subject = _fact_words(scene4_fact_clean) or (topics[0] if topics else language)
    fact_base = scene4_fact_clean.rstrip(".: ").strip() or scene4_fact_clean.strip()
    voiceover = _normalize_proper_nouns(fact_base) if fact_base else f"A {language} repository with practical developer use cases."
    trimmed = _sentence_safe_trim(scene4_fact_clean, max_chars=100)
    if not trimmed:
        trimmed = _sentence_safe_trim(fact_base, max_chars=80) or subject or language
    text = f"Project Highlight\n{trimmed}"
    visual = f"concept illustration for {topic}: {subject}, clean modern graphics, dark theme"
    return voiceover, text, visual


def _scene5_voiceover(research: ResearchOutput, scene1_voice: str = "", scene3_voice: str = "", scene4_voice: str = "") -> tuple[str, str, str]:
    topic = _topic_label(research)
    topic_display = _normalize_topic_name(topic.split("/")[-1]) if "/" in topic else _normalize_topic_name(topic)
    language = research.github.language or "code"
    description = research.github.description or research.summary or ""
    repo_name = topic_display.split("/")[-1] if "/" in topic_display else topic_display

    # Build CTA candidates from cleaned fact keywords, not raw verbatim facts.
    cta_candidates = []
    # Option 1: use_case keyword-driven
    for raw in (research.use_cases or []):
        cleaned = _clean_research_text(raw, max_chars=100)
        if cleaned and len(cleaned.split()) >= 4:
            subject = _fact_words(cleaned) or language
            cta_candidates.append(f"Explore {repo_name} on GitHub to build with {subject}.")
    # Option 2: interesting_facts keyword-driven
    for raw in (research.interesting_facts or []):
        cleaned = _clean_research_text(raw, max_chars=100)
        if cleaned and len(cleaned.split()) >= 4:
            subject = _fact_words(cleaned) or language
            cta_candidates.append(f"Discover {repo_name} on GitHub and see how it enables {subject}.")
    # Option 3: technical_details keyword-driven
    for raw in (research.technical_details or []):
        cleaned = _clean_research_text(raw, max_chars=100)
        if cleaned and len(cleaned.split()) >= 4:
            subject = _fact_words(cleaned) or language
            cta_candidates.append(f"Check out {repo_name} on GitHub to learn more about its {subject}.")

    for cta in cta_candidates:
        words = cta.split()
        if not (12 <= len(words) <= 22):
            continue
        if _is_generic(cta, _GENERIC_SCENE5_PATTERNS):
            continue
        if _is_scene5_template(cta, topic):
            continue
        if cta.lower().startswith(("if you're interested in", "see how")):
            continue
        if scene1_voice and _similarity(cta.lower(), scene1_voice.lower()) > 0.4:
            continue
        if scene3_voice and _similarity(cta.lower(), scene3_voice.lower()) > 0.4:
            continue
        if scene4_voice and _similarity(cta.lower(), scene4_voice.lower()) > 0.4:
            continue
        if description and _similarity(cta.lower(), description.lower()) > 0.4:
            continue
        if not cta.endswith((".", "!", "?")):
            continue
        if cta[0].islower():
            continue
        # Must not reuse raw research facts as CTA text
        if _is_readme_like(cta, research, index=4):
            continue
        return cta, f"{topic_display}\nExplore on GitHub", f"{topic_display} project summary card with GitHub icon and explore call-to-action, clean minimal design"

    # Final fallback: repo-aware CTA using available metadata, not generic filler
    cta = f"Explore {repo_name} on GitHub today and read its documentation to understand how it works."
    words = cta.split()
    if not (12 <= len(words) <= 22):
        cta = f"Explore {repo_name} on GitHub today and check out its source code and documentation for details."
    return cta, f"{topic_display}\nExplore on GitHub", f"{topic_display} project summary card with GitHub icon and explore call-to-action, clean minimal design"


def _scene1_voiceover(research: ResearchOutput) -> tuple[str, str, str]:
    topic = _topic_label(research)
    topic_display = _normalize_topic_name(topic.split("/")[-1]) if "/" in topic else _normalize_topic_name(topic)
    language = research.github.language or "code"
    description = research.summary or research.github.description or "a GitHub project"
    topics = research.github.topics or []
    description_clean = _clean_research_text(description, max_chars=160).rstrip(".,;:!?") if description else ""
    if description_clean:
        voiceover = f"{description_clean}."
    else:
        voiceover = f"{topic_display} is a {language} project on GitHub."
    subject = _fact_words(description_clean) or (topics[0] if topics else language)
    text = f"{topic_display}\n{language}" + (f"\n{', '.join(topics[:3])}" if topics else "")
    visual = f"{language} project concept illustration for {topic_display}: {subject}, clean modern infographic, dark theme"
    return voiceover, text, visual


class WriterAgent:
    def __init__(self, llm: ChatProvider, output_dir: Path | None = None) -> None:
        self.llm = llm
        self.output_dir = output_dir or (settings.tasks_dir / "default")

    def _prompt(self, research: ResearchOutput) -> str:
        facts_block = ""
        if research.technical_details:
            facts_block += f"\nTechnical details:\n" + "\n".join(f"- {_clean_bullet(item)}" for item in research.technical_details[:8])
        if research.interesting_facts:
            facts_block += f"\nInteresting facts:\n" + "\n".join(f"- {_clean_bullet(item)}" for item in research.interesting_facts[:8])
        if research.installation:
            facts_block += f"\nInstallation:\n- {_clean_bullet(research.installation)}"
        if research.use_cases:
            facts_block += f"\nUse cases:\n" + "\n".join(f"- {_clean_bullet(item)}" for item in research.use_cases[:5])
        topics = ", ".join((research.github.topics or [])[:8]) if research.github.topics else "Not specified"
        license_name = research.github.license or "Not specified"
        return f"""You are a script writer for a short faceless tech video about a real GitHub project.
Write a script that sounds like a real project introduction, NOT a generic template.

PROJECT NAME: {research.topic or 'This Project'}
PROJECT DESCRIPTION: {research.github.description or research.summary or 'Not available'}
Language: {research.github.language or 'Not specified'}
Stars: {research.github.stars:,}
Forks: {research.github.forks:,}
Topics: {topics}
License: {license_name}
Summary: {research.summary}
Key points:
{(chr(10).join(f"- {_clean_bullet(item)}" for item in research.key_points[:6])) if research.key_points else '- Not specified'}
{facts_block}

IMPORTANT:
- Use "PROJECT NAME" as the project name in the script.
- Use "PROJECT DESCRIPTION" only as background info, do NOT copy-paste it verbatim.
- Do NOT start scene 1 with "Let's talk about..." unless the project name is the only available info.
- Each voiceover must be 1-2 complete natural English sentences.
- No truncated sentences, no fragmentary phrases.
- Do NOT repeat the same sentence structure across scenes.
- Do NOT copy-paste the description with the project name inserted.
- Use facts from the research above.

SCENE RULES:
1. Scene 1: Hook + what this project IS and what problem it solves. Use the description/README facts, but write original sentences.
2. Scene 2: Community stats or real significance (stars, forks, adoption, history) with context, not just numbers.
3. Scene 3: Actual tech stack, architecture, or core functionality based on technical_details or README facts.
4. Scene 4: MUST be project-specific: pick ONE real feature, design decision, use case, or technical detail from the research. Generic phrases like "What makes X stand out? It solves real problems for developers." are FORBIDDEN.
5. Scene 5: Summarize project value and include a project-related CTA such as "Explore {research.topic} on GitHub" or "Build with {research.topic}". Do NOT use "Whether you're building or learning..." or "Follow for more tech content."

VISUAL PROMPT RULES:
- Each visual_prompt must describe a specific image related to the project content.
- Avoid repeating the same scene concept 5 times.
- Include project-specific concepts such as: component architecture, ORM, REST API, distributed system, CLI, database engine, etc., based on the research.

ONSCREEN TEXT RULES:
- Show actual information: project name, language, star count, key features, API names, architecture concepts, performance numbers.
- Avoid generic labels like only "Tech Stack", "Why X?", "Follow for more".

Return JSON with keys: title, hook, duration_target, scenes, cta.
scenes is an array of 5 objects with keys: id, duration, voiceover, visual_prompt, onscreen_text, transition.
Duration should be 5-8 seconds per scene. Total target 30-40 seconds.
Output strict JSON only. No markdown, no explanations."""

    def _fallback_scenes(self, research: ResearchOutput) -> list[dict]:
        topic = _topic_label(research)
        topic_display = _normalize_topic_name(topic.split("/")[-1]) if "/" in topic else _normalize_topic_name(topic)
        description = research.summary or research.github.description or "a GitHub project"
        language = research.github.language or "code"
        stars = research.github.stars or 0
        forks = research.github.forks or 0
        topics = research.github.topics or []
        topics_str = ", ".join(topics[:5]) if topics else ""

        # Scene 1: natural language hook, avoid mechanical topic + description.
        scene1_voice, scene1_text, scene1_visual = _scene1_voiceover(research)
        if not scene1_voice or len(scene1_voice) < 25:
            voiceover = f"{topic_display} is a {language} project on GitHub."
            scene1_voice = voiceover
            scene1_text = f"{topic_display}\n{language}"
            scene1_visual = f"{language} project concept illustration for {topic_display}, clean modern infographic, dark theme"

        # Scene 2: community stats with context.
        scene2_voice, scene2_text, scene2_visual = _scene2_voiceover(research)

        # Scene 3: tech/architecture from research with strict priority, never generic fallback.
        scene3_fact = _pick_scene3_fact(research, topic)
        scene3_fact_clean = _strip_topic_prefix(scene3_fact, topic) if scene3_fact else ""
        if not scene3_fact_clean or not _is_valid_fact(scene3_fact_clean, topic):
            scene3_fact_clean = _pick_scene3_fact(research, topic)
            scene3_fact_clean = _strip_topic_prefix(scene3_fact_clean, topic) if scene3_fact_clean else ""
        scene3_voice, scene3_text, scene3_visual = _scene3_voiceover(research, scene3_fact_clean)

        # Scene 4: interesting_facts / use_cases priority, no generic filler, dedup vs Scene 3.
        scene4_fact = _pick_scene4_fact(research, scene3_fact_clean, topic)
        if scene4_fact:
            scene4_fact_clean = _strip_topic_prefix(scene4_fact, topic)
            scene4_voice, scene4_text, scene4_visual = _scene4_voiceover(research, scene4_fact_clean, topics)
        else:
            # Re-pick with relaxed filters rather than hardcoded generic template
            scene4_fact = _pick_scene4_fact(research, scene3_fact_clean, topic)
            if scene4_fact:
                scene4_fact_clean = _strip_topic_prefix(scene4_fact, topic)
                scene4_voice, scene4_text, scene4_visual = _scene4_voiceover(research, scene4_fact_clean, topics)
            else:
                scene4_voice = f"A {language} repository with practical developer use cases."
                scene4_text = f"Project Highlight\n{language} Use Cases"
                scene4_visual = f"workflow diagram for {topic}, clean modern graphics, dark theme"

        # Scene 5: dynamic CTA from research, no hardcoded repo branches.
        scene5_voice, scene5_text, scene5_visual = _scene5_voiceover(research, scene1_voice, scene3_voice, scene4_voice)

        return [
            {"id": 1, "duration": 6, "voiceover": scene1_voice, "visual_prompt": scene1_visual, "onscreen_text": scene1_text, "transition": "fade"},
            {"id": 2, "duration": 6, "voiceover": scene2_voice, "visual_prompt": scene2_visual, "onscreen_text": scene2_text, "transition": "fade"},
            {"id": 3, "duration": 6, "voiceover": scene3_voice, "visual_prompt": scene3_visual, "onscreen_text": scene3_text, "transition": "fade"},
            {"id": 4, "duration": 6, "voiceover": scene4_voice, "visual_prompt": scene4_visual, "onscreen_text": scene4_text, "transition": "fade"},
            {"id": 5, "duration": 6, "voiceover": scene5_voice, "visual_prompt": scene5_visual, "onscreen_text": scene5_text, "transition": "fade"},
        ]

    def _repair_scene(self, scene: dict, index: int, research: ResearchOutput, all_scenes: list[dict] | None = None) -> dict:
        topic = _topic_label(research)
        description = research.summary or research.github.description or "a GitHub project"
        language = research.github.language or "code"
        stars = research.github.stars or 0
        forks = research.github.forks or 0
        topics = research.github.topics or []
        tech_details = [_clean_research_text(item, max_chars=180) for item in (research.technical_details or []) if _clean_research_text(item, max_chars=180)]
        use_cases = [_clean_research_text(item, max_chars=180) for item in (research.use_cases or []) if _clean_research_text(item, max_chars=180)]
        interesting = [_clean_research_text(item, max_chars=180) for item in (research.interesting_facts or []) if _clean_research_text(item, max_chars=180)]

        if index == 0:
            voiceover, onscreen_text, visual_prompt = _scene1_voiceover(research)
            if not voiceover or len(voiceover) < 25:
                voiceover = f"{topic} is a {language} project on GitHub."
                onscreen_text = f"{topic}\n{language}"
                visual_prompt = f"{language} project concept illustration for {topic}, clean modern infographic, dark theme"
        elif index == 1:
            voiceover, onscreen_text, visual_prompt = _scene2_voiceover(research)
        elif index == 2:
            # Re-pick fact rather than hardcoding a generic template
            tech_fact = _pick_scene3_fact(research, topic)
            tech_fact_clean = _strip_topic_prefix(tech_fact, topic) if tech_fact else ""
            if not tech_fact_clean or not _is_valid_fact(tech_fact_clean, topic):
                tech_fact_clean = _pick_scene3_fact(research, topic)
                tech_fact_clean = _strip_topic_prefix(tech_fact_clean, topic) if tech_fact_clean else ""
            voiceover, onscreen_text, visual_prompt = _scene3_voiceover(research, tech_fact_clean)
        elif index == 3:
            scene3_voice = all_scenes[2]["voiceover"] if all_scenes and len(all_scenes) > 2 else ""
            scene4_fact = _pick_scene4_fact(research, scene3_voice, topic)
            if scene4_fact:
                scene4_fact_clean = _strip_topic_prefix(scene4_fact, topic)
                voiceover, onscreen_text, visual_prompt = _scene4_voiceover(research, scene4_fact_clean, topics)
            else:
                voiceover = f"A {language} repository with practical developer use cases."
                onscreen_text = f"Project Highlight\n{language} Use Cases"
                visual_prompt = f"workflow diagram for {topic}, clean modern graphics, dark theme"
        elif index == 4:
            scene1_voice = all_scenes[0]["voiceover"] if all_scenes and len(all_scenes) > 0 else ""
            scene3_voice = all_scenes[2]["voiceover"] if all_scenes and len(all_scenes) > 2 else ""
            scene4_voice = all_scenes[3]["voiceover"] if all_scenes and len(all_scenes) > 3 else ""
            voiceover, onscreen_text, visual_prompt = _scene5_voiceover(research, scene1_voice, scene3_voice, scene4_voice)
        else:
            return scene
        scene["voiceover"] = voiceover
        scene["onscreen_text"] = onscreen_text
        scene["visual_prompt"] = visual_prompt
        return scene

    def _is_quality_good(self, scene: dict, index: int, research: ResearchOutput) -> bool:
        topic = _topic_label(research)
        voiceover = (scene.get("voiceover") or "").strip()
        if not voiceover or len(voiceover) < 25:
            return False
        if _has_markdown(voiceover):
            return False
        if _URL_PATTERN.search(voiceover) and index not in (4,):
            return False
        if _PATH_PATTERN.search(voiceover) or _CODE_EXT_PATTERN.search(voiceover):
            return False
        if voiceover.endswith("..") or voiceover.endswith(",.") or voiceover.endswith("..."):
            return False
        # Expanded generic checks
        if index in (2, 3, 4) and _is_generic(voiceover, _GENERIC_SCENE3_PATTERNS if index == 2 else _GENERIC_SCENE4_PATTERNS if index == 3 else _GENERIC_SCENE5_PATTERNS):
            return False
        if index == 0 and (voiceover.lower().startswith(f"{topic.lower()} is {topic.lower()} is") or voiceover.lower().startswith(f"{topic.lower()} is a {topic.lower()}")):
            return False
        if index in (1, 2, 3, 4) and _is_project_definition(voiceover, topic):
            return False
        if index in (0, 1, 2, 3, 4) and _is_sentence_fragment(voiceover):
            return False
        if index in (0, 1, 2, 3, 4) and _is_readme_like(voiceover, research, index):
            return False
        if index in (2, 3) and (voiceover.lower().startswith("at its core") or voiceover.lower().startswith("a defining characteristic is")):
            return False
        if index in (3, 4) and (voiceover.lower().startswith("one notable aspect is") or voiceover.lower().startswith("what sets it apart is that")):
            return False
        if index == 4 and _is_scene5_template(voiceover, topic):
            return False
        # lowercase start
        if index in (0, 1, 2, 3, 4) and voiceover[0].islower():
            return False
        # trailing punctuation fragments
        if voiceover.endswith((":", ",", ";", "-")):
            return False
        # onscreen checks
        onscreen = (scene.get("onscreen_text") or "").strip()
        if not onscreen:
            return False
        if _has_markdown(onscreen) or _URL_PATTERN.search(onscreen) or _PATH_PATTERN.search(onscreen):
            return False
        if onscreen.endswith("..") or onscreen.endswith(":.") or onscreen.endswith(",.") or "..." in onscreen:
            return False
        if onscreen.lower().endswith((" and", " or", " but", " since", " because", " instead of", " as", " while", " to", " for", " in", " on", " at", " by", ":", ",", ";", "-")):
            return False
        # reject mechanical substring / truncation of voiceover
        voiceover_norm = re.sub(r"\s+", " ", voiceover).strip()
        onscreen_norm = re.sub(r"\s+", " ", onscreen).strip()
        if onscreen_norm in voiceover_norm or voiceover_norm.startswith(onscreen_norm):
            return False
        # Scene 5 must not duplicate Scene 1 description verbatim
        scene1_text = ""
        description = research.summary or research.github.description or ""
        if index == 4 and description:
            desc_norm = re.sub(r"\s+", " ", description.lower()).strip()
            if desc_norm and desc_norm in onscreen_norm.lower():
                return False
        return True

    def _cross_scene_dedup(self, scenes: list[dict], research: ResearchOutput) -> list[dict]:
        if not scenes or len(scenes) < 5:
            return scenes
        topic = _topic_label(research)
        description = research.summary or research.github.description or ""
        desc_norm = re.sub(r"\s+", " ", description.lower()).strip() if description else ""
        result = [dict(s) for s in scenes]

        for i in range(len(result)):
            for j in range(i + 1, len(result)):
                vi = re.sub(r"\s+", " ", result[i].get("voiceover", "").lower()).strip()
                vj = re.sub(r"\s+", " ", result[j].get("voiceover", "").lower()).strip()
                if not vi or not vj:
                    continue

                # Scene 3 vs Scene 4 cannot be same text, case variants, or high token overlap
                if i == 2 and j == 3:
                    if vi == vj:
                        result[j] = self._repair_scene(result[j], j, research, result)
                        continue
                    if vi in vj or vj in vi:
                        result[j] = self._repair_scene(result[j], j, research, result)
                        continue
                    if _similarity(vi, vj) > 0.7:
                        result[j] = self._repair_scene(result[j], j, research, result)
                        continue

                # Scene 5 cannot copy Scene 1/3/4 text or reuse Scene 1 description/raw fact as CTA
                if j == 4:
                    if vi in vj:
                        result[j] = self._repair_scene(result[j], j, research, result)
                        continue
                    if _similarity(vi, vj) > 0.5:
                        result[j] = self._repair_scene(result[j], j, research, result)
                        continue
                    if desc_norm and desc_norm in vj:
                        result[j] = self._repair_scene(result[j], j, research, result)
                        continue

        return result

    def _normalize_scenes(self, raw_scenes: list, research: ResearchOutput) -> list[dict]:
        normalized: list[dict] = []
        for idx, scene in enumerate(raw_scenes[:6], start=1):
            if not isinstance(scene, dict):
                continue
            voiceover = (scene.get("voiceover") or scene.get("narration") or "").strip()
            visual_prompt = (scene.get("visual_prompt") or scene.get("image_prompt") or "").strip()
            onscreen_text = (scene.get("onscreen_text") or scene.get("text") or "").strip()
            transition = (scene.get("transition") or "fade").strip()
            duration = max(1, min(int(scene.get("duration", 6)), 30))
            if not voiceover:
                continue
            normalized.append({
                "id": idx,
                "duration": duration,
                "voiceover": voiceover,
                "visual_prompt": visual_prompt,
                "onscreen_text": onscreen_text,
                "transition": transition,
            })
        if len(normalized) < 4:
            return self._fallback_scenes(research)

        # Individual quality repair
        for i in range(5):
            if i < len(normalized) and not self._is_quality_good(normalized[i], i, research):
                normalized[i] = self._repair_scene(normalized[i], i, research, normalized)

        # Cross-scene dedup with bounded retries
        for _ in range(3):
            deduped = self._cross_scene_dedup(normalized[:5], research)
            if deduped == normalized[:5]:
                break
            normalized[:5] = deduped
            # Re-validate after dedup repair
            for i in range(5):
                if i < len(normalized) and not self._is_quality_good(normalized[i], i, research):
                    normalized[i] = self._repair_scene(normalized[i], i, research, normalized)

        # Ensure visual prompts and final quality
        for i, scene in enumerate(normalized[:5]):
            if not scene.get("visual_prompt"):
                normalized[i] = self._repair_scene(scene, i, research, normalized)
            if not self._is_quality_good(normalized[i], i, research):
                normalized[i] = self._repair_scene(normalized[i], i, research, normalized)

        return normalized[:5]

    def run(self, task_id: str, research: ResearchOutput) -> ScriptOutput:
        cache_key = {"topic": research.topic, "summary": research.summary, "key_points": research.key_points}
        cached = cache_get("script", cache_key)
        if cached:
            script = ScriptOutput.model_validate(cached)
            task_dir = settings.tasks_dir / task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / "script.json").write_text(json.dumps(script.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("script complete task_id=%s title=%s scenes=%d (cached)", task_id, script.title, len(script.scenes))
            return script
        prompt = self._prompt(research)
        messages = [
            {"role": "system", "content": "Output strict JSON only. No markdown, no explanations."},
            {"role": "user", "content": prompt},
        ]
        result = self.llm.chat(settings.step.model_agent, messages, stage="script", temperature=0.4, max_tokens=2500)
        data = self._extract_json(result.text or "")
        title = data.get("title") or research.topic
        hook = data.get("hook") or research.summary[:120]
        duration_target = int(data.get("duration_target") or 60)
        raw_scenes = data.get("scenes") or []
        scenes = self._normalize_scenes(raw_scenes, research)
        cta = data.get("cta") or f"Explore {research.topic} on GitHub"
        script_data = {
            "title": title,
            "hook": hook,
            "duration_target": duration_target,
            "scenes": scenes,
            "cta": cta,
        }
        script = ScriptOutput.model_validate(script_data)
        cache_set("script", cache_key, script.model_dump())
        task_dir = settings.tasks_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "script.json").write_text(json.dumps(script.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("script complete task_id=%s title=%s scenes=%d", task_id, script.title, len(script.scenes))
        return script

    def _extract_json(self, text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and start < end:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {}


def _is_valid_fact_after_clean(text: str) -> bool:
    """Additional checks after markdown/path removal."""
    if not text or len(text) < 30:
        return False
    lowered = text.lower()
    fragment_starters = ("and ", "or ", "but ", "nor ", "for ", "so ", "yet ", "thanks ", "thank you ", "since ", "because ", "as ", "while ")
    if lowered.startswith(fragment_starters):
        return False
    if text.endswith("..") or text.endswith(",...") or "..." in text:
        return False
    if lowered.endswith((" instead of", " because", " and", " or", " but", " since", " as", " while", " to", " for", " in", " on", " at", " by")):
        return False
    return True


def _is_valid_fact(text: str, topic: str = "") -> bool:
    """Check if a research fact is clean, complete, and safe for voiceover."""
    if not text or len(text) < 30:
        return False
    lowered = text.lower()
    if topic and lowered.startswith(topic.lower()):
        return False
    if topic and _is_project_definition(text, topic):
        return False
    if _has_markdown(text):
        return False
    if _URL_PATTERN.search(text) or _PATH_PATTERN.search(text) or _CODE_EXT_PATTERN.search(text):
        return False
    return _is_valid_fact_after_clean(text)

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.providers.base import ChatProvider, ResearchExtractor
from app.providers.cache import cache_get, cache_set
from app.schemas.research import ResearchOutput
from app.agents.writer import _has_markdown, _URL_PATTERN, _PATH_PATTERN, _CODE_EXT_PATTERN

logger = logging.getLogger(__name__)
settings = get_settings()


def _clean_readme_snippet(text: str, max_chars: int = 180) -> str:
    """Clean a README snippet for safe inclusion in voiceover / onscreen text."""
    if not text:
        return ""
    # remove markdown
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    # remove markdown inline/links like {docs} or [text](url)
    text = re.sub(r"\{[^}]+\}", "", text)
    text = re.sub(r"\[[^\]]*\]\([^\)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\*\*[^*]*\*\*", lambda m: m.group(0).strip("*"), text)
    text = re.sub(r"\*[^*]*\*", lambda m: m.group(0).strip("*"), text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    # remove bullet markers when line-leading
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.M)
    # remove URLs
    text = re.sub(r"https?://\S+", "", text)
    # remove file paths
    text = re.sub(r"(?i)(?:^|/)(?:readme|docs?|src|lib|examples?|scripts?|config|assets?|tutorial|installing)/[\w./-]+", "", text)
    text = re.sub(r"(?i)/[\w./-]+\.(?:html|htm|md|txt)", "", text)
    text = re.sub(r"(?i)(?:\b\w+)?\.(?:py|js|ts|java|cpp|c|h|md|txt|json|yaml|yml|toml|ini|cfg)\b", "", text)
    # remove README noise lines (headings, thanks, installation headings, separators)
    text = re.sub(r"(?i)^(thanks for checking|thanks for reading|installation and getting started|==+\s*installation).*$", "", text, flags=re.M)
    text = re.sub(r"(?i)^(---+\s*$)", "", text, flags=re.M)
    # remove code-like artifacts
    text = re.sub(r"(?<!\w)\.{2,}(?!\w)", " ", text)
    # remove common README nav / thanks / heading lines
    text = re.sub(
        r"(?i)^(thanks for (checking it out|reading)|read the docs|see the documentation|visit |check out |first, read|next, work through).*$",
        "",
        text,
        flags=re.M,
    )
    text = re.sub(r"(?i)^(installation|getting started|quick start)\s*$", "", text, flags=re.M)
    text = re.sub(r"(?i)^(#{1,6}\s+installation|#{1,6}\s+getting started).*$", "", text, flags=re.M)
    # collapse whitespace before sentence handling
    text = re.sub(r"\s+", " ", text).strip()
    # sentence-safe trim: prefer complete sentences; if none, return empty rather than fragment
    if len(text) > max_chars:
        for sep in [". ", "! ", "? "]:
            idx = text.rfind(sep, 0, max_chars + 1)
            if idx != -1 and idx >= 20:
                text = text[: idx + len(sep)].strip()
                break
        else:
            # no sentence boundary found within limit -> reject fragment
            return ""
    return text.strip()


def _extract_fallback_facts(readme: str) -> tuple[list[str], list[str]]:
    """Extract candidate technical_details and interesting_facts from README when LLM omits them."""
    if not readme:
        return [], []
    text = readme[:4000]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # drop headings, code fences, markdown noise
    filtered: list[str] = []
    for line in lines:
        low = line.lower()
        if low.startswith("#"):
            continue
        if low.startswith("```"):
            continue
        if low.startswith("![") or low.startswith("["):
            continue
        if "http://" in low or "https://" in low:
            continue
        if re.search(r"(?:^|/)(?:readme|docs?|src|lib|examples?|scripts?|config|assets?)/", low):
            continue
        if re.search(r"\.(?:py|js|ts|java|cpp|c|h|md|txt|json|yaml|yml|toml|ini|cfg)\b", low):
            continue
        if re.search(r"(?i)^(thanks for checking|thanks for reading|installation and getting started|==+\s*installation)", line):
            continue
        if len(line) < 25:
            continue
        filtered.append(line)

    # prefer bullets / meaningful sentences
    technical_details: list[str] = []
    interesting_facts: list[str] = []
    seen: set[str] = set()
    for line in filtered:
        cleaned = _clean_readme_snippet(line, max_chars=220)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        if not _is_valid_fact(cleaned, topic="") or not _is_valid_fact_after_clean(cleaned):
            continue
        # heuristic: architecture / API / how-it-works → technical_details
        if re.search(r"(?i)\b(architecture|api|core|framework|library|runtime|engine|module|system|protocol|layer|design)\b", cleaned):
            technical_details.append(cleaned)
        # heuristic: unique / benchmark / performance / history / philosophy → interesting_facts
        elif re.search(r"(?i)\b(fast|perform|benchmark|unique|designed|built|faster|smaller|production|million|billion|first|since|goal)\b", cleaned):
            interesting_facts.append(cleaned)

    return technical_details[:4], interesting_facts[:4]


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
    if lowered.endswith((" instead of", " because", " and", " or", " but", " since", " as", " while", " to", " for", " in", " on", " at", " by", ":", ",", ";", "-")):
        return False
    # reject description-like project definitions for technical/interesting fields
    if re.search(r"(?i)^\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(is|are|was|were)\s+(a|an|the)\s+", text):
        if len(text.split()) <= 12:
            return False
    return True


def _is_valid_fact(text: str, topic: str = "") -> bool:
    """Check if a research fact is clean, complete, and safe for voiceover."""
    if not text or len(text) < 30:
        return False
    lowered = text.lower()
    if topic and lowered.startswith(topic.lower()):
        return False
    if lowered.startswith(("is a ", "is an ", "is the ")):
        return False
    if topic and _is_project_definition(text, topic):
        return False
    if _has_markdown(text):
        return False
    if _URL_PATTERN.search(text) or _PATH_PATTERN.search(text) or _CODE_EXT_PATTERN.search(text):
        return False
    return _is_valid_fact_after_clean(text)


def _sentence_safe_trim(text: str, max_chars: int = 160) -> str:
    """Trim text at a sentence boundary without breaking words."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    # try to cut at last complete sentence
    for sep in [". ", "! ", "? "]:
        idx = text.rfind(sep, 0, max_chars + 1)
        if idx != -1 and idx >= 20:
            return text[: idx + len(sep)].strip()
    # fallback: cut at last space
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut.strip(".,;:")


class ResearcherAgent:
    def __init__(self, github: ResearchExtractor, llm: ChatProvider, output_dir: Path | None = None) -> None:
        self.github = github
        self.llm = llm
        self.output_dir = output_dir or (settings.tasks_dir / "default")

    def _prompt(self, repo_data: dict, readme: str) -> str:
        return f"""You are a research assistant for a short tech video. Analyze the GitHub repository below and extract concrete facts for a 30-90 second video.

Repository: {repo_data.get('full_name')}
URL: {repo_data.get('html_url')}
Description: {repo_data.get('description')}
Language: {repo_data.get('language')}
Stars: {repo_data.get('stargazers_count')}
Forks: {repo_data.get('forks_count')}
License: {repo_data.get('license', {}).get('name', 'Not specified') if isinstance(repo_data.get('license'), dict) else repo_data.get('license', 'Not specified')}
Topics: {', '.join(repo_data.get('topics', []) or [])}
Created: {repo_data.get('created_at')}
Updated: {repo_data.get('updated_at')}

README (first 6000 chars):
{readme[:6000]}

Return strict JSON with keys:
- topic: string
- title_candidates: string[] (2-3 short titles for the video)
- summary: string (1-2 sentences, factual, based on README/description)
- key_points: string[] (3-5 bullet points with specific facts: language, stars, forks, main features, use cases)
- technical_details: string[] (2-4 specific technical facts: architecture, core APIs, frameworks, dependencies, design patterns found in README)
- interesting_facts: string[] (2-4 interesting facts: benchmarks, performance claims, unique features, history, design philosophy from README)
- installation: string (installation command or setup steps from README, if present)
- use_cases: string[] (2-3 specific use cases or target audience from README)
- sources: string[]
- github: object with stars, forks, language, description, topics, license, html_url

Rules:
- Do NOT fabricate facts. If information is not in README or repo metadata, omit it.
- Extract actual README content, do not just paraphrase description.
- If README contains code examples, API references, or architecture sections, include them in technical_details.
- If README contains benchmarks, performance data, or comparisons, include them in interesting_facts.
- If README contains installation instructions, include them in installation field.
- summary must be based on README content, not just description."""

    def _build_fallback(self, repo_data: dict, readme: str) -> ResearchOutput:
        topic = repo_data.get("full_name") or "unknown/project"
        description = repo_data.get("description") or ""
        language = repo_data.get("language") or "code"
        stars = repo_data.get("stargazers_count") or 0
        forks = repo_data.get("forks_count") or 0
        topics = repo_data.get("topics") or []
        summary = description or readme[:500].strip() or f"{topic} is a {language} project on GitHub."
        key_points = [f"Language: {language}"] if language else []
        if stars:
            key_points.append(f"Stars: {stars:,}")
        if forks:
            key_points.append(f"Forks: {forks:,}")
        if topics:
            key_points.append(f"Topics: {', '.join(topics[:5])}")
        if not key_points:
            key_points = [f"Repository: {topic}"]

        technical_details, interesting_facts = _extract_fallback_facts(readme)

        installation = ""
        if readme:
            for line in readme.splitlines():
                low = line.lower()
                if any(k in low for k in ["install", "pip install", "npm install", "brew install"]):
                    installation = _clean_readme_snippet(line.strip(), max_chars=220)
                    if not _is_valid_fact(installation, topic=""):
                        installation = ""
                    break

        use_cases: list[str] = []
        if readme:
            for line in readme.splitlines():
                low = line.lower()
                if any(k in low for k in ["use case", "target", "audience", "for developers", "for teams", "for building", "for production"]):
                    cleaned = _clean_readme_snippet(line.strip(), max_chars=220)
                    if cleaned:
                        use_cases.append(cleaned)
                        if len(use_cases) >= 3:
                            break

        return ResearchOutput(
            topic=topic,
            title_candidates=[f"{topic} Explained", f"What is {topic}?", f"{topic} Overview"],
            summary=_clean_readme_snippet(summary, max_chars=220),
            key_points=key_points,
            technical_details=technical_details,
            interesting_facts=interesting_facts,
            installation=installation,
            use_cases=use_cases,
            sources=[repo_data.get("html_url") or f"https://github.com/{topic}"],
            github={
                "stars": stars,
                "forks": forks,
                "language": language,
                "description": description,
                "topics": topics,
                "license": repo_data.get("license", {}).get("name") if isinstance(repo_data.get("license"), dict) else repo_data.get("license", ""),
                "updated_at": repo_data.get("updated_at", ""),
                "html_url": repo_data.get("html_url", ""),
            },
        )

    def run(self, task_id: str, input_url: str) -> ResearchOutput:
        repo_data = self.github.repo(input_url)
        readme = self.github.readme(repo_data["owner"]["login"], repo_data["name"])
        cache_key = {"url": input_url, "readme_length": len(readme)}
        cached = cache_get("research", cache_key)
        if cached:
            research = ResearchOutput.model_validate(cached)
            if not research.summary:
                research.summary = repo_data.get("description") or readme[:500].strip()
            if not research.key_points:
                language = repo_data.get("language") or ""
                stars = repo_data.get("stargazers_count") or 0
                forks = repo_data.get("forks_count") or 0
                topics = repo_data.get("topics") or []
                research.key_points = [f"Language: {language}"] if language else []
                if stars:
                    research.key_points.append(f"Stars: {stars:,}, Forks: {forks:,}")
                elif forks:
                    research.key_points.append(f"Forks: {forks:,}")
                if topics:
                    research.key_points.append(f"Topics: {', '.join(topics[:5])}")
            if not research.technical_details and readme:
                technical_details, _ = _extract_fallback_facts(readme)
                research.technical_details = technical_details
            if not research.installation:
                for line in readme.splitlines():
                    if any(k in line.lower() for k in ["install", "pip install", "npm install", "brew install"]):
                        research.installation = _clean_readme_snippet(line.strip(), max_chars=220)
                        if not _is_valid_fact(research.installation, topic=""):
                            research.installation = ""
                        break
            if not research.title_candidates:
                research.title_candidates = [
                    f"{repo_data.get('full_name', 'This Project')} Explained",
                    f"What is {repo_data.get('full_name', 'This Project')}?",
                    f"{repo_data.get('full_name', 'This Project')} Overview",
                ]
            if not research.interesting_facts:
                _, interesting_facts = _extract_fallback_facts(readme)
                research.interesting_facts = interesting_facts
            if not research.use_cases:
                use_cases = []
                for line in readme.splitlines():
                    low = line.lower()
                    if any(k in low for k in ["use case", "target", "audience", "for developers", "for teams", "for building", "for production"]):
                        cleaned = _clean_readme_snippet(line.strip(), max_chars=220)
                        if cleaned:
                            use_cases.append(cleaned)
                            if len(use_cases) >= 3:
                                break
                research.use_cases = use_cases
            cache_set("research", cache_key, research.model_dump())
        else:
            prompt = self._prompt(repo_data, readme)
            messages = [
                {"role": "system", "content": "Output strict JSON only. No markdown, no explanations."},
                {"role": "user", "content": prompt},
            ]
            try:
                result = self.llm.chat(settings.step.model_agent, messages, stage="research", temperature=0.2, max_tokens=2000)
                text = result.text or ""
            except Exception as exc:
                logger.warning("research LLM failed task_id=%s error=%s", task_id, exc)
                text = ""
            data: dict[str, Any] = {}
            if text:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    logger.debug("research JSON decode failed task_id=%s", task_id)
            if not data.get("summary"):
                raw_summary = repo_data.get("description") or readme[:500].strip()
                data["summary"] = _clean_readme_snippet(raw_summary, max_chars=220)
            else:
                data["summary"] = _clean_readme_snippet(data.get("summary", ""), max_chars=220)
            if not _is_valid_fact(data["summary"], topic=""):
                data["summary"] = _clean_readme_snippet(repo_data.get("description") or "", max_chars=220)
            if not data.get("key_points"):
                language = repo_data.get("language") or ""
                stars = repo_data.get("stargazers_count") or 0
                forks = repo_data.get("forks_count") or 0
                topics = repo_data.get("topics") or []
                data["key_points"] = [f"Language: {language}"] if language else []
                if stars:
                    data["key_points"].append(f"Stars: {stars:,}, Forks: {forks:,}")
                elif forks:
                    data["key_points"].append(f"Forks: {forks:,}")
                if topics:
                    data["key_points"].append(f"Topics: {', '.join(topics[:5])}")
            if not data.get("technical_details"):
                technical_details, _ = _extract_fallback_facts(readme)
                data["technical_details"] = technical_details
            else:
                data["technical_details"] = [_clean_readme_snippet(item, max_chars=220) for item in data.get("technical_details", [])]
            data["technical_details"] = [item for item in data["technical_details"] if _is_valid_fact(item, topic="")]
            if not data.get("interesting_facts"):
                _, interesting_facts = _extract_fallback_facts(readme)
                data["interesting_facts"] = interesting_facts
            else:
                data["interesting_facts"] = [_clean_readme_snippet(item, max_chars=220) for item in data.get("interesting_facts", [])]
            data["interesting_facts"] = [item for item in data["interesting_facts"] if _is_valid_fact(item, topic="")]
            if not data.get("title_candidates"):
                data["title_candidates"] = [
                    f"{repo_data.get('full_name', 'This Project')} Explained",
                    f"What is {repo_data.get('full_name', 'This Project')}?",
                    f"{repo_data.get('full_name', 'This Project')} Overview",
                ]
            if not data.get("installation"):
                data["installation"] = ""
                for line in readme.splitlines():
                    if any(k in line.lower() for k in ["install", "pip install", "npm install", "brew install"]):
                        data["installation"] = _clean_readme_snippet(line.strip(), max_chars=220)
                        break
            if not data.get("use_cases"):
                use_cases = []
                for line in readme.splitlines():
                    low = line.lower()
                    if any(k in low for k in ["use case", "target", "audience", "for developers", "for teams", "for building", "for production"]):
                        cleaned = _clean_readme_snippet(line.strip(), max_chars=220)
                        if cleaned and _is_valid_fact(cleaned, topic=""):
                            use_cases.append(cleaned)
                        if len(use_cases) >= 3:
                            break
                data["use_cases"] = use_cases
            if not data.get("sources"):
                data["sources"] = [repo_data.get("html_url") or f"https://github.com/{repo_data.get('full_name')}"]
            if not data.get("github"):
                data["github"] = {}
            data["github"].setdefault("stars", repo_data.get("stargazers_count", 0) or 0)
            data["github"].setdefault("forks", repo_data.get("forks_count", 0) or 0)
            data["github"].setdefault("language", repo_data.get("language") or "")
            data["github"].setdefault("description", repo_data.get("description") or "")
            data["github"].setdefault("topics", repo_data.get("topics") or [])
            data["github"].setdefault("license", repo_data.get("license", {}).get("name") if isinstance(repo_data.get("license"), dict) else repo_data.get("license", ""))
            data["github"].setdefault("html_url", repo_data.get("html_url", ""))
            research = ResearchOutput.model_validate(data)
            if not research.topic:
                research.topic = repo_data.get("full_name") or ""
            cache_set("research", cache_key, research.model_dump())
        task_dir = settings.tasks_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "research.json").write_text(json.dumps(research.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("research complete task_id=%s topic=%s technical=%d facts=%d", task_id, research.topic, len(research.technical_details), len(research.interesting_facts))
        return research

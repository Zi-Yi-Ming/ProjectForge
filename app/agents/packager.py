from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.schemas.research import ResearchOutput
from app.schemas.content import GeneratedContent, ContentPackage

logger = logging.getLogger(__name__)
settings = get_settings()


def _build_source_facts(research: ResearchOutput) -> list[str]:
    facts: list[str] = []
    if research.topic:
        facts.append(f"topic: {research.topic}")
    if research.summary:
        facts.append(f"summary: {research.summary}")
    if research.github.description:
        facts.append(f"description: {research.github.description}")
    if research.github.stars:
        facts.append(f"stars: {research.github.stars}")
    if research.github.forks:
        facts.append(f"forks: {research.github.forks}")
    if research.github.language:
        facts.append(f"language: {research.github.language}")
    if research.github.topics:
        facts.append(f"topics: {', '.join(research.github.topics[:5])}")
    if research.github.license:
        facts.append(f"license: {research.github.license}")
    for kp in research.key_points[:3]:
        facts.append(f"key_point: {kp}")
    for td in research.technical_details[:3]:
        facts.append(f"technical_detail: {td}")
    for if_ in research.interesting_facts[:3]:
        facts.append(f"interesting_fact: {if_}")
    return facts


def _generate_overview(research: ResearchOutput) -> GeneratedContent:
    source_facts = _build_source_facts(research)
    lines = [
        f"# {research.topic}",
        "",
        f"> {research.summary or research.github.description or ''}",
        "",
        "## What is it?",
        "",
        research.github.description or research.summary or f"{research.topic} is a GitHub project.",
        "",
        "## Key Information",
        "",
    ]
    if research.github.language:
        lines.append(f"- **Language**: {research.github.language}")
    if research.github.stars:
        lines.append(f"- **Stars**: {research.github.stars:,}")
    if research.github.forks:
        lines.append(f"- **Forks**: {research.github.forks:,}")
    if research.github.topics:
        lines.append(f"- **Topics**: {', '.join(research.github.topics[:5])}")
    lines.append("")

    if research.key_points:
        lines.append("## Highlights")
        lines.append("")
        for kp in research.key_points[:5]:
            lines.append(f"- {kp}")
        lines.append("")

    if research.use_cases:
        lines.append("## Use Cases")
        lines.append("")
        for uc in research.use_cases[:3]:
            lines.append(f"- {uc}")
        lines.append("")

    lines.append("## GitHub")
    lines.append("")
    lines.append(f"[{research.topic}]({research.github.html_url})")
    lines.append("")

    return GeneratedContent(
        platform="overview",
        title=f"{research.topic} Overview",
        content="\n".join(lines),
        source_facts=source_facts,
    )


def _generate_blog(research: ResearchOutput) -> GeneratedContent:
    source_facts = _build_source_facts(research)
    title = research.title_candidates[0] if research.title_candidates else f"{research.topic}: A Deep Dive"

    lines = [f"# {title}", ""]
    if research.summary:
        lines.append(f"*{research.summary}*")
        lines.append("")

    lines.extend([
        "## Introduction",
        "",
        research.github.description or research.summary or f"{research.topic} is an open-source project on GitHub.",
        "",
    ])

    if research.key_points:
        lines.append("## Why It Matters")
        lines.append("")
        for kp in research.key_points[:5]:
            lines.append(f"- {kp}")
        lines.append("")

    if research.technical_details:
        lines.append("## Under the Hood")
        lines.append("")
        for td in research.technical_details[:4]:
            lines.append(f"- {td}")
        lines.append("")

    if research.interesting_facts:
        lines.append("## What Makes It Interesting")
        lines.append("")
        for if_ in research.interesting_facts[:4]:
            lines.append(f"- {if_}")
        lines.append("")

    if research.use_cases:
        lines.append("## Who Is This For?")
        lines.append("")
        for uc in research.use_cases[:3]:
            lines.append(f"- {uc}")
        lines.append("")

    lines.append("## By the Numbers")
    lines.append("")
    if research.github.stars:
        lines.append(f"- **{research.github.stars:,} stars** on GitHub")
    if research.github.forks:
        lines.append(f"- **{research.github.forks:,} forks**")
    if research.github.language:
        lines.append(f"- Written in **{research.github.language}**")
    if research.github.topics:
        lines.append(f"- Tagged: {', '.join(research.github.topics[:5])}")
    lines.append("")

    lines.extend([
        "## Wrapping Up",
        "",
        f"{research.topic} is more than just another open-source project. It's a testament to what the community can build together.",
        "",
    ])

    if research.github.html_url:
        lines.append(f"Explore the project on GitHub: [{research.topic}]({research.github.html_url})")
        lines.append("")

    return GeneratedContent(
        platform="blog",
        title=title,
        content="\n".join(lines),
        source_facts=source_facts,
    )


def _generate_x(research: ResearchOutput) -> GeneratedContent:
    source_facts = _build_source_facts(research)
    topic_display = research.topic.split("/")[-1] if "/" in research.topic else research.topic

    parts = []
    if research.summary:
        parts.append(research.summary)

    stats = []
    if research.github.stars:
        stats.append(f"{research.github.stars:,} stars")
    if research.github.forks:
        stats.append(f"{research.github.forks:,} forks")
    if stats:
        parts.append(f"{', '.join(stats)} on GitHub")

    if research.github.language:
        parts.append(f"Written in {research.github.language}")

    if research.interesting_facts:
        parts.append(research.interesting_facts[0])

    if research.github.html_url:
        parts.append(f"GitHub: {research.github.html_url}")

    content = "\n\n".join(parts) if len(parts) > 2 else " | ".join(parts)

    return GeneratedContent(
        platform="x",
        title=f"{topic_display} on GitHub",
        content=content,
        source_facts=source_facts,
    )


def _generate_reddit(research: ResearchOutput) -> GeneratedContent:
    source_facts = _build_source_facts(research)
    topic_display = research.topic.split("/")[-1] if "/" in research.topic else research.topic

    lines = [f"I've been looking at **{research.topic}** and wanted to share what it does:", ""]

    if research.github.description:
        lines.append(f"> {research.github.description}")
        lines.append("")

    lines.append("**What it is:**")
    lines.append("")
    lines.append(research.summary or f"{research.topic} is an open-source project on GitHub.")
    lines.append("")

    if research.key_points:
        lines.append("**Key points:**")
        lines.append("")
        for kp in research.key_points[:5]:
            lines.append(f"- {kp}")
        lines.append("")

    if research.technical_details:
        lines.append("**Technical details:**")
        lines.append("")
        for td in research.technical_details[:3]:
            lines.append(f"- {td}")
        lines.append("")

    if research.use_cases:
        lines.append("**Use cases:**")
        lines.append("")
        for uc in research.use_cases[:3]:
            lines.append(f"- {uc}")
        lines.append("")

    lines.append("**Community stats:**")
    lines.append("")
    if research.github.stars:
        lines.append(f"- {research.github.stars:,} stars")
    if research.github.forks:
        lines.append(f"- {research.github.forks:,} forks")
    if research.github.language:
        lines.append(f"- Written in {research.github.language}")
    lines.append("")

    lines.append(f"**GitHub:** [{research.topic}]({research.github.html_url})")
    lines.append("")
    lines.append("Has anyone here used this? I'd be curious to hear about your experience.")

    return GeneratedContent(
        platform="reddit",
        title=f"{topic_display} - An interesting open-source project",
        content="\n".join(lines),
        source_facts=source_facts,
    )


class PackagerAgent:
    def __init__(self, llm: Any = None) -> None:
        self.llm = llm

    def run(self, research: ResearchOutput, repo_name: str | None = None) -> ContentPackage:
        """Generate ContentPackage from ResearchOutput.

        Does NOT call GitHub provider. Uses only the provided ResearchOutput.
        """
        return ContentPackage(
            repo={
                "full_name": research.topic,
                "html_url": research.github.html_url,
                "name": research.topic.split("/")[-1] if "/" in research.topic else research.topic,
            },
            research=research,
            contents={
                "overview": _generate_overview(research),
                "blog": _generate_blog(research),
                "x": _generate_x(research),
                "reddit": _generate_reddit(research),
            },
        )

    def write(self, package: ContentPackage, output_dir: Path) -> None:
        """Write ContentPackage to disk."""
        output_dir.mkdir(parents=True, exist_ok=True)

        research_path = output_dir / "research.json"
        research_path.write_text(
            json.dumps(package.research.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        for platform, content in package.contents.items():
            md_path = output_dir / f"{platform}.md"
            md_lines = [
                "---",
                f"platform: {content.platform}",
                f"title: {content.title}",
                "source_facts:",
            ]
            for fact in content.source_facts:
                md_lines.append(f"  - {fact}")
            md_lines.append("---")
            md_lines.append("")
            md_lines.append(content.content)
            md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

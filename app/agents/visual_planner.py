from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.config import get_settings
from app.schemas.visual import VisualPlan, SceneVisualPlan, VisualType, Motion, ScreenshotSource, ProgrammaticConfig, validate_visual_plan

logger = logging.getLogger(__name__)
settings = get_settings()

# Keywords that force non-AI visual types
_CODE_PATTERNS = [
    r"\b[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)\s*\{",
    r"function\s+\w+",
    r"def\s+\w+",
    r"class\s+\w+",
    r"import\s+",
    r"from\s+\w+\s+import",
    r"const\s+\w+",
    r"let\s+\w+",
    r"var\s+\w+",
    r"\.py\b",
    r"\.js\b",
    r"\.ts\b",
    r"\.java\b",
    r"useState\s*\(",
    r"useEffect\s*\(",
    r"useReducer\s*\(",
    r"=>\s*\{?",
    r"<\w+[\s/>]",
    r"\bconst\s+\[[^\]]+\]\s*=",
]


def _looks_like_code(text: str) -> bool:
    if not text:
        return False
    strong_patterns = [
        r"\b[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)\s*\{",
        r"\bdef\s+\w+",
        r"\bclass\s+\w+",
        r"\bimport\s+",
        r"\bfrom\s+\w+\s+import",
        r"\bconst\s+\w+",
        r"\blet\s+\w+",
        r"\bvar\s+\w+",
        r"\.py\b",
        r"\.js\b",
        r"\.ts\b",
        r"\.java\b",
        r"useState\s*\(",
        r"useEffect\s*\(",
        r"useReducer\s*\(",
        r"=>\s*\{?",
        r"<\w+[\s/>]",
        r"\bconst\s+\[[^\]]+\]\s*=",
    ]
    if any(re.search(p, text, re.IGNORECASE) for p in strong_patterns):
        return True
    generic_upper = {
        "UI", "AI", "API", "HTML", "JSON", "SQL", "CLI", "HTTP", "HTTPS", "URL", "DOM", "CSS",
        "GITHUB", "README", "REACT", "NODE", "PYTHON", "JAVASCRIPT", "TYPESCRIPT",
    }
    for word in re.findall(r"\b[A-Z]{2,}\b", text):
        if word in generic_upper:
            continue
        if len(word) >= 4:
            return True
    return False


_URL_PATTERN = re.compile(r"https?://\S+")
_PATH_PATTERN = re.compile(r"(?:^|/)(?:readme|docs?|src|lib|examples?|scripts?|config|assets?)/[\w./-]+")
_NUMBER_PATTERN = re.compile(
    r"\b(?:\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*[KMB]?\s*(?:stars|forks|issues|percent|%|MB|ms|seconds|minutes|hours)"
    r"|(?:stars|forks|issues|percent|%|MB|ms|seconds|minutes|hours)\s*:\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*[KMB]?)",
    re.IGNORECASE,
)
_GITHUB_UI_PATTERNS = [
    "github.com",
    "pull request",
    "issue",
    "actions",
    "workflow",
    "readme",
    "stars",
    "fork",
    "repository",
    "repo",
]

_DIAGRAM_KEYWORDS = [
    "architecture",
    "workflow",
    "pipeline",
    "component",
    "flow",
    "relationship",
    "state",
    "data flow",
    "structure",
]

_CODE_KEYWORDS = [
    "source code",
    "function",
    "class",
    "api",
    "command",
    "file path",
    "filename",
    "configuration",
    "import",
    "export",
    "method",
    "variable",
    "parameter",
]

_METRICS_KEYWORDS = [
    "stars",
    "forks",
    "count",
    "percentage",
    "benchmark",
    "performance",
    "comparison",
    "metric",
    "speed",
    "latency",
    "throughput",
]

_AI_IMAGE_ALLOWED_KEYWORDS = [
    "abstract",
    "concept",
    "atmosphere",
    "background",
    "imagery",
    "illustration",
    "visualize",
    "imagine",
    "future",
    "creative",
]


def _classify_scene(voiceover: str, onscreen_text: str, scene_id: int, topic: str = "") -> VisualType:
    text = f"{voiceover} {onscreen_text}".lower()

    # Absolute exclusions for ai_image
    if _looks_like_code(voiceover):
        return VisualType.code
    if _NUMBER_PATTERN.search(voiceover) or _NUMBER_PATTERN.search(onscreen_text):
        return VisualType.metrics

    # URL / path / filename -> screenshot
    if _URL_PATTERN.search(voiceover) or _PATH_PATTERN.search(voiceover):
        return VisualType.screenshot

    # GitHub UI / README / docs
    if any(keyword in text for keyword in _GITHUB_UI_PATTERNS):
        return VisualType.screenshot

    # Diagram / architecture / workflow
    if any(keyword in text for keyword in _DIAGRAM_KEYWORDS):
        return VisualType.diagram

    # Code / command / config
    if any(keyword in text for keyword in _CODE_KEYWORDS):
        return VisualType.code

    # Metrics / numbers
    if any(keyword in text for keyword in _METRICS_KEYWORDS):
        return VisualType.metrics

    # AI image allowed only for abstract/conceptual narration
    if any(keyword in text for keyword in _AI_IMAGE_ALLOWED_KEYWORDS):
        return VisualType.ai_image

    return VisualType.ai_image


class VisualPlanner:
    def __init__(self, task_id: str = "", title: str = "") -> None:
        self.task_id = task_id
        self.title = title

    def plan(self, script, validate: bool = True) -> VisualPlan:
        from app.schemas.script import ScriptOutput
        script_data = script if isinstance(script, dict) else script.model_dump()
        scenes = []
        raw_scenes = script_data.get("scenes", [])
        if not raw_scenes and hasattr(script, "scenes"):
            raw_scenes = [s.model_dump() for s in script.scenes]

        for raw in raw_scenes:
            scene_id = int(raw.get("id", 0))
            voiceover = raw.get("voiceover", "")
            onscreen_text = raw.get("onscreen_text", "")
            visual_type = _classify_scene(voiceover, onscreen_text, scene_id, self.title)

            scene_plan = self._build_scene_plan(scene_id, visual_type, voiceover, onscreen_text)
            scenes.append(scene_plan)

        plan = VisualPlan(task_id=self.task_id, title=self.title, scenes=scenes)
        if validate:
            errors = validate_visual_plan(plan)
            if errors:
                logger.warning("VisualPlan validation issues: %s", errors)
        return plan

    def _build_scene_plan(self, scene_id: int, visual_type: VisualType, voiceover: str, onscreen_text: str) -> SceneVisualPlan:
        if visual_type == VisualType.screenshot:
            return SceneVisualPlan(
                scene_id=scene_id,
                visual_type=VisualType.screenshot,
                provider="github_screenshot",
                purpose="Show real repository UI or documentation",
                source=ScreenshotSource(url="", selector="markdown-body", annotate=[]),
                motion=Motion(),
                fallback="placeholder",
            )

        if visual_type == VisualType.diagram:
            return SceneVisualPlan(
                scene_id=scene_id,
                visual_type=VisualType.diagram,
                provider="programmatic",
                purpose="Explain architecture or workflow with deterministic diagram",
                programmatic=ProgrammaticConfig(
                    type="architecture",
                    data=onscreen_text or voiceover,
                    theme="dark",
                ),
                motion=Motion(),
                fallback="placeholder",
            )

        if visual_type == VisualType.code:
            language = self._detect_language(voiceover, onscreen_text)
            return SceneVisualPlan(
                scene_id=scene_id,
                visual_type=VisualType.code,
                provider="programmatic",
                purpose="Render exact code/config with syntax highlighting",
                programmatic=ProgrammaticConfig(
                    type="code_block",
                    data=onscreen_text or voiceover,
                    theme="dark",
                    language=language,
                    highlight_keywords=self._extract_keywords(voiceover + " " + onscreen_text),
                ),
                motion=Motion(),
                fallback="placeholder",
            )

        if visual_type == VisualType.metrics:
            source = "GitHub" if "github" in (self.title or "").lower() else None
            return SceneVisualPlan(
                scene_id=scene_id,
                visual_type=VisualType.metrics,
                provider="programmatic",
                purpose="Show exact metrics from structured data",
                programmatic=ProgrammaticConfig(
                    type="metrics_card",
                    data=onscreen_text or voiceover,
                    theme="dark",
                    source=source,
                ),
                motion=Motion(),
                fallback="placeholder",
            )

        # ai_image fallback
        return SceneVisualPlan(
            scene_id=scene_id,
            visual_type=VisualType.ai_image,
            provider="stepfun",
            purpose="Abstract concept illustration; must not carry precise text/code/URLs",
            programmatic=None,
            motion=Motion(),
            fallback="placeholder",
        )

    @staticmethod
    def _detect_language(voiceover: str, onscreen_text: str) -> str:
        text = f"{voiceover} {onscreen_text}".lower()
        if any(k in text for k in ["python", ".py", "def ", "import "]):
            return "python"
        if any(k in text for k in ["javascript", ".js", "function ", "const "]):
            return "javascript"
        if any(k in text for k in ["typescript", ".ts"]):
            return "typescript"
        if any(k in text for k in ["java ", ".java", "public class"]):
            return "java"
        if any(k in text for k in ["yaml", ".yaml", ".yml"]):
            return "yaml"
        if any(k in text for k in ["json", ".json"]):
            return "json"
        return "text"

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text or "")
        stop = {
            "the", "and", "for", "with", "from", "this", "that", "have", "has", "been",
            "were", "was", "are", "not", "but", "can", "may", "will", "its", "into",
            "than", "when", "what", "which", "their", "there", "would", "could", "should",
        }
        seen = []
        seen_set = set()
        for w in words:
            low = w.lower()
            if low not in stop and low not in seen_set:
                seen.append(w)
                seen_set.add(low)
            if len(seen) >= 6:
                break
        return seen

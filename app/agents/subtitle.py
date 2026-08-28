from __future__ import annotations
import json
import logging
import math
from pathlib import Path
from app.config import get_settings
from app.schemas.script import ScriptOutput
logger = logging.getLogger(__name__)
settings = get_settings()
class SubtitleAgent:
    def run(self, task_id: str, script: ScriptOutput) -> Path:
        task_dir = settings.tasks_dir / task_id
        subtitle_dir = task_dir / "subtitles"
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        audio_dir = task_dir / "audio"
        manifest_path = audio_dir / "manifest.json"
        audio_durations: dict[int, float] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                audio_durations = {item["scene_id"]: item.get("duration") for item in manifest if item.get("duration") is not None}
            except Exception as exc:
                logger.debug("audio manifest load failed task_id=%s error=%s", task_id, exc)
        subs = []
        cursor = 0.0
        for scene in script.scenes:
            text = scene.voiceover or scene.onscreen_text or ""
            audio_duration = audio_durations.get(scene.id)
            duration = float(audio_duration) if audio_duration is not None else float(scene.duration)
            if not text.strip():
                cursor += duration
                continue
            parts = [p.strip() for p in text.split("\n") if p.strip()]
            if not parts:
                parts = [text]
            chunk = max(duration / max(len(parts), 1), 2.0)
            for idx, part in enumerate(parts):
                start = cursor + min(idx * chunk, duration)
                end = min(start + chunk, cursor + duration)
                subs.append({"start": round(start, 2), "end": round(end, 2), "text": part})
            cursor += duration
        srt_path = subtitle_dir / "subtitle.srt"
        srt = []
        for idx, item in enumerate(subs, start=1):
            srt.append(f"{idx}\n{self._format_ts(item['start'])} --> {self._format_ts(item['end'])}\n{item['text']}\n")
        srt_path.write_text("\n".join(srt), encoding="utf-8")
        (subtitle_dir / "subtitles.json").write_text(json.dumps(subs, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("subtitle complete task_id=%s entries=%d", task_id, len(subs))
        return srt_path
    @staticmethod
    def _format_ts(seconds: float) -> str:
        seconds = max(seconds, 0.0)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int(round((seconds - math.floor(seconds)) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

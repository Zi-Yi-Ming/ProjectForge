from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path
from app.config import get_settings
from app.providers.base import TTSProvider
from app.providers.cache import cache_get
from app.providers.edge_tts import synthesize_edge_tts
from app.schemas.script import ScriptOutput
logger = logging.getLogger(__name__)
settings = get_settings()


def _probe_audio_duration(path: Path) -> float | None:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        value = proc.stdout.strip()
        if not value:
            return None
        duration = float(value)
        return duration if duration > 0 else None
    except Exception as exc:
        logger.debug("audio probe failed path=%s error=%s", path, exc)
        return None


class VoiceAgent:
    def __init__(self, tts_provider: TTSProvider | None = None) -> None:
        self.tts_provider = tts_provider
    def run(self, task_id: str, script: ScriptOutput) -> Path:
        task_dir = settings.tasks_dir / task_id
        audio_dir = task_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        manifest = []
        for scene in script.scenes:
            text = scene.voiceover or scene.onscreen_text or ""
            audio_path = audio_dir / f"scene_{scene.id:03d}.mp3"
            cache_key = {"scene": scene.id, "text": text, "model": settings.step.model_tts}
            cached = cache_get("audio", cache_key)
            if cached and cached.get("path"):
                audio_path = Path(cached["path"])
                if not audio_path.exists():
                    audio_path = self._synthesize(task_id, scene, text, audio_path)
            else:
                audio_path = self._synthesize(task_id, scene, text, audio_path)

            duration = _probe_audio_duration(audio_path) if audio_path.exists() and audio_path.stat().st_size > 0 else None
            if duration is None:
                logger.warning("audio missing or empty task_id=%s scene=%s path=%s", task_id, scene.id, audio_path)
            manifest.append({
                "scene_id": scene.id,
                "path": str(audio_path),
                "duration": duration,
                "text": text[:120],
            })
        (audio_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("voice complete task_id=%s scenes=%d", task_id, len(script.scenes))
        return audio_dir
    def _synthesize(self, task_id: str, scene, text: str, audio_path: Path) -> Path:
        if not text:
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(b"")
            return audio_path
        if self.tts_provider:
            try:
                return self.tts_provider.tts(
                    settings.step.model_tts,
                    text,
                    output_path=audio_path,
                    voice=settings.step.tts_voice,
                    response_format=settings.step.tts_response_format,
                )
            except Exception as exc:
                logger.warning("tts provider failed task_id=%s scene=%s error=%s", task_id, scene.id, exc)
        try:
            return synthesize_edge_tts(text, audio_path)
        except Exception as exc:
            logger.warning("edge tts failed task_id=%s scene=%s error=%s", task_id, scene.id, exc)
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"")
        return audio_path

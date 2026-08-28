from __future__ import annotations
import json
from enum import Enum
from pathlib import Path
from app.config import get_settings
class Stage(str, Enum):
    CREATED = "CREATED"
    RESEARCHING = "RESEARCHING"
    RESEARCHED = "RESEARCHED"
    SCRIPTING = "SCRIPTING"
    SCRIPTED = "SCRIPTED"
    GENERATING_ASSETS = "GENERATING_ASSETS"
    ASSETS_READY = "ASSETS_READY"
    GENERATING_AUDIO = "GENERATING_AUDIO"
    AUDIO_READY = "AUDIO_READY"
    GENERATING_SUBTITLES = "GENERATING_SUBTITLES"
    SUBTITLES_READY = "SUBTITLES_READY"
    RENDERING = "RENDERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
class State:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        settings = get_settings()
        self.root = settings.tasks_dir / task_id
        self.path = self.root / "state.json"
        self.current_stage = Stage.CREATED
        self.input: dict = {}
        self.metadata: dict = {}
        self.load()
    def load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.current_stage = Stage(data.get("current_stage", Stage.CREATED))
            self.input = data.get("input", {})
            self.metadata = data.get("metadata", {})
    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({
                "task_id": self.task_id,
                "current_stage": self.current_stage.value,
                "input": self.input,
                "metadata": self.metadata,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    def set_stage(self, stage: Stage) -> None:
        self.current_stage = stage
        self.save()

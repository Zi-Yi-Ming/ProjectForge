from __future__ import annotations
from pydantic import BaseModel, Field
class Scene(BaseModel):
    id: int
    duration: int = Field(ge=1, description="Duration in seconds")
    voiceover: str = ""
    visual_prompt: str = ""
    onscreen_text: str = ""
    transition: str = ""
class ScriptOutput(BaseModel):
    title: str = ""
    hook: str = ""
    duration_target: int = 60
    scenes: list[Scene] = Field(default_factory=list)
    cta: str = ""

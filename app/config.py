from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env", override=True)


class StepSettings(BaseModel):
    api_key: str = Field(default="")
    base_url: str = Field(default="https://api.stepfun.com/step_plan/v1")
    timeout: int = Field(default=60)
    max_retries: int = Field(default=3)
    router_enabled: bool = Field(default=False)
    router_model: str = Field(default="step-router-v1")
    model_fast: str = Field(default="step-3.7-flash")
    model_agent: str = Field(default="step-explore")
    model_reasoning: str = Field(default="step-explore")
    model_vision: str = Field(default="step-1o-turbo-vision")
    model_image: str = Field(default="step-image-edit-2")
    model_tts: str = Field(default="stepaudio-2.5-tts")
    tts_voice: str = Field(default="zixinnansheng")
    tts_response_format: str = Field(default="mp3")


class GitHubSettings(BaseModel):
    token: str = Field(default="")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    step: StepSettings = Field(default_factory=StepSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    project_root: Path = Field(default=Path("/home/azureuser/content-agent").resolve())
    tasks_dir: Path = Field(default_factory=lambda: Path("/home/azureuser/content-agent/tasks").resolve())
    cache_dir: Path = Field(default_factory=lambda: Path("/home/azureuser/content-agent/cache").resolve())
    logs_dir: Path = Field(default_factory=lambda: Path("/home/azureuser/content-agent/logs").resolve())
    outputs_dir: Path = Field(default_factory=lambda: Path("/home/azureuser/content-agent/outputs").resolve())

    def __init__(self, **data):  # type: ignore[override]
        data.setdefault("step", {})
        data.setdefault("github", {})
        data["step"]["api_key"] = data["step"].get("api_key") or os.getenv("STEPFUN_API_KEY", "")
        data["github"]["token"] = data["github"].get("token") or os.getenv("GITHUB_TOKEN", "")
        step_data = data.setdefault("step", {})
        step_data["tts_voice"] = step_data.get("tts_voice") or os.getenv("STEPFUN_TTS_VOICE", "zixinnansheng")
        step_data["tts_response_format"] = step_data.get("tts_response_format") or os.getenv("STEPFUN_TTS_RESPONSE_FORMAT", "mp3")
        super().__init__(**data)


def get_settings() -> AppSettings:
    return AppSettings()  # type: ignore[call-arg]

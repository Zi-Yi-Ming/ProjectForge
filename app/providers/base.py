from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
class ChatResult:
    def __init__(self, text: str, request_id: str | None = None, model: str | None = None, token_usage: dict | None = None):
        self.text = text
        self.request_id = request_id
        self.model = model
        self.token_usage = token_usage
class ChatProvider(ABC):
    @abstractmethod
    def chat(self, model: str, messages: list[dict], **kwargs) -> ChatResult:
        raise NotImplementedError
class VisionProvider(ABC):
    @abstractmethod
    def vision(self, model: str, image_path: Path, prompt: str, **kwargs) -> str:
        raise NotImplementedError
class ImageProvider(ABC):
    @abstractmethod
    def image(self, model: str, prompt: str, **kwargs) -> Path:
        raise NotImplementedError
class TTSProvider(ABC):
    @abstractmethod
    def tts(self, model: str, text: str, **kwargs) -> Path:
        raise NotImplementedError
class ResearchExtractor(ABC):
    @abstractmethod
    def repo(self, url: str) -> dict:
        raise NotImplementedError
    @abstractmethod
    def readme(self, owner: str, repo: str) -> str:
        raise NotImplementedError

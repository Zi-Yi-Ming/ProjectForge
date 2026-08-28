from __future__ import annotations
import base64
import json
import logging
from pathlib import Path
from typing import Any
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import get_settings
from app.providers.base import ChatProvider, ImageProvider, TTSProvider, VisionProvider, ChatResult
logger = logging.getLogger(__name__)
settings = get_settings()
class StepProvider(ChatProvider, VisionProvider, ImageProvider, TTSProvider):
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            base_url=settings.step.base_url,
            timeout=settings.step.timeout,
            headers={"Authorization": f"Bearer {settings.step.api_key}"},
        )
        self._available_models: set[str] | None = None
        self._model_probe_failed = False
    def _now(self) -> float:
        try:
            return httpx.get_system_time() / 1000
        except Exception:
            import time
            return time.time()
    def _probe_models(self) -> set[str]:
        if self._available_models is not None:
            return self._available_models
        try:
            with httpx.Client(base_url=settings.step.base_url, timeout=10, headers={"Authorization": f"Bearer {settings.step.api_key}"}) as client:
                resp = client.get("/models")
                if resp.status_code == 200:
                    data = resp.json()
                    models = {m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)}
                    self._available_models = models
                    return models
        except Exception as exc:
            logger.debug("step model probe failed: %s", exc)
        self._available_models = set()
        self._model_probe_failed = True
        return self._available_models
    def _resolve_model(self, model: str) -> str:
        if model in (settings.step.model_agent, settings.step.model_reasoning):
            available = self._probe_models()
            if available and model not in available:
                fallback = settings.step.model_fast
                if fallback and fallback != model:
                    logger.info("step model downgrade %s -> %s", model, fallback)
                    return fallback
        return model
    def _log_call(self, stage: str, model: str, start: float, status: str, http_status: int | None, error: str | None, token_usage: dict | None) -> None:
        duration_ms = int((self._now() - start) * 1000)
        record = {
            "stage": stage,
            "model": model,
            "status": status,
            "http_status": http_status,
            "duration_ms": duration_ms,
            "token_usage": token_usage,
            "error": error,
        }
        path = settings.logs_dir / "calls.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    def _chat(self, model: str, payload: dict, stage: str) -> ChatResult:
        start = self._now()
        resolved_model = self._resolve_model(model)
        try:
            resp = self.client.post("/chat/completions", json={**payload, "model": resolved_model})
            http_status = resp.status_code
            if http_status != 200:
                self._log_call(stage, resolved_model, start, "error", http_status, resp.text, None)
                resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage")
            request_id = data.get("id")
            self._log_call(stage, resolved_model, start, "success", http_status, None, dict(usage) if usage else None)
            return ChatResult(text=text, request_id=request_id, model=resolved_model, token_usage=dict(usage) if usage else None)
        except Exception as exc:
            http_status = None
            if hasattr(exc, "response") and getattr(exc, "response", None) is not None:
                http_status = getattr(exc.response, "status_code", None)
            self._log_call(stage, resolved_model, start, "error", http_status, str(exc), None)
            if resolved_model == settings.step.model_fast and model == settings.step.model_agent:
                raise
            if model == settings.step.model_agent and http_status == 404:
                fallback_model = settings.step.model_fast
                if fallback_model and fallback_model != model:
                    fallback_payload = {**payload, "model": fallback_model}
                    return self._chat(fallback_model, fallback_payload, stage=stage)
            raise
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)))
    def chat(self, model: str, messages: list[dict], **kwargs: Any) -> ChatResult:
        payload = {"model": model, "messages": messages, **kwargs}
        return self._chat(model, payload, stage=kwargs.get("stage", "chat"))
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)))
    def vision(self, model: str, image_path: Path, prompt: str, **kwargs: Any) -> str:
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
            ]},
        ]
        payload = {"model": model, "messages": messages, **kwargs}
        result = self._chat(model, payload, stage=kwargs.get("stage", "vision"))
        return result.text
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)))
    def image(self, model: str, prompt: str, **kwargs: Any) -> Path:
        start = self._now()
        payload = {"model": model, "prompt": prompt, "n": 1, "size": kwargs.get("size", "1024x1024")}
        resp = self.client.post("/images/generations", json=payload)
        http_status = resp.status_code
        if http_status != 200:
            self._log_call("image", model, start, "error", http_status, resp.text, None)
            resp.raise_for_status()
        data = resp.json()
        item = data["data"][0]
        if item.get("url"):
            img_resp = httpx.get(item["url"], timeout=settings.step.timeout)
            img_resp.raise_for_status()
            content = img_resp.content
        elif item.get("b64_json"):
            content = base64.b64decode(item["b64_json"])
        else:
            raise ValueError("Image response missing url or b64_json")
        out = settings.outputs_dir / f"image_{int(start)}.png"
        out.write_bytes(content)
        self._log_call("image", model, start, "success", http_status, None, None)
        return out
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)))
    def tts(self, model: str, text: str, output_path: Path | None = None, **kwargs: Any) -> Path:
        start = self._now()
        voice = kwargs.get("voice", settings.step.tts_voice)
        response_format = kwargs.get("response_format", settings.step.tts_response_format)
        payload = {"model": model, "input": text, "voice": voice, "response_format": response_format}
        resp = self.client.post("/audio/speech", json=payload)
        http_status = resp.status_code
        if http_status != 200:
            self._log_call("tts", model, start, "error", http_status, resp.text, None)
            resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "audio" not in content_type:
            self._log_call("tts", model, start, "error", http_status, f"unexpected content-type: {content_type}", None)
            raise ValueError(f"TTS response is not audio: {content_type}")
        target = output_path or settings.outputs_dir / f"audio_{int(start)}.{response_format}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(resp.content)
        if target.stat().st_size == 0:
            self._log_call("tts", model, start, "error", http_status, "empty audio body", None)
            raise ValueError("TTS returned empty audio body")
        self._log_call("tts", model, start, "success", http_status, None, None)
        return target

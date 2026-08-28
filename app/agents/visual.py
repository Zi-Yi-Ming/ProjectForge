from __future__ import annotations
import json
import logging
import struct
import zlib
from pathlib import Path
from app.config import get_settings
from app.providers.base import ImageProvider
from app.providers.cache import cache_get, cache_set
from app.schemas.script import ScriptOutput
logger = logging.getLogger(__name__)
settings = get_settings()


def _create_placeholder_png(path: Path, width: int = 1080, height: int = 1920, color: tuple[int, int, int] = (17, 17, 17)) -> Path:
    """Create a minimal valid RGB PNG using stdlib only."""
    path = path.with_suffix(".png")

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + chunk + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)
    row = bytes([0x00] + list(color) * width)
    raw = row * height
    idat = _chunk(b"IDAT", zlib.compress(raw, 9))
    iend = _chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(signature + ihdr + idat + iend)
    return path


class VisualAgent:
    def __init__(self, image_provider: ImageProvider | None = None) -> None:
        self.image_provider = image_provider
    def run(self, task_id: str, script: ScriptOutput) -> Path:
        task_dir = settings.tasks_dir / task_id
        assets_dir = task_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        assets_json = []
        for scene in script.scenes:
            asset_path = assets_dir / f"scene_{scene.id:03d}.png"
            prompt = scene.visual_prompt or script.title
            cache_key = {"scene": scene.id, "prompt": prompt}
            cached = cache_get("visual", cache_key)
            is_placeholder = False
            if cached and cached.get("path"):
                cached_path = Path(cached["path"])
                if cached_path.exists() and cached_path.parent == assets_dir:
                    asset_path = cached_path
                else:
                    asset_path, is_placeholder = self._generate(task_id, scene, prompt, asset_path)
            else:
                asset_path, is_placeholder = self._generate(task_id, scene, prompt, asset_path)
            source = "stepfun" if not is_placeholder else "fallback"
            asset_type = "generated_image" if not is_placeholder else "placeholder"
            assets_json.append({"scene_id": scene.id, "type": asset_type, "path": str(asset_path), "source": source, "prompt": prompt})
        (assets_dir / "assets.json").write_text(json.dumps(assets_json, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("visual complete task_id=%s scenes=%d", task_id, len(script.scenes))
        return assets_dir
    def _generate(self, task_id: str, scene, prompt: str, asset_path: Path) -> tuple[Path, bool]:
        if self.image_provider:
            try:
                generated_path = self.image_provider.image(settings.step.model_image, prompt)
                asset_path.parent.mkdir(parents=True, exist_ok=True)
                asset_path.write_bytes(generated_path.read_bytes())
                return asset_path, False
            except Exception as exc:
                logger.warning("image provider failed task_id=%s scene=%s error=%s", task_id, scene.id, exc)
        return _create_placeholder_png(asset_path), True

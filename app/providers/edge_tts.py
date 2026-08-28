from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


async def _synthesize(text: str, output_path: Path, voice: str = _DEFAULT_VOICE) -> Path:
    import edge_tts

    output_path.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(text, voice=voice)
    await communicate.save(str(output_path))
    return output_path


def synthesize_edge_tts(text: str, output_path: Path, voice: str = _DEFAULT_VOICE) -> Path:
    return asyncio.run(_synthesize(text, output_path, voice))

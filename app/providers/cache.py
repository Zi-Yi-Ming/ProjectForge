from __future__ import annotations
import hashlib
import json
from pathlib import Path
from app.config import get_settings
def _namespace_path(namespace: str) -> Path:
    settings = get_settings()
    path = settings.cache_dir / namespace
    path.mkdir(parents=True, exist_ok=True)
    return path
def _stable_key(value: dict | str) -> str:
    if isinstance(value, dict):
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False)
    else:
        raw = str(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
def cache_get(namespace: str, key: dict | str) -> dict | None:
    path = _namespace_path(namespace) / f"{_stable_key(key)}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
def cache_set(namespace: str, key: dict | str, value: dict) -> None:
    path = _namespace_path(namespace) / f"{_stable_key(key)}.json"
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

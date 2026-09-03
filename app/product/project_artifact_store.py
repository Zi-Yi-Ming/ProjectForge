from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.schemas.blueprint import ProjectBlueprint
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.task import TaskGraph


class ProjectArtifactStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(".runtime/projects")

    def save(self, project_id: str, artifact_name: str, obj: Any) -> str:
        artifact_dir = self.base_dir / project_id / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        target = artifact_dir / f"{artifact_name}.json"
        fd, tmp = tempfile.mkstemp(dir=artifact_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                if hasattr(obj, "model_dump"):
                    json.dump(obj.model_dump(), f, ensure_ascii=False, indent=2)
                else:
                    json.dump(obj, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(target))
        except Exception:
            if Path(tmp).exists():
                Path(tmp).unlink()
            raise
        return str(target)

    def load(self, project_id: str, artifact_name: str) -> Any:
        path = self.base_dir / project_id / "artifacts" / f"{artifact_name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Artifact {artifact_name} for project {project_id} not found.")
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data

    def exists(self, project_id: str, artifact_name: str) -> bool:
        return (self.base_dir / project_id / "artifacts" / f"{artifact_name}.json").exists()

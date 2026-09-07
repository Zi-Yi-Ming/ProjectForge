from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.schemas.project import Project


class ProjectPersistence:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(".runtime/projects")

    def save_project(self, project: Project) -> None:
        project_dir = self.base_dir / project.project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        path = project_dir / "project.json"
        fd, tmp = tempfile.mkstemp(dir=project_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(project.model_dump(), f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(path))
        except Exception:
            if Path(tmp).exists():
                Path(tmp).unlink()
            raise

    def load_project(self, project_id: str) -> Project:
        path = self.base_dir / project_id / "project.json"
        if not path.exists():
            raise FileNotFoundError(f"Project {project_id} not found")
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return Project.model_validate(data)

    def exists(self, project_id: str) -> bool:
        return (self.base_dir / project_id / "project.json").exists()

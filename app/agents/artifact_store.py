from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.schemas.persistence import Artifact, ArtifactType


class ArtifactStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.artifacts_dir = run_dir / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def save(self, artifact: Artifact, content: str | bytes) -> Artifact:
        if not artifact.artifact_id:
            raise ValueError("artifact_id is required")
        suffix = self._suffix_for_type(artifact.artifact_type)
        target = self.artifacts_dir / f"{artifact.artifact_id}{suffix}"
        if isinstance(content, str):
            fd, tmp = tempfile.mkstemp(dir=self.artifacts_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, str(target))
            except Exception:
                if Path(tmp).exists():
                    Path(tmp).unlink()
                raise
        else:
            fd, tmp = tempfile.mkstemp(dir=self.artifacts_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, str(target))
            except Exception:
                if Path(tmp).exists():
                    Path(tmp).unlink()
                raise
        artifact.path = str(target.relative_to(self.run_dir))
        return artifact

    def load(self, artifact_id: str) -> tuple[Artifact, str | bytes]:
        candidates = list(self.artifacts_dir.glob(f"{artifact_id}.*"))
        if not candidates:
            raise FileNotFoundError(f"artifact {artifact_id} not found")
        target = candidates[0]
        artifact_type = ArtifactType.AGENT_OUTPUT
        if target.suffix.lower() == ".diff":
            artifact_type = ArtifactType.DIFF
        elif target.suffix.lower() == ".txt":
            artifact_type = ArtifactType.ERROR_LOG
        elif target.suffix.lower() == ".json":
            artifact_type = ArtifactType.VALIDATION_RESULT
        artifact = Artifact(
            artifact_id=artifact_id,
            task_id="",
            artifact_type=artifact_type,
            path=str(target.relative_to(self.run_dir)),
        )
        if target.suffix.lower() == ".json":
            data = target.read_text(encoding="utf-8")
            return artifact, data
        return artifact, target.read_bytes()

    def list_for_task(self, task_id: str) -> list[Artifact]:
        results: list[Artifact] = []
        for path in self.artifacts_dir.iterdir():
            if path.stem.startswith(f"{task_id}_"):
                results.append(
                    Artifact(
                        artifact_id=path.stem,
                        task_id=task_id,
                        artifact_type=ArtifactType.AGENT_OUTPUT,
                        path=str(path.relative_to(self.run_dir)),
                    )
                )
        results.sort(key=lambda a: a.artifact_id)
        return results

    @staticmethod
    def _suffix_for_type(artifact_type: ArtifactType) -> str:
        mapping = {
            ArtifactType.AGENT_OUTPUT: ".json",
            ArtifactType.VALIDATION_RESULT: ".json",
            ArtifactType.GIT_CHECKPOINT: ".json",
            ArtifactType.DIFF: ".diff",
            ArtifactType.TEST_RESULT: ".txt",
            ArtifactType.ERROR_LOG: ".txt",
        }
        return mapping.get(artifact_type, ".bin")

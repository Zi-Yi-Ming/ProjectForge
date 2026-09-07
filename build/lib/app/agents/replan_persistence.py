from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.schemas.persistence import Artifact, ArtifactType, PersistedExecution
from app.schemas.replan import ReplanProposal


class ReplanPersistence:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(".runtime")
        self.runs_dir = self.base_dir / "runs"

    def save_proposal(self, proposal: ReplanProposal) -> None:
        run_dir = self.runs_dir / proposal.run_id / "replans"
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{proposal.proposal_id}.json"
        self._write_json(path, proposal.model_dump())

    def load_proposal(self, run_id: str, proposal_id: str) -> ReplanProposal:
        path = self.runs_dir / run_id / "replans" / f"{proposal_id}.json"
        data = self._read_json(path)
        return ReplanProposal.model_validate(data)

    def list_proposals(self, run_id: str) -> list[ReplanProposal]:
        replans_dir = self.runs_dir / run_id / "replans"
        if not replans_dir.exists():
            return []
        proposals: list[ReplanProposal] = []
        for path in replans_dir.glob("*.json"):
            data = self._read_json(path)
            proposals.append(ReplanProposal.model_validate(data))
        proposals.sort(key=lambda p: p.created_at)
        return proposals

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(path))
        except Exception:
            if Path(tmp).exists():
                Path(tmp).unlink()
            raise

    def _read_json(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.artifact_store import ArtifactStore
from app.schemas.persistence import Artifact, ArtifactType


def test_save_and_load_text_artifact(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact = Artifact(artifact_id="T1_output", task_id="T1", artifact_type=ArtifactType.AGENT_OUTPUT)
    saved = store.save(artifact, "hello world")
    assert saved.path.endswith(".json")
    loaded_artifact, content = store.load("T1_output")
    assert loaded_artifact.artifact_id == "T1_output"
    assert content == "hello world"


def test_save_and_load_diff_artifact(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact = Artifact(artifact_id="T1_diff", task_id="T1", artifact_type=ArtifactType.DIFF)
    saved = store.save(artifact, b"diff --git a/x.py b/x.py\n")
    assert saved.path.endswith(".diff")
    loaded_artifact, content = store.load("T1_diff")
    assert loaded_artifact.artifact_id == "T1_diff"
    assert content == b"diff --git a/x.py b/x.py\n"


def test_list_for_task_filters_by_prefix(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    for task_id, artifact_id in [("T1", "T1_output"), ("T1", "T1_validation"), ("T2", "T2_output")]:
        artifact = Artifact(artifact_id=artifact_id, task_id=task_id, artifact_type=ArtifactType.AGENT_OUTPUT)
        store.save(artifact, "")
    assert len(store.list_for_task("T1")) == 2
    assert len(store.list_for_task("T2")) == 1


def test_save_requires_artifact_id(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError):
        store.save(Artifact(artifact_id="", task_id="T1", artifact_type=ArtifactType.AGENT_OUTPUT), "")


def test_load_missing_artifact(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.load("missing")

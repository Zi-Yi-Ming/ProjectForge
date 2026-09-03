from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.replan_persistence import ReplanPersistence
from app.schemas.replan import ReplanAction, ReplanProposal, ReplanProposalStatus


def test_save_and_load_proposal(tmp_path: Path) -> None:
    persistence = ReplanPersistence(base_dir=tmp_path)
    proposal = ReplanProposal(proposal_id="rp-1", run_id="run-1", task_id="T1", action="BLOCK")
    persistence.save_proposal(proposal)
    loaded = persistence.load_proposal("run-1", "rp-1")
    assert loaded.proposal_id == "rp-1"
    assert loaded.run_id == "run-1"


def test_list_proposals_sorted(tmp_path: Path) -> None:
    persistence = ReplanPersistence(base_dir=tmp_path)
    for proposal_id in ["rp-2", "rp-1"]:
        persistence.save_proposal(ReplanProposal(proposal_id=proposal_id, run_id="run-1", task_id="T1", action="BLOCK", created_at=proposal_id))
    proposals = persistence.list_proposals("run-1")
    assert [p.proposal_id for p in proposals] == ["rp-1", "rp-2"]

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_discovery_contract_defines_structural_navigation_and_bounded_queries() -> None:
    phase = (ROOT / "runtime/workflow/phases/re-knowledge-discovery.md").read_text()
    agent = (ROOT / "prosaic/subagents/echelon.re-discoverer.md").read_text()

    for text in (phase, agent):
        text = " ".join(text.split())
        assert "structural_evidence" in text
        assert "structural-query" in text
        assert "navigation" in text
        assert "not evidence of absence" in text


@pytest.mark.unit
def test_discovery_reviewer_contract_checks_structure_without_certifying_it() -> None:
    reviewer = (
        ROOT / "prosaic/subagents/echelon.re-discovery-reviewer.md"
    ).read_text()
    reviewer = " ".join(reviewer.split())

    assert "structural_evidence" in reviewer
    assert "navigation" in reviewer
    assert "not evidence of absence" in reviewer
    assert "source evidence" in reviewer


@pytest.mark.unit
def test_exhaustive_roles_treat_structure_as_navigation_only() -> None:
    for name in (
        "echelon.re-exhaustive-analyst.md",
        "echelon.re-exhaustive-verifier.md",
    ):
        text = " ".join((ROOT / "prosaic/subagents" / name).read_text().split())
        assert "structural_evidence" in text
        assert "navigation" in text
        assert "not evidence of absence" in text
        assert "permitted evidence anchors" in text

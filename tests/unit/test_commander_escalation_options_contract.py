"""Tests for COMMANDER escalation option contract."""

from __future__ import annotations

from pathlib import Path


def test_commander_human_escalations_require_structured_options() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "extension" / "agents" / "control" / "commander.md").read_text(
        encoding="utf-8"
    )

    assert "escalation_options" in text
    assert "Do not offer any choice that cannot be represented as an executable option" in text
    assert "next_phase" in text
    assert "valid workflow phase IDs" in text


def test_commander_decision_resolution_has_strict_non_mutating_authority() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "extension" / "agents" / "control" / "commander.md").read_text(
        encoding="utf-8"
    )

    assert "DECISION_RESOLVED" in text
    assert "selected_option_id" in text
    assert "answer_text" in text
    assert "Do not ask another question" in text
    assert "Do not write files" in text
    assert "state_updates: {}" in text
    assert "journal_entries: []" in text
    assert "user-clarifications.md" not in text
    assert "escalation_question: null" not in text

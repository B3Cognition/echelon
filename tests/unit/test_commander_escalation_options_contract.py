"""Tests for COMMANDER escalation option contract."""

from __future__ import annotations

from pathlib import Path


def test_commander_generic_judgment_has_no_unregistered_human_question_path() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "prosaic" / "subagents" / "echelon.commander.md").read_text(
        encoding="utf-8"
    )

    assert "JUDGMENT_RESOLVED" in text
    assert "BLOCKED" in text
    assert "Generic judgments must not originate a human question" in text
    assert "**Human escalation**" not in text
    assert "escalation_question:" not in text
    assert "escalation_options:" not in text


def test_commander_decision_resolution_has_strict_non_mutating_authority() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "prosaic" / "subagents" / "echelon.commander.md").read_text(
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

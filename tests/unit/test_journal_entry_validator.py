"""Tests for Python reasoning-journal entry validation."""

from harness.journal_entry_validator import (
    prepare_journal_entries_for_append,
    validate_journal_entry,
)


def test_valid_registered_entry_passes() -> None:
    verdict = validate_journal_entry(
        {
            "type": "routing_decision",
            "data": {
                "from_phase": "phase1-why1",
                "to_phase": "phase2-how",
                "reason": "complete",
                "evoi_score": 0.8,
            },
        }
    )

    assert verdict.valid
    assert verdict.errors == []


def test_missing_required_field_fails_registered_type() -> None:
    verdict = validate_journal_entry(
        {
            "type": "routing_decision",
            "data": {
                "from_phase": "phase1-why1",
                "to_phase": "phase2-how",
                "reason": "missing score",
            },
        }
    )

    assert not verdict.valid
    assert "evoi_score" in verdict.errors[0]


def test_unknown_type_warns_but_is_valid() -> None:
    verdict = validate_journal_entry({"type": "future_signal", "data": {"x": 1}})

    assert verdict.valid
    assert verdict.warnings == ["Type not registered in schema: future_signal"]


def test_prepare_adds_schema_warning_for_invalid_registered_type() -> None:
    prepared = prepare_journal_entries_for_append(
        [
            {
                "type": "routing_decision",
                "data": {
                    "from_phase": "phase1-why1",
                    "to_phase": "phase2-how",
                    "reason": "missing score",
                },
            }
        ],
        phase_id="phase1-why1",
        next_id=7,
        timestamp="2026-06-26T12:00:00Z",
    )

    assert [entry["type"] for entry in prepared] == ["routing_decision", "schema_warning"]
    assert prepared[0]["id"] == 7
    assert prepared[1]["id"] == 8
    assert prepared[1]["data"]["violating_entry_id"] == 7
    assert prepared[1]["data"]["violation_type"] == "missing_required_field"


def test_prepare_quarantines_invalid_registered_type_when_strict() -> None:
    prepared = prepare_journal_entries_for_append(
        [
            {
                "type": "routing_decision",
                "data": {
                    "from_phase": "phase1-why1",
                    "to_phase": "phase2-how",
                    "reason": "missing score",
                },
            }
        ],
        phase_id="phase1-why1",
        next_id=7,
        timestamp="2026-06-26T12:00:00Z",
        invalid_registered_policy="quarantine",
    )

    assert [entry["type"] for entry in prepared] == ["schema_warning"]
    assert prepared[0]["id"] == 7
    assert prepared[0]["data"]["violating_entry_type"] == "routing_decision"
    assert prepared[0]["data"]["violation_type"] == "missing_required_field"

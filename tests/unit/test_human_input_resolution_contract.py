"""Tests for the closed COMMANDER decision-resolution result contract."""

from __future__ import annotations

import pytest

import harness.echelon_result_schema as result_schema
from harness.echelon_result_schema import (
    EchelonResultValidationError,
    validate_decision_resolution_result,
)
from harness.human_input import HumanInputOption


OPTIONS = (
    HumanInputOption(
        id="approve",
        label="Approve",
        description="Continue with the declared plan.",
        recommended=True,
        risk_level="low",
        next_phase="phase4-document",
        outcome="approved",
    ),
)


def _decision_resolution_payload(*, decision: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "verdict": "DECISION_RESOLVED",
        "state_updates": {},
        "journal_entries": [],
        "decision": decision or {
            "selected_option_id": "approve",
            "answer_text": None,
            "rationale": "The declared plan is internally consistent.",
            "confidence": "high",
        },
    }


def test_decision_resolution_accepts_the_exact_choice_envelope() -> None:
    resolution = validate_decision_resolution_result(
        _decision_resolution_payload(),
        options=OPTIONS,
    )

    assert resolution.selected_option_id == "approve"
    assert resolution.answer_text is None
    assert resolution.rationale == "The declared plan is internally consistent."
    assert resolution.confidence == "high"


def test_decision_resolution_enforces_the_exported_rationale_limit() -> None:
    limit = result_schema.DECISION_RESOLUTION_RATIONALE_MAX_CHARS
    accepted = _decision_resolution_payload(
        decision={
            "selected_option_id": "approve",
            "answer_text": None,
            "rationale": "r" * limit,
            "confidence": "high",
        }
    )
    rejected = _decision_resolution_payload(
        decision={
            "selected_option_id": "approve",
            "answer_text": None,
            "rationale": "r" * (limit + 1),
            "confidence": "high",
        }
    )

    resolution = validate_decision_resolution_result(accepted, options=OPTIONS)

    assert len(resolution.rationale) == limit
    with pytest.raises(
        EchelonResultValidationError,
        match=rf"at most {limit:,} characters",
    ):
        validate_decision_resolution_result(rejected, options=OPTIONS)


@pytest.mark.parametrize(
    "payload",
    [
        {
            **_decision_resolution_payload(),
            1: "malformed field name",
            "unexpected": "extra field",
        },
        _decision_resolution_payload(
            decision={
                "selected_option_id": "approve",
                "answer_text": None,
                "rationale": "The declared plan is internally consistent.",
                "confidence": "high",
                1: "malformed field name",
                "unexpected": "extra field",
            }
        ),
    ],
)
def test_decision_resolution_rejects_mixed_type_extra_field_names(
    payload: dict[object, object],
) -> None:
    with pytest.raises(
        EchelonResultValidationError,
        match="field names must be strings",
    ):
        validate_decision_resolution_result(payload, options=OPTIONS)


@pytest.mark.parametrize(
    ("payload", "options", "match"),
    [
        (
            {
                **_decision_resolution_payload(),
                "unexpected": True,
            },
            OPTIONS,
            "unsupported field",
        ),
        (
            {
                **_decision_resolution_payload(),
                "state_updates": {"phase": "phase4-document"},
            },
            OPTIONS,
            "state_updates",
        ),
        (
            {
                **_decision_resolution_payload(),
                "journal_entries": [{"kind": "note"}],
            },
            OPTIONS,
            "journal_entries",
        ),
        (
            _decision_resolution_payload(
                decision={
                    "selected_option_id": "invented",
                    "answer_text": None,
                    "rationale": "The declared plan is internally consistent.",
                    "confidence": "high",
                }
            ),
            OPTIONS,
            "selected_option_id",
        ),
        (
            _decision_resolution_payload(
                decision={
                    "selected_option_id": "approve",
                    "answer_text": "Proceed.",
                    "rationale": "The declared plan is internally consistent.",
                    "confidence": "high",
                }
            ),
            OPTIONS,
            "exactly one",
        ),
        (
            _decision_resolution_payload(
                decision={
                    "selected_option_id": None,
                    "answer_text": None,
                    "rationale": "The declared plan is internally consistent.",
                    "confidence": "high",
                }
            ),
            OPTIONS,
            "exactly one",
        ),
        (
            _decision_resolution_payload(
                decision={
                    "selected_option_id": "approve",
                    "answer_text": None,
                    "rationale": "The declared plan is internally consistent.",
                    "confidence": "certain",
                }
            ),
            OPTIONS,
            "confidence",
        ),
        (
            _decision_resolution_payload(
                decision={
                    "selected_option_id": "approve",
                    "answer_text": None,
                    "rationale": "The declared plan is internally consistent.",
                    "confidence": ["high"],
                }
            ),
            OPTIONS,
            "confidence",
        ),
        (
            {
                **_decision_resolution_payload(),
                "verdict": "BLOCKED",
            },
            OPTIONS,
            "DECISION_RESOLVED",
        ),
        (
            _decision_resolution_payload(
                decision={
                    "selected_option_id": "approve",
                    "answer_text": None,
                    "rationale": "r" * 2_001,
                    "confidence": "high",
                }
            ),
            OPTIONS,
            "rationale",
        ),
    ],
)
def test_decision_resolution_rejects_noncanonical_envelopes(
    payload: dict[str, object],
    options: tuple[HumanInputOption, ...],
    match: str,
) -> None:
    with pytest.raises(EchelonResultValidationError, match=match):
        validate_decision_resolution_result(payload, options=options)


def test_decision_resolution_requires_nonempty_free_text_without_options() -> None:
    resolution = validate_decision_resolution_result(
        _decision_resolution_payload(
            decision={
                "selected_option_id": None,
                "answer_text": "Use the existing product boundary.",
                "rationale": "It preserves the declared constraints.",
                "confidence": "medium",
            }
        ),
        options=(),
    )

    assert resolution.selected_option_id is None
    assert resolution.answer_text == "Use the existing product boundary."

"""Tests for typed blocked decisions and resume metadata."""

from __future__ import annotations

import pytest

from harness.blocked_decision import (
    BlockedDecisionError,
    build_blocked_decision,
    build_blocked_decision_v2,
    build_resume_metadata,
    ensure_blocked_decision,
    validate_blocked_decision,
    validate_blocked_decision_v2,
)


def _v2_decision() -> dict[str, object]:
    return {
        "schema_version": 2,
        "id": "dec-7f4d2",
        "status": "pending",
        "source_kind": "provider_escalation",
        "producer_id": "phase1-why1",
        "source_phase": "phase1-why1",
        "reason_code": "human_clarification_required",
        "classification": "material",
        "question": "Which product constraint should apply?",
        "options": [],
        "recommended_answer": None,
        "risk_level": None,
        "resolution_handler": "clarification_resume",
        "autonomy_mode": "banzai",
        "source_state_revision": 42,
        "selected_option_id": None,
        "answer_text": None,
        "resolved_by": None,
        "attempts": 0,
        "failure_code": None,
        "created_at": "2026-07-28T10:00:00+00:00",
        "resolved_at": None,
    }


def test_builds_free_text_blocked_decision_when_no_choices_exist() -> None:
    decision = build_blocked_decision(
        {
            "status": "blocked",
            "phase": "phase1-why1",
            "blocked_reason": "consecutive_why_fails",
            "escalation_question": "What product constraint should CARTOGRAPHER apply?",
        },
        now="2026-06-23T10:00:00+00:00",
    )

    assert decision == {
        "schema_version": 1,
        "status": "pending",
        "answer_type": "free_text",
        "question": "What product constraint should CARTOGRAPHER apply?",
        "blocked_reason": "consecutive_why_fails",
        "blocked_phase": "phase1-why1",
        "blocked_at": "2026-06-23T10:00:00+00:00",
    }


def test_builds_choice_blocked_decision_with_recommendation_and_risk() -> None:
    decision = build_blocked_decision(
        {
            "status": "blocked",
            "phase": "checkpoint-assess",
            "blocked_reason": "checkpoint-assess human gate",
            "escalation_question": "A: return to WHAT\nB: proceed",
            "escalation_options": [
                {
                    "id": "route_back_to_what",
                    "label": "Return to WHAT",
                    "next_phase": "phase1-what",
                    "recommended": True,
                },
                {
                    "id": "proceed_anyway",
                    "label": "Proceed to DECIDE",
                    "next_phase": "phase2-decide",
                },
            ],
            "escalation_risk_level": "high",
        },
        now="2026-06-23T10:00:00+00:00",
    )

    assert decision["answer_type"] == "choice"
    assert decision["risk_level"] == "high"
    assert decision["recommended_answer"] == "route_back_to_what"
    assert decision["default_answer"] == "route_back_to_what"
    assert decision["options"] == [
        {
            "id": "route_back_to_what",
            "label": "Return to WHAT",
            "next_phase": "phase1-what",
            "recommended": True,
        },
        {
            "id": "proceed_anyway",
            "label": "Proceed to DECIDE",
            "next_phase": "phase2-decide",
        },
    ]


def test_build_resume_metadata_records_free_text_answer() -> None:
    metadata = build_resume_metadata(
        answer="Use a narrower audience and keep missions under 10 minutes.",
        state={
            "blocked_decision": {
                "schema_version": 1,
                "answer_type": "free_text",
                "blocked_phase": "phase1-why1",
            },
        },
        selected_option=None,
        resumed_phase="phase1-why1",
        now="2026-06-23T10:05:00+00:00",
    )

    assert metadata == {
        "schema_version": 1,
        "answered_at": "2026-06-23T10:05:00+00:00",
        "answered_by": "user",
        "source": "echelon spec resume",
        "answer_type": "free_text",
        "answer_text": "Use a narrower audience and keep missions under 10 minutes.",
        "blocked_phase": "phase1-why1",
        "resumed_phase": "phase1-why1",
    }


def test_builds_schema_v2_blocked_decision_with_all_nullable_fields_explicit() -> None:
    decision = build_blocked_decision_v2(
        decision_id="dec-7f4d2",
        status="pending",
        source_kind="provider_escalation",
        producer_id="phase1-why1",
        source_phase="phase1-why1",
        reason_code="human_clarification_required",
        classification="material",
        question="Which product constraint should apply?",
        options=[],
        recommended_answer=None,
        risk_level=None,
        resolution_handler="clarification_resume",
        autonomy_mode="banzai",
        source_state_revision=42,
        now="2026-07-28T10:00:00+00:00",
    )

    assert decision == _v2_decision()
    assert validate_blocked_decision_v2(decision) == decision


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda decision: decision.update({"unknown": "field"}),
            "unknown blocked decision field",
        ),
        (
            lambda decision: decision.update({"status": "paused"}),
            "unknown blocked decision status",
        ),
        (
            lambda decision: decision.update({"id": "decision-7f4d2"}),
            "blocked decision id",
        ),
        (
            lambda decision: decision.pop("source_state_revision"),
            "missing blocked decision field",
        ),
        (
            lambda decision: decision.update({"attempts": -1}),
            "attempts must be a non-negative integer",
        ),
        (
            lambda decision: decision.update({"created_at": "yesterday"}),
            "created_at must be a UTC timestamp",
        ),
        (
            lambda decision: decision.update(
                {
                    "options": [
                        {
                            "id": "approve",
                            "label": "Approve",
                            "description": "Continue.",
                            "recommended": True,
                            "risk_level": "low",
                            "next_phase": "phase2-decide",
                            "outcome": None,
                        }
                    ],
                    "recommended_answer": "Free text recommendation",
                }
            ),
            "choice decisions cannot record recommended_answer",
        ),
        (
            lambda decision: decision.update(
                {
                    "status": "resolved",
                    "selected_option_id": "undeclared",
                    "answer_text": None,
                    "resolved_by": "user",
                    "resolved_at": "2026-07-28T10:01:00+00:00",
                }
            ),
            "selected_option_id requires a declared option",
        ),
        (
            lambda decision: decision.update(
                {
                    "options": [
                        {
                            "id": "approve",
                            "label": "Approve",
                            "description": "Continue.",
                            "recommended": True,
                            "risk_level": "low",
                            "next_phase": "phase2-decide",
                            "outcome": None,
                        }
                    ],
                    "status": "resolved",
                    "selected_option_id": "approve",
                    "answer_text": "Continue.",
                    "resolved_by": "user",
                    "resolved_at": "2026-07-28T10:01:00+00:00",
                }
            ),
            "choice decisions cannot record answer_text",
        ),
    ],
)
def test_schema_v2_blocked_decision_rejects_unsafe_shapes(
    mutate: object,
    message: str,
) -> None:
    decision = _v2_decision()
    assert callable(mutate)
    mutate(decision)

    with pytest.raises(BlockedDecisionError, match=message):
        validate_blocked_decision_v2(decision)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda decision: decision.update({1: "invalid", "unknown": "invalid"}),
        lambda decision: decision.update(
            {
                "options": [
                    {
                        "id": "approve",
                        "label": "Approve",
                        "description": "Continue.",
                        "recommended": True,
                        "risk_level": "low",
                        "next_phase": "phase2-decide",
                        "outcome": None,
                        1: "invalid",
                        "unknown": "invalid",
                    }
                ]
            }
        ),
    ],
)
def test_schema_v2_blocked_decision_rejects_mixed_mapping_key_types(
    mutate: object,
) -> None:
    decision = _v2_decision()
    assert callable(mutate)
    mutate(decision)

    with pytest.raises(BlockedDecisionError):
        validate_blocked_decision_v2(decision)


@pytest.mark.parametrize("schema_version", [True, "2", 3])
def test_blocked_decision_dispatch_requires_an_exact_integer_schema_version(
    schema_version: object,
) -> None:
    decision = _v2_decision()
    decision["schema_version"] = schema_version

    with pytest.raises(BlockedDecisionError, match="unsupported blocked decision schema"):
        validate_blocked_decision(decision)


@pytest.mark.parametrize(
    "state",
    [
        {"status": "blocked", "escalation_question": "Answer this."},
        {"status": "running", "escalation_question": "Stale display text."},
        {"status": "blocked", "escalation_question": None},
    ],
)
def test_ensure_blocked_decision_never_replaces_a_schema_v2_mapping(
    state: dict[str, object],
) -> None:
    decision = {"schema_version": 2, "opaque": "leave me untouched"}
    state["blocked_decision"] = decision

    ensure_blocked_decision(state)

    assert state["blocked_decision"] is decision

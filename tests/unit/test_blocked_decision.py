"""Tests for typed blocked decisions and resume metadata."""

from __future__ import annotations

from harness.blocked_decision import (
    build_blocked_decision,
    build_resume_metadata,
)


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

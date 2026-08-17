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
        (
            lambda decision: decision.update(
                {
                    "options": [
                        {
                            "id": "approve",
                            "label": "Same label",
                            "description": "Continue.",
                            "recommended": True,
                            "risk_level": "low",
                            "next_phase": "phase2-decide",
                            "outcome": None,
                        },
                        {
                            "id": "reject",
                            "label": "Same label",
                            "description": "Stop.",
                            "recommended": False,
                            "risk_level": "low",
                            "next_phase": "phase1-what",
                            "outcome": None,
                        },
                    ]
                }
            ),
            "duplicate option label",
        ),
        (
            lambda decision: decision.update(
                {
                    "options": [
                        {
                            "id": "approve",
                            "label": "reject",
                            "description": "Continue.",
                            "recommended": True,
                            "risk_level": "low",
                            "next_phase": "phase2-decide",
                            "outcome": None,
                        },
                        {
                            "id": "reject",
                            "label": "Reject",
                            "description": "Stop.",
                            "recommended": False,
                            "risk_level": "low",
                            "next_phase": "phase1-what",
                            "outcome": None,
                        },
                    ]
                }
            ),
            "option label conflicts with an option id",
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


def test_schema_v2_allows_an_option_whose_own_id_is_its_label() -> None:
    decision = _v2_decision()
    decision["options"] = [
        {
            "id": "continue",
            "label": "continue",
            "description": "Continue with the bounded investigation.",
            "recommended": True,
            "risk_level": "low",
            "next_phase": "phase1-what",
            "outcome": None,
        }
    ]

    assert validate_blocked_decision_v2(decision)["options"] == decision["options"]


def _v2_decision_with_status(status: str, attempts: int) -> dict[str, object]:
    decision = _v2_decision()
    decision["status"] = status
    decision["attempts"] = attempts
    if status == "failed":
        decision["failure_code"] = "decision_setup_failed" if attempts == 0 else "provider_failed"
    elif status == "resolved":
        decision.update(
            {
                "answer_text": "Use the bounded answer.",
                "resolved_by": "user" if attempts == 0 else "COMMANDER",
                "resolved_at": "2026-07-28T10:01:00+00:00",
            }
        )
    return decision


@pytest.mark.parametrize(
    ("status", "attempts"),
    [
        ("pending", 0),
        ("pending", 1),
        ("resolving", 1),
        ("resolving", 2),
        ("awaiting_human", 0),
        ("failed", 0),
        ("failed", 1),
        ("failed", 2),
        ("resolved", 0),
        ("resolved", 1),
        ("resolved", 2),
    ],
)
def test_schema_v2_accepts_only_reachable_status_attempt_combinations(
    status: str,
    attempts: int,
) -> None:
    decision = _v2_decision_with_status(status, attempts)

    assert validate_blocked_decision_v2(decision)["attempts"] == attempts


@pytest.mark.parametrize(
    ("status", "attempts"),
    [
        ("pending", 2),
        ("pending", 3),
        ("resolving", 0),
        ("resolving", 3),
        ("awaiting_human", 1),
        ("failed", 3),
        ("resolved", 3),
    ],
)
def test_schema_v2_rejects_unreachable_status_attempt_combinations(
    status: str,
    attempts: int,
) -> None:
    decision = _v2_decision_with_status(status, attempts)

    with pytest.raises(BlockedDecisionError, match="attempt"):
        validate_blocked_decision_v2(decision)


def test_schema_v2_dispatch_cap_requires_at_least_one_complete_option() -> None:
    decision = _v2_decision()
    decision.update(
        {
            "source_kind": "controller_safeguard",
            "producer_id": "phase_dispatch_limit",
            "reason_code": "phase_dispatch_limit",
            "resolution_handler": "phase_dispatch_limit",
            "options": [],
        }
    )

    with pytest.raises(BlockedDecisionError, match="option"):
        validate_blocked_decision_v2(decision)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("question", "q" * 40_000),
        ("recommended_answer", "r" * 40_000),
        ("producer_id", "p" * 5_000),
        ("reason_code", "r" * 5_000),
        ("resolution_handler", "h" * 5_000),
    ],
)
def test_schema_v2_bounds_every_prompt_request_string(
    field: str,
    value: str,
) -> None:
    decision = _v2_decision()
    decision[field] = value
    if field == "recommended_answer":
        decision["risk_level"] = "low"

    with pytest.raises(BlockedDecisionError, match=field):
        validate_blocked_decision_v2(decision)


def test_schema_v2_bounds_option_count_and_option_fields() -> None:
    decision = _v2_decision()
    decision["options"] = [
        {
            "id": f"option-{index}",
            "label": f"Option {index}",
            "description": "One bounded option.",
            "recommended": False,
            "risk_level": "medium",
            "next_phase": "phase1-what",
            "outcome": None,
        }
        for index in range(65)
    ]

    with pytest.raises(BlockedDecisionError, match="options"):
        validate_blocked_decision_v2(decision)

    decision = _v2_decision()
    decision["options"] = [
        {
            "id": "option",
            "label": "Option",
            "description": "d" * 5_000,
            "recommended": False,
            "risk_level": "medium",
            "next_phase": "phase1-what",
            "outcome": None,
        }
    ]

    with pytest.raises(BlockedDecisionError, match="description"):
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


def _proportional_quality_decision() -> dict[str, object]:
    decision = _v2_decision()
    decision.update(
        {
            "source_kind": "controller_safeguard",
            "producer_id": "proportional_quality_budget_exhausted",
            "source_phase": "phase1-why2",
            "reason_code": "proportional_quality_budget_exhausted",
            "classification": "material",
            "question": "Choose how to resolve the exhausted quality budget.",
            "resolution_handler": "proportional_quality_debt",
            "options": [
                {
                    "id": "extend_once",
                    "label": "Extend once",
                    "description": "Authorize one final specification quality repair.",
                    "recommended": True,
                    "risk_level": "medium",
                    "next_phase": "phase1-what",
                    "outcome": None,
                },
                {
                    "id": "continue_with_debt",
                    "label": "Continue with debt",
                    "description": "Accept the restored candidate with explicit quality debt.",
                    "recommended": False,
                    "risk_level": "high",
                    "next_phase": None,
                    "outcome": None,
                },
                {
                    "id": "stop",
                    "label": "Stop",
                    "description": "Preserve the blocked run without accepting quality debt.",
                    "recommended": False,
                    "risk_level": "low",
                    "next_phase": "terminal-blocked",
                    "outcome": None,
                },
            ],
        }
    )
    return decision


def test_schema_v2_accepts_a_sealed_proportional_quality_choice_decision() -> None:
    decision = _proportional_quality_decision()

    normalized = validate_blocked_decision_v2(decision)

    assert normalized["schema_version"] == 2
    assert [option["id"] for option in normalized["options"]] == [
        "extend_once",
        "continue_with_debt",
        "stop",
    ]


def test_schema_v2_requires_an_option_for_proportional_quality_debt_resolution(
) -> None:
    decision = _proportional_quality_decision()
    decision["options"] = []

    with pytest.raises(BlockedDecisionError, match="option"):
        validate_blocked_decision_v2(decision)


def test_schema_v2_keeps_two_as_the_proportional_commander_attempt_limit() -> None:
    decision = _proportional_quality_decision()
    decision.update(
        {
            "status": "failed",
            "attempts": 2,
            "failure_code": "invalid_resolution_result",
        }
    )
    assert validate_blocked_decision_v2(decision)["attempts"] == 2

    decision["attempts"] = 3
    with pytest.raises(BlockedDecisionError, match="attempts must not exceed 2"):
        validate_blocked_decision_v2(decision)

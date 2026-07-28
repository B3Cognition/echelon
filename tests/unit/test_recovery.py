from __future__ import annotations

import pytest

from harness.recovery_instruction import (
    RecoveryInstructionError,
    controller_contract_recovery,
    retry_phase_recovery,
    trusted_executor_block_recovery,
    validate_decision_recovery_pair,
    validate_recovery_instruction,
)


def _v2_decision(status: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "id": "dec-7f4d2",
        "status": status,
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
        "failure_code": "commander_failure" if status == "failed" else None,
        "created_at": "2026-07-28T10:00:00+00:00",
        "resolved_at": None,
    }


def _v2_instruction(kind: str, *, phase: str, requires_human_input: bool) -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": kind,
        "reason_code": "human_clarification_required",
        "phase": phase,
        "requires_human_input": requires_human_input,
        "decision_id": "dec-7f4d2",
    }


def test_controller_contract_recovery_retries_current_phase_after_runtime_sync() -> None:
    instruction = controller_contract_recovery("phase1-why2")

    assert instruction.to_dict() == {
        "schema_version": 1,
        "kind": "sync_runtime_then_retry",
        "reason_code": "controller_state_contract_validation_failed",
        "phase": "phase1-why2",
        "requires_human_input": False,
    }


def test_retry_phase_recovery_preserves_failure_reason() -> None:
    instruction = retry_phase_recovery(
        "phase1-what",
        "controller_state_contract_validation_failed",
    )

    assert instruction.to_dict() == {
        "schema_version": 1,
        "kind": "retry_phase",
        "reason_code": "controller_state_contract_validation_failed",
        "phase": "phase1-what",
        "requires_human_input": False,
    }


def test_trusted_executor_block_recovery_retries_recorded_phase() -> None:
    instruction = trusted_executor_block_recovery(
        "phase1-what",
        "missing_phase_outputs",
    )

    assert instruction.to_dict() == {
        "schema_version": 1,
        "kind": "retry_phase",
        "reason_code": "missing_phase_outputs",
        "phase": "phase1-what",
        "requires_human_input": False,
    }


def test_trusted_executor_block_recovery_rejects_unknown_reason() -> None:
    with pytest.raises(
        RecoveryInstructionError,
        match="unsupported trusted executor block reason",
    ):
        trusted_executor_block_recovery(
            "phase1-what",
            "invented_recovery",
        )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (
            {
                "schema_version": 1,
                "kind": "invented_recovery",
                "reason_code": "unknown",
                "phase": "phase1-why2",
                "requires_human_input": False,
            },
            "unknown recovery kind",
        ),
        (
            {
                "schema_version": 1,
                "kind": "retry_phase",
                "reason_code": "agent_timeout",
                "phase": "",
                "requires_human_input": False,
            },
            "requires a retryable phase",
        ),
        (
            {
                "schema_version": 1,
                "kind": "wait_for_provider",
                "reason_code": "provider_session_limit",
                "phase": "",
                "requires_human_input": False,
            },
            "requires a retryable phase",
        ),
        (
            {
                "schema_version": 1,
                "kind": "await_human_answer",
                "reason_code": "product_decision",
                "phase": "phase1-why1",
                "requires_human_input": False,
            },
            "requires_human_input must be true",
        ),
    ],
)
def test_recovery_instruction_rejects_unsafe_shapes(
    value: object,
    message: str,
) -> None:
    with pytest.raises(RecoveryInstructionError, match=message):
        validate_recovery_instruction(value)


def test_recovery_instruction_accepts_day_one_vocabulary() -> None:
    kinds = [
        "retry_phase",
        "sync_runtime_then_retry",
        "await_human_answer",
        "resolve_issue",
        "safe_rewind",
        "manual_repair",
        "increase_budget",
        "wait_for_provider",
        "manual_diagnosis",
    ]

    for kind in kinds:
        requires_human_input = kind in {
            "await_human_answer",
            "resolve_issue",
        }
        phase = "" if kind in {
            "increase_budget",
            "manual_diagnosis",
        } else "phase1-why2"
        validated = validate_recovery_instruction(
            {
                "schema_version": 1,
                "kind": kind,
                "reason_code": "test_reason",
                "phase": phase,
                "requires_human_input": requires_human_input,
            }
        )

        assert validated.kind.value == kind


def test_schema_v1_recovery_instruction_rejects_decision_id() -> None:
    with pytest.raises(RecoveryInstructionError, match="unknown recovery instruction field"):
        validate_recovery_instruction(
            {
                "schema_version": 1,
                "kind": "await_human_answer",
                "reason_code": "product_decision",
                "phase": "phase1-why1",
                "requires_human_input": True,
                "decision_id": "dec-7f4d2",
            }
        )


def test_schema_v2_recovery_instruction_requires_a_decision_id() -> None:
    instruction = _v2_instruction(
        "resolve_decision",
        phase="phase1-why1",
        requires_human_input=False,
    )
    instruction.pop("decision_id")

    with pytest.raises(RecoveryInstructionError, match="missing recovery instruction field"):
        validate_recovery_instruction(instruction)


def test_schema_v2_recovery_instruction_rejects_mixed_mapping_key_types() -> None:
    instruction = _v2_instruction(
        "resolve_decision",
        phase="phase1-why1",
        requires_human_input=False,
    )
    instruction.update({1: "invalid", "unknown": "invalid"})

    with pytest.raises(RecoveryInstructionError):
        validate_recovery_instruction(instruction)


@pytest.mark.parametrize(
    ("status", "kind", "phase", "requires_human_input"),
    [
        ("pending", "resolve_decision", "phase1-why1", False),
        ("resolving", "resolve_decision", "phase1-why1", False),
        ("awaiting_human", "await_human_answer", "phase1-why1", True),
        ("failed", "manual_diagnosis", "", False),
    ],
)
def test_schema_v2_recovery_instruction_matches_its_decision_status(
    status: str,
    kind: str,
    phase: str,
    requires_human_input: bool,
) -> None:
    instruction = _v2_instruction(
        kind,
        phase=phase,
        requires_human_input=requires_human_input,
    )

    paired = validate_decision_recovery_pair(_v2_decision(status), instruction)

    assert paired is not None
    assert paired.to_dict() == instruction


def test_schema_v2_recovery_instruction_requires_the_decision_reason_code() -> None:
    instruction = _v2_instruction(
        "await_human_answer",
        phase="phase1-why1",
        requires_human_input=True,
    )
    instruction["reason_code"] = "stale_unrelated_reason"

    with pytest.raises(RecoveryInstructionError, match="reason code"):
        validate_decision_recovery_pair(_v2_decision("awaiting_human"), instruction)


def test_schema_v2_resolved_decision_requires_no_recovery_instruction() -> None:
    decision = _v2_decision("resolved")
    decision.update(
        {
            "answer_text": "Use the public contract.",
            "resolved_by": "user",
            "resolved_at": "2026-07-28T10:01:00+00:00",
        }
    )

    assert validate_decision_recovery_pair(decision, None) is None

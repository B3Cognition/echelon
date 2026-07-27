from __future__ import annotations

import pytest

from harness.recovery_instruction import (
    RecoveryInstructionError,
    controller_contract_recovery,
    retry_phase_recovery,
    trusted_executor_block_recovery,
    validate_recovery_instruction,
)


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

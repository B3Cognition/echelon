"""Typed recovery instructions for blocked controller runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class RecoveryInstructionError(ValueError):
    """Raised when a persisted recovery instruction is unsafe."""


class RecoveryKind(str, Enum):
    RETRY_PHASE = "retry_phase"
    SYNC_RUNTIME_THEN_RETRY = "sync_runtime_then_retry"
    AWAIT_HUMAN_ANSWER = "await_human_answer"
    RESOLVE_ISSUE = "resolve_issue"
    SAFE_REWIND = "safe_rewind"
    MANUAL_REPAIR = "manual_repair"
    INCREASE_BUDGET = "increase_budget"
    WAIT_FOR_PROVIDER = "wait_for_provider"
    MANUAL_DIAGNOSIS = "manual_diagnosis"


_HUMAN_INPUT_KINDS = frozenset(
    {
        RecoveryKind.AWAIT_HUMAN_ANSWER,
        RecoveryKind.RESOLVE_ISSUE,
    }
)
_PHASE_KINDS = frozenset(
    {
        RecoveryKind.RETRY_PHASE,
        RecoveryKind.SYNC_RUNTIME_THEN_RETRY,
        RecoveryKind.AWAIT_HUMAN_ANSWER,
        RecoveryKind.RESOLVE_ISSUE,
        RecoveryKind.SAFE_REWIND,
        RecoveryKind.MANUAL_REPAIR,
        RecoveryKind.WAIT_FOR_PROVIDER,
    }
)
_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "reason_code",
        "phase",
        "requires_human_input",
    }
)
_TRUSTED_EXECUTOR_BLOCK_REASONS = frozenset(
    {
        "invalid_evidence_inventory",
        "missing_consensus_prerequisite",
        "missing_phase_outputs",
    }
)


@dataclass(frozen=True)
class RecoveryInstruction:
    kind: RecoveryKind
    reason_code: str
    phase: str = ""
    requires_human_input: bool = False
    schema_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "reason_code": self.reason_code,
            "phase": self.phase,
            "requires_human_input": self.requires_human_input,
        }


def validate_recovery_instruction(value: object) -> RecoveryInstruction:
    if not isinstance(value, Mapping):
        raise RecoveryInstructionError("recovery instruction must be an object")
    unknown = set(value) - _FIELDS
    if unknown:
        raise RecoveryInstructionError(
            f"unknown recovery instruction field: {sorted(unknown)[0]}"
        )
    if value.get("schema_version") != 1:
        raise RecoveryInstructionError("unsupported recovery instruction schema")
    try:
        kind = RecoveryKind(str(value.get("kind") or ""))
    except ValueError as exc:
        raise RecoveryInstructionError("unknown recovery kind") from exc
    reason_code = str(value.get("reason_code") or "").strip()
    if not reason_code:
        raise RecoveryInstructionError("recovery instruction requires a reason code")
    phase = str(value.get("phase") or "").strip()
    if kind in _PHASE_KINDS and (
        not phase or phase == "terminal-blocked"
    ):
        raise RecoveryInstructionError(
            f"{kind.value} requires a retryable phase"
        )
    requires_human_input = value.get("requires_human_input")
    if type(requires_human_input) is not bool:
        raise RecoveryInstructionError(
            "requires_human_input must be a boolean"
        )
    expected_human_input = kind in _HUMAN_INPUT_KINDS
    if requires_human_input is not expected_human_input:
        expected = "true" if expected_human_input else "false"
        raise RecoveryInstructionError(
            f"requires_human_input must be {expected} for {kind.value}"
        )
    return RecoveryInstruction(
        kind=kind,
        reason_code=reason_code,
        phase=phase,
        requires_human_input=requires_human_input,
    )


def controller_contract_recovery(phase: str) -> RecoveryInstruction:
    return validate_recovery_instruction(
        {
            "schema_version": 1,
            "kind": RecoveryKind.SYNC_RUNTIME_THEN_RETRY.value,
            "reason_code": "controller_state_contract_validation_failed",
            "phase": phase,
            "requires_human_input": False,
        }
    )


def retry_phase_recovery(
    phase: str,
    reason_code: str,
) -> RecoveryInstruction:
    return validate_recovery_instruction(
        {
            "schema_version": 1,
            "kind": RecoveryKind.RETRY_PHASE.value,
            "reason_code": reason_code,
            "phase": phase,
            "requires_human_input": False,
        }
    )


def trusted_executor_block_recovery(
    phase: str,
    reason_code: str,
) -> RecoveryInstruction:
    if reason_code not in _TRUSTED_EXECUTOR_BLOCK_REASONS:
        raise RecoveryInstructionError(
            "unsupported trusted executor block reason"
        )
    return retry_phase_recovery(phase, reason_code)

"""Typed recovery instructions for blocked controller runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from harness.blocked_decision import (
    BlockedDecisionError,
    SCHEMA_V2,
    SCHEMA_V3,
    is_valid_decision_id,
    validate_blocked_decision,
)


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
    RESOLVE_DECISION = "resolve_decision"


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
_V2_FIELDS = _FIELDS | {"decision_id"}
_V1_KINDS = frozenset(kind for kind in RecoveryKind if kind is not RecoveryKind.RESOLVE_DECISION)
_V2_KINDS = frozenset(
    {
        RecoveryKind.RESOLVE_DECISION,
        RecoveryKind.AWAIT_HUMAN_ANSWER,
        RecoveryKind.MANUAL_DIAGNOSIS,
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
    decision_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "reason_code": self.reason_code,
            "phase": self.phase,
            "requires_human_input": self.requires_human_input,
        }
        if self.schema_version == 2:
            result["decision_id"] = self.decision_id
        return result


def _validate_recovery_instruction_v1(value: Mapping[object, object]) -> RecoveryInstruction:
    """Keep schema-v1 recovery validation behavior intact."""
    unknown = set(value) - _FIELDS
    if unknown:
        raise RecoveryInstructionError(
            f"unknown recovery instruction field: {sorted(unknown)[0]}"
        )
    try:
        kind = RecoveryKind(str(value.get("kind") or ""))
    except ValueError as exc:
        raise RecoveryInstructionError("unknown recovery kind") from exc
    if kind not in _V1_KINDS:
        raise RecoveryInstructionError("unknown recovery kind")
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


def validate_recovery_instruction_v2(value: object) -> RecoveryInstruction:
    """Validate a schema-v2 recovery instruction bound to one decision ID."""
    if not isinstance(value, Mapping):
        raise RecoveryInstructionError("recovery instruction must be an object")
    if not all(isinstance(key, str) for key in value):
        raise RecoveryInstructionError("recovery instruction field names must be strings")
    unknown = set(value) - _V2_FIELDS
    missing = _V2_FIELDS - set(value)
    if unknown:
        raise RecoveryInstructionError(
            f"unknown recovery instruction field: {sorted(unknown)[0]}"
        )
    if missing:
        raise RecoveryInstructionError(
            f"missing recovery instruction field: {sorted(missing)[0]}"
        )
    if type(value["schema_version"]) is not int or value["schema_version"] != 2:
        raise RecoveryInstructionError("unsupported recovery instruction schema")
    try:
        kind = RecoveryKind(str(value["kind"] or ""))
    except ValueError as exc:
        raise RecoveryInstructionError("unknown recovery kind") from exc
    if kind not in _V2_KINDS:
        raise RecoveryInstructionError("unknown recovery kind")
    reason_code = value["reason_code"]
    if not isinstance(reason_code, str):
        raise RecoveryInstructionError("recovery instruction requires a reason code")
    reason_code = reason_code.strip()
    if not reason_code:
        raise RecoveryInstructionError("recovery instruction requires a reason code")
    phase_value = value["phase"]
    if not isinstance(phase_value, str):
        raise RecoveryInstructionError("phase must be a string")
    phase = phase_value.strip()
    if kind in {RecoveryKind.RESOLVE_DECISION, RecoveryKind.AWAIT_HUMAN_ANSWER} and (
        not phase or phase == "terminal-blocked"
    ):
        raise RecoveryInstructionError(
            f"{kind.value} requires a retryable phase"
        )
    if kind is RecoveryKind.MANUAL_DIAGNOSIS and phase:
        raise RecoveryInstructionError("manual_diagnosis requires an empty phase")
    requires_human_input = value.get("requires_human_input")
    if type(requires_human_input) is not bool:
        raise RecoveryInstructionError(
            "requires_human_input must be a boolean"
        )
    expected_human_input = kind is RecoveryKind.AWAIT_HUMAN_ANSWER
    if requires_human_input is not expected_human_input:
        expected = "true" if expected_human_input else "false"
        raise RecoveryInstructionError(
            f"requires_human_input must be {expected} for {kind.value}"
        )
    decision_id = value["decision_id"]
    if not is_valid_decision_id(decision_id):
        raise RecoveryInstructionError("decision_id must name a durable decision")
    return RecoveryInstruction(
        kind=kind,
        reason_code=reason_code,
        phase=phase,
        requires_human_input=requires_human_input,
        schema_version=2,
        decision_id=decision_id,
    )


def validate_recovery_instruction(value: object) -> RecoveryInstruction:
    """Dispatch recovery validation by its exact integer schema version."""
    if not isinstance(value, Mapping):
        raise RecoveryInstructionError("recovery instruction must be an object")
    schema_version = value.get("schema_version")
    if type(schema_version) is not int:
        raise RecoveryInstructionError("unsupported recovery instruction schema")
    if schema_version == 1:
        return _validate_recovery_instruction_v1(value)
    if schema_version == 2:
        return validate_recovery_instruction_v2(value)
    raise RecoveryInstructionError("unsupported recovery instruction schema")


def validate_decision_recovery_pair(
    decision: object,
    instruction: object | None,
) -> RecoveryInstruction | None:
    """Validate recovery paired with a versioned human-input decision."""
    validated_decision = validate_blocked_decision(decision)
    if validated_decision.get("schema_version") not in {SCHEMA_V2, SCHEMA_V3}:
        raise BlockedDecisionError(
            "decision recovery requires blocked-decision schema 2 or 3"
        )
    status = validated_decision["status"]
    if status == "resolved":
        if instruction is not None:
            raise RecoveryInstructionError("resolved decisions must not have recovery")
        return None
    if instruction is None:
        raise RecoveryInstructionError("unresolved decisions require recovery")
    validated_instruction = validate_recovery_instruction(instruction)
    if validated_instruction.schema_version != 2:
        raise RecoveryInstructionError("decision recovery must use schema 2")
    if validated_instruction.decision_id != validated_decision["id"]:
        raise RecoveryInstructionError("recovery decision_id does not match decision")
    if validated_instruction.reason_code != validated_decision["reason_code"]:
        raise RecoveryInstructionError("recovery reason code does not match decision")
    expected = {
        "pending": (RecoveryKind.RESOLVE_DECISION, False, validated_decision["source_phase"]),
        "resolving": (RecoveryKind.RESOLVE_DECISION, False, validated_decision["source_phase"]),
        "awaiting_human": (
            RecoveryKind.AWAIT_HUMAN_ANSWER,
            True,
            validated_decision["source_phase"],
        ),
        "failed": (RecoveryKind.MANUAL_DIAGNOSIS, False, ""),
    }
    expected_kind, expected_human_input, expected_phase = expected[status]
    if (
        validated_instruction.kind is not expected_kind
        or validated_instruction.requires_human_input is not expected_human_input
        or validated_instruction.phase != expected_phase
    ):
        raise RecoveryInstructionError("recovery instruction does not match decision status")
    return validated_instruction


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

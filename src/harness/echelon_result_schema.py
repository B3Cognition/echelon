"""Deterministic schema validation for agent echelon_result payloads."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from harness.quality_scores import validate_quality_scores_shape


class EchelonResultValidationError(ValueError):
    """Raised when an agent echelon_result payload is not safe to consume."""


ALLOWED_VERDICTS = frozenset({
    "ALIGNED",
    "ALTERNATIVES_GENERATED",
    "APPROVED",
    "BLOCKED",
    "CALIBRATED",
    "CHANGES_REQUESTED",
    "COMPLETE",
    "COMPLIANT",
    "CONCERNS",
    "CONSOLIDATED",
    "CONVERGING",
    "DEFER",
    "DONE",
    "DONE_WITH_CONCERNS",
    "DRIFT",
    "DRIFTING",
    "ESCALATE",
    "FAILED",
    "FAIL",
    "FINDINGS",
    "GROUNDED",
    "INTEGRATED",
    "INTERNALIZED",
    "JUDGMENT_RESOLVED",
    "KILL",
    "NEEDS_CONTEXT",
    "ON_TRACK",
    "PARTIAL",
    "PASS",
    "PATTERNS_APPLIED",
    "REJECTED",
    "RESOLVED",
    "SCORED",
    "STABLE",
    "STOP_AND_ASK",
    "SUFFICIENT",
    "VERIFIED",
    "VISUAL_PASS",
    "WARN",
})

RESERVED_STATE_UPDATE_KEYS = frozenset({
    "completed_phases",
    "created_at",
    "last_dispatch",
    "phase_dispatch_counts",
    "run_id",
    "squad_dir",
    "staging_dir",
    "updated_at",
})

PRODUCT_INPUT_DISPOSITIONS = frozenset({
    "included",
    "excluded",
    "duplicate",
    "open_question",
    "conflict",
})

PRODUCT_INPUT_UPDATE_FIELDS = frozenset({
    "input_unit_id",
    "disposition",
    "rationale",
    "spec_ids",
    "task_ids",
    "targets",
})


def validate_echelon_result(
    payload: Any,
    *,
    allowed_state_update_keys: Iterable[str] | None = None,
) -> dict:
    """Return a normalized copy of a safe echelon_result payload.

    The validator intentionally checks only the harness-critical contract:
    top-level object shape, verdict enum, state update object shape, journal
    entry list shape, and reserved state keys. Domain-specific fields remain
    agent-owned.
    """
    if not isinstance(payload, dict):
        raise EchelonResultValidationError("echelon_result must be an object")

    result = deepcopy(payload)
    verdict = result.get("verdict")
    if not isinstance(verdict, str) or not verdict.strip():
        raise EchelonResultValidationError(
            "echelon_result.verdict must be a non-empty string"
        )
    verdict = verdict.strip()
    if verdict not in ALLOWED_VERDICTS:
        raise EchelonResultValidationError(f"unsupported verdict {verdict!r}")
    result["verdict"] = verdict

    if "state_updates" not in result:
        if verdict == "BLOCKED":
            raise EchelonResultValidationError(
                "echelon_result.state_updates is required for BLOCKED verdicts"
            )
        result["state_updates"] = {}

    state_updates = result.get("state_updates")
    if not isinstance(state_updates, dict):
        raise EchelonResultValidationError(
            "echelon_result.state_updates must be an object"
        )
    if verdict == "STOP_AND_ASK":
        status = state_updates.get("status")
        if status != "blocked":
            raise EchelonResultValidationError(
                "STOP_AND_ASK verdicts require state_updates.status = 'blocked'"
            )
        blocked_reason = state_updates.get("blocked_reason")
        if not isinstance(blocked_reason, str) or not blocked_reason.strip():
            raise EchelonResultValidationError(
                "STOP_AND_ASK verdicts require state_updates.blocked_reason"
            )
        escalation_question = state_updates.get("escalation_question")
        if not isinstance(escalation_question, str) or not escalation_question.strip():
            raise EchelonResultValidationError(
                "STOP_AND_ASK verdicts require state_updates.escalation_question"
            )

    allowed_keys = (
        frozenset(allowed_state_update_keys)
        if allowed_state_update_keys is not None
        else None
    )

    for key in state_updates:
        if not isinstance(key, str):
            raise EchelonResultValidationError(
                "echelon_result.state_updates keys must be strings"
            )
        if key in RESERVED_STATE_UPDATE_KEYS:
            raise EchelonResultValidationError(
                f"echelon_result.state_updates cannot set reserved key {key!r}"
            )
        if allowed_keys is not None and key not in allowed_keys:
            allowed = ", ".join(sorted(allowed_keys)) or "(none)"
            raise EchelonResultValidationError(
                "echelon_result.state_updates key "
                f"{key!r} is not allowed for this phase; allowed keys: {allowed}"
            )

    if "quality_scores" in state_updates:
        error = validate_quality_scores_shape(state_updates["quality_scores"])
        if error:
            raise EchelonResultValidationError(error)

    if "journal_entries" in result and not isinstance(result["journal_entries"], list):
        raise EchelonResultValidationError(
            "echelon_result.journal_entries must be a list"
        )
    result.setdefault("journal_entries", [])

    product_input_updates = result.get("product_input_updates")
    if product_input_updates is not None:
        if not isinstance(product_input_updates, list):
            raise EchelonResultValidationError(
                "echelon_result.product_input_updates must be a list of objects"
            )
        for index, update in enumerate(product_input_updates):
            field_path = f"echelon_result.product_input_updates[{index}]"
            if not isinstance(update, dict):
                raise EchelonResultValidationError(
                    "echelon_result.product_input_updates must be a list of objects"
                )
            missing_fields = PRODUCT_INPUT_UPDATE_FIELDS - update.keys()
            if missing_fields:
                raise EchelonResultValidationError(
                    f"{field_path} is missing required field(s): "
                    + ", ".join(sorted(missing_fields))
                )
            unexpected_fields = update.keys() - PRODUCT_INPUT_UPDATE_FIELDS
            if unexpected_fields:
                raise EchelonResultValidationError(
                    f"{field_path} has unsupported field(s): "
                    + ", ".join(sorted(unexpected_fields))
                )
            for field in ("input_unit_id", "rationale"):
                value = update[field]
                if not isinstance(value, str) or not value.strip():
                    raise EchelonResultValidationError(
                        f"{field_path}.{field} must be a non-empty string"
                    )
            disposition = update["disposition"]
            if disposition not in PRODUCT_INPUT_DISPOSITIONS:
                allowed = ", ".join(sorted(PRODUCT_INPUT_DISPOSITIONS))
                raise EchelonResultValidationError(
                    f"{field_path}.disposition must be one of: {allowed}"
                )
            for field in ("spec_ids", "task_ids", "targets"):
                values = update[field]
                if not isinstance(values, list) or not all(
                    isinstance(value, str) and value.strip() for value in values
                ):
                    raise EchelonResultValidationError(
                        f"{field_path}.{field} must be a list of non-empty strings"
                    )

    return result

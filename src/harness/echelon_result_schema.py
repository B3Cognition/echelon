"""Deterministic schema validation for agent echelon_result payloads."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


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

    if "journal_entries" in result and not isinstance(result["journal_entries"], list):
        raise EchelonResultValidationError(
            "echelon_result.journal_entries must be a list"
        )
    result.setdefault("journal_entries", [])

    return result

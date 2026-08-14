"""Controller-owned accounting for proportional Phase 1 quality repair."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping

from echelon.spec_authoring import (
    PERFECTIONIST_MODE,
    PROPORTIONAL_MODE,
    normalize_spec_authoring_mode,
)


SCHEMA_VERSION = 1
AUTOMATIC_REPAIR_LIMIT = 3
EXTENSION_REPAIR_LIMIT = 1

_REPAIR_STATE_KEYS = frozenset(
    {
        "schema_version",
        "authoring_mode",
        "automatic_limit",
        "automatic_consumed",
        "extension_limit",
        "extension_authorized",
        "extension_consumed",
        "migration_basis",
    }
)
_MIGRATION_BASES = frozenset(
    {"fresh", "why2_history", "iteration_fallback"}
)


@dataclass(frozen=True)
class RepairOutcome:
    """Detached repair state and its accounting result for one WHAT attempt."""

    repair_state: dict[str, object]
    outcome: str


def initialize_repair_state(
    state: Mapping[str, object],
) -> dict[str, object] | None:
    """Return the proportional repair record for a new or continued run.

    Legacy runs without the record are migrated from immutable controller WHY2
    history.  Only when that history is unavailable may the global workflow
    iteration seed the dedicated counter.
    """
    if not isinstance(state, Mapping):
        raise ValueError("repair state source must be a mapping")
    mode = normalize_spec_authoring_mode(state.get("spec_authoring_mode"))
    has_existing = "phase1_quality_repair" in state
    existing = state.get("phase1_quality_repair")
    if mode == PERFECTIONIST_MODE:
        if has_existing:
            raise ValueError("perfectionist runs cannot contain repair state")
        return None
    if has_existing:
        return validate_repair_state(existing)

    history_count = _certified_why2_assessment_count(state)
    if history_count is None:
        consumed = min(_legacy_iteration(state), AUTOMATIC_REPAIR_LIMIT)
        migration_basis = "iteration_fallback"
    else:
        consumed = min(history_count, AUTOMATIC_REPAIR_LIMIT)
        migration_basis = "why2_history"
    if not _is_legacy_state(state):
        consumed = 0
        migration_basis = "fresh"
    return {
        "schema_version": SCHEMA_VERSION,
        "authoring_mode": PROPORTIONAL_MODE,
        "automatic_limit": AUTOMATIC_REPAIR_LIMIT,
        "automatic_consumed": consumed,
        "extension_limit": EXTENSION_REPAIR_LIMIT,
        "extension_authorized": 0,
        "extension_consumed": 0,
        "migration_basis": migration_basis,
    }


def validate_repair_state(value: object) -> dict[str, object]:
    """Return one detached exact-schema repair record or fail closed."""
    if type(value) is not dict or frozenset(value) != _REPAIR_STATE_KEYS:
        raise ValueError("proportional repair state has invalid fields")
    state = deepcopy(value)
    if (
        type(state["schema_version"]) is not int
        or state["schema_version"] != SCHEMA_VERSION
    ):
        raise ValueError("proportional repair state schema version is invalid")
    if state["authoring_mode"] != PROPORTIONAL_MODE:
        raise ValueError("proportional repair state authoring mode is invalid")
    if (
        type(state["automatic_limit"]) is not int
        or state["automatic_limit"] != AUTOMATIC_REPAIR_LIMIT
    ):
        raise ValueError("proportional automatic repair limit is invalid")
    if (
        type(state["extension_limit"]) is not int
        or state["extension_limit"] != EXTENSION_REPAIR_LIMIT
    ):
        raise ValueError("proportional extension repair limit is invalid")
    for key, limit in (
        ("automatic_consumed", AUTOMATIC_REPAIR_LIMIT),
        ("extension_authorized", EXTENSION_REPAIR_LIMIT),
        ("extension_consumed", EXTENSION_REPAIR_LIMIT),
    ):
        counter = state[key]
        if type(counter) is not int or not 0 <= counter <= limit:
            raise ValueError(f"proportional repair state {key} is invalid")
    if state["extension_consumed"] > state["extension_authorized"]:
        raise ValueError("proportional extension consumption is unauthorized")
    if state["migration_basis"] not in _MIGRATION_BASES:
        raise ValueError("proportional repair migration basis is invalid")
    return state


def record_what_outcome(
    repair_state: object,
    *,
    baseline_sha256: object,
    current_sha256: object,
    valid_completion: object,
    extension_active: object,
) -> RepairOutcome:
    """Account for a completed WHAT attempt without touching global iteration."""
    state = validate_repair_state(repair_state)
    if type(valid_completion) is not bool or type(extension_active) is not bool:
        raise ValueError("WHAT outcome flags must be Boolean")
    if not valid_completion:
        return RepairOutcome(state, "not_consumed")
    if not _is_sha256(baseline_sha256) or not _is_sha256(current_sha256):
        raise ValueError("WHAT outcome digests must be SHA-256 strings")

    changed = baseline_sha256 != current_sha256
    if extension_active:
        if (
            state["extension_authorized"] != EXTENSION_REPAIR_LIMIT
            or state["extension_consumed"] == EXTENSION_REPAIR_LIMIT
        ):
            return RepairOutcome(state, "not_consumed")
        state["extension_consumed"] = EXTENSION_REPAIR_LIMIT
        return RepairOutcome(
            state,
            "consumed" if changed else "no_artifact_progress",
        )

    if not changed:
        return RepairOutcome(state, "no_artifact_progress")
    if state["automatic_consumed"] == AUTOMATIC_REPAIR_LIMIT:
        return RepairOutcome(state, "not_consumed")
    state["automatic_consumed"] = int(state["automatic_consumed"]) + 1
    return RepairOutcome(state, "consumed")


def _is_legacy_state(state: Mapping[str, object]) -> bool:
    if "spec_authoring_mode" not in state or state.get(
        "spec_authoring_mode"
    ) in {None, ""}:
        return True
    return any(
        key in state
        for key in (
            "iteration",
            "quality_scores",
            "completed_phases",
            "last_dispatch",
        )
    )


def _certified_why2_assessment_count(state: Mapping[str, object]) -> int | None:
    scores = state.get("quality_scores")
    if not isinstance(scores, list):
        return None
    assessment_ids: set[str] = set()
    for score in scores:
        if not isinstance(score, Mapping) or score.get(
            "source"
        ) != "harness:understanding":
            continue
        assessment_id = _certified_why2_assessment_id(score)
        if assessment_id is None:
            return None
        assessment_ids.add(assessment_id)
    return len(assessment_ids) if assessment_ids else None


def _certified_why2_assessment_id(score: Mapping[str, object]) -> str | None:
    """Return one WHY2 identity only when its immutable report verifies."""
    pass_id = score.get("pass_id")
    passed = score.get("pass")
    evidence = score.get("evidence")
    evidence_digest = score.get("evidence_digest")
    if (
        type(pass_id) is not str
        or type(passed) is not bool
        or type(evidence) is not str
        or not evidence.strip()
        or not _is_sha256(evidence_digest)
    ):
        return None
    try:
        report_path = Path(evidence).expanduser()
        content = report_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != evidence_digest:
            return None
        report = json.loads(content)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(report, Mapping):
        return None
    iteration = report.get("iteration")
    report_spec = report.get("spec")
    if (
        type(report.get("schema_version")) is not int
        or report.get("schema_version") != 1
        or report.get("status") != "completed"
        or report.get("phase") != "phase1-why2"
        or type(iteration) is not int
        or iteration < 0
        or pass_id != f"WHY2-iter-{iteration}"
        or report.get("pass") is not passed
        or not isinstance(report_spec, Mapping)
        or type(report_spec.get("path")) is not str
        or not report_spec.get("path").strip()
        or not _is_sha256(report_spec.get("sha256"))
    ):
        return None
    return pass_id


def _legacy_iteration(state: Mapping[str, object]) -> int:
    iteration = state.get("iteration", 0)
    if type(iteration) is not int or iteration < 0:
        raise ValueError("legacy workflow iteration is invalid")
    return iteration


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )

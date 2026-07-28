"""Typed human decision metadata for blocked squad runs."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Mapping


SCHEMA_VERSION = 1
SCHEMA_V2 = 2
VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}
_V2_STATUSES = frozenset({"pending", "resolving", "awaiting_human", "resolved", "failed"})
_V2_SOURCE_KINDS = frozenset(
    {"provider_escalation", "human_gate", "controller_safeguard", "legacy_recovery"}
)
_V2_CLASSIFICATIONS = frozenset(
    {"operational", "material", "external_prerequisite"}
)
_V2_AUTONOMY_MODES = frozenset({"guided", "semi", "banzai"})
_V2_RESOLVERS = frozenset({"user", "semi", "COMMANDER"})
_V2_OPTION_FIELDS = frozenset(
    {"id", "label", "description", "recommended", "risk_level", "next_phase", "outcome"}
)
_V2_FIELDS = frozenset(
    {
        "schema_version",
        "id",
        "status",
        "source_kind",
        "producer_id",
        "source_phase",
        "reason_code",
        "classification",
        "question",
        "options",
        "recommended_answer",
        "risk_level",
        "resolution_handler",
        "autonomy_mode",
        "source_state_revision",
        "selected_option_id",
        "answer_text",
        "resolved_by",
        "attempts",
        "failure_code",
        "created_at",
        "resolved_at",
    }
)
_DECISION_ID_RE = re.compile(r"dec-[A-Za-z0-9][A-Za-z0-9_-]*$")


class BlockedDecisionError(ValueError):
    """Raised when persisted blocked decision metadata is unsafe."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def is_valid_decision_id(value: object) -> bool:
    """Return whether a durable decision ID has the persisted v2 form."""
    return isinstance(value, str) and bool(_DECISION_ID_RE.fullmatch(value))


def _required_v2_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BlockedDecisionError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_v2_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_v2_string(value, field)


def _validate_v2_timestamp(value: object, field: str, *, nullable: bool) -> str | None:
    if value is None and nullable:
        return None
    timestamp = _required_v2_string(value, field)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BlockedDecisionError(f"{field} must be a UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise BlockedDecisionError(f"{field} must be a UTC timestamp")
    return timestamp


def _validate_v2_options(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise BlockedDecisionError("options must be a list")

    options: list[dict[str, object]] = []
    option_ids: set[str] = set()
    option_labels: set[str] = set()
    recommended_count = 0
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise BlockedDecisionError(f"options[{index}] must be an object")
        if not all(isinstance(key, str) for key in raw):
            raise BlockedDecisionError(f"options[{index}] field names must be strings")
        unknown = set(raw) - _V2_OPTION_FIELDS
        missing = _V2_OPTION_FIELDS - set(raw)
        if unknown:
            raise BlockedDecisionError(f"unknown option field: {sorted(unknown)[0]}")
        if missing:
            raise BlockedDecisionError(f"missing option field: {sorted(missing)[0]}")
        option_id = _required_v2_string(raw["id"], f"options[{index}].id")
        if option_id in option_ids:
            raise BlockedDecisionError("duplicate option id")
        option_ids.add(option_id)
        option_label = _required_v2_string(raw["label"], f"options[{index}].label")
        if option_label in option_labels:
            raise BlockedDecisionError("duplicate option label")
        option_labels.add(option_label)
        recommended = raw["recommended"]
        if type(recommended) is not bool:
            raise BlockedDecisionError(f"options[{index}].recommended must be a boolean")
        recommended_count += int(recommended)
        risk_level = raw["risk_level"]
        if risk_level is not None and (
            not isinstance(risk_level, str) or risk_level not in VALID_RISK_LEVELS
        ):
            raise BlockedDecisionError(
                f"options[{index}].risk_level must be low, medium, high, or critical"
            )
        options.append(
            {
                "id": option_id,
                "label": option_label,
                "description": _required_v2_string(
                    raw["description"], f"options[{index}].description"
                ),
                "recommended": recommended,
                "risk_level": risk_level,
                "next_phase": _optional_v2_string(
                    raw["next_phase"], f"options[{index}].next_phase"
                ),
                "outcome": _optional_v2_string(raw["outcome"], f"options[{index}].outcome"),
            }
        )
    if recommended_count > 1:
        raise BlockedDecisionError("at most one option may be recommended")
    if option_ids & option_labels:
        raise BlockedDecisionError("option label conflicts with an option id")
    return options


def validate_blocked_decision_v2(value: object) -> dict[str, object]:
    """Validate and return a copy of a complete schema-v2 blocked decision."""
    if not isinstance(value, Mapping):
        raise BlockedDecisionError("blocked decision must be an object")
    if not all(isinstance(key, str) for key in value):
        raise BlockedDecisionError("blocked decision field names must be strings")
    unknown = set(value) - _V2_FIELDS
    missing = _V2_FIELDS - set(value)
    if unknown:
        raise BlockedDecisionError(f"unknown blocked decision field: {sorted(unknown)[0]}")
    if missing:
        raise BlockedDecisionError(f"missing blocked decision field: {sorted(missing)[0]}")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_V2:
        raise BlockedDecisionError("unsupported blocked decision schema")
    if not is_valid_decision_id(value["id"]):
        raise BlockedDecisionError("blocked decision id must start with dec-")

    status = value["status"]
    if not isinstance(status, str) or status not in _V2_STATUSES:
        raise BlockedDecisionError("unknown blocked decision status")
    source_kind = value["source_kind"]
    if not isinstance(source_kind, str) or source_kind not in _V2_SOURCE_KINDS:
        raise BlockedDecisionError("unknown blocked decision source kind")
    classification = value["classification"]
    if not isinstance(classification, str) or classification not in _V2_CLASSIFICATIONS:
        raise BlockedDecisionError("unknown blocked decision classification")
    autonomy_mode = value["autonomy_mode"]
    if not isinstance(autonomy_mode, str) or autonomy_mode not in _V2_AUTONOMY_MODES:
        raise BlockedDecisionError("unknown blocked decision autonomy mode")
    risk_level = value["risk_level"]
    if risk_level is not None and (
        not isinstance(risk_level, str) or risk_level not in VALID_RISK_LEVELS
    ):
        raise BlockedDecisionError("risk_level must be low, medium, high, or critical")
    source_state_revision = value["source_state_revision"]
    if type(source_state_revision) is not int or source_state_revision < 0:
        raise BlockedDecisionError("source_state_revision must be a non-negative integer")
    attempts = value["attempts"]
    if type(attempts) is not int or attempts < 0:
        raise BlockedDecisionError("attempts must be a non-negative integer")

    options = _validate_v2_options(value["options"])
    option_ids = {option["id"] for option in options}
    recommended_answer = _optional_v2_string(
        value["recommended_answer"], "recommended_answer"
    )
    selected_option_id = _optional_v2_string(value["selected_option_id"], "selected_option_id")
    answer_text = _optional_v2_string(value["answer_text"], "answer_text")
    resolved_by = _optional_v2_string(value["resolved_by"], "resolved_by")
    failure_code = _optional_v2_string(value["failure_code"], "failure_code")
    resolved_at = _validate_v2_timestamp(value["resolved_at"], "resolved_at", nullable=True)

    if selected_option_id is not None and selected_option_id not in option_ids:
        raise BlockedDecisionError("selected_option_id requires a declared option")
    if options and answer_text is not None:
        raise BlockedDecisionError("choice decisions cannot record answer_text")
    if options and recommended_answer is not None:
        raise BlockedDecisionError("choice decisions cannot record recommended_answer")
    if not options and selected_option_id is not None:
        raise BlockedDecisionError("free-text decisions cannot record selected_option_id")
    if status == "resolved":
        if (selected_option_id is None) == (answer_text is None):
            raise BlockedDecisionError("resolved decisions require exactly one answer shape")
        if resolved_by not in _V2_RESOLVERS:
            raise BlockedDecisionError("resolved decisions require a supported resolver")
        if resolved_at is None:
            raise BlockedDecisionError("resolved decisions require resolved_at")
        if failure_code is not None:
            raise BlockedDecisionError("resolved decisions cannot record failure_code")
    else:
        if selected_option_id is not None or answer_text is not None:
            raise BlockedDecisionError("unresolved decisions cannot record an answer")
        if resolved_by is not None or resolved_at is not None:
            raise BlockedDecisionError("unresolved decisions cannot record resolution metadata")
        if status == "failed" and failure_code is None:
            raise BlockedDecisionError("failed decisions require failure_code")
        if status != "failed" and failure_code is not None:
            raise BlockedDecisionError("active decisions cannot record failure_code")

    return {
        "schema_version": SCHEMA_V2,
        "id": value["id"],
        "status": status,
        "source_kind": source_kind,
        "producer_id": _required_v2_string(value["producer_id"], "producer_id"),
        "source_phase": _required_v2_string(value["source_phase"], "source_phase"),
        "reason_code": _required_v2_string(value["reason_code"], "reason_code"),
        "classification": classification,
        "question": _required_v2_string(value["question"], "question"),
        "options": options,
        "recommended_answer": recommended_answer,
        "risk_level": risk_level,
        "resolution_handler": _required_v2_string(
            value["resolution_handler"], "resolution_handler"
        ),
        "autonomy_mode": autonomy_mode,
        "source_state_revision": source_state_revision,
        "selected_option_id": selected_option_id,
        "answer_text": answer_text,
        "resolved_by": resolved_by,
        "attempts": attempts,
        "failure_code": failure_code,
        "created_at": _validate_v2_timestamp(value["created_at"], "created_at", nullable=False),
        "resolved_at": resolved_at,
    }


def validate_blocked_decision(value: object) -> dict[str, object]:
    """Dispatch blocked-decision validation by its exact integer schema version."""
    if not isinstance(value, Mapping):
        raise BlockedDecisionError("blocked decision must be an object")
    schema_version = value.get("schema_version")
    if type(schema_version) is not int:
        raise BlockedDecisionError("unsupported blocked decision schema")
    if schema_version == SCHEMA_VERSION:
        return deepcopy(dict(value))
    if schema_version == SCHEMA_V2:
        return validate_blocked_decision_v2(value)
    raise BlockedDecisionError("unsupported blocked decision schema")


def build_blocked_decision_v2(
    *,
    decision_id: str,
    status: str,
    source_kind: str,
    producer_id: str,
    source_phase: str,
    reason_code: str,
    classification: str,
    question: str,
    options: list[dict[str, object]],
    recommended_answer: str | None,
    risk_level: str | None,
    resolution_handler: str,
    autonomy_mode: str,
    source_state_revision: int,
    selected_option_id: str | None = None,
    answer_text: str | None = None,
    resolved_by: str | None = None,
    attempts: int = 0,
    failure_code: str | None = None,
    now: str | None = None,
    resolved_at: str | None = None,
) -> dict[str, object]:
    """Build a fully populated, validated schema-v2 blocked decision."""
    return validate_blocked_decision_v2(
        {
            "schema_version": SCHEMA_V2,
            "id": decision_id,
            "status": status,
            "source_kind": source_kind,
            "producer_id": producer_id,
            "source_phase": source_phase,
            "reason_code": reason_code,
            "classification": classification,
            "question": question,
            "options": options,
            "recommended_answer": recommended_answer,
            "risk_level": risk_level,
            "resolution_handler": resolution_handler,
            "autonomy_mode": autonomy_mode,
            "source_state_revision": source_state_revision,
            "selected_option_id": selected_option_id,
            "answer_text": answer_text,
            "resolved_by": resolved_by,
            "attempts": attempts,
            "failure_code": failure_code,
            "created_at": now or _utc_now(),
            "resolved_at": resolved_at,
        }
    )


def normalize_escalation_options(options: object) -> list[dict[str, Any]]:
    """Return machine-readable escalation options safe to persist."""
    if not isinstance(options, list):
        return []

    normalized: list[dict[str, Any]] = []
    for raw in options:
        if not isinstance(raw, dict):
            continue
        option: dict[str, Any] = {}
        for key in (
            "id",
            "label",
            "description",
            "next_phase",
            "recommended",
            "risk_level",
        ):
            if key in raw:
                value = raw[key]
                if key == "recommended":
                    option[key] = bool(value)
                elif isinstance(value, str):
                    stripped = value.strip()
                    if stripped:
                        option[key] = stripped
                else:
                    option[key] = deepcopy(value)
        if option.get("id") or option.get("label"):
            normalized.append(option)
    return normalized


def build_blocked_decision(
    state: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any] | None:
    """Build the typed pending decision for a blocked state, if one exists."""
    question = _clean_string(state.get("escalation_question"))
    if not question:
        return None

    existing = state.get("blocked_decision")
    existing_decision = existing if isinstance(existing, dict) else {}
    options = normalize_escalation_options(state.get("escalation_options"))
    answer_type = "choice" if options else "free_text"
    timestamp = now or _utc_now()

    decision: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": _clean_string(existing_decision.get("status")) or "pending",
        "answer_type": answer_type,
        "question": question,
        "blocked_reason": _clean_string(state.get("blocked_reason")),
        "blocked_phase": (
            _clean_string(existing_decision.get("blocked_phase"))
            or _clean_string(state.get("phase"))
        ),
        "blocked_at": _clean_string(existing_decision.get("blocked_at")) or timestamp,
    }

    risk_level = (
        _clean_string(state.get("escalation_risk_level"))
        or _clean_string(existing_decision.get("risk_level"))
        or _clean_string(state.get("risk_level"))
    ).lower()
    if risk_level in VALID_RISK_LEVELS:
        decision["risk_level"] = risk_level

    if options:
        decision["options"] = options

    recommended = (
        _clean_string(state.get("escalation_recommended_answer"))
        or _clean_string(existing_decision.get("recommended_answer"))
    )
    if not recommended:
        for option in options:
            if option.get("recommended"):
                recommended = _clean_string(option.get("id")) or _clean_string(
                    option.get("label")
                )
                break
    if recommended:
        decision["recommended_answer"] = recommended

    default_answer = (
        _clean_string(state.get("escalation_default_answer"))
        or _clean_string(existing_decision.get("default_answer"))
        or recommended
    )
    if default_answer:
        decision["default_answer"] = default_answer

    return decision


def ensure_blocked_decision(state: dict[str, Any]) -> None:
    """Attach typed decision metadata to a blocked escalation state in-place."""
    existing = state.get("blocked_decision")
    if isinstance(existing, Mapping) and existing.get("schema_version") == SCHEMA_V2:
        return
    if state.get("status") != "blocked":
        return
    decision = build_blocked_decision(state)
    if decision is not None:
        state["blocked_decision"] = decision


def build_resume_metadata(
    *,
    answer: str,
    state: dict[str, Any],
    selected_option: dict[str, Any] | None,
    resumed_phase: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Build typed metadata for a human resume answer."""
    decision = state.get("blocked_decision")
    decision = decision if isinstance(decision, dict) else {}
    answer_type = _clean_string(decision.get("answer_type"))
    if not answer_type:
        answer_type = "choice" if selected_option else "free_text"

    metadata: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "answered_at": now or _utc_now(),
        "answered_by": "user",
        "source": "echelon spec resume",
        "answer_type": answer_type,
        "answer_text": answer,
        "blocked_phase": _clean_string(decision.get("blocked_phase"))
        or _clean_string(state.get("phase")),
        "resumed_phase": resumed_phase,
    }

    if selected_option:
        option_id = _clean_string(selected_option.get("id"))
        option_label = _clean_string(selected_option.get("label"))
        if option_id:
            metadata["selected_option_id"] = option_id
        if option_label:
            metadata["selected_option_label"] = option_label
        next_phase = _clean_string(selected_option.get("next_phase"))
        if next_phase:
            metadata["selected_option_next_phase"] = next_phase

    return metadata


def mark_blocked_decision_resolved(
    state: dict[str, Any],
    *,
    answer: str,
    selected_option: dict[str, Any] | None,
    resumed_phase: str,
) -> None:
    """Mark the state's blocked decision resolved and attach resume metadata."""
    decision = build_blocked_decision(state)
    if decision is None:
        existing = state.get("blocked_decision")
        decision = deepcopy(existing) if isinstance(existing, dict) else {}
        decision.setdefault("schema_version", SCHEMA_VERSION)
        decision.setdefault("answer_type", "choice" if selected_option else "free_text")

    metadata = build_resume_metadata(
        answer=answer,
        state={**state, "blocked_decision": decision},
        selected_option=selected_option,
        resumed_phase=resumed_phase,
    )

    decision["status"] = "resolved"
    decision["resolved_at"] = metadata["answered_at"]
    decision["resolved_by"] = "user"
    decision["answer_text"] = answer
    if selected_option:
        option_id = _clean_string(selected_option.get("id"))
        option_label = _clean_string(selected_option.get("label"))
        if option_id:
            decision["selected_option_id"] = option_id
        if option_label:
            decision["selected_option_label"] = option_label

    state["blocked_decision"] = decision
    state["resume_metadata"] = metadata

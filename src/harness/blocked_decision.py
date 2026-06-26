"""Typed human decision metadata for blocked squad runs."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = 1
VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


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
        "source": "echelon resume",
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

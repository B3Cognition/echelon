"""Deterministic schema validation for agent echelon_result payloads."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from harness.quality_scores import validate_quality_scores_shape
from harness.state_transaction_namespace import (
    PROVIDER_CONTROL_INTENT_KEYS,
    STORE_OWNED_TRANSACTION_KEYS,
)
from harness.human_input import DecisionResolution, HumanInputOption


class EchelonResultValidationError(ValueError):
    """Raised when an agent echelon_result payload is not safe to consume."""


SUPPORTED_STATE_UPDATE_TYPES = frozenset({
    "array",
    "boolean",
    "integer",
    "number",
    "object",
    "quality_scores",
    "string",
})


@dataclass(frozen=True)
class EchelonResultContract:
    """Dispatch-scoped contract for the state mutation control plane.

    ``allowed_state_update_keys`` defines the mutation surface. Reporting-only
    extras can be quarantined, while missing or malformed required routing
    fields remain fail-closed. The contract is immutable so one parallel agent
    cannot broaden another agent's permissions at runtime.
    """

    allowed_state_update_keys: frozenset[str] | None = None
    required_state_update_keys: frozenset[str] = frozenset()
    state_update_types: Mapping[str, str] = field(default_factory=dict)
    state_update_enums: Mapping[str, frozenset[Any]] = field(default_factory=dict)
    allowed_verdicts: frozenset[str] | None = None
    unexpected_state_updates: str = "quarantine"
    evidence_routing: str = "none"


@dataclass(frozen=True)
class EchelonResultContractOutcome:
    """Normalized result plus non-authoritative fields removed from state."""

    result: dict
    quarantined_state_updates: dict = field(default_factory=dict)


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
    "DECISION_RESOLVED",
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
    "REPAIR",
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

RESERVED_STATE_UPDATE_KEYS = STORE_OWNED_TRANSACTION_KEYS

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
    permitted_reserved_state_update_keys: Iterable[str] | None = None,
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
        recommendation = state_updates.get("escalation_recommended_answer")
        if recommendation is not None and (
            not isinstance(recommendation, str) or not recommendation.strip()
        ):
            raise EchelonResultValidationError(
                "escalation_recommended_answer must be a non-empty string when provided"
            )
        risk_level = state_updates.get("escalation_risk_level")
        if risk_level is not None and (
            not isinstance(risk_level, str)
            or risk_level not in {"low", "medium", "high", "critical"}
        ):
            raise EchelonResultValidationError(
                "escalation_risk_level must be low, medium, high, or critical"
            )
    else:
        escalation_question = state_updates.get("escalation_question")
        if escalation_question is not None and escalation_question != "":
            raise EchelonResultValidationError(
                "escalation_question is only valid with STOP_AND_ASK verdicts"
            )

    allowed_keys = (
        frozenset(allowed_state_update_keys)
        if allowed_state_update_keys is not None
        else None
    )
    permitted_reserved_keys = frozenset(
        permitted_reserved_state_update_keys or ()
    )

    for key in state_updates:
        if not isinstance(key, str):
            raise EchelonResultValidationError(
                "echelon_result.state_updates keys must be strings"
            )
        if (
            key in RESERVED_STATE_UPDATE_KEYS
            and (allowed_keys is None or key not in allowed_keys)
            and key not in permitted_reserved_keys
            and key not in PROVIDER_CONTROL_INTENT_KEYS
        ):
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


def validate_decision_resolution_result(
    payload: Any,
    *,
    options: tuple[HumanInputOption, ...],
) -> DecisionResolution:
    """Validate the exact, non-mutating COMMANDER decision envelope."""
    if type(payload) is not dict:
        raise EchelonResultValidationError("decision resolution result must be an object")
    if type(options) is not tuple or not all(
        type(option) is HumanInputOption for option in options
    ):
        raise EchelonResultValidationError(
            "decision resolution options must be a tuple of HumanInputOption values"
        )

    expected_fields = {"verdict", "state_updates", "journal_entries", "decision"}
    fields = set(payload)
    unexpected = fields - expected_fields
    if unexpected:
        raise EchelonResultValidationError(
            "decision resolution has unsupported field " + repr(sorted(unexpected)[0])
        )
    missing = expected_fields - fields
    if missing:
        raise EchelonResultValidationError(
            "decision resolution is missing required field " + repr(sorted(missing)[0])
        )
    if payload["verdict"] != "DECISION_RESOLVED":
        raise EchelonResultValidationError(
            "decision resolution verdict must be 'DECISION_RESOLVED'"
        )
    if type(payload["state_updates"]) is not dict or payload["state_updates"]:
        raise EchelonResultValidationError(
            "decision resolution state_updates must be an empty object"
        )
    if type(payload["journal_entries"]) is not list or payload["journal_entries"]:
        raise EchelonResultValidationError(
            "decision resolution journal_entries must be an empty list"
        )

    decision = payload["decision"]
    if type(decision) is not dict:
        raise EchelonResultValidationError("decision resolution decision must be an object")
    expected_decision_fields = {
        "selected_option_id", "answer_text", "rationale", "confidence",
    }
    decision_fields = set(decision)
    unexpected_decision = decision_fields - expected_decision_fields
    if unexpected_decision:
        raise EchelonResultValidationError(
            "decision resolution decision has unsupported field "
            + repr(sorted(unexpected_decision)[0])
        )
    missing_decision = expected_decision_fields - decision_fields
    if missing_decision:
        raise EchelonResultValidationError(
            "decision resolution decision is missing required field "
            + repr(sorted(missing_decision)[0])
        )

    selected_option_id = decision["selected_option_id"]
    answer_text = decision["answer_text"]
    if (selected_option_id is None) == (answer_text is None):
        raise EchelonResultValidationError(
            "decision resolution requires exactly one of selected_option_id or answer_text"
        )
    if selected_option_id is not None:
        if not isinstance(selected_option_id, str) or not selected_option_id.strip():
            raise EchelonResultValidationError(
                "decision resolution selected_option_id must be a non-empty string"
            )
        if selected_option_id not in {option.id for option in options}:
            raise EchelonResultValidationError(
                "decision resolution selected_option_id is not an allowed option"
            )
        if answer_text is not None:
            raise EchelonResultValidationError(
                "decision resolution choice answer_text must be null"
            )
    else:
        if options:
            raise EchelonResultValidationError(
                "decision resolution choice requires an allowed selected_option_id"
            )
        if not isinstance(answer_text, str) or not answer_text.strip():
            raise EchelonResultValidationError(
                "decision resolution answer_text must be a non-empty string"
            )

    rationale = decision["rationale"]
    if (
        not isinstance(rationale, str)
        or not rationale.strip()
        or len(rationale) > 2_000
    ):
        raise EchelonResultValidationError(
            "decision resolution rationale must be a non-empty string of at most 2,000 characters"
        )
    confidence = decision["confidence"]
    if not isinstance(confidence, str) or confidence not in {"high", "medium", "low"}:
        raise EchelonResultValidationError(
            "decision resolution confidence must be high, medium, or low"
        )

    return DecisionResolution(
        selected_option_id=selected_option_id,
        answer_text=answer_text,
        rationale=rationale,
        confidence=confidence,
    )


def validate_echelon_result_contract(
    payload: Any,
    contract: EchelonResultContract,
) -> EchelonResultContractOutcome:
    """Validate and normalize a payload against one dispatch's contract.

    Extra, non-reserved keys may be quarantined when explicitly configured.
    Required fields and typed routing values are validated *after* quarantine,
    preventing a misspelled routing key from falling back to stale state.
    """
    if contract.unexpected_state_updates not in {"reject", "quarantine"}:
        raise EchelonResultValidationError(
            "unexpected_state_updates must be 'reject' or 'quarantine'"
        )
    if contract.evidence_routing not in {"none", "requests", "finding_routes"}:
        raise EchelonResultValidationError(
            "evidence_routing must be 'none', 'requests', or 'finding_routes'"
        )

    unsupported_types = {
        value_type
        for value_type in contract.state_update_types.values()
        if value_type not in SUPPORTED_STATE_UPDATE_TYPES
    }
    if unsupported_types:
        raise EchelonResultValidationError(
            "unsupported state update type(s): "
            + ", ".join(sorted(unsupported_types))
        )

    result = validate_echelon_result(
        payload,
        permitted_reserved_state_update_keys=(
            contract.allowed_state_update_keys
        ),
    )
    verdict = result["verdict"]
    if verdict == "DECISION_RESOLVED":
        raise EchelonResultValidationError(
            "DECISION_RESOLVED is only valid for the decision resolution contract"
        )
    if contract.allowed_verdicts is not None and verdict not in contract.allowed_verdicts:
        allowed = ", ".join(sorted(contract.allowed_verdicts)) or "(none)"
        raise EchelonResultValidationError(
            f"verdict {verdict!r} is not allowed for this dispatch; allowed verdicts: {allowed}"
        )

    # BLOCKED is a harness control result. Its blocked_reason/status metadata is
    # consumed by the controller, never applied as ordinary phase state.
    if verdict == "BLOCKED":
        return EchelonResultContractOutcome(result=result)

    updates = result["state_updates"]
    quarantined: dict = {}
    allowed = contract.allowed_state_update_keys
    if allowed is not None:
        unexpected = [key for key in updates if key not in allowed]
        if unexpected and contract.unexpected_state_updates == "reject":
            allowed_text = ", ".join(sorted(allowed)) or "(none)"
            raise EchelonResultValidationError(
                "echelon_result.state_updates key "
                f"{unexpected[0]!r} is not allowed for this dispatch; "
                f"allowed keys: {allowed_text}"
            )
        for key in unexpected:
            quarantined[key] = updates.pop(key)

    missing = contract.required_state_update_keys - updates.keys()
    if missing:
        raise EchelonResultValidationError(
            "required state_updates missing for this dispatch: "
            + ", ".join(sorted(missing))
        )

    for key, value_type in contract.state_update_types.items():
        if key not in updates:
            continue
        _validate_state_update_type(key, updates[key], value_type)
    for key, allowed_values in contract.state_update_enums.items():
        if key not in updates:
            continue
        if updates[key] not in allowed_values:
            allowed_text = ", ".join(repr(value) for value in sorted(allowed_values))
            raise EchelonResultValidationError(
                f"echelon_result.state_updates.{key} must be one of: {allowed_text}"
            )

    if contract.evidence_routing != "none":
        validate_evidence_routing_state_updates(
            updates,
            verdict=verdict,
            require_finding_routes=contract.evidence_routing == "finding_routes",
        )

    return EchelonResultContractOutcome(
        result=result,
        quarantined_state_updates=quarantined,
    )


def validate_evidence_routing_state_updates(
    updates: Mapping[str, Any],
    *,
    verdict: str,
    require_finding_routes: bool,
) -> None:
    """Fail closed when an evidence route lacks executable request data."""
    status = updates.get("evidence_resolution_status")
    if status not in {"not_required", "pending"}:
        raise EchelonResultValidationError(
            "evidence_resolution_status must be 'not_required' or 'pending'"
        )

    requests = updates.get("evidence_requests")
    if status == "pending":
        if not isinstance(requests, Mapping):
            raise EchelonResultValidationError(
                "evidence_requests must be an object when evidence resolution is pending"
            )
        items = requests.get("requests")
        if not isinstance(items, list) or not items:
            raise EchelonResultValidationError(
                "evidence_requests.requests must be a non-empty list"
            )
        for index, request in enumerate(items):
            prefix = f"evidence_requests.requests[{index}]"
            if not isinstance(request, Mapping):
                raise EchelonResultValidationError(f"{prefix} must be an object")
            for field in ("id", "question", "evidence_needed"):
                if not isinstance(request.get(field), str) or not request[field].strip():
                    raise EchelonResultValidationError(
                        f"{prefix}.{field} must be a non-empty string"
                    )
            for field in ("affected_requirements", "supplied_reference_ids"):
                values = request.get(field)
                if (
                    not isinstance(values, list)
                    or not values
                    or not all(isinstance(value, str) and value.strip() for value in values)
                ):
                    raise EchelonResultValidationError(
                        f"{prefix}.{field} must be a non-empty list of strings"
                    )
    elif requests is not None:
        raise EchelonResultValidationError(
            "evidence_requests is allowed only when evidence resolution is pending"
        )

    if not require_finding_routes:
        return

    finding_routes = updates.get("finding_routes")
    findings = finding_routes.get("findings") if isinstance(finding_routes, Mapping) else None
    if not isinstance(findings, list):
        raise EchelonResultValidationError("finding_routes.findings must be a list")
    if verdict == "FAIL" and not findings:
        raise EchelonResultValidationError(
            "failing WHY2 results require at least one finding_routes.findings entry"
        )

    has_evidence_route = False
    for index, finding in enumerate(findings):
        prefix = f"finding_routes.findings[{index}]"
        if not isinstance(finding, Mapping):
            raise EchelonResultValidationError(f"{prefix} must be an object")
        for field in ("issue_id", "rationale"):
            if not isinstance(finding.get(field), str) or not finding[field].strip():
                raise EchelonResultValidationError(
                    f"{prefix}.{field} must be a non-empty string"
                )
        route = finding.get("route")
        if route not in {"spec_repair", "evidence_resolution", "human_decision"}:
            raise EchelonResultValidationError(
                f"{prefix}.route must be spec_repair, evidence_resolution, or human_decision"
            )
        has_evidence_route = has_evidence_route or route == "evidence_resolution"

    if has_evidence_route != (status == "pending"):
        raise EchelonResultValidationError(
            "evidence_resolution findings must exactly match evidence_resolution_status"
        )


def _validate_state_update_type(key: str, value: Any, value_type: str) -> None:
    if value_type == "quality_scores":
        error = validate_quality_scores_shape(value)
        if error:
            raise EchelonResultValidationError(error)
        return

    valid = {
        "array": lambda item: isinstance(item, list),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "object": lambda item: isinstance(item, dict),
        "string": lambda item: isinstance(item, str),
    }[value_type](value)
    if not valid:
        article = "an" if value_type in {"array", "integer", "object"} else "a"
        raise EchelonResultValidationError(
            f"echelon_result.state_updates.{key} must be {article} {value_type}"
        )

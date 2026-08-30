"""Closed, controller-owned human-input policy definitions."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Literal, Mapping


HUMAN_INPUT_MAX_OPTIONS = 16
HUMAN_INPUT_PROMPT_REQUEST_MAX_BYTES = 24_000
HUMAN_INPUT_QUESTION_MAX_BYTES = 4_000
HUMAN_INPUT_RECOMMENDATION_MAX_BYTES = 4_000
HUMAN_INPUT_IDENTIFIER_MAX_BYTES = 256
HUMAN_INPUT_OPTION_ID_MAX_BYTES = 128
HUMAN_INPUT_OPTION_LABEL_MAX_BYTES = 256
HUMAN_INPUT_OPTION_DESCRIPTION_MAX_BYTES = 1_024
HUMAN_INPUT_OPTION_OUTCOME_MAX_BYTES = 128

HumanInputSourceKind = Literal[
    "provider_escalation",
    "human_gate",
    "controller_safeguard",
    "legacy_recovery",
]
HumanInputClassification = Literal[
    "operational",
    "material",
    "external_prerequisite",
]
HumanInputRisk = Literal["low", "medium", "high", "critical"]
SemiPolicy = Literal["require_human", "auto_if_recommended_low_risk"]
RecommendationAuthority = Literal[
    "workflow_policy", "controller_evidence", "provider_evidence",
]
RecommendationConfidence = Literal["high", "medium", "low"]
RecommendationMode = Literal["static", "controller"]


def gate_outcome_route_error(outcome: str, route: str) -> str | None:
    """Return the closed gate outcome/route violation shared by all consumers."""
    if outcome == "approved" and route == "terminal-blocked":
        return "approved human gate outcome cannot target terminal-blocked"
    if outcome == "rejected" and route != "terminal-blocked":
        return "rejected human gate outcome must target terminal-blocked"
    return None


class HumanInputPolicyError(ValueError):
    """Raised when a policy declaration or request is outside the closed contract."""


_SOURCE_KINDS = frozenset({
    "provider_escalation", "human_gate", "controller_safeguard", "legacy_recovery",
})
_CLASSIFICATIONS = frozenset({"operational", "material", "external_prerequisite"})
_RISKS = frozenset({"low", "medium", "high", "critical"})
_SEMI_POLICIES = frozenset({"require_human", "auto_if_recommended_low_risk"})
_RECOMMENDATION_AUTHORITIES = frozenset({
    "workflow_policy", "controller_evidence", "provider_evidence",
})
_RECOMMENDATION_CONFIDENCES = frozenset({"high", "medium", "low"})
_RECOMMENDATION_MODES = frozenset({"static", "controller"})
_RESOLUTION_HANDLERS = frozenset({
    "clarification_resume",
    "gate_outcome",
    "phase_dispatch_limit",
    "proportional_quality_debt",
    "reset_why_fail_count",
    "reset_why2_stagnation",
})
_CONTEXT_STATE_KEYS = frozenset({
    "user_message",
    "phase",
    "quality_scores",
    "iteration",
    "max_iterations",
    "why_fail_count",
    "why2_metric_stagnation_count",
    "phase_dispatch_limit_phase",
    "phase_dispatch_limit",
    "issue_resolution_ledger",
    "phase1_quality_repair",
    "understanding_evidence",
    "proportional_quality_candidate_evidence",
})
_CONTEXT_ROOTS = ("{staging_dir}", "{spec_dir}", "{context_dir}", "{squad_dir}")
_POLICY_FIELDS = frozenset({
    "reason_code",
    "classification",
    "semi_policy",
    "resolution_handler",
    "allow_free_text",
    "allowed_target_phases",
    "context_state_keys",
    "context_paths",
    "options",
    "recommendation_mode",
})
_REQUIRED_POLICY_FIELDS = _POLICY_FIELDS - {"options"}
_OPTION_FIELDS = frozenset({
    "id", "label", "description", "recommended", "risk_level", "next_phase", "outcome",
})
_PROVIDER_OPTION_FIELDS = _OPTION_FIELDS - {"outcome"}
_SHA256_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _clean_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise HumanInputPolicyError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if not normalized:
        raise HumanInputPolicyError(f"{field} must be a non-empty string")
    return normalized


def _clean_bounded_string(
    value: object,
    field: str,
    *,
    max_bytes: int,
    max_characters: int | None = None,
) -> str:
    normalized = _clean_string(value, field)
    if max_characters is not None and len(normalized) > max_characters:
        raise HumanInputPolicyError(
            f"{field} must not exceed {max_characters:,} characters"
        )
    if len(normalized.encode("utf-8")) > max_bytes:
        raise HumanInputPolicyError(
            f"{field} must not exceed {max_bytes:,} UTF-8 bytes"
        )
    return normalized


def _clean_optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _clean_string(value, field)


def _clean_optional_bounded_string(
    value: object,
    field: str,
    *,
    max_bytes: int,
) -> str | None:
    if value is None:
        return None
    return _clean_bounded_string(value, field, max_bytes=max_bytes)


def _clean_string_collection(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, frozenset)):
        raise HumanInputPolicyError(f"{field} must be a list of non-empty strings")
    normalized = tuple(_clean_string(item, field) for item in value)
    if len(set(normalized)) != len(normalized):
        raise HumanInputPolicyError(f"{field} must not contain duplicates")
    return normalized


@dataclass(frozen=True)
class HumanInputOption:
    id: str
    label: str
    description: str
    recommended: bool
    risk_level: HumanInputRisk | None
    next_phase: str | None
    outcome: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "id",
            _clean_bounded_string(
                self.id,
                "option.id",
                max_bytes=HUMAN_INPUT_OPTION_ID_MAX_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "label",
            _clean_bounded_string(
                self.label,
                "option.label",
                max_bytes=HUMAN_INPUT_OPTION_LABEL_MAX_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "description",
            _clean_bounded_string(
                self.description,
                "option.description",
                max_bytes=HUMAN_INPUT_OPTION_DESCRIPTION_MAX_BYTES,
            ),
        )
        if type(self.recommended) is not bool:
            raise HumanInputPolicyError("option.recommended must be a boolean")
        if self.risk_level is not None and self.risk_level not in _RISKS:
            raise HumanInputPolicyError("option.risk_level must be low, medium, high, or critical")
        object.__setattr__(
            self,
            "next_phase",
            _clean_optional_bounded_string(
                self.next_phase,
                "option.next_phase",
                max_bytes=HUMAN_INPUT_IDENTIFIER_MAX_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "outcome",
            _clean_optional_bounded_string(
                self.outcome,
                "option.outcome",
                max_bytes=HUMAN_INPUT_OPTION_OUTCOME_MAX_BYTES,
            ),
        )


@dataclass(frozen=True)
class RecommendationEvidence:
    """An immutable reference supporting one prepared recommendation."""

    id: str
    kind: str
    reference: str
    digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "id",
            _clean_bounded_string(
                self.id,
                "recommendation_evidence.id",
                max_bytes=HUMAN_INPUT_IDENTIFIER_MAX_BYTES,
            ),
        )
        for field in ("kind", "reference"):
            object.__setattr__(
                self,
                field,
                _clean_bounded_string(
                    getattr(self, field),
                    f"recommendation_evidence.{field}",
                    max_bytes=HUMAN_INPUT_RECOMMENDATION_MAX_BYTES,
                ),
            )
        if not isinstance(self.digest, str) or _SHA256_DIGEST.fullmatch(self.digest) is None:
            raise HumanInputPolicyError(
                "recommendation_evidence.digest must be a lowercase SHA-256"
            )


def _canonical_sha256(payload: Mapping[str, object]) -> str:
    """Return the stable SHA-256 for recommendation evidence content."""
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _recommendation_option_payload(option: HumanInputOption) -> dict[str, object]:
    return {
        "id": option.id,
        "label": option.label,
        "description": option.description,
        "risk_level": option.risk_level,
        "next_phase": option.next_phase,
        "outcome": option.outcome,
    }


def _validate_options(
    options: tuple[HumanInputOption, ...],
    *,
    allowed_target_phases: frozenset[str] | None,
) -> None:
    if len(options) > HUMAN_INPUT_MAX_OPTIONS:
        raise HumanInputPolicyError(
            f"options must not contain more than {HUMAN_INPUT_MAX_OPTIONS} entries"
        )
    option_id_indexes: dict[str, int] = {}
    option_label_indexes: dict[str, int] = {}
    for index, option in enumerate(options):
        if option.id in option_id_indexes:
            raise HumanInputPolicyError("duplicate option id")
        if option.label in option_label_indexes:
            raise HumanInputPolicyError("duplicate option label")
        option_id_indexes[option.id] = index
        option_label_indexes[option.label] = index
    if any(
        option_id_indexes[label] != label_index
        for label, label_index in option_label_indexes.items()
        if label in option_id_indexes
    ):
        raise HumanInputPolicyError("option label conflicts with an option id")
    if sum(item.recommended for item in options) > 1:
        raise HumanInputPolicyError("at most one recommended option is allowed")
    for option in options:
        if (
            option.next_phase is not None
            and allowed_target_phases is not None
            and option.next_phase not in allowed_target_phases
        ):
            raise HumanInputPolicyError("option.next_phase must be in allowed_target_phases")


def _normalize_provider_options(
    value: object,
    *,
    allowed_target_phases: frozenset[str],
) -> tuple[HumanInputOption, ...]:
    if not isinstance(value, list):
        raise HumanInputPolicyError("options must be a list")
    if len(value) > HUMAN_INPUT_MAX_OPTIONS:
        raise HumanInputPolicyError(
            f"options must not contain more than {HUMAN_INPUT_MAX_OPTIONS} entries"
        )
    options: list[HumanInputOption] = []
    for index, raw_option in enumerate(value):
        if not isinstance(raw_option, Mapping):
            raise HumanInputPolicyError(f"options[{index}] must be a mapping")
        if "outcome" in raw_option:
            raise HumanInputPolicyError("provider options cannot set outcome")
        unknown = set(raw_option) - _PROVIDER_OPTION_FIELDS
        required = _PROVIDER_OPTION_FIELDS - {"risk_level"}
        missing = required - set(raw_option)
        if unknown:
            raise HumanInputPolicyError(
                f"options[{index}] has unsupported key {sorted(unknown)[0]!r}"
            )
        if missing:
            raise HumanInputPolicyError(
                f"options[{index}] is missing {sorted(missing)[0]!r}"
            )
        options.append(HumanInputOption(
            id=raw_option["id"],
            label=raw_option["label"],
            description=raw_option["description"],
            recommended=raw_option["recommended"],
            risk_level=raw_option.get("risk_level"),
            next_phase=raw_option["next_phase"],
            outcome=None,
        ))
    normalized = tuple(options)
    _validate_options(normalized, allowed_target_phases=allowed_target_phases)
    return normalized


@dataclass(frozen=True)
class HumanInputPolicy:
    source_kind: HumanInputSourceKind
    producer_id: str
    reason_code: str
    classification: HumanInputClassification
    semi_policy: SemiPolicy
    resolution_handler: str
    allow_free_text: bool
    allowed_phase_ids: frozenset[str]
    allowed_target_phases: frozenset[str]
    context_state_keys: tuple[str, ...]
    context_paths: tuple[str, ...]
    options: tuple[HumanInputOption, ...]
    recommendation_mode: RecommendationMode = "controller"

    def __post_init__(self) -> None:
        if self.source_kind not in _SOURCE_KINDS:
            raise HumanInputPolicyError("source_kind is not supported")
        object.__setattr__(
            self,
            "producer_id",
            _clean_bounded_string(
                self.producer_id,
                "producer_id",
                max_bytes=HUMAN_INPUT_IDENTIFIER_MAX_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "reason_code",
            _clean_bounded_string(
                self.reason_code,
                "reason_code",
                max_bytes=HUMAN_INPUT_IDENTIFIER_MAX_BYTES,
            ),
        )
        if self.classification not in _CLASSIFICATIONS:
            raise HumanInputPolicyError("classification is not supported")
        if self.semi_policy not in _SEMI_POLICIES:
            raise HumanInputPolicyError("semi_policy is not supported")
        if self.recommendation_mode not in _RECOMMENDATION_MODES:
            raise HumanInputPolicyError("recommendation_mode must be static or controller")
        if self.resolution_handler not in _RESOLUTION_HANDLERS:
            raise HumanInputPolicyError("resolution_handler is not supported")
        if type(self.allow_free_text) is not bool:
            raise HumanInputPolicyError("allow_free_text must be a boolean")
        phases = frozenset(_clean_string_collection(self.allowed_phase_ids, "allowed_phase_ids"))
        if not phases:
            raise HumanInputPolicyError("allowed_phase_ids must not be empty")
        targets = frozenset(_clean_string_collection(self.allowed_target_phases, "allowed_target_phases"))
        state_keys = _clean_string_collection(self.context_state_keys, "context_state_keys")
        if not set(state_keys).issubset(_CONTEXT_STATE_KEYS):
            raise HumanInputPolicyError("context_state_keys contains unsupported key")
        paths = _clean_string_collection(self.context_paths, "context_paths")
        for path in paths:
            if not any(path == root or path.startswith(f"{root}/") for root in _CONTEXT_ROOTS):
                raise HumanInputPolicyError("context_paths must start with an allowed context root")
            if ".." in path.split("/"):
                raise HumanInputPolicyError("context_paths must remain inside the declared root")
        if not isinstance(self.options, tuple) or not all(isinstance(item, HumanInputOption) for item in self.options):
            raise HumanInputPolicyError("options must be a tuple of HumanInputOption values")
        _validate_options(self.options, allowed_target_phases=targets)
        if self.recommendation_mode == "static" and (
            sum(option.recommended for option in self.options) != 1
        ):
            raise HumanInputPolicyError(
                "static policies require exactly one recommended option"
            )
        if (
            self.recommendation_mode == "controller"
            and self.options
            and not any(option.recommended for option in self.options)
            and (
                self.source_kind,
                self.producer_id,
                self.reason_code,
            ) not in _CONTROLLER_RECOMMENDATION_PREPARERS
        ):
            raise HumanInputPolicyError(
                "controller recommendation mode requires a registered preparer"
            )
        if self.source_kind == "human_gate":
            if self.allow_free_text:
                raise HumanInputPolicyError("human_gate policies cannot allow free text")
            if not self.options:
                raise HumanInputPolicyError("human_gate policies require options")
            if any(option.next_phase is None or option.outcome is None for option in self.options):
                raise HumanInputPolicyError("human_gate options require next_phase and outcome")
            outcomes = [str(option.outcome) for option in self.options]
            if len(set(outcomes)) != len(outcomes):
                raise HumanInputPolicyError("duplicate human_gate option outcome")
        elif any(option.outcome is not None for option in self.options):
            raise HumanInputPolicyError("option.outcome is only valid for human_gate policies")
        object.__setattr__(self, "allowed_phase_ids", phases)
        object.__setattr__(self, "allowed_target_phases", targets)
        object.__setattr__(self, "context_state_keys", state_keys)
        object.__setattr__(self, "context_paths", paths)


@dataclass(frozen=True)
class PreparedHumanInput:
    schema_version: Literal[2]
    source_kind: HumanInputSourceKind
    producer_id: str
    phase_id: str
    reason_code: str
    classification: HumanInputClassification
    question: str
    options: tuple[HumanInputOption, ...]
    recommended_answer: str | None
    recommended_option_id: str | None
    recommended_action: str | None
    automatic_eligible: bool
    recommendation_rationale: str
    recommendation_confidence: RecommendationConfidence
    recommendation_authority: RecommendationAuthority
    recommendation_evidence: tuple[RecommendationEvidence, ...]
    risk_level: HumanInputRisk | None
    resolution_handler: str
    source_state_revision: int

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise HumanInputPolicyError("prepared human input schema_version must be 2")
        if self.source_kind not in _SOURCE_KINDS:
            raise HumanInputPolicyError("source_kind is not supported")
        object.__setattr__(
            self,
            "producer_id",
            _clean_bounded_string(
                self.producer_id,
                "producer_id",
                max_bytes=HUMAN_INPUT_IDENTIFIER_MAX_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "phase_id",
            _clean_bounded_string(
                self.phase_id,
                "phase_id",
                max_bytes=HUMAN_INPUT_IDENTIFIER_MAX_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "reason_code",
            _clean_bounded_string(
                self.reason_code,
                "reason_code",
                max_bytes=HUMAN_INPUT_IDENTIFIER_MAX_BYTES,
            ),
        )
        if self.classification not in _CLASSIFICATIONS:
            raise HumanInputPolicyError("classification is not supported")
        object.__setattr__(
            self,
            "question",
            _clean_bounded_string(
                self.question,
                "question",
                max_bytes=HUMAN_INPUT_QUESTION_MAX_BYTES,
                max_characters=4_000,
            ),
        )
        if not isinstance(self.options, tuple) or not all(
            isinstance(option, HumanInputOption) for option in self.options
        ):
            raise HumanInputPolicyError(
                "options must be a tuple of HumanInputOption values"
            )
        _validate_options(self.options, allowed_target_phases=None)
        recommendation = _clean_optional_bounded_string(
            self.recommended_answer,
            "recommended_answer",
            max_bytes=HUMAN_INPUT_RECOMMENDATION_MAX_BYTES,
        )
        object.__setattr__(self, "recommended_answer", recommendation)
        recommended_option_id = _clean_optional_bounded_string(
            self.recommended_option_id,
            "recommended_option_id",
            max_bytes=HUMAN_INPUT_OPTION_ID_MAX_BYTES,
        )
        recommended_action = _clean_optional_bounded_string(
            self.recommended_action,
            "recommended_action",
            max_bytes=HUMAN_INPUT_RECOMMENDATION_MAX_BYTES,
        )
        if type(self.automatic_eligible) is not bool:
            raise HumanInputPolicyError("automatic_eligible must be a boolean")
        object.__setattr__(self, "recommended_option_id", recommended_option_id)
        object.__setattr__(self, "recommended_action", recommended_action)
        rationale = _clean_bounded_string(
            self.recommendation_rationale,
            "recommendation_rationale",
            max_bytes=HUMAN_INPUT_RECOMMENDATION_MAX_BYTES,
        )
        object.__setattr__(self, "recommendation_rationale", rationale)
        if self.recommendation_confidence not in _RECOMMENDATION_CONFIDENCES:
            raise HumanInputPolicyError(
                "recommendation_confidence must be high, medium, or low"
            )
        if self.recommendation_authority not in _RECOMMENDATION_AUTHORITIES:
            raise HumanInputPolicyError("recommendation_authority is not supported")
        if not isinstance(self.recommendation_evidence, tuple) or not all(
            isinstance(item, RecommendationEvidence)
            for item in self.recommendation_evidence
        ):
            raise HumanInputPolicyError(
                "recommendation_evidence must be a tuple of RecommendationEvidence values"
            )
        recommendation_ids = [option.id for option in self.options if option.recommended]
        if self.options:
            if len(recommendation_ids) != 1:
                raise HumanInputPolicyError(
                    "choices require exactly one option recommendation"
                )
            if recommended_option_id != recommendation_ids[0]:
                raise HumanInputPolicyError(
                    "recommended_option_id must identify the recommended option"
                )
            if recommendation is not None or recommended_action is not None:
                raise HumanInputPolicyError(
                    "choice recommendations cannot include free-text metadata"
                )
        elif recommendation is not None:
            if recommended_option_id is not None or recommended_action is not None:
                raise HumanInputPolicyError(
                    "automatic free text cannot include a choice target or action"
                )
        else:
            if (
                recommended_option_id is not None
                or recommended_action is None
                or self.automatic_eligible
            ):
                raise HumanInputPolicyError(
                    "human-only free text requires a recommended action"
                )
            if self.recommendation_evidence:
                raise HumanInputPolicyError(
                    "human-only free text cannot retain recommendation evidence"
                )
        if (self.options or recommendation is not None) and not self.recommendation_evidence:
            raise HumanInputPolicyError(
                "prepared recommendations require recommendation evidence"
            )
        if self.risk_level is not None and self.risk_level not in _RISKS:
            raise HumanInputPolicyError(
                "risk_level must be low, medium, high, or critical"
            )
        object.__setattr__(
            self,
            "resolution_handler",
            _clean_bounded_string(
                self.resolution_handler,
                "resolution_handler",
                max_bytes=HUMAN_INPUT_IDENTIFIER_MAX_BYTES,
            ),
        )
        if (
            type(self.source_state_revision) is not int
            or self.source_state_revision < 0
        ):
            raise HumanInputPolicyError(
                "source_state_revision must be a non-negative integer"
            )
        validate_human_input_prompt_request_payload(
            {
                "source_kind": self.source_kind,
                "producer_id": self.producer_id,
                "source_phase": self.phase_id,
                "reason_code": self.reason_code,
                "classification": self.classification,
                "question": self.question,
                "options": [
                    {
                        "id": option.id,
                        "label": option.label,
                        "description": option.description,
                        "recommended": option.recommended,
                        "risk_level": option.risk_level,
                        "next_phase": option.next_phase,
                        "outcome": option.outcome,
                    }
                    for option in self.options
                ],
                "recommended_answer": self.recommended_answer,
                "recommended_option_id": self.recommended_option_id,
                "recommended_action": self.recommended_action,
                "automatic_eligible": self.automatic_eligible,
                "recommendation_rationale": self.recommendation_rationale,
                "recommendation_confidence": self.recommendation_confidence,
                "recommendation_authority": self.recommendation_authority,
                "recommendation_evidence": [
                    {
                        "id": evidence.id,
                        "kind": evidence.kind,
                        "reference": evidence.reference,
                        "digest": evidence.digest,
                    }
                    for evidence in self.recommendation_evidence
                ],
                "risk_level": self.risk_level,
            }
        )


def validate_human_input_answer_shape(
    *,
    options: tuple[HumanInputOption, ...] | list[Mapping[str, object]],
    recommended_answer: str | None,
) -> None:
    """Reject answer metadata that cannot be represented by durable v2 state."""
    if options and recommended_answer is not None:
        raise HumanInputPolicyError(
            "recommended_answer cannot be combined with options"
        )


def validate_human_input_prompt_request_payload(
    payload: Mapping[str, object],
) -> None:
    """Keep the fixed COMMANDER request portion below its allocated byte budget."""
    try:
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HumanInputPolicyError(
            "human-input prompt request must be JSON serializable"
        ) from exc
    if len(encoded) > HUMAN_INPUT_PROMPT_REQUEST_MAX_BYTES:
        raise HumanInputPolicyError(
            "human-input prompt request exceeds the byte limit"
        )

@dataclass(frozen=True)
class DecisionResolution:
    selected_option_id: str | None
    answer_text: str | None
    rationale: str
    confidence: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class AppliedHumanInputResolution:
    selected_option_id: str | None
    answer_text: str | None
    resolved_by: Literal["user", "semi", "COMMANDER", "controller"]
    rationale: str | None = None
    confidence: Literal["high", "medium", "low"] | None = None


# Historical callers construct this internal value directly.  Keep the old
# import name as an alias while making the complete applied result the one
# concrete runtime type accepted by handlers and state transactions.
HumanInputResolution = AppliedHumanInputResolution


@dataclass(frozen=True)
class ProportionalQualityRecommendationEvidence:
    """Immutable score evidence for the bounded quality-budget recommendation."""

    borderline_margin: float
    previous_gates: tuple[tuple[str, float, float, bool], ...]
    current_gates: tuple[tuple[str, float, float, bool], ...]
    previous_formal_statement_count: int
    formal_statement_count: int
    qualitative_failure_count: int = 0
    qualitative_hard_blocker_count: int = 0

    def __post_init__(self) -> None:
        margin = self.borderline_margin
        if (
            type(margin) not in {int, float}
            or not math.isfinite(float(margin))
            or margin < 0
        ):
            raise HumanInputPolicyError(
                "borderline_margin must be a non-negative finite number"
            )
        object.__setattr__(self, "borderline_margin", float(margin))
        for field in (
            "previous_formal_statement_count",
            "formal_statement_count",
            "qualitative_failure_count",
            "qualitative_hard_blocker_count",
        ):
            count = getattr(self, field)
            if type(count) is not int or count < 0:
                raise HumanInputPolicyError(
                    f"{field} must be a non-negative integer"
                )
        if self.qualitative_hard_blocker_count > self.qualitative_failure_count:
            raise HumanInputPolicyError(
                "qualitative hard blockers cannot exceed qualitative failures"
            )
        previous = self._validate_gates(self.previous_gates, "previous_gates")
        current = self._validate_gates(self.current_gates, "current_gates")
        if {row[0] for row in previous} != {row[0] for row in current}:
            raise HumanInputPolicyError(
                "recommendation gate evidence must cover the same dimensions"
            )
        if (
            not any(not row[3] for row in current)
            and self.qualitative_failure_count == 0
        ):
            raise HumanInputPolicyError(
                "recommendation evidence requires residual quality debt"
            )
        object.__setattr__(self, "previous_gates", previous)
        object.__setattr__(self, "current_gates", current)

    @staticmethod
    def _validate_gates(
        value: object,
        field: str,
    ) -> tuple[tuple[str, float, float, bool], ...]:
        if type(value) is not tuple or not value:
            raise HumanInputPolicyError(f"{field} must be a non-empty tuple")
        normalized: list[tuple[str, float, float, bool]] = []
        names: set[str] = set()
        for index, row in enumerate(value):
            if type(row) is not tuple or len(row) != 4:
                raise HumanInputPolicyError(
                    f"{field}[{index}] must be a complete gate tuple"
                )
            name, score, threshold, passed = row
            if type(name) is not str or not name.strip() or name in names:
                raise HumanInputPolicyError(
                    f"{field} gate names must be non-empty and unique"
                )
            if (
                type(score) not in {int, float}
                or type(threshold) not in {int, float}
                or not math.isfinite(float(score))
                or not math.isfinite(float(threshold))
                or type(passed) is not bool
            ):
                raise HumanInputPolicyError(
                    f"{field}[{index}] contains malformed gate evidence"
                )
            names.add(name)
            normalized.append(
                (name, float(score), float(threshold), passed)
            )
        return tuple(normalized)


class HumanInputPolicyRegistry:
    """An immutable registry addressed solely by exact policy triples."""

    def __init__(self, policies: tuple[HumanInputPolicy, ...] | list[HumanInputPolicy]) -> None:
        policies_by_key: dict[tuple[str, str, str], HumanInputPolicy] = {}
        for policy in policies:
            if not isinstance(policy, HumanInputPolicy):
                raise HumanInputPolicyError("registry policies must be HumanInputPolicy values")
            key = (policy.source_kind, policy.producer_id, policy.reason_code)
            if key in policies_by_key:
                raise HumanInputPolicyError(f"duplicate human input policy {key!r}")
            policies_by_key[key] = policy
        self._policies = MappingProxyType(policies_by_key)

    @property
    def policies(self) -> tuple[HumanInputPolicy, ...]:
        return tuple(self._policies.values())

    def lookup(
        self,
        source_kind: HumanInputSourceKind,
        producer_id: str,
        reason_code: str,
    ) -> HumanInputPolicy:
        key = (_clean_string(source_kind, "source_kind"), _clean_string(producer_id, "producer_id"), _clean_string(reason_code, "reason_code"))
        policy = self._policies.get(key)
        if policy is None:
            raise HumanInputPolicyError(f"unknown human input policy {key!r}")
        return policy

    def prepare(
        self,
        *,
        source_kind: HumanInputSourceKind,
        producer_id: str,
        phase_id: str,
        reason_code: str,
        question: str,
        recommended_answer: str | None = None,
        risk_level: HumanInputRisk | None = None,
        options: list[Mapping[str, object]] | None = None,
        source_state_revision: int,
        **provider_fields: object,
    ) -> PreparedHumanInput:
        if provider_fields:
            fields = ", ".join(sorted(provider_fields))
            raise HumanInputPolicyError(f"provider cannot set policy-owned fields: {fields}")
        policy = self.lookup(source_kind, producer_id, reason_code)
        if options is not None and policy.source_kind != "provider_escalation":
            raise HumanInputPolicyError("provider options are only valid for provider_escalation policies")
        normalized_phase = _clean_string(phase_id, "phase_id")
        if normalized_phase not in policy.allowed_phase_ids:
            raise HumanInputPolicyError("phase_id is not allowed by the selected policy")
        normalized_question = _clean_string(question, "question")
        if len(normalized_question) > 4_000:
            raise HumanInputPolicyError("question must not exceed 4,000 characters")
        normalized_recommendation = _clean_optional_bounded_string(
            recommended_answer,
            "recommended_answer",
            max_bytes=HUMAN_INPUT_RECOMMENDATION_MAX_BYTES,
        )
        if risk_level is not None and risk_level not in _RISKS:
            raise HumanInputPolicyError("risk_level must be low, medium, high, or critical")
        normalized_options = (
            _normalize_provider_options(
                options,
                allowed_target_phases=policy.allowed_target_phases,
            )
            if options is not None
            else policy.options
        )
        validate_human_input_answer_shape(
            options=normalized_options,
            recommended_answer=normalized_recommendation,
        )
        if (
            normalized_recommendation is None
            and risk_level is not None
            and not any(option.recommended for option in normalized_options)
        ):
            raise HumanInputPolicyError("risk_level requires a recommendation")
        if type(source_state_revision) is not int or source_state_revision < 0:
            raise HumanInputPolicyError("source_state_revision must be a non-negative integer")
        recommended_options = [
            option for option in normalized_options if option.recommended
        ]
        if normalized_options and len(recommended_options) != 1:
            raise HumanInputPolicyError("choices require exactly one option recommendation")
        has_recommendation = bool(recommended_options) or normalized_recommendation is not None
        recommended_option_id = (
            recommended_options[0].id if recommended_options else None
        )
        automatic_eligible = _derive_automatic_eligibility(
            policy=policy,
            options=normalized_options,
            recommended_answer=normalized_recommendation,
            risk_level=risk_level,
        )
        if policy.recommendation_mode == "static":
            authority: RecommendationAuthority = "workflow_policy"
        elif has_recommendation:
            authority = "provider_evidence"
        else:
            authority = "workflow_policy"
        evidence = (
            (
                RecommendationEvidence(
                    id=f"{policy.producer_id}:{policy.reason_code}",
                    kind=authority,
                    reference=f"{policy.producer_id}:{policy.reason_code}",
                    digest=_canonical_sha256({
                        "authority": authority,
                        "source_kind": policy.source_kind,
                        "producer_id": policy.producer_id,
                        "phase_id": normalized_phase,
                        "reason_code": policy.reason_code,
                        "question": normalized_question,
                        "recommended_answer": normalized_recommendation,
                        "recommended_option": (
                            _recommendation_option_payload(recommended_options[0])
                            if recommended_options
                            else None
                        ),
                        "risk_level": risk_level,
                    }),
                ),
            )
            if has_recommendation
            else ()
        )
        return PreparedHumanInput(
            schema_version=2,
            source_kind=policy.source_kind,
            producer_id=policy.producer_id,
            phase_id=normalized_phase,
            reason_code=policy.reason_code,
            classification=policy.classification,
            question=normalized_question,
            options=normalized_options,
            recommended_answer=normalized_recommendation,
            recommended_option_id=recommended_option_id,
            recommended_action=(
                None
                if has_recommendation
                else 'Run echelon spec resume "<answer>" with the requested value.'
            ),
            automatic_eligible=automatic_eligible,
            recommendation_rationale=(
                "A controller-prepared recommendation is available."
                if has_recommendation
                else "Human input is required because no automatic recommendation is available."
            ),
            recommendation_confidence="medium" if has_recommendation else "low",
            recommendation_authority=authority,
            recommendation_evidence=evidence,
            risk_level=risk_level,
            resolution_handler=policy.resolution_handler,
            source_state_revision=source_state_revision,
        )

    def prepare_controller(
        self,
        *,
        source_kind: HumanInputSourceKind,
        producer_id: str,
        reason_code: str,
        phase_id: str,
        question: str,
        source_state_revision: int,
        **controller_evidence: object,
    ) -> PreparedHumanInput:
        """Invoke only the preparer registered for one exact policy triple."""
        policy = self.lookup(source_kind, producer_id, reason_code)
        key = (policy.source_kind, policy.producer_id, policy.reason_code)
        preparer = _CONTROLLER_RECOMMENDATION_PREPARERS.get(key)
        if preparer is None or policy.recommendation_mode != "controller":
            raise HumanInputPolicyError(
                "policy has no registered controller recommendation preparer"
            )
        return preparer(
            self,
            reason_code=policy.reason_code,
            phase_id=phase_id,
            question=question,
            source_state_revision=source_state_revision,
            **controller_evidence,
        )

    def has_controller_preparer(
        self,
        source_kind: HumanInputSourceKind,
        producer_id: str,
        reason_code: str,
    ) -> bool:
        """Return whether one exact registered policy has a controller preparer."""
        policy = self.lookup(source_kind, producer_id, reason_code)
        key = (policy.source_kind, policy.producer_id, policy.reason_code)
        return (
            policy.recommendation_mode == "controller"
            and key in _CONTROLLER_RECOMMENDATION_PREPARERS
        )


def _derive_automatic_eligibility(
    *,
    policy: HumanInputPolicy,
    options: tuple[HumanInputOption, ...],
    recommended_answer: str | None,
    risk_level: HumanInputRisk | None,
) -> bool:
    """Derive intrinsic automatic eligibility from recommendation and risk."""
    if policy.classification == "external_prerequisite":
        return False
    recommended_options = [option for option in options if option.recommended]
    if len(recommended_options) == 1:
        return (recommended_options[0].risk_level or risk_level) == "low"
    return not options and recommended_answer is not None and risk_level == "low"


def v2_automatic_decision_is_registered(
    decision: Mapping[str, object],
    policy: HumanInputPolicy,
) -> bool:
    """Reconstruct intrinsic v2 eligibility without requiring v3 preparation."""
    if decision.get("schema_version") != 2:
        return False
    if (
        decision.get("source_kind") != policy.source_kind
        or decision.get("producer_id") != policy.producer_id
        or decision.get("reason_code") != policy.reason_code
        or decision.get("classification") != policy.classification
        or decision.get("resolution_handler") != policy.resolution_handler
        or decision.get("source_phase") not in policy.allowed_phase_ids
    ):
        return False
    raw_options = decision.get("options")
    if not isinstance(raw_options, list):
        return False
    try:
        options = tuple(
            HumanInputOption(
                id=raw_option.get("id"),
                label=raw_option.get("label"),
                description=raw_option.get("description"),
                recommended=raw_option.get("recommended"),
                risk_level=raw_option.get("risk_level"),
                next_phase=raw_option.get("next_phase"),
                outcome=raw_option.get("outcome"),
            )
            for raw_option in raw_options
            if isinstance(raw_option, Mapping)
        )
    except HumanInputPolicyError:
        return False
    if len(options) != len(raw_options):
        return False

    dynamic_dispatch_cap = (
        policy.source_kind == "controller_safeguard"
        and policy.producer_id == "phase_dispatch_limit"
        and policy.reason_code == "phase_dispatch_limit"
        and policy.resolution_handler == "phase_dispatch_limit"
    )
    if dynamic_dispatch_cap:
        if not options:
            return False
    elif policy.source_kind != "provider_escalation":
        if tuple(
            replace(option, recommended=False) for option in options
        ) != tuple(
            replace(option, recommended=False) for option in policy.options
        ):
            return False
    if any(
        option.next_phase is not None
        and option.next_phase not in policy.allowed_target_phases
        for option in options
    ):
        return False
    if policy.source_kind != "human_gate" and any(
        option.outcome is not None for option in options
    ):
        return False
    if not dynamic_dispatch_cap and bool(options) == policy.allow_free_text:
        return False
    if policy.classification == "external_prerequisite":
        return False
    recommended_options = [option for option in options if option.recommended]
    if len(recommended_options) == 1:
        return (
            recommended_options[0].risk_level
            or decision.get("risk_level")
        ) == "low"
    return (
        not options
        and isinstance(decision.get("recommended_answer"), str)
        and bool(str(decision["recommended_answer"]).strip())
        and decision.get("risk_level") == "low"
    )


def _within_inclusive_decimal_margin(
    score: float,
    threshold: float,
    margin: float,
) -> bool:
    """Compare decimal-domain quality inputs without binary subtraction drift."""
    return Decimal(str(threshold)) - Decimal(str(score)) <= Decimal(str(margin))


def _controller_preparation_identity(
    policy: HumanInputPolicy,
    *,
    phase_id: str,
    question: str,
    source_state_revision: int,
) -> tuple[str, str, int]:
    normalized_phase = _clean_string(phase_id, "phase_id")
    if normalized_phase not in policy.allowed_phase_ids:
        raise HumanInputPolicyError("phase_id is not allowed by the selected policy")
    normalized_question = _clean_bounded_string(
        question,
        "question",
        max_bytes=HUMAN_INPUT_QUESTION_MAX_BYTES,
        max_characters=4_000,
    )
    if type(source_state_revision) is not int or source_state_revision < 0:
        raise HumanInputPolicyError(
            "source_state_revision must be a non-negative integer"
        )
    return normalized_phase, normalized_question, source_state_revision


def prepare_controller_checkpoint_assessment_decision(
    registry: HumanInputPolicyRegistry,
    *,
    reason_code: str,
    phase_id: str,
    question: str,
    source_state_revision: int,
    authority_kind: object,
    authority_evidence: object,
    accepted_debt_resolver: object = None,
    authorization_digest: object = None,
) -> PreparedHumanInput:
    """Select checkpoint approval from current controller-certified authority."""
    if type(registry) is not HumanInputPolicyRegistry:
        raise HumanInputPolicyError(
            "checkpoint assessment preparation requires a policy registry"
        )
    if reason_code != "checkpoint_assess_decision_required":
        raise HumanInputPolicyError(
            "reason_code is not the checkpoint assessment decision"
        )
    policy = registry.lookup(
        "human_gate",
        "checkpoint-assess",
        reason_code,
    )
    normalized_phase, normalized_question, revision = (
        _controller_preparation_identity(
            policy,
            phase_id=phase_id,
            question=question,
            source_state_revision=source_state_revision,
        )
    )
    if authority_kind not in {"ordinary_pass", "accepted_with_debt"}:
        raise HumanInputPolicyError(
            "checkpoint assessment authority is unavailable"
        )
    if (
        type(authority_evidence) is not tuple
        or not authority_evidence
        or not all(
            isinstance(item, RecommendationEvidence)
            for item in authority_evidence
        )
        or len({item.id for item in authority_evidence})
        != len(authority_evidence)
    ):
        raise HumanInputPolicyError(
            "checkpoint assessment evidence is invalid"
        )
    evidence_kinds = {item.kind for item in authority_evidence}
    if authority_kind == "ordinary_pass":
        if (
            "phase1_quality_certificate" not in evidence_kinds
            or not evidence_kinds
            <= {"phase1_quality_certificate", "spec_lexicon_pass"}
            or accepted_debt_resolver is not None
            or authorization_digest is not None
        ):
            raise HumanInputPolicyError(
                "ordinary checkpoint authority evidence is invalid"
            )
        rationale = (
            "Current ordinary Phase 1 PASS authority"
            + (
                " and current Spec Lexicon pass authority"
                if "spec_lexicon_pass" in evidence_kinds
                else ""
            )
            + " authorize the existing approve option."
        )
    else:
        resolver = _clean_bounded_string(
            accepted_debt_resolver,
            "accepted_debt_resolver",
            max_bytes=HUMAN_INPUT_IDENTIFIER_MAX_BYTES,
        )
        if (
            not isinstance(authorization_digest, str)
            or _SHA256_DIGEST.fullmatch(authorization_digest) is None
            or evidence_kinds
            != {"accepted_with_debt", "quality_gate_failure"}
            or not any(
                item.kind == "accepted_with_debt"
                and item.digest == authorization_digest
                for item in authority_evidence
            )
        ):
            raise HumanInputPolicyError(
                "accepted-debt checkpoint authority evidence is invalid"
            )
        rationale = (
            "Current accepted_with_debt authority resolved by "
            f"{resolver} authorizes the existing approve option under "
            f"authorization digest {authorization_digest}; the retained "
            "quality-gate FAIL is authorized debt, not an ordinary PASS."
        )

    if {option.id for option in policy.options} != {"approve", "reject"}:
        raise HumanInputPolicyError(
            "checkpoint assessment option contract is invalid"
        )
    prepared_options = tuple(
        replace(option, recommended=option.id == "approve")
        for option in policy.options
    )
    return PreparedHumanInput(
        schema_version=2,
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id=normalized_phase,
        reason_code=policy.reason_code,
        classification=policy.classification,
        question=normalized_question,
        options=prepared_options,
        recommended_answer=None,
        recommended_option_id="approve",
        recommended_action=None,
        automatic_eligible=True,
        recommendation_rationale=rationale,
        recommendation_confidence="high",
        recommendation_authority="controller_evidence",
        recommendation_evidence=authority_evidence,
        risk_level=None,
        resolution_handler=policy.resolution_handler,
        source_state_revision=revision,
    )


def prepare_controller_phase_dispatch_limit_decision(
    registry: HumanInputPolicyRegistry,
    *,
    reason_code: str,
    phase_id: str,
    question: str,
    source_state_revision: int,
    option_contract: object,
) -> PreparedHumanInput:
    """Recommend the first eligible issues.md option without inventing priority."""
    if type(registry) is not HumanInputPolicyRegistry:
        raise HumanInputPolicyError(
            "phase dispatch preparation requires a policy registry"
        )
    if reason_code != "phase_dispatch_limit":
        raise HumanInputPolicyError("reason_code is not a phase dispatch limit")
    policy = registry.lookup(
        "controller_safeguard",
        "phase_dispatch_limit",
        reason_code,
    )
    normalized_phase, normalized_question, revision = (
        _controller_preparation_identity(
            policy,
            phase_id=phase_id,
            question=question,
            source_state_revision=source_state_revision,
        )
    )
    if (
        type(option_contract) is not tuple
        or not option_contract
        or not all(isinstance(option, HumanInputOption) for option in option_contract)
        or any(option.recommended for option in option_contract)
        or any(option.outcome is not None for option in option_contract)
    ):
        raise HumanInputPolicyError(
            "phase dispatch option contract is invalid"
        )
    _validate_options(
        option_contract,
        allowed_target_phases=policy.allowed_target_phases,
    )
    selected = option_contract[0]
    prepared_options = tuple(
        replace(option, recommended=index == 0)
        for index, option in enumerate(option_contract)
    )
    evidence_payload = {
        "kind": "phase_dispatch_issue",
        "phase_id": normalized_phase,
        "document_order": [option.id for option in option_contract],
        "recommended_option": _recommendation_option_payload(
            prepared_options[0]
        ),
    }
    return PreparedHumanInput(
        schema_version=2,
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id=normalized_phase,
        reason_code=policy.reason_code,
        classification=policy.classification,
        question=normalized_question,
        options=prepared_options,
        recommended_answer=None,
        recommended_option_id=selected.id,
        recommended_action=None,
        automatic_eligible=True,
        recommendation_rationale=(
            "The selected issue is the first eligible entry in authoritative "
            "issues.md document order. This is a deterministic processing "
            "choice, not a product or quality priority claim."
        ),
        recommendation_confidence="high",
        recommendation_authority="controller_evidence",
        recommendation_evidence=(
            RecommendationEvidence(
                id=f"phase-dispatch-limit:{selected.id}",
                kind="phase_dispatch_issue",
                reference=f"issues.md#{selected.id}",
                digest=_canonical_sha256(evidence_payload),
            ),
        ),
        risk_level=None,
        resolution_handler=policy.resolution_handler,
        source_state_revision=revision,
    )


def prepare_controller_proportional_quality_decision(
    registry: HumanInputPolicyRegistry,
    *,
    reason_code: str,
    phase_id: str,
    question: str,
    source_state_revision: int,
    repair_state: Mapping[str, object],
    recommendation_evidence: ProportionalQualityRecommendationEvidence,
    option_contract: tuple[HumanInputOption, ...],
    no_artifact_progress: bool = False,
) -> PreparedHumanInput:
    """Prepare one quality-budget choice from sealed controller evidence.

    The registered option tuple is validated in full before this helper changes
    recommendation flags.  No provider-shaped options or recommendation inputs
    enter this boundary.
    """
    if type(registry) is not HumanInputPolicyRegistry:
        raise HumanInputPolicyError(
            "proportional quality preparation requires a policy registry"
        )
    if reason_code not in {
        "proportional_quality_budget_exhausted",
        "proportional_quality_extension_exhausted",
    }:
        raise HumanInputPolicyError(
            "reason_code is not a proportional quality decision"
        )
    policy = registry.lookup(
        "controller_safeguard",
        reason_code,
        reason_code,
    )
    if type(option_contract) is not tuple or option_contract != policy.options:
        raise HumanInputPolicyError(
            "controller option contract does not match the registered policy"
        )
    if type(recommendation_evidence) is not ProportionalQualityRecommendationEvidence:
        raise HumanInputPolicyError(
            "recommendation evidence must be controller-validated"
        )
    if type(no_artifact_progress) is not bool:
        raise HumanInputPolicyError(
            "no_artifact_progress must be Boolean"
        )

    try:
        from harness.proportional_quality import validate_repair_state

        validated_repair = validate_repair_state(repair_state)
    except (TypeError, ValueError) as exc:
        raise HumanInputPolicyError(
            "proportional quality repair state is invalid"
        ) from exc
    automatic_no_progress = (
        reason_code == "proportional_quality_budget_exhausted"
        and no_artifact_progress
        and validated_repair["extension_authorized"] == 0
        and validated_repair["extension_consumed"] == 0
    )
    if (
        reason_code == "proportional_quality_budget_exhausted"
        and validated_repair["automatic_consumed"]
        != validated_repair["automatic_limit"]
        and not automatic_no_progress
    ):
        raise HumanInputPolicyError(
            "proportional automatic quality budget is not exhausted"
        )
    if reason_code == "proportional_quality_budget_exhausted":
        if (
            validated_repair["extension_authorized"] != 0
            or validated_repair["extension_consumed"] != 0
        ):
            raise HumanInputPolicyError(
                "quality budget decision cannot be prepared after extension authorization"
            )
    elif (
        validated_repair["extension_authorized"]
        != validated_repair["extension_limit"]
        or validated_repair["extension_consumed"]
        != validated_repair["extension_limit"]
    ):
        raise HumanInputPolicyError(
            "quality extension decision requires a consumed authorized extension"
        )

    current_failures = tuple(
        row for row in recommendation_evidence.current_gates if not row[3]
    )
    previous_scores = {
        name: score
        for name, score, _threshold, _passed
        in recommendation_evidence.previous_gates
    }
    has_hard_blocker = (
        recommendation_evidence.qualitative_hard_blocker_count > 0
    )
    should_extend = (
        has_hard_blocker
        and reason_code == "proportional_quality_budget_exhausted"
    ) or (
        not has_hard_blocker
        and reason_code == "proportional_quality_budget_exhausted"
        and not no_artifact_progress
        and bool(current_failures)
        and all(
            _within_inclusive_decimal_margin(
                score,
                threshold,
                recommendation_evidence.borderline_margin,
            )
            for _name, score, threshold, _passed in current_failures
        )
        and all(
            score > previous_scores[name]
            for name, score, _threshold, _passed in current_failures
        )
        and recommendation_evidence.formal_statement_count
        <= recommendation_evidence.previous_formal_statement_count
    )
    recommended_id = (
        "extend_once"
        if should_extend
        else "stop"
        if has_hard_blocker
        else "continue_with_debt"
    )
    if recommended_id not in {option.id for option in policy.options}:
        raise HumanInputPolicyError(
            "registered policy does not contain the controller recommendation"
        )

    prepared_options = tuple(
        replace(option, recommended=option.id == recommended_id)
        for option in option_contract
    )
    normalized_phase, normalized_question, revision = (
        _controller_preparation_identity(
            policy,
            phase_id=phase_id,
            question=question,
            source_state_revision=source_state_revision,
        )
    )
    if has_hard_blocker and should_extend:
        rationale = (
            "The residual qualitative finding is a hard blocker that cannot be "
            "accepted as quality debt, so the single available extension is required."
        )
    elif has_hard_blocker:
        rationale = (
            "The residual qualitative finding is a hard blocker that cannot be "
            "accepted as quality debt, and the bounded extension is exhausted."
        )
    elif should_extend:
        rationale = (
            "Residual gates improved within the configured borderline margin "
            "without formal-statement growth, so one final repair is favored."
        )
    elif reason_code == "proportional_quality_extension_exhausted":
        rationale = (
            "The single authorized extension is consumed and quality still "
            "fails, so the remaining non-stop choice is explicit debt acceptance."
        )
    elif no_artifact_progress:
        rationale = (
            "The repair produced no artifact progress, so another automatic "
            "attempt is not favored over explicit debt acceptance."
        )
    elif not current_failures:
        rationale = (
            "Numeric gates pass, but authoritative qualitative failures remain; "
            "extension is not inferred from an empty numeric comparison, so "
            "explicit debt acceptance is favored."
        )
    else:
        rationale = (
            "At least one residual gate is outside the improving borderline "
            "case or formal statements grew, so explicit debt acceptance is favored."
        )
    return PreparedHumanInput(
        schema_version=2,
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id=normalized_phase,
        reason_code=policy.reason_code,
        classification=policy.classification,
        question=normalized_question,
        options=prepared_options,
        recommended_answer=None,
        recommended_option_id=recommended_id,
        recommended_action=None,
        automatic_eligible=True,
        recommendation_rationale=rationale,
        recommendation_confidence="medium",
        recommendation_authority="controller_evidence",
        recommendation_evidence=(
            RecommendationEvidence(
                id=f"{reason_code}:{recommended_id}",
                kind="proportional_quality",
                reference=reason_code,
                digest=_canonical_sha256({
                    "kind": "proportional_quality",
                    "reason_code": reason_code,
                    "phase_id": normalized_phase,
                    "question": normalized_question,
                    "recommended_option": _recommendation_option_payload(
                        next(
                            option
                            for option in prepared_options
                            if option.id == recommended_id
                        )
                    ),
                    "repair_state": dict(validated_repair),
                    "evidence": {
                        "borderline_margin": recommendation_evidence.borderline_margin,
                        "previous_gates": recommendation_evidence.previous_gates,
                        "current_gates": recommendation_evidence.current_gates,
                        "previous_formal_statement_count": (
                            recommendation_evidence.previous_formal_statement_count
                        ),
                        "formal_statement_count": (
                            recommendation_evidence.formal_statement_count
                        ),
                        "qualitative_failure_count": (
                            recommendation_evidence.qualitative_failure_count
                        ),
                        "qualitative_hard_blocker_count": (
                            recommendation_evidence.qualitative_hard_blocker_count
                        ),
                    },
                }),
            ),
        ),
        risk_level=None,
        resolution_handler=policy.resolution_handler,
        source_state_revision=revision,
    )


_CONTROLLER_RECOMMENDATION_PREPARERS = MappingProxyType({
    (
        "human_gate",
        "checkpoint-assess",
        "checkpoint_assess_decision_required",
    ): prepare_controller_checkpoint_assessment_decision,
    (
        "controller_safeguard",
        "phase_dispatch_limit",
        "phase_dispatch_limit",
    ): prepare_controller_phase_dispatch_limit_decision,
    (
        "controller_safeguard",
        "proportional_quality_budget_exhausted",
        "proportional_quality_budget_exhausted",
    ): prepare_controller_proportional_quality_decision,
    (
        "controller_safeguard",
        "proportional_quality_extension_exhausted",
        "proportional_quality_extension_exhausted",
    ): prepare_controller_proportional_quality_decision,
})


def legacy_recovery_policy_alias(
    current_policy: HumanInputPolicy,
) -> HumanInputPolicy:
    """Copy one exact current provider or safeguard policy as a legacy alias."""
    if type(current_policy) is not HumanInputPolicy:
        raise HumanInputPolicyError(
            "legacy recovery requires one current human-input policy"
        )
    if current_policy.source_kind not in {
        "provider_escalation",
        "controller_safeguard",
    }:
        raise HumanInputPolicyError(
            "legacy recovery can alias only a provider or safeguard policy"
        )
    return replace(current_policy, source_kind="legacy_recovery")


def select_initial_decision_status(
    mode: str,
    policy: HumanInputPolicy,
    request: PreparedHumanInput,
) -> Literal["pending", "awaiting_human"]:
    """Select the only two durable initial statuses without a fallback route."""
    if mode not in {"guided", "semi", "banzai"}:
        raise HumanInputPolicyError("mode must be guided, semi, or banzai")
    if request.source_kind != policy.source_kind or request.producer_id != policy.producer_id or request.reason_code != policy.reason_code:
        raise HumanInputPolicyError("request does not match the selected policy")
    if mode == "guided":
        return "awaiting_human"
    if mode == "banzai":
        return "pending" if request.automatic_eligible else "awaiting_human"
    if (
        policy.classification != "operational"
        or policy.semi_policy != "auto_if_recommended_low_risk"
    ):
        return "awaiting_human"
    if mode == "semi":
        return "pending" if request.automatic_eligible else "awaiting_human"
    return "pending"


def compile_workflow_human_input_policies(
    phase: Mapping[str, Any],
    *,
    known_phase_ids: frozenset[str],
) -> tuple[HumanInputPolicy, ...]:
    """Compile one phase's explicit workflow declarations into closed policies."""
    raw_policies = phase.get("human_input", [])
    if raw_policies is None or not isinstance(raw_policies, list):
        raise HumanInputPolicyError("human_input must be a list of mappings")
    if not raw_policies:
        return ()
    phase_id = _clean_string(phase.get("id"), "phase.id")
    source_kind: HumanInputSourceKind = (
        "human_gate" if phase.get("type") == "human_gate" else "provider_escalation"
    )
    compiled: list[HumanInputPolicy] = []
    reason_codes: set[str] = set()
    for index, raw_policy in enumerate(raw_policies):
        if not isinstance(raw_policy, Mapping):
            raise HumanInputPolicyError(f"human_input[{index}] must be a mapping")
        unknown = set(raw_policy) - _POLICY_FIELDS
        missing = _REQUIRED_POLICY_FIELDS - set(raw_policy)
        if unknown:
            raise HumanInputPolicyError(f"human_input[{index}] has unsupported key {sorted(unknown)[0]!r}")
        if missing:
            raise HumanInputPolicyError(f"human_input[{index}] is missing {sorted(missing)[0]!r}")
        reason_code = _clean_string(raw_policy["reason_code"], "reason_code")
        if reason_code in reason_codes:
            raise HumanInputPolicyError("duplicate human_input reason_code")
        reason_codes.add(reason_code)
        if source_kind == "human_gate" and "options" not in raw_policy:
            raise HumanInputPolicyError(f"human_input[{index}] is missing 'options'")
        raw_options = raw_policy.get("options", [])
        if not isinstance(raw_options, list):
            raise HumanInputPolicyError("options must be a list")
        options: list[HumanInputOption] = []
        for option_index, raw_option in enumerate(raw_options):
            if not isinstance(raw_option, Mapping):
                raise HumanInputPolicyError(f"options[{option_index}] must be a mapping")
            unknown_option = set(raw_option) - _OPTION_FIELDS
            missing_option = _OPTION_FIELDS - set(raw_option)
            if unknown_option:
                raise HumanInputPolicyError(f"options[{option_index}] has unsupported key {sorted(unknown_option)[0]!r}")
            if missing_option:
                raise HumanInputPolicyError(f"options[{option_index}] is missing {sorted(missing_option)[0]!r}")
            options.append(HumanInputOption(**dict(raw_option)))
        targets = _clean_string_collection(raw_policy["allowed_target_phases"], "allowed_target_phases")
        unknown_targets = set(targets) - known_phase_ids
        if unknown_targets:
            raise HumanInputPolicyError("allowed_target_phases contains unknown target " + repr(sorted(unknown_targets)[0]))
        compiled.append(HumanInputPolicy(
            source_kind=source_kind,
            producer_id=phase_id,
            reason_code=reason_code,
            classification=raw_policy["classification"],
            semi_policy=raw_policy["semi_policy"],
            resolution_handler=raw_policy["resolution_handler"],
            allow_free_text=raw_policy["allow_free_text"],
            allowed_phase_ids=frozenset({phase_id}),
            allowed_target_phases=frozenset(targets),
            context_state_keys=tuple(raw_policy["context_state_keys"]),
            context_paths=tuple(raw_policy["context_paths"]),
            options=tuple(options),
            recommendation_mode=raw_policy["recommendation_mode"],
        ))
    return tuple(compiled)


def controller_safeguard_policies() -> tuple[HumanInputPolicy, ...]:
    """Return exact policies for safeguards which have no workflow node."""
    phase_a_sources = frozenset({
        "init", "phase1-discover", "phase1-synthesizer", "phase1-modeler",
        "phase1-tracker", "phase1-why1", "phase1-constitution", "phase1-what",
        "phase1-understanding", "phase1-why2", "phase1-investigate",
        "phase1-lexicon-derive", "phase1-lexicon", "checkpoint-assess",
        "phase2-decide", "phase2-feasibility-structural", "phase2-strategic-overview",
        "phase2-tracker-alignment", "phase2-intent-alignment-structural", "phase3-how",
        "phase3-specialists", "phase3-sentinel", "phase3-plan", "phase3-tasks-lexicon",
        "phase3-understanding", "phase3-consensus", "phase3-consensus-tasks-lexicon",
        "checkpoint-plan", "phase4-document",
        "escalate",
    })
    return (
        HumanInputPolicy(
            source_kind="controller_safeguard", producer_id="phase_dispatch_limit",
            reason_code="phase_dispatch_limit", classification="material",
            semi_policy="require_human", resolution_handler="phase_dispatch_limit",
            allow_free_text=False, allowed_phase_ids=phase_a_sources,
            allowed_target_phases=frozenset({
                "phase1-what",
                "phase3-how",
                "phase3-sentinel",
                "phase3-plan",
            }),
            context_state_keys=("phase", "phase_dispatch_limit_phase", "phase_dispatch_limit", "issue_resolution_ledger"),
            context_paths=(), options=(),
        ),
        HumanInputPolicy(
            source_kind="controller_safeguard", producer_id="consecutive_why_fails",
            reason_code="consecutive_why_fails", classification="material",
            semi_policy="require_human", resolution_handler="reset_why_fail_count",
            allow_free_text=True, allowed_phase_ids=frozenset({"phase1-why2"}),
            allowed_target_phases=frozenset({"phase1-why2"}),
            context_state_keys=("phase", "why_fail_count", "issue_resolution_ledger"),
            context_paths=(), options=(),
        ),
        HumanInputPolicy(
            source_kind="controller_safeguard", producer_id="why2_metric_stagnation",
            reason_code="why2_metric_stagnation", classification="material",
            semi_policy="require_human", resolution_handler="reset_why2_stagnation",
            allow_free_text=True, allowed_phase_ids=frozenset({"phase1-why2"}),
            allowed_target_phases=frozenset({"phase1-why2"}),
            context_state_keys=("phase", "why_fail_count", "why2_metric_stagnation_count"),
            context_paths=(), options=(),
        ),
        HumanInputPolicy(
            source_kind="controller_safeguard",
            producer_id="proportional_quality_budget_exhausted",
            reason_code="proportional_quality_budget_exhausted",
            classification="material",
            semi_policy="require_human",
            resolution_handler="proportional_quality_debt",
            allow_free_text=False,
            allowed_phase_ids=frozenset({"phase1-why2"}),
            allowed_target_phases=frozenset({
                "phase1-what",
                "phase1-lexicon-derive",
                "checkpoint-assess",
                "terminal-blocked",
            }),
            context_state_keys=(
                "phase",
                "phase1_quality_repair",
                "understanding_evidence",
                "proportional_quality_candidate_evidence",
            ),
            context_paths=(),
            options=(
                HumanInputOption(
                    id="extend_once",
                    label="Extend once",
                    description=(
                        "Authorize one final specification quality repair."
                    ),
                    recommended=False,
                    risk_level="medium",
                    next_phase="phase1-what",
                    outcome=None,
                ),
                HumanInputOption(
                    id="continue_with_debt",
                    label="Continue with debt",
                    description=(
                        "Accept the restored candidate with explicit quality debt."
                    ),
                    recommended=False,
                    risk_level="high",
                    next_phase=None,
                    outcome=None,
                ),
                HumanInputOption(
                    id="stop",
                    label="Stop",
                    description=(
                        "Preserve the blocked run without accepting quality debt."
                    ),
                    recommended=False,
                    risk_level="low",
                    next_phase="terminal-blocked",
                    outcome=None,
                ),
            ),
        ),
        HumanInputPolicy(
            source_kind="controller_safeguard",
            producer_id="proportional_quality_extension_exhausted",
            reason_code="proportional_quality_extension_exhausted",
            classification="material",
            semi_policy="require_human",
            resolution_handler="proportional_quality_debt",
            allow_free_text=False,
            allowed_phase_ids=frozenset({"phase1-why2"}),
            allowed_target_phases=frozenset({
                "phase1-lexicon-derive",
                "checkpoint-assess",
                "terminal-blocked",
            }),
            context_state_keys=(
                "phase",
                "phase1_quality_repair",
                "understanding_evidence",
                "proportional_quality_candidate_evidence",
            ),
            context_paths=(),
            options=(
                HumanInputOption(
                    id="continue_with_debt",
                    label="Continue with debt",
                    description=(
                        "Accept the restored candidate with explicit quality debt."
                    ),
                    recommended=False,
                    risk_level="high",
                    next_phase=None,
                    outcome=None,
                ),
                HumanInputOption(
                    id="stop",
                    label="Stop",
                    description=(
                        "Preserve the blocked run without accepting quality debt."
                    ),
                    recommended=False,
                    risk_level="low",
                    next_phase="terminal-blocked",
                    outcome=None,
                ),
            ),
        ),
        HumanInputPolicy(
            source_kind="controller_safeguard", producer_id="agent_blocked",
            reason_code="agent_blocked", classification="material",
            semi_policy="require_human", resolution_handler="clarification_resume",
            allow_free_text=True, allowed_phase_ids=phase_a_sources,
            allowed_target_phases=frozenset(),
            context_state_keys=("phase", "user_message"),
            context_paths=("{spec_dir}/unknowns.md", "{spec_dir}/spec.md"),
            options=(),
        ),
    )

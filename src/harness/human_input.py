"""Closed, controller-owned human-input policy definitions."""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Literal, Mapping


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
_RESOLUTION_HANDLERS = frozenset({
    "clarification_resume",
    "gate_outcome",
    "phase_dispatch_limit",
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
})
_REQUIRED_POLICY_FIELDS = _POLICY_FIELDS - {"options"}
_OPTION_FIELDS = frozenset({
    "id", "label", "description", "recommended", "risk_level", "next_phase", "outcome",
})
_PROVIDER_OPTION_FIELDS = _OPTION_FIELDS - {"outcome"}


def _clean_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise HumanInputPolicyError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if not normalized:
        raise HumanInputPolicyError(f"{field} must be a non-empty string")
    return normalized


def _clean_optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _clean_string(value, field)


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
        object.__setattr__(self, "id", _clean_string(self.id, "option.id"))
        object.__setattr__(self, "label", _clean_string(self.label, "option.label"))
        object.__setattr__(self, "description", _clean_string(self.description, "option.description"))
        if type(self.recommended) is not bool:
            raise HumanInputPolicyError("option.recommended must be a boolean")
        if self.risk_level is not None and self.risk_level not in _RISKS:
            raise HumanInputPolicyError("option.risk_level must be low, medium, high, or critical")
        object.__setattr__(self, "next_phase", _clean_optional_string(self.next_phase, "option.next_phase"))
        object.__setattr__(self, "outcome", _clean_optional_string(self.outcome, "option.outcome"))


def _validate_options(
    options: tuple[HumanInputOption, ...],
    *,
    allowed_target_phases: frozenset[str],
) -> None:
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
        if option.next_phase is not None and option.next_phase not in allowed_target_phases:
            raise HumanInputPolicyError("option.next_phase must be in allowed_target_phases")


def _normalize_provider_options(
    value: object,
    *,
    allowed_target_phases: frozenset[str],
) -> tuple[HumanInputOption, ...]:
    if not isinstance(value, list):
        raise HumanInputPolicyError("options must be a list")
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

    def __post_init__(self) -> None:
        if self.source_kind not in _SOURCE_KINDS:
            raise HumanInputPolicyError("source_kind is not supported")
        object.__setattr__(self, "producer_id", _clean_string(self.producer_id, "producer_id"))
        object.__setattr__(self, "reason_code", _clean_string(self.reason_code, "reason_code"))
        if self.classification not in _CLASSIFICATIONS:
            raise HumanInputPolicyError("classification is not supported")
        if self.semi_policy not in _SEMI_POLICIES:
            raise HumanInputPolicyError("semi_policy is not supported")
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
    schema_version: Literal[1]
    source_kind: HumanInputSourceKind
    producer_id: str
    phase_id: str
    reason_code: str
    classification: HumanInputClassification
    question: str
    options: tuple[HumanInputOption, ...]
    recommended_answer: str | None
    risk_level: HumanInputRisk | None
    resolution_handler: str
    source_state_revision: int


@dataclass(frozen=True)
class DecisionResolution:
    selected_option_id: str | None
    answer_text: str | None
    rationale: str
    confidence: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class HumanInputResolution:
    selected_option_id: str | None
    answer_text: str | None
    resolved_by: Literal["user", "semi", "COMMANDER"]


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
        normalized_recommendation = _clean_optional_string(recommended_answer, "recommended_answer")
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
        if (
            normalized_recommendation is None
            and risk_level is not None
            and not any(option.recommended for option in normalized_options)
        ):
            raise HumanInputPolicyError("risk_level requires a recommendation")
        if type(source_state_revision) is not int or source_state_revision < 0:
            raise HumanInputPolicyError("source_state_revision must be a non-negative integer")
        return PreparedHumanInput(
            schema_version=1,
            source_kind=policy.source_kind,
            producer_id=policy.producer_id,
            phase_id=normalized_phase,
            reason_code=policy.reason_code,
            classification=policy.classification,
            question=normalized_question,
            options=normalized_options,
            recommended_answer=normalized_recommendation,
            risk_level=risk_level,
            resolution_handler=policy.resolution_handler,
            source_state_revision=source_state_revision,
        )


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
        return (
            "awaiting_human"
            if policy.classification == "external_prerequisite"
            else "pending"
        )
    if policy.classification != "operational":
        return "awaiting_human"
    if mode == "semi":
        if policy.semi_policy != "auto_if_recommended_low_risk":
            return "awaiting_human"
        recommended_options = [option for option in request.options if option.recommended]
        if len(recommended_options) == 1:
            effective_risk = recommended_options[0].risk_level or request.risk_level
            return "pending" if effective_risk == "low" else "awaiting_human"
        if not request.options and request.recommended_answer and request.risk_level == "low":
            return "pending"
        return "awaiting_human"
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
            allowed_target_phases=frozenset({"phase1-what"}),
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
    )

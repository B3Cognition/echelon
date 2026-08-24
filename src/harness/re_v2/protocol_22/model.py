"""Closed immutable value contracts for RE v2 protocol 2.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.model import RE_V2_SCHEMA_2_PROTOCOLS

from .schema import (
    Protocol22SchemaError,
    boolean,
    bounded_int,
    digest_value,
    exact_object,
    integer_or_none,
    literal,
    load_canonical_object,
    nonnegative_int,
    one_of,
    optional_digest,
    optional_text,
    positive_int,
    positive_or_none,
    safe_id,
    safe_relative_path,
    sorted_unique_digests,
    text_value,
    utc_timestamp,
)


GoalV2 = Literal["baseline", "inventory", "selective-deepening"]
LayerV2 = Literal["L0", "L1", "L2"]
AttemptKindV2 = Literal[
    "initial_generation",
    "result_contract_retry",
    "artifact_contract_retry",
]

_GOALS = frozenset({"baseline", "inventory", "selective-deepening"})
_LAYERS = frozenset({"L0", "L1", "L2"})
_ATTEMPT_KINDS = frozenset(
    {"initial_generation", "result_contract_retry", "artifact_contract_retry"}
)
_DOMAIN_ARTIFACT_KINDS = frozenset(
    {
        "domain-inventory",
        "domain-evidence-pack",
        "domain-context-bundle",
        "domain-baseline",
    }
)
_SOURCE_ARTIFACT_KINDS = frozenset(
    {
        "source-inventory",
        "source-partition",
        "source-evidence-pack",
        "source-overview-context-bundle",
        "source-overview",
        "source-baseline-root",
    }
)
_ARTIFACT_LAYERS = {
    "source-inventory": "L0",
    "source-partition": "L0",
    "domain-inventory": "L0",
    "source-evidence-pack": "L0",
    "domain-evidence-pack": "L0",
    "domain-context-bundle": "L1",
    "source-overview-context-bundle": "L1",
    "domain-baseline": frozenset({"L1", "L2"}),
    "source-overview": "L1",
    "source-baseline-root": "L1",
}


class _CanonicalIdentity:
    __slots__ = ()

    def to_json_dict(self) -> dict[str, object]:
        raise NotImplementedError

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())


@dataclass(frozen=True, slots=True)
class CatalogReferenceV1(_CanonicalIdentity):
    object_hash: str
    relative_path: str

    FIELDS: ClassVar[tuple[str, ...]] = ("object_hash", "relative_path")

    def __post_init__(self) -> None:
        digest_value(self.object_hash, "CatalogReferenceV1.object_hash")
        safe_relative_path(self.relative_path, "CatalogReferenceV1.relative_path")

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "CatalogReferenceV1":
        raw = exact_object(value, frozenset(cls.FIELDS), "CatalogReferenceV1")
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class BudgetPolicyV2(_CanonicalIdentity):
    token_limit: int | None
    active_ms_limit: int | None
    provider_attempt_limit: int
    artifact_generation_attempt_limit: int
    semantic_repair_round_limit: int
    result_contract_retry_limit: int
    shared_retry_limit: int
    artifact_contract_retry_limit: int

    ATTEMPT_FIELDS: ClassVar[tuple[str, ...]] = (
        "provider_attempt_limit",
        "artifact_generation_attempt_limit",
        "semantic_repair_round_limit",
        "result_contract_retry_limit",
        "shared_retry_limit",
        "artifact_contract_retry_limit",
    )
    FIELDS: ClassVar[tuple[str, ...]] = (
        "token_limit",
        "active_ms_limit",
        *ATTEMPT_FIELDS,
    )
    GOAL_ATTEMPTS: ClassVar[Mapping[str, tuple[int, ...]]] = {
        "baseline": (2, 2, 0, 1, 1, 1),
        "inventory": (0, 1, 0, 0, 0, 0),
    }

    def __post_init__(self) -> None:
        positive_or_none(self.token_limit, "BudgetPolicyV2.token_limit")
        positive_or_none(self.active_ms_limit, "BudgetPolicyV2.active_ms_limit")
        for field in self.ATTEMPT_FIELDS:
            nonnegative_int(getattr(self, field), f"BudgetPolicyV2.{field}")

    @classmethod
    def for_goal(
        cls,
        goal: str,
        token_limit: int | None,
        active_ms_limit: int | None,
    ) -> "BudgetPolicyV2":
        selected = one_of(goal, _GOALS, "goal")
        attempts = cls.GOAL_ATTEMPTS[selected]
        return cls(token_limit, active_ms_limit, *attempts)

    def matches_goal(self, goal: str) -> bool:
        selected = one_of(goal, _GOALS, "goal")
        return (
            tuple(getattr(self, field) for field in self.ATTEMPT_FIELDS)
            == (self.GOAL_ATTEMPTS[selected])
        )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "BudgetPolicyV2":
        raw = exact_object(value, frozenset(cls.FIELDS), "BudgetPolicyV2")
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ArtifactScope(_CanonicalIdentity):
    source_id: str
    domain_key: str | None
    content_id: str | None

    FIELDS: ClassVar[tuple[str, ...]] = ("source_id", "domain_key", "content_id")

    def __post_init__(self) -> None:
        safe_id(self.source_id, "ArtifactScope.source_id")
        optional_digest(self.domain_key, "ArtifactScope.domain_key")
        optional_digest(self.content_id, "ArtifactScope.content_id")

    @property
    def is_domain(self) -> bool:
        return self.domain_key is not None

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ArtifactScope":
        raw = exact_object(value, frozenset(cls.FIELDS), "ArtifactScope")
        return cls(**{field: raw[field] for field in cls.FIELDS})


def _validate_scope_for_artifact(scope: ArtifactScope, artifact_kind: str) -> None:
    if artifact_kind in _DOMAIN_ARTIFACT_KINDS and scope.domain_key is None:
        raise Protocol22SchemaError(
            f"{artifact_kind} requires ArtifactScope.domain_key"
        )
    if artifact_kind in _SOURCE_ARTIFACT_KINDS and scope.domain_key is not None:
        raise Protocol22SchemaError(
            f"{artifact_kind} requires null ArtifactScope.domain_key"
        )


def _validate_artifact_layer(artifact_kind: str, layer: str) -> None:
    expected = _ARTIFACT_LAYERS.get(artifact_kind)
    if isinstance(expected, str) and layer != expected:
        raise Protocol22SchemaError(
            f"{artifact_kind} requires layer {expected}, not {layer}"
        )
    if isinstance(expected, frozenset) and layer not in expected:
        raise Protocol22SchemaError(
            f"{artifact_kind} requires one of layers {sorted(expected)}, not {layer}"
        )


@dataclass(frozen=True, slots=True)
class ArtifactKeyV2(_CanonicalIdentity):
    identity_schema_version: int
    scope: ArtifactScope
    partition_id: str | None
    artifact_kind: str
    layer: LayerV2
    producer_protocol_version: str
    layer_policy_hash: str
    dependency_hashes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "identity_schema_version",
        "scope",
        "partition_id",
        "artifact_kind",
        "layer",
        "producer_protocol_version",
        "layer_policy_hash",
        "dependency_hashes",
    )

    def __post_init__(self) -> None:
        literal(
            self.identity_schema_version, 2, "ArtifactKeyV2.identity_schema_version"
        )
        if not isinstance(self.scope, ArtifactScope):
            raise Protocol22SchemaError("ArtifactKeyV2.scope must be an ArtifactScope")
        optional_digest(self.partition_id, "ArtifactKeyV2.partition_id")
        safe_id(self.artifact_kind, "ArtifactKeyV2.artifact_kind")
        one_of(self.layer, _LAYERS, "ArtifactKeyV2.layer")
        safe_id(
            self.producer_protocol_version,
            "ArtifactKeyV2.producer_protocol_version",
        )
        digest_value(self.layer_policy_hash, "ArtifactKeyV2.layer_policy_hash")
        object.__setattr__(
            self,
            "dependency_hashes",
            sorted_unique_digests(
                self.dependency_hashes,
                "ArtifactKeyV2.dependency_hashes",
            ),
        )
        _validate_scope_for_artifact(self.scope, self.artifact_kind)
        _validate_artifact_layer(self.artifact_kind, self.layer)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "identity_schema_version": self.identity_schema_version,
            "scope": self.scope.to_json_dict(),
            "partition_id": self.partition_id,
            "artifact_kind": self.artifact_kind,
            "layer": self.layer,
            "producer_protocol_version": self.producer_protocol_version,
            "layer_policy_hash": self.layer_policy_hash,
            "dependency_hashes": list(self.dependency_hashes),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ArtifactKeyV2":
        raw = exact_object(value, frozenset(cls.FIELDS), "ArtifactKeyV2")
        return cls(
            identity_schema_version=raw["identity_schema_version"],
            scope=ArtifactScope.from_json_dict(raw["scope"]),
            partition_id=raw["partition_id"],
            artifact_kind=raw["artifact_kind"],
            layer=raw["layer"],
            producer_protocol_version=raw["producer_protocol_version"],
            layer_policy_hash=raw["layer_policy_hash"],
            dependency_hashes=raw["dependency_hashes"],
        )


def _validate_work_contract_fields(value: object, label: str) -> None:
    one_of(getattr(value, "goal_id"), _GOALS, f"{label}.goal_id")
    safe_id(getattr(value, "producer_id"), f"{label}.producer_id")
    safe_id(getattr(value, "producer_family"), f"{label}.producer_family")
    safe_id(
        getattr(value, "producer_protocol_version"),
        f"{label}.producer_protocol_version",
    )
    digest_value(
        getattr(value, "executor_contract_hash"),
        f"{label}.executor_contract_hash",
    )
    safe_id(getattr(value, "verifier_id"), f"{label}.verifier_id")
    safe_id(getattr(value, "verifier_version"), f"{label}.verifier_version")
    digest_value(
        getattr(value, "verifier_implementation_digest"),
        f"{label}.verifier_implementation_digest",
    )
    safe_id(getattr(value, "result_contract_id"), f"{label}.result_contract_id")
    for field in WorkTemplateV2.ATTEMPT_FIELDS:
        nonnegative_int(getattr(value, field), f"{label}.{field}")


@dataclass(frozen=True, slots=True)
class WorkTemplateV2(_CanonicalIdentity):
    identity_schema_version: int
    goal_id: GoalV2
    scope: ArtifactScope
    artifact_kind: str
    layer: LayerV2
    producer_id: str
    producer_family: str
    producer_protocol_version: str
    layer_policy_hash: str
    required_template_ids: tuple[str, ...]
    executor_contract_hash: str
    verifier_id: str
    verifier_version: str
    verifier_implementation_digest: str
    result_contract_id: str
    max_provider_attempts: int
    max_generation_attempts: int
    max_semantic_rounds: int
    max_result_contract_retries: int
    max_shared_retries: int
    max_artifact_contract_retries: int

    ATTEMPT_FIELDS: ClassVar[tuple[str, ...]] = (
        "max_provider_attempts",
        "max_generation_attempts",
        "max_semantic_rounds",
        "max_result_contract_retries",
        "max_shared_retries",
        "max_artifact_contract_retries",
    )
    FIELDS: ClassVar[tuple[str, ...]] = (
        "identity_schema_version",
        "goal_id",
        "scope",
        "artifact_kind",
        "layer",
        "producer_id",
        "producer_family",
        "producer_protocol_version",
        "layer_policy_hash",
        "required_template_ids",
        "executor_contract_hash",
        "verifier_id",
        "verifier_version",
        "verifier_implementation_digest",
        "result_contract_id",
        *ATTEMPT_FIELDS,
    )

    def __post_init__(self) -> None:
        literal(
            self.identity_schema_version,
            2,
            "WorkTemplateV2.identity_schema_version",
        )
        if not isinstance(self.scope, ArtifactScope):
            raise Protocol22SchemaError("WorkTemplateV2.scope must be an ArtifactScope")
        safe_id(self.artifact_kind, "WorkTemplateV2.artifact_kind")
        one_of(self.layer, _LAYERS, "WorkTemplateV2.layer")
        digest_value(self.layer_policy_hash, "WorkTemplateV2.layer_policy_hash")
        object.__setattr__(
            self,
            "required_template_ids",
            sorted_unique_digests(
                self.required_template_ids,
                "WorkTemplateV2.required_template_ids",
            ),
        )
        _validate_work_contract_fields(self, "WorkTemplateV2")
        _validate_scope_for_artifact(self.scope, self.artifact_kind)
        _validate_artifact_layer(self.artifact_kind, self.layer)

    @property
    def template_id(self) -> str:
        return self.identity

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["scope"] = self.scope.to_json_dict()
        result["required_template_ids"] = list(self.required_template_ids)
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "WorkTemplateV2":
        raw = exact_object(value, frozenset(cls.FIELDS), "WorkTemplateV2")
        data = {field: raw[field] for field in cls.FIELDS}
        data["scope"] = ArtifactScope.from_json_dict(data["scope"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class WorkItemV2(_CanonicalIdentity):
    identity_schema_version: int
    template_id: str
    goal_id: GoalV2
    output_key: ArtifactKeyV2
    required_artifact_hashes: tuple[str, ...]
    producer_id: str
    producer_family: str
    producer_protocol_version: str
    executor_contract_hash: str
    verifier_id: str
    verifier_version: str
    verifier_implementation_digest: str
    result_contract_id: str
    max_provider_attempts: int
    max_generation_attempts: int
    max_semantic_rounds: int
    max_result_contract_retries: int
    max_shared_retries: int
    max_artifact_contract_retries: int

    COPIED_TEMPLATE_FIELDS: ClassVar[tuple[str, ...]] = (
        "goal_id",
        "producer_id",
        "producer_family",
        "producer_protocol_version",
        "executor_contract_hash",
        "verifier_id",
        "verifier_version",
        "verifier_implementation_digest",
        "result_contract_id",
        *WorkTemplateV2.ATTEMPT_FIELDS,
    )
    FIELDS: ClassVar[tuple[str, ...]] = (
        "identity_schema_version",
        "template_id",
        "goal_id",
        "output_key",
        "required_artifact_hashes",
        "producer_id",
        "producer_family",
        "producer_protocol_version",
        "executor_contract_hash",
        "verifier_id",
        "verifier_version",
        "verifier_implementation_digest",
        "result_contract_id",
        *WorkTemplateV2.ATTEMPT_FIELDS,
    )

    def __post_init__(self) -> None:
        literal(self.identity_schema_version, 2, "WorkItemV2.identity_schema_version")
        digest_value(self.template_id, "WorkItemV2.template_id")
        if not isinstance(self.output_key, ArtifactKeyV2):
            raise Protocol22SchemaError(
                "WorkItemV2.output_key must be an ArtifactKeyV2"
            )
        object.__setattr__(
            self,
            "required_artifact_hashes",
            sorted_unique_digests(
                self.required_artifact_hashes,
                "WorkItemV2.required_artifact_hashes",
            ),
        )
        if self.required_artifact_hashes != self.output_key.dependency_hashes:
            raise Protocol22SchemaError(
                "WorkItemV2.required_artifact_hashes must equal output_key.dependency_hashes"
            )
        _validate_work_contract_fields(self, "WorkItemV2")

    @property
    def work_item_id(self) -> str:
        return self.identity

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["output_key"] = self.output_key.to_json_dict()
        result["required_artifact_hashes"] = list(self.required_artifact_hashes)
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "WorkItemV2":
        raw = exact_object(value, frozenset(cls.FIELDS), "WorkItemV2")
        data = {field: raw[field] for field in cls.FIELDS}
        data["output_key"] = ArtifactKeyV2.from_json_dict(data["output_key"])
        return cls(**data)


def instantiate_work_item_v2(
    template: WorkTemplateV2,
    output_key: ArtifactKeyV2,
    dependency_hashes: object,
) -> WorkItemV2:
    if not isinstance(template, WorkTemplateV2):
        raise Protocol22SchemaError("template must be a WorkTemplateV2")
    if not isinstance(output_key, ArtifactKeyV2):
        raise Protocol22SchemaError("output_key must be an ArtifactKeyV2")
    dependencies = sorted_unique_digests(dependency_hashes, "dependency_hashes")
    expected_key_fields = {
        "scope": template.scope,
        "artifact_kind": template.artifact_kind,
        "layer": template.layer,
        "producer_protocol_version": template.producer_protocol_version,
        "layer_policy_hash": template.layer_policy_hash,
        "dependency_hashes": dependencies,
    }
    for field, expected in expected_key_fields.items():
        if getattr(output_key, field) != expected:
            raise Protocol22SchemaError(
                f"output_key.{field} does not match WorkTemplateV2.{field}"
            )
    copied = {
        field: getattr(template, field) for field in WorkItemV2.COPIED_TEMPLATE_FIELDS
    }
    return WorkItemV2(
        identity_schema_version=2,
        template_id=template.template_id,
        output_key=output_key,
        required_artifact_hashes=dependencies,
        **copied,
    )


@dataclass(frozen=True, slots=True)
class ProviderMessageV1:
    role: Literal["system", "user"]
    content_utf8: str

    FIELDS: ClassVar[tuple[str, ...]] = ("role", "content_utf8")

    def __post_init__(self) -> None:
        one_of(self.role, frozenset({"system", "user"}), "ProviderMessageV1.role")
        text_value(self.content_utf8, "ProviderMessageV1.content_utf8")

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ProviderMessageV1":
        raw = exact_object(value, frozenset(cls.FIELDS), "ProviderMessageV1")
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class RetryDiagnosticsV1:
    """Closed controller-owned diagnostics supplied only to one shared retry."""

    schema_version: int
    diagnostics: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = ("schema_version", "diagnostics")

    def __post_init__(self) -> None:
        literal(self.schema_version, 1, "RetryDiagnosticsV1.schema_version")
        if not isinstance(self.diagnostics, (list, tuple)):
            raise Protocol22SchemaError(
                "RetryDiagnosticsV1.diagnostics must be an array"
            )
        values = tuple(self.diagnostics)
        if not values or len(values) > 64 or values != tuple(sorted(set(values))):
            raise Protocol22SchemaError(
                "RetryDiagnosticsV1.diagnostics must be nonempty, sorted, and unique"
            )
        for value in values:
            if (
                not isinstance(value, str)
                or not value
                or value.strip() != value
                or "\r" in value
                or len(value.encode("utf-8")) > 1024
            ):
                raise Protocol22SchemaError(
                    "RetryDiagnosticsV1 contains an invalid diagnostic"
                )
        object.__setattr__(self, "diagnostics", values)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "diagnostics": list(self.diagnostics),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "RetryDiagnosticsV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(raw["schema_version"], raw["diagnostics"])


@dataclass(frozen=True, slots=True)
class ProviderResponseFormatV1:
    kind: Literal["json_schema"]
    schema_name: Literal["echelon_compact_baseline_v1"]
    strict: bool
    schema_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "kind",
        "schema_name",
        "strict",
        "schema_hash",
    )

    def __post_init__(self) -> None:
        literal(self.kind, "json_schema", "ProviderResponseFormatV1.kind")
        literal(
            self.schema_name,
            "echelon_compact_baseline_v1",
            "ProviderResponseFormatV1.schema_name",
        )
        literal(self.strict, True, "ProviderResponseFormatV1.strict")
        digest_value(self.schema_hash, "ProviderResponseFormatV1.schema_hash")

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ProviderResponseFormatV1":
        raw = exact_object(value, frozenset(cls.FIELDS), "ProviderResponseFormatV1")
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ProviderGenerationV1:
    temperature_micros: int
    top_p_micros: int
    seed: int | None
    max_completion_tokens: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "temperature_micros",
        "top_p_micros",
        "seed",
        "max_completion_tokens",
    )

    def __post_init__(self) -> None:
        bounded_int(
            self.temperature_micros,
            "ProviderGenerationV1.temperature_micros",
            minimum=0,
            maximum=2_000_000,
        )
        bounded_int(
            self.top_p_micros,
            "ProviderGenerationV1.top_p_micros",
            minimum=0,
            maximum=1_000_000,
        )
        integer_or_none(self.seed, "ProviderGenerationV1.seed")
        positive_int(
            self.max_completion_tokens,
            "ProviderGenerationV1.max_completion_tokens",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ProviderGenerationV1":
        raw = exact_object(value, frozenset(cls.FIELDS), "ProviderGenerationV1")
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ProviderRequestEnvelopeV1(_CanonicalIdentity):
    schema_version: int
    dispatch_id: str
    work_item_id: str
    executor_contract_hash: str
    target_artifact_kind: Literal["domain-baseline", "source-overview"]
    provider_id: str
    model_id: str
    model_revision: str
    reasoning_effort: str | None
    messages: tuple[ProviderMessageV1, ...]
    response_format: ProviderResponseFormatV1
    generation: ProviderGenerationV1
    tools: tuple[object, ...]
    tool_choice: Literal["none"]
    stream: bool

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "dispatch_id",
        "work_item_id",
        "executor_contract_hash",
        "target_artifact_kind",
        "provider_id",
        "model_id",
        "model_revision",
        "reasoning_effort",
        "messages",
        "response_format",
        "generation",
        "tools",
        "tool_choice",
        "stream",
    )

    def __post_init__(self) -> None:
        literal(self.schema_version, 1, "ProviderRequestEnvelopeV1.schema_version")
        safe_id(self.dispatch_id, "ProviderRequestEnvelopeV1.dispatch_id")
        digest_value(self.work_item_id, "ProviderRequestEnvelopeV1.work_item_id")
        digest_value(
            self.executor_contract_hash,
            "ProviderRequestEnvelopeV1.executor_contract_hash",
        )
        one_of(
            self.target_artifact_kind,
            frozenset({"domain-baseline", "source-overview"}),
            "ProviderRequestEnvelopeV1.target_artifact_kind",
        )
        safe_id(self.provider_id, "ProviderRequestEnvelopeV1.provider_id")
        text_value(self.model_id, "ProviderRequestEnvelopeV1.model_id")
        text_value(self.model_revision, "ProviderRequestEnvelopeV1.model_revision")
        optional_text(
            self.reasoning_effort, "ProviderRequestEnvelopeV1.reasoning_effort"
        )
        if not isinstance(self.messages, (list, tuple)) or any(
            not isinstance(message, ProviderMessageV1) for message in self.messages
        ):
            raise Protocol22SchemaError(
                "ProviderRequestEnvelopeV1.messages must contain ProviderMessageV1 values"
            )
        object.__setattr__(self, "messages", tuple(self.messages))
        roles = tuple(message.role for message in self.messages)
        if roles not in {("system", "user"), ("system", "user", "user")}:
            raise Protocol22SchemaError(
                "ProviderRequestEnvelopeV1.messages must contain system then user context and optional user retry diagnostics"
            )
        if len(self.messages) == 3:
            diagnostics_bytes = self.messages[2].content_utf8.encode("utf-8")
            diagnostics = load_canonical_object(
                diagnostics_bytes,
                RetryDiagnosticsV1.from_json_dict,
            )
            if canonical_json_bytes(diagnostics.to_json_dict()) != diagnostics_bytes:
                raise Protocol22SchemaError(
                    "retry diagnostics message must be canonical JSON bytes"
                )
        if not isinstance(self.response_format, ProviderResponseFormatV1):
            raise Protocol22SchemaError(
                "ProviderRequestEnvelopeV1.response_format must be ProviderResponseFormatV1"
            )
        if not isinstance(self.generation, ProviderGenerationV1):
            raise Protocol22SchemaError(
                "ProviderRequestEnvelopeV1.generation must be ProviderGenerationV1"
            )
        if not isinstance(self.tools, (list, tuple)) or tuple(self.tools) != ():
            raise Protocol22SchemaError("ProviderRequestEnvelopeV1.tools must be empty")
        object.__setattr__(self, "tools", ())
        literal(self.tool_choice, "none", "ProviderRequestEnvelopeV1.tool_choice")
        literal(self.stream, False, "ProviderRequestEnvelopeV1.stream")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dispatch_id": self.dispatch_id,
            "work_item_id": self.work_item_id,
            "executor_contract_hash": self.executor_contract_hash,
            "target_artifact_kind": self.target_artifact_kind,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "reasoning_effort": self.reasoning_effort,
            "messages": [message.to_json_dict() for message in self.messages],
            "response_format": self.response_format.to_json_dict(),
            "generation": self.generation.to_json_dict(),
            "tools": [],
            "tool_choice": self.tool_choice,
            "stream": self.stream,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ProviderRequestEnvelopeV1":
        raw = exact_object(value, frozenset(cls.FIELDS), "ProviderRequestEnvelopeV1")
        messages = raw["messages"]
        if not isinstance(messages, (list, tuple)):
            raise Protocol22SchemaError(
                "ProviderRequestEnvelopeV1.messages must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            dispatch_id=raw["dispatch_id"],
            work_item_id=raw["work_item_id"],
            executor_contract_hash=raw["executor_contract_hash"],
            target_artifact_kind=raw["target_artifact_kind"],
            provider_id=raw["provider_id"],
            model_id=raw["model_id"],
            model_revision=raw["model_revision"],
            reasoning_effort=raw["reasoning_effort"],
            messages=tuple(ProviderMessageV1.from_json_dict(item) for item in messages),
            response_format=ProviderResponseFormatV1.from_json_dict(
                raw["response_format"]
            ),
            generation=ProviderGenerationV1.from_json_dict(raw["generation"]),
            tools=raw["tools"],
            tool_choice=raw["tool_choice"],
            stream=raw["stream"],
        )


@dataclass(frozen=True, slots=True)
class DeterministicInvocationInputV1:
    role: str
    object_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = ("role", "object_hash")

    def __post_init__(self) -> None:
        safe_id(self.role, "DeterministicInvocationInputV1.role")
        digest_value(self.object_hash, "DeterministicInvocationInputV1.object_hash")

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "DeterministicInvocationInputV1":
        raw = exact_object(
            value,
            frozenset(cls.FIELDS),
            "DeterministicInvocationInputV1",
        )
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class DeterministicInvocationV1(_CanonicalIdentity):
    schema_version: int
    producer_family: str
    output_key: ArtifactKeyV2
    artifact_policy_hash: str
    inputs: tuple[DeterministicInvocationInputV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "producer_family",
        "output_key",
        "artifact_policy_hash",
        "inputs",
    )

    def __post_init__(self) -> None:
        literal(self.schema_version, 1, "DeterministicInvocationV1.schema_version")
        safe_id(self.producer_family, "DeterministicInvocationV1.producer_family")
        if not isinstance(self.output_key, ArtifactKeyV2):
            raise Protocol22SchemaError(
                "DeterministicInvocationV1.output_key must be an ArtifactKeyV2"
            )
        digest_value(
            self.artifact_policy_hash,
            "DeterministicInvocationV1.artifact_policy_hash",
        )
        if self.artifact_policy_hash != self.output_key.layer_policy_hash:
            raise Protocol22SchemaError(
                "DeterministicInvocationV1.artifact_policy_hash must match output_key"
            )
        if not isinstance(self.inputs, (list, tuple)) or any(
            not isinstance(item, DeterministicInvocationInputV1) for item in self.inputs
        ):
            raise Protocol22SchemaError(
                "DeterministicInvocationV1.inputs must contain invocation inputs"
            )
        object.__setattr__(self, "inputs", tuple(self.inputs))
        roles = tuple(item.role for item in self.inputs)
        if roles != tuple(sorted(set(roles))):
            raise Protocol22SchemaError(
                "DeterministicInvocationV1.inputs must be sorted and unique by role"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_family": self.producer_family,
            "output_key": self.output_key.to_json_dict(),
            "artifact_policy_hash": self.artifact_policy_hash,
            "inputs": [item.to_json_dict() for item in self.inputs],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "DeterministicInvocationV1":
        raw = exact_object(value, frozenset(cls.FIELDS), "DeterministicInvocationV1")
        inputs = raw["inputs"]
        if not isinstance(inputs, (list, tuple)):
            raise Protocol22SchemaError(
                "DeterministicInvocationV1.inputs must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            producer_family=raw["producer_family"],
            output_key=ArtifactKeyV2.from_json_dict(raw["output_key"]),
            artifact_policy_hash=raw["artifact_policy_hash"],
            inputs=tuple(
                DeterministicInvocationInputV1.from_json_dict(item) for item in inputs
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutionInputV1(_CanonicalIdentity):
    schema_version: int
    dispatch_id: str
    work_item_id: str
    attempt_kind: AttemptKindV2
    executor_contract_hash: str
    agent_contract_hash: str | None
    context_bundle_hash: str | None
    provider_request_envelope_hash: str | None
    deterministic_invocation: DeterministicInvocationV1 | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "dispatch_id",
        "work_item_id",
        "attempt_kind",
        "executor_contract_hash",
        "agent_contract_hash",
        "context_bundle_hash",
        "provider_request_envelope_hash",
        "deterministic_invocation",
    )

    def __post_init__(self) -> None:
        literal(self.schema_version, 1, "ExecutionInputV1.schema_version")
        safe_id(self.dispatch_id, "ExecutionInputV1.dispatch_id")
        digest_value(self.work_item_id, "ExecutionInputV1.work_item_id")
        one_of(self.attempt_kind, _ATTEMPT_KINDS, "ExecutionInputV1.attempt_kind")
        digest_value(
            self.executor_contract_hash,
            "ExecutionInputV1.executor_contract_hash",
        )
        optional_digest(
            self.agent_contract_hash, "ExecutionInputV1.agent_contract_hash"
        )
        optional_digest(
            self.context_bundle_hash, "ExecutionInputV1.context_bundle_hash"
        )
        optional_digest(
            self.provider_request_envelope_hash,
            "ExecutionInputV1.provider_request_envelope_hash",
        )
        if self.deterministic_invocation is not None and not isinstance(
            self.deterministic_invocation, DeterministicInvocationV1
        ):
            raise Protocol22SchemaError(
                "ExecutionInputV1.deterministic_invocation must be an invocation or null"
            )
        provider_branch = (
            self.agent_contract_hash is not None
            and self.context_bundle_hash is not None
            and self.deterministic_invocation is None
        )
        deterministic_branch = (
            self.deterministic_invocation is not None
            and self.agent_contract_hash is None
            and self.context_bundle_hash is None
            and self.provider_request_envelope_hash is None
        )
        if provider_branch == deterministic_branch:
            raise Protocol22SchemaError(
                "ExecutionInputV1 must populate exactly one provider or deterministic branch"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dispatch_id": self.dispatch_id,
            "work_item_id": self.work_item_id,
            "attempt_kind": self.attempt_kind,
            "executor_contract_hash": self.executor_contract_hash,
            "agent_contract_hash": self.agent_contract_hash,
            "context_bundle_hash": self.context_bundle_hash,
            "provider_request_envelope_hash": self.provider_request_envelope_hash,
            "deterministic_invocation": (
                None
                if self.deterministic_invocation is None
                else self.deterministic_invocation.to_json_dict()
            ),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExecutionInputV1":
        raw = exact_object(value, frozenset(cls.FIELDS), "ExecutionInputV1")
        invocation = raw["deterministic_invocation"]
        return cls(
            schema_version=raw["schema_version"],
            dispatch_id=raw["dispatch_id"],
            work_item_id=raw["work_item_id"],
            attempt_kind=raw["attempt_kind"],
            executor_contract_hash=raw["executor_contract_hash"],
            agent_contract_hash=raw["agent_contract_hash"],
            context_bundle_hash=raw["context_bundle_hash"],
            provider_request_envelope_hash=raw["provider_request_envelope_hash"],
            deterministic_invocation=(
                None
                if invocation is None
                else DeterministicInvocationV1.from_json_dict(invocation)
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutionCaptureV1(_CanonicalIdentity):
    schema_version: int
    dispatch_id: str
    work_item_id: str
    execution_input_hash: str
    executor_contract_hash: str
    execution_mode: Literal["in_process", "api", "cli"]
    result_kind: Literal["provider_candidate", "deterministic_artifact", "none"]
    candidate_inventory_hash: str | None
    deterministic_artifact_hash: str | None
    stdout_digest: str
    stdout_blob_hash: str
    stdout_byte_count: int
    stdout_retained_byte_count: int
    stdout_capture: Literal["complete", "terminal_tail"]
    stderr_digest: str | None
    provider_usage_blob_hash: str | None
    started_at: str
    ended_at: str
    duration_ms: int
    exit_code: int | None
    timed_out: bool
    output_truncated: bool
    provider_name: str
    resolved_model_revision: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "dispatch_id",
        "work_item_id",
        "execution_input_hash",
        "executor_contract_hash",
        "execution_mode",
        "result_kind",
        "candidate_inventory_hash",
        "deterministic_artifact_hash",
        "stdout_digest",
        "stdout_blob_hash",
        "stdout_byte_count",
        "stdout_retained_byte_count",
        "stdout_capture",
        "stderr_digest",
        "provider_usage_blob_hash",
        "started_at",
        "ended_at",
        "duration_ms",
        "exit_code",
        "timed_out",
        "output_truncated",
        "provider_name",
        "resolved_model_revision",
    )

    def __post_init__(self) -> None:
        literal(self.schema_version, 1, "ExecutionCaptureV1.schema_version")
        safe_id(self.dispatch_id, "ExecutionCaptureV1.dispatch_id")
        digest_value(self.work_item_id, "ExecutionCaptureV1.work_item_id")
        digest_value(
            self.execution_input_hash, "ExecutionCaptureV1.execution_input_hash"
        )
        digest_value(
            self.executor_contract_hash,
            "ExecutionCaptureV1.executor_contract_hash",
        )
        one_of(
            self.execution_mode,
            frozenset({"in_process", "api", "cli"}),
            "ExecutionCaptureV1.execution_mode",
        )
        one_of(
            self.result_kind,
            frozenset({"provider_candidate", "deterministic_artifact", "none"}),
            "ExecutionCaptureV1.result_kind",
        )
        optional_digest(
            self.candidate_inventory_hash,
            "ExecutionCaptureV1.candidate_inventory_hash",
        )
        optional_digest(
            self.deterministic_artifact_hash,
            "ExecutionCaptureV1.deterministic_artifact_hash",
        )
        digest_value(self.stdout_digest, "ExecutionCaptureV1.stdout_digest")
        digest_value(self.stdout_blob_hash, "ExecutionCaptureV1.stdout_blob_hash")
        nonnegative_int(self.stdout_byte_count, "ExecutionCaptureV1.stdout_byte_count")
        nonnegative_int(
            self.stdout_retained_byte_count,
            "ExecutionCaptureV1.stdout_retained_byte_count",
        )
        one_of(
            self.stdout_capture,
            frozenset({"complete", "terminal_tail"}),
            "ExecutionCaptureV1.stdout_capture",
        )
        if self.stdout_capture == "complete":
            if (
                self.stdout_retained_byte_count != self.stdout_byte_count
                or self.stdout_blob_hash != self.stdout_digest
                or self.output_truncated
            ):
                raise Protocol22SchemaError(
                    "complete stdout capture requires complete matching stdout blob authority"
                )
        elif (
            self.stdout_retained_byte_count >= self.stdout_byte_count
            or not self.output_truncated
        ):
            raise Protocol22SchemaError(
                "terminal-tail stdout requires a smaller retained tail and truncation"
            )
        optional_digest(self.stderr_digest, "ExecutionCaptureV1.stderr_digest")
        optional_digest(
            self.provider_usage_blob_hash,
            "ExecutionCaptureV1.provider_usage_blob_hash",
        )
        utc_timestamp(self.started_at, "ExecutionCaptureV1.started_at")
        utc_timestamp(self.ended_at, "ExecutionCaptureV1.ended_at")
        nonnegative_int(self.duration_ms, "ExecutionCaptureV1.duration_ms")
        integer_or_none(self.exit_code, "ExecutionCaptureV1.exit_code")
        boolean(self.timed_out, "ExecutionCaptureV1.timed_out")
        boolean(self.output_truncated, "ExecutionCaptureV1.output_truncated")
        safe_id(self.provider_name, "ExecutionCaptureV1.provider_name")
        optional_text(
            self.resolved_model_revision,
            "ExecutionCaptureV1.resolved_model_revision",
        )
        if self.execution_mode in {"api", "cli"}:
            if (
                self.result_kind != "provider_candidate"
                or self.candidate_inventory_hash is None
                or self.deterministic_artifact_hash is not None
            ):
                raise Protocol22SchemaError(
                    "provider execution requires candidate_inventory_hash"
                )
            if self.execution_mode == "api" and self.resolved_model_revision is None:
                raise Protocol22SchemaError(
                    "api execution requires a resolved model revision"
                )
        elif (
            self.candidate_inventory_hash is not None
            or self.provider_usage_blob_hash is not None
            or self.resolved_model_revision is not None
            or self.result_kind not in {"deterministic_artifact", "none"}
            or (
                self.result_kind == "deterministic_artifact"
                and self.deterministic_artifact_hash is None
            )
            or (
                self.result_kind == "none"
                and self.deterministic_artifact_hash is not None
            )
        ):
            raise Protocol22SchemaError(
                "in_process execution requires the deterministic result branch"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ExecutionCaptureV1":
        raw = exact_object(value, frozenset(cls.FIELDS), "ExecutionCaptureV1")
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ExecutionCaptureCommitV1(_CanonicalIdentity):
    schema_version: int
    dispatch_id: str
    work_item_id: str
    execution_input_hash: str
    execution_capture_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "dispatch_id",
        "work_item_id",
        "execution_input_hash",
        "execution_capture_hash",
    )

    def __post_init__(self) -> None:
        literal(self.schema_version, 1, "ExecutionCaptureCommitV1.schema_version")
        safe_id(self.dispatch_id, "ExecutionCaptureCommitV1.dispatch_id")
        digest_value(self.work_item_id, "ExecutionCaptureCommitV1.work_item_id")
        digest_value(
            self.execution_input_hash,
            "ExecutionCaptureCommitV1.execution_input_hash",
        )
        digest_value(
            self.execution_capture_hash,
            "ExecutionCaptureCommitV1.execution_capture_hash",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ExecutionCaptureCommitV1":
        raw = exact_object(value, frozenset(cls.FIELDS), "ExecutionCaptureCommitV1")
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class PersistedCandidateV2(_CanonicalIdentity):
    schema_version: int
    dispatch_id: str
    work_item_id: str
    execution_capture_hash: str
    candidate_inventory_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "dispatch_id",
        "work_item_id",
        "execution_capture_hash",
        "candidate_inventory_hash",
    )

    def __post_init__(self) -> None:
        literal(self.schema_version, 2, "PersistedCandidateV2.schema_version")
        safe_id(self.dispatch_id, "PersistedCandidateV2.dispatch_id")
        digest_value(self.work_item_id, "PersistedCandidateV2.work_item_id")
        digest_value(
            self.execution_capture_hash,
            "PersistedCandidateV2.execution_capture_hash",
        )
        digest_value(
            self.candidate_inventory_hash,
            "PersistedCandidateV2.candidate_inventory_hash",
        )

    @property
    def candidate_id(self) -> str:
        return self.identity

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "PersistedCandidateV2":
        raw = exact_object(value, frozenset(cls.FIELDS), "PersistedCandidateV2")
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class RunManifestV2(_CanonicalIdentity):
    schema_version: int
    engine: Literal["re-v2"]
    engine_protocol_version: Literal["2.2", "2.3"]
    run_id: str
    created_at: str
    source_snapshot_id: str
    source_snapshot_kind: Literal["workspace-git-composite"]
    partition_manifest_id: str
    workspace_partition_catalog: CatalogReferenceV1
    artifact_policy_catalog: CatalogReferenceV1
    executor_contract_catalog: CatalogReferenceV1
    requested_goals: tuple[GoalV2, ...]
    initial_budget_policy: BudgetPolicyV2
    parent_run_id: None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "engine",
        "engine_protocol_version",
        "run_id",
        "created_at",
        "source_snapshot_id",
        "source_snapshot_kind",
        "partition_manifest_id",
        "workspace_partition_catalog",
        "artifact_policy_catalog",
        "executor_contract_catalog",
        "requested_goals",
        "initial_budget_policy",
        "parent_run_id",
    )

    def __post_init__(self) -> None:
        literal(self.schema_version, 2, "RunManifestV2.schema_version")
        literal(self.engine, "re-v2", "RunManifestV2.engine")
        one_of(
            self.engine_protocol_version,
            frozenset(RE_V2_SCHEMA_2_PROTOCOLS),
            "RunManifestV2.engine_protocol_version",
        )
        safe_id(self.run_id, "RunManifestV2.run_id")
        utc_timestamp(self.created_at, "RunManifestV2.created_at")
        digest_value(self.source_snapshot_id, "RunManifestV2.source_snapshot_id")
        literal(
            self.source_snapshot_kind,
            "workspace-git-composite",
            "RunManifestV2.source_snapshot_kind",
        )
        digest_value(
            self.partition_manifest_id,
            "RunManifestV2.partition_manifest_id",
        )
        references = (
            self.workspace_partition_catalog,
            self.artifact_policy_catalog,
            self.executor_contract_catalog,
        )
        if any(
            not isinstance(reference, CatalogReferenceV1) for reference in references
        ):
            raise Protocol22SchemaError(
                "RunManifestV2 catalog references must be CatalogReferenceV1 values"
            )
        if (
            len({reference.relative_path for reference in references}) != 3
            or len({reference.object_hash for reference in references}) != 3
        ):
            raise Protocol22SchemaError(
                "RunManifestV2 catalog references must be three distinct references"
            )
        if not isinstance(self.requested_goals, (list, tuple)):
            raise Protocol22SchemaError(
                "RunManifestV2.requested_goals must be an array"
            )
        goals = tuple(self.requested_goals)
        if goals not in {("baseline",), ("inventory",)}:
            raise Protocol22SchemaError(
                "RunManifestV2.requested_goals must be exactly baseline or inventory"
            )
        object.__setattr__(self, "requested_goals", goals)
        if not isinstance(self.initial_budget_policy, BudgetPolicyV2):
            raise Protocol22SchemaError(
                "RunManifestV2.initial_budget_policy must be a BudgetPolicyV2"
            )
        if not self.initial_budget_policy.matches_goal(goals[0]):
            raise Protocol22SchemaError(
                "RunManifestV2 budget policy does not match the selected goal"
            )
        literal(self.parent_run_id, None, "RunManifestV2.parent_run_id")

    @property
    def run_manifest_id(self) -> str:
        return self.identity

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "engine": self.engine,
            "engine_protocol_version": self.engine_protocol_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_kind": self.source_snapshot_kind,
            "partition_manifest_id": self.partition_manifest_id,
            "workspace_partition_catalog": self.workspace_partition_catalog.to_json_dict(),
            "artifact_policy_catalog": self.artifact_policy_catalog.to_json_dict(),
            "executor_contract_catalog": self.executor_contract_catalog.to_json_dict(),
            "requested_goals": list(self.requested_goals),
            "initial_budget_policy": self.initial_budget_policy.to_json_dict(),
            "parent_run_id": self.parent_run_id,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "RunManifestV2":
        raw = exact_object(value, frozenset(cls.FIELDS), "RunManifestV2")
        return cls(
            schema_version=raw["schema_version"],
            engine=raw["engine"],
            engine_protocol_version=raw["engine_protocol_version"],
            run_id=raw["run_id"],
            created_at=raw["created_at"],
            source_snapshot_id=raw["source_snapshot_id"],
            source_snapshot_kind=raw["source_snapshot_kind"],
            partition_manifest_id=raw["partition_manifest_id"],
            workspace_partition_catalog=CatalogReferenceV1.from_json_dict(
                raw["workspace_partition_catalog"]
            ),
            artifact_policy_catalog=CatalogReferenceV1.from_json_dict(
                raw["artifact_policy_catalog"]
            ),
            executor_contract_catalog=CatalogReferenceV1.from_json_dict(
                raw["executor_contract_catalog"]
            ),
            requested_goals=raw["requested_goals"],
            initial_budget_policy=BudgetPolicyV2.from_json_dict(
                raw["initial_budget_policy"]
            ),
            parent_run_id=raw["parent_run_id"],
        )


__all__ = (
    "ArtifactKeyV2",
    "ArtifactScope",
    "AttemptKindV2",
    "BudgetPolicyV2",
    "CatalogReferenceV1",
    "DeterministicInvocationInputV1",
    "DeterministicInvocationV1",
    "ExecutionCaptureCommitV1",
    "ExecutionCaptureV1",
    "ExecutionInputV1",
    "GoalV2",
    "LayerV2",
    "PersistedCandidateV2",
    "ProviderGenerationV1",
    "ProviderMessageV1",
    "ProviderRequestEnvelopeV1",
    "ProviderResponseFormatV1",
    "RetryDiagnosticsV1",
    "RunManifestV2",
    "WorkItemV2",
    "WorkTemplateV2",
    "instantiate_work_item_v2",
)

"""Closed protocol-2.7 workspace-synthesis authority values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    nonnegative_int,
    one_of,
    optional_digest,
    positive_int,
    safe_id,
    sorted_unique_digests,
    utc_timestamp,
)


SourceOutcomeV1 = Literal["complete", "partial"]
SynthesisScopeKindV1 = Literal["source", "workspace-domain", "workspace"]
InputQualityV1 = Literal["complete", "partial"]

_SOURCE_OUTCOMES = frozenset({"complete", "partial"})
_SCOPE_KINDS = frozenset({"source", "workspace-domain", "workspace"})
_INPUT_QUALITIES = frozenset({"complete", "partial"})
_LAYERS = frozenset({"L1", "L2", "L3"})


class Protocol27SchemaError(Protocol22SchemaError):
    """Raised when protocol-2.7 authority violates its closed schema."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol27SchemaError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol27SchemaError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(canonical_json_bytes(value))


def _optional_safe_id(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _schema(safe_id, value, field)


def _optional_positive(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _schema(positive_int, value, field)


def _sorted_unique_ids(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol27SchemaError(f"{field} must be an array")
    result = tuple(_schema(safe_id, item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise Protocol27SchemaError(f"{field} must be sorted and unique")
    return result


def _typed_tuple(
    value: object,
    expected: type,
    field: str,
    *,
    identity_attribute: str = "identity",
    sort_attribute: str | None = None,
) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, expected) for item in value
    ):
        raise Protocol27SchemaError(
            f"{field} must be an array of {expected.__name__} values"
        )
    result = tuple(value)
    identities = tuple(getattr(item, identity_attribute) for item in result)
    if len(identities) != len(set(identities)):
        raise Protocol27SchemaError(f"{field} must be unique")
    sort_keys = (
        tuple(getattr(item, sort_attribute) for item in result)
        if sort_attribute is not None
        else identities
    )
    if sort_keys != tuple(sorted(sort_keys)):
        raise Protocol27SchemaError(f"{field} must be canonically sorted")
    return result


@dataclass(frozen=True, slots=True)
class AcceptedSourceOutcomeV1:
    schema_version: int
    source_id: str
    source_root_key_id: str
    source_root_hash: str
    outcome: SourceOutcomeV1
    debt_manifest_hash: str | None
    lower_authority_ids: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "source_id",
        "source_root_key_id",
        "source_root_hash",
        "outcome",
        "debt_manifest_hash",
        "lower_authority_ids",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(safe_id, self.source_id, f"{label}.source_id")
        _schema(digest_value, self.source_root_key_id, f"{label}.source_root_key_id")
        _schema(digest_value, self.source_root_hash, f"{label}.source_root_hash")
        outcome = _schema(one_of, self.outcome, _SOURCE_OUTCOMES, f"{label}.outcome")
        debt = _schema(
            optional_digest,
            self.debt_manifest_hash,
            f"{label}.debt_manifest_hash",
        )
        if outcome == "partial" and debt is None:
            raise Protocol27SchemaError("partial source outcome requires debt authority")
        if outcome == "complete" and debt is not None:
            raise Protocol27SchemaError("complete source outcome must not carry debt")
        object.__setattr__(
            self,
            "lower_authority_ids",
            _schema(
                sorted_unique_digests,
                self.lower_authority_ids,
                f"{label}.lower_authority_ids",
            ),
        )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "source_root_key_id": self.source_root_key_id,
            "source_root_hash": self.source_root_hash,
            "outcome": self.outcome,
            "debt_manifest_hash": self.debt_manifest_hash,
            "lower_authority_ids": list(self.lower_authority_ids),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "AcceptedSourceOutcomeV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class AcceptedSourceOverviewProjectionV1:
    schema_version: int
    source_id: str
    selected_layer: Literal["L1", "L2", "L3"]
    source_root_key_id: str
    source_root_hash: str
    materializer_protocol_version: str
    materializer_authority_hash: str
    content_hash: str
    object_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "source_id",
        "selected_layer",
        "source_root_key_id",
        "source_root_hash",
        "materializer_protocol_version",
        "materializer_authority_hash",
        "content_hash",
        "object_hash",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(safe_id, self.source_id, f"{label}.source_id")
        _schema(one_of, self.selected_layer, _LAYERS, f"{label}.selected_layer")
        _schema(safe_id, self.materializer_protocol_version, f"{label}.materializer_protocol_version")
        for field in (
            "source_root_key_id",
            "source_root_hash",
            "materializer_authority_hash",
            "content_hash",
            "object_hash",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        if self.content_hash != self.object_hash:
            raise Protocol27SchemaError(
                "AcceptedSourceOverviewProjectionV1 content_hash and object_hash must match"
            )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "AcceptedSourceOverviewProjectionV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class AcceptedSourceOverviewCatalogV1:
    schema_version: int
    projections: tuple[AcceptedSourceOverviewProjectionV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = ("schema_version", "projections")

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "AcceptedSourceOverviewCatalogV1.schema_version")
        projections = _typed_tuple(
            self.projections,
            AcceptedSourceOverviewProjectionV1,
            "AcceptedSourceOverviewCatalogV1.projections",
            sort_attribute="source_id",
        )
        source_ids = tuple(item.source_id for item in projections)
        if len(source_ids) != len(set(source_ids)):
            raise Protocol27SchemaError(
                "AcceptedSourceOverviewCatalogV1 source IDs must be unique"
            )
        object.__setattr__(self, "projections", projections)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "projections": [item.to_json_dict() for item in self.projections],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "AcceptedSourceOverviewCatalogV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        projections = raw["projections"]
        if not isinstance(projections, (list, tuple)):
            raise Protocol27SchemaError(
                "AcceptedSourceOverviewCatalogV1.projections must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            projections=tuple(
                AcceptedSourceOverviewProjectionV1.from_json_dict(item)
                for item in projections
            ),
        )


@dataclass(frozen=True, slots=True)
class SynthesisBudgetPolicyV1:
    schema_version: int
    token_limit: int | None
    active_ms_limit: int | None
    provider_attempt_limit: int
    generation_attempt_limit: int
    result_contract_retry_limit: int
    artifact_contract_retry_limit: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "token_limit",
        "active_ms_limit",
        "provider_attempt_limit",
        "generation_attempt_limit",
        "result_contract_retry_limit",
        "artifact_contract_retry_limit",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "SynthesisBudgetPolicyV1.schema_version")
        _optional_positive(self.token_limit, "SynthesisBudgetPolicyV1.token_limit")
        _optional_positive(self.active_ms_limit, "SynthesisBudgetPolicyV1.active_ms_limit")
        if (
            self.provider_attempt_limit,
            self.generation_attempt_limit,
            self.result_contract_retry_limit,
            self.artifact_contract_retry_limit,
        ) != (2, 2, 1, 1):
            raise Protocol27SchemaError(
                "SynthesisBudgetPolicyV1 requires the fixed bounded attempt policy (2, 2, 1, 1)"
            )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisBudgetPolicyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisRequestV1:
    schema_version: int
    parent_manifest_hash: str
    accepted_source_outcome_ids: tuple[str, ...]
    accepted_partial_source_ids: tuple[str, ...]
    budget_policy_hash: str
    expected_v2_index_hash: str
    expected_compatibility_generation: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "parent_manifest_hash",
        "accepted_source_outcome_ids",
        "accepted_partial_source_ids",
        "budget_policy_hash",
        "expected_v2_index_hash",
        "expected_compatibility_generation",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        for field in (
            "parent_manifest_hash",
            "budget_policy_hash",
            "expected_v2_index_hash",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        object.__setattr__(
            self,
            "accepted_source_outcome_ids",
            _schema(
                sorted_unique_digests,
                self.accepted_source_outcome_ids,
                f"{label}.accepted_source_outcome_ids",
            ),
        )
        object.__setattr__(
            self,
            "accepted_partial_source_ids",
            _sorted_unique_ids(
                self.accepted_partial_source_ids,
                f"{label}.accepted_partial_source_ids",
            ),
        )
        _schema(
            nonnegative_int,
            self.expected_compatibility_generation,
            f"{label}.expected_compatibility_generation",
        )

    @property
    def request_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.request_id

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "parent_manifest_hash": self.parent_manifest_hash,
            "accepted_source_outcome_ids": list(self.accepted_source_outcome_ids),
            "accepted_partial_source_ids": list(self.accepted_partial_source_ids),
            "budget_policy_hash": self.budget_policy_hash,
            "expected_v2_index_hash": self.expected_v2_index_hash,
            "expected_compatibility_generation": self.expected_compatibility_generation,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisRequestV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class PartialSourceAcceptanceV1:
    schema_version: int
    parent_run_id: str
    parent_manifest_hash: str
    source_id: str
    source_root_key_id: str
    source_root_hash: str
    debt_manifest_hash: str
    debt_summary_hash: str
    operation_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "parent_run_id",
        "parent_manifest_hash",
        "source_id",
        "source_root_key_id",
        "source_root_hash",
        "debt_manifest_hash",
        "debt_summary_hash",
        "operation_id",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(safe_id, self.parent_run_id, f"{label}.parent_run_id")
        _schema(safe_id, self.source_id, f"{label}.source_id")
        for field in (
            "parent_manifest_hash",
            "source_root_key_id",
            "source_root_hash",
            "debt_manifest_hash",
            "debt_summary_hash",
            "operation_id",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")

    @property
    def receipt_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.receipt_id

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "PartialSourceAcceptanceV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisScopeV1:
    schema_version: int
    kind: SynthesisScopeKindV1
    source_id: str | None
    workspace_domain_id: str | None
    participant_ids: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "kind",
        "source_id",
        "workspace_domain_id",
        "participant_ids",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        kind = _schema(one_of, self.kind, _SCOPE_KINDS, f"{label}.kind")
        source = _optional_safe_id(self.source_id, f"{label}.source_id")
        domain = _optional_safe_id(
            self.workspace_domain_id, f"{label}.workspace_domain_id"
        )
        participants = _sorted_unique_ids(
            self.participant_ids, f"{label}.participant_ids"
        )
        if kind == "source" and (
            source is None or domain is not None or participants != (source,)
        ):
            raise Protocol27SchemaError(
                "source synthesis scope requires one matching source participant"
            )
        if kind == "workspace-domain" and (
            source is not None or domain is None or not participants
        ):
            raise Protocol27SchemaError(
                "workspace-domain synthesis scope requires a domain and participants"
            )
        if kind == "workspace" and (
            source is not None or domain is not None or not participants
        ):
            raise Protocol27SchemaError(
                "workspace synthesis scope forbids source/domain IDs and requires participants"
            )
        object.__setattr__(self, "participant_ids", participants)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_id": self.source_id,
            "workspace_domain_id": self.workspace_domain_id,
            "participant_ids": list(self.participant_ids),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisScopeV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisArtifactDependencyV1:
    artifact_key_id: str
    artifact_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = ("artifact_key_id", "artifact_hash")

    def __post_init__(self) -> None:
        _schema(digest_value, self.artifact_key_id, "artifact_key_id")
        _schema(digest_value, self.artifact_hash, "artifact_hash")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisArtifactDependencyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisArtifactKeyV1:
    identity_schema_version: int
    scope: SynthesisScopeV1
    artifact_kind: str
    producer_protocol_version: str
    synthesis_policy_hash: str
    response_schema_hash: str
    context_policy_hash: str
    artifact_dependencies: tuple[SynthesisArtifactDependencyV1, ...]
    non_artifact_dependency_hashes: tuple[str, ...]
    debt_manifest_hashes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "identity_schema_version",
        "scope",
        "artifact_kind",
        "producer_protocol_version",
        "synthesis_policy_hash",
        "response_schema_hash",
        "context_policy_hash",
        "artifact_dependencies",
        "non_artifact_dependency_hashes",
        "debt_manifest_hashes",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.identity_schema_version, 1, f"{label}.identity_schema_version")
        if not isinstance(self.scope, SynthesisScopeV1):
            raise Protocol27SchemaError(f"{label}.scope must be SynthesisScopeV1")
        _schema(safe_id, self.artifact_kind, f"{label}.artifact_kind")
        _schema(literal, self.producer_protocol_version, "2.7", f"{label}.producer_protocol_version")
        for field in (
            "synthesis_policy_hash",
            "response_schema_hash",
            "context_policy_hash",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        dependencies = _typed_tuple(
            self.artifact_dependencies,
            SynthesisArtifactDependencyV1,
            f"{label}.artifact_dependencies",
        )
        key_ids = tuple(item.artifact_key_id for item in dependencies)
        if len(key_ids) != len(set(key_ids)):
            raise Protocol27SchemaError(f"{label}.artifact dependency keys must be unique")
        object.__setattr__(self, "artifact_dependencies", dependencies)
        for field in ("non_artifact_dependency_hashes", "debt_manifest_hashes"):
            object.__setattr__(
                self,
                field,
                _schema(sorted_unique_digests, getattr(self, field), f"{label}.{field}"),
            )

    @property
    def artifact_key_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.artifact_key_id

    def to_json_dict(self) -> dict[str, object]:
        return {
            "identity_schema_version": self.identity_schema_version,
            "scope": self.scope.to_json_dict(),
            "artifact_kind": self.artifact_kind,
            "producer_protocol_version": self.producer_protocol_version,
            "synthesis_policy_hash": self.synthesis_policy_hash,
            "response_schema_hash": self.response_schema_hash,
            "context_policy_hash": self.context_policy_hash,
            "artifact_dependencies": [
                item.to_json_dict() for item in self.artifact_dependencies
            ],
            "non_artifact_dependency_hashes": list(
                self.non_artifact_dependency_hashes
            ),
            "debt_manifest_hashes": list(self.debt_manifest_hashes),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisArtifactKeyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        dependencies = raw["artifact_dependencies"]
        if not isinstance(dependencies, (list, tuple)):
            raise Protocol27SchemaError(
                "SynthesisArtifactKeyV1.artifact_dependencies must be an array"
            )
        return cls(
            identity_schema_version=raw["identity_schema_version"],
            scope=SynthesisScopeV1.from_json_dict(raw["scope"]),
            artifact_kind=raw["artifact_kind"],
            producer_protocol_version=raw["producer_protocol_version"],
            synthesis_policy_hash=raw["synthesis_policy_hash"],
            response_schema_hash=raw["response_schema_hash"],
            context_policy_hash=raw["context_policy_hash"],
            artifact_dependencies=tuple(
                SynthesisArtifactDependencyV1.from_json_dict(item)
                for item in dependencies
            ),
            non_artifact_dependency_hashes=raw["non_artifact_dependency_hashes"],
            debt_manifest_hashes=raw["debt_manifest_hashes"],
        )


@dataclass(frozen=True, slots=True)
class SynthesisWorkTemplateV1:
    schema_version: int
    artifact_kind: str
    scope_kind: SynthesisScopeKindV1
    producer_id: str
    producer_protocol_version: str
    producer_authority_hash: str
    executor_contract_hash: str
    verifier_id: str
    verifier_version: str
    verifier_authority_hash: str
    synthesis_policy_hash: str
    response_schema_hash: str
    context_policy_hash: str
    required_artifact_kinds: tuple[str, ...]
    max_provider_attempts: int
    max_generation_attempts: int
    max_result_contract_retries: int
    max_artifact_contract_retries: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_kind",
        "scope_kind",
        "producer_id",
        "producer_protocol_version",
        "producer_authority_hash",
        "executor_contract_hash",
        "verifier_id",
        "verifier_version",
        "verifier_authority_hash",
        "synthesis_policy_hash",
        "response_schema_hash",
        "context_policy_hash",
        "required_artifact_kinds",
        "max_provider_attempts",
        "max_generation_attempts",
        "max_result_contract_retries",
        "max_artifact_contract_retries",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(one_of, self.scope_kind, _SCOPE_KINDS, f"{label}.scope_kind")
        for field in (
            "artifact_kind",
            "producer_id",
            "producer_protocol_version",
            "verifier_id",
            "verifier_version",
        ):
            _schema(safe_id, getattr(self, field), f"{label}.{field}")
        _schema(literal, self.producer_protocol_version, "2.7", f"{label}.producer_protocol_version")
        for field in (
            "producer_authority_hash",
            "executor_contract_hash",
            "verifier_authority_hash",
            "synthesis_policy_hash",
            "response_schema_hash",
            "context_policy_hash",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        object.__setattr__(
            self,
            "required_artifact_kinds",
            _sorted_unique_ids(
                self.required_artifact_kinds, f"{label}.required_artifact_kinds"
            ),
        )
        if (
            self.max_provider_attempts,
            self.max_generation_attempts,
            self.max_result_contract_retries,
            self.max_artifact_contract_retries,
        ) != (2, 2, 1, 1):
            raise Protocol27SchemaError(
                "SynthesisWorkTemplateV1 requires the fixed bounded attempt policy"
            )

    @property
    def template_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.template_id

    def to_json_dict(self) -> dict[str, object]:
        return {
            field: list(getattr(self, field))
            if field == "required_artifact_kinds"
            else getattr(self, field)
            for field in self.FIELDS
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisWorkTemplateV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisWorkItemV1:
    schema_version: int
    template_id: str
    output_key: SynthesisArtifactKeyV1
    dependency_key_ids: tuple[str, ...]
    executor_contract_hash: str
    verifier_id: str
    verifier_version: str
    verifier_authority_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "template_id",
        "output_key",
        "dependency_key_ids",
        "executor_contract_hash",
        "verifier_id",
        "verifier_version",
        "verifier_authority_hash",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(digest_value, self.template_id, f"{label}.template_id")
        if not isinstance(self.output_key, SynthesisArtifactKeyV1):
            raise Protocol27SchemaError(f"{label}.output_key is invalid")
        dependencies = _schema(
            sorted_unique_digests,
            self.dependency_key_ids,
            f"{label}.dependency_key_ids",
        )
        expected = tuple(
            sorted(item.artifact_key_id for item in self.output_key.artifact_dependencies)
        )
        if dependencies != expected:
            raise Protocol27SchemaError(
                "SynthesisWorkItemV1 dependency keys disagree with output key"
            )
        object.__setattr__(self, "dependency_key_ids", dependencies)
        _schema(digest_value, self.executor_contract_hash, f"{label}.executor_contract_hash")
        _schema(safe_id, self.verifier_id, f"{label}.verifier_id")
        _schema(safe_id, self.verifier_version, f"{label}.verifier_version")
        _schema(digest_value, self.verifier_authority_hash, f"{label}.verifier_authority_hash")

    @property
    def work_item_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.work_item_id

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "template_id": self.template_id,
            "output_key": self.output_key.to_json_dict(),
            "dependency_key_ids": list(self.dependency_key_ids),
            "executor_contract_hash": self.executor_contract_hash,
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "verifier_authority_hash": self.verifier_authority_hash,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisWorkItemV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            template_id=raw["template_id"],
            output_key=SynthesisArtifactKeyV1.from_json_dict(raw["output_key"]),
            dependency_key_ids=raw["dependency_key_ids"],
            executor_contract_hash=raw["executor_contract_hash"],
            verifier_id=raw["verifier_id"],
            verifier_version=raw["verifier_version"],
            verifier_authority_hash=raw["verifier_authority_hash"],
        )


@dataclass(frozen=True, slots=True)
class SynthesisArtifactAuthorityV1:
    artifact_key_id: str
    artifact_hash: str
    acceptance_receipt_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "artifact_key_id",
        "artifact_hash",
        "acceptance_receipt_id",
    )

    def __post_init__(self) -> None:
        for field in self.FIELDS:
            _schema(digest_value, getattr(self, field), field)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisArtifactAuthorityV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisRootV1:
    schema_version: int
    accepted_source_outcome_ids: tuple[str, ...]
    accepted_artifacts: tuple[SynthesisArtifactAuthorityV1, ...]
    partial_acceptance_receipt_ids: tuple[str, ...]
    debt_manifest_hashes: tuple[str, ...]
    topology_id: str
    graph_id: str
    materialization_policy_hash: str
    producer_authority_hash: str
    verifier_authority_hash: str
    synthesis_policy_hash: str
    input_quality: InputQualityV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "accepted_source_outcome_ids",
        "accepted_artifacts",
        "partial_acceptance_receipt_ids",
        "debt_manifest_hashes",
        "topology_id",
        "graph_id",
        "materialization_policy_hash",
        "producer_authority_hash",
        "verifier_authority_hash",
        "synthesis_policy_hash",
        "input_quality",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(one_of, self.input_quality, _INPUT_QUALITIES, f"{label}.input_quality")
        for field in (
            "accepted_source_outcome_ids",
            "partial_acceptance_receipt_ids",
            "debt_manifest_hashes",
        ):
            object.__setattr__(
                self,
                field,
                _schema(sorted_unique_digests, getattr(self, field), f"{label}.{field}"),
            )
        artifacts = _typed_tuple(
            self.accepted_artifacts,
            SynthesisArtifactAuthorityV1,
            f"{label}.accepted_artifacts",
        )
        object.__setattr__(self, "accepted_artifacts", artifacts)
        for field in (
            "topology_id",
            "graph_id",
            "materialization_policy_hash",
            "producer_authority_hash",
            "verifier_authority_hash",
            "synthesis_policy_hash",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        partial = bool(self.debt_manifest_hashes or self.partial_acceptance_receipt_ids)
        if (self.input_quality == "partial") != partial:
            raise Protocol27SchemaError(
                "SynthesisRootV1 input_quality disagrees with partial debt authority"
            )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "accepted_source_outcome_ids": list(self.accepted_source_outcome_ids),
            "accepted_artifacts": [item.to_json_dict() for item in self.accepted_artifacts],
            "partial_acceptance_receipt_ids": list(self.partial_acceptance_receipt_ids),
            "debt_manifest_hashes": list(self.debt_manifest_hashes),
            "topology_id": self.topology_id,
            "graph_id": self.graph_id,
            "materialization_policy_hash": self.materialization_policy_hash,
            "producer_authority_hash": self.producer_authority_hash,
            "verifier_authority_hash": self.verifier_authority_hash,
            "synthesis_policy_hash": self.synthesis_policy_hash,
            "input_quality": self.input_quality,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisRootV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        artifacts = raw["accepted_artifacts"]
        if not isinstance(artifacts, (list, tuple)):
            raise Protocol27SchemaError("SynthesisRootV1.accepted_artifacts must be an array")
        return cls(
            schema_version=raw["schema_version"],
            accepted_source_outcome_ids=raw["accepted_source_outcome_ids"],
            accepted_artifacts=tuple(
                SynthesisArtifactAuthorityV1.from_json_dict(item) for item in artifacts
            ),
            partial_acceptance_receipt_ids=raw["partial_acceptance_receipt_ids"],
            debt_manifest_hashes=raw["debt_manifest_hashes"],
            topology_id=raw["topology_id"],
            graph_id=raw["graph_id"],
            materialization_policy_hash=raw["materialization_policy_hash"],
            producer_authority_hash=raw["producer_authority_hash"],
            verifier_authority_hash=raw["verifier_authority_hash"],
            synthesis_policy_hash=raw["synthesis_policy_hash"],
            input_quality=raw["input_quality"],
        )


@dataclass(frozen=True, slots=True)
class PublicationDescriptorV1:
    schema_version: int
    run_id: str
    synthesis_root_id: str
    input_quality: InputQualityV1
    accepted_source_outcome_ids: tuple[str, ...]
    debt_manifest_hashes: tuple[str, ...]
    partial_acceptance_receipt_ids: tuple[str, ...]
    materialization_manifest_id: str
    compatibility_generation: int
    compatibility_index_hash: str
    synthesis_policy_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "run_id",
        "synthesis_root_id",
        "input_quality",
        "accepted_source_outcome_ids",
        "debt_manifest_hashes",
        "partial_acceptance_receipt_ids",
        "materialization_manifest_id",
        "compatibility_generation",
        "compatibility_index_hash",
        "synthesis_policy_hash",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(safe_id, self.run_id, f"{label}.run_id")
        _schema(one_of, self.input_quality, _INPUT_QUALITIES, f"{label}.input_quality")
        for field in (
            "synthesis_root_id",
            "materialization_manifest_id",
            "compatibility_index_hash",
            "synthesis_policy_hash",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        for field in (
            "accepted_source_outcome_ids",
            "debt_manifest_hashes",
            "partial_acceptance_receipt_ids",
        ):
            object.__setattr__(
                self,
                field,
                _schema(sorted_unique_digests, getattr(self, field), f"{label}.{field}"),
            )
        _schema(nonnegative_int, self.compatibility_generation, f"{label}.compatibility_generation")

    @property
    def descriptor_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.descriptor_id

    def to_json_dict(self) -> dict[str, object]:
        return {
            field: list(getattr(self, field))
            if field in {
                "accepted_source_outcome_ids",
                "debt_manifest_hashes",
                "partial_acceptance_receipt_ids",
            }
            else getattr(self, field)
            for field in self.FIELDS
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "PublicationDescriptorV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class RunManifestV6:
    schema_version: int
    engine: Literal["re-v2"]
    engine_protocol_version: Literal["2.7"]
    goal: Literal["workspace-synthesis"]
    run_id: str
    created_at: str
    request_id: str
    parent_run_id: str
    parent_manifest_hash: str
    source_snapshot_id: str
    source_snapshot_kind: Literal["workspace-git-composite"]
    partition_manifest_id: str
    accepted_sources: tuple[AcceptedSourceOutcomeV1, ...]
    source_overview_catalog_id: str
    partial_acceptances: tuple[PartialSourceAcceptanceV1, ...]
    input_authority_catalog_id: str
    synthesis_graph_id: str
    synthesis_policy_hash: str
    prosaic_authority_hash: str
    budget_policy: SynthesisBudgetPolicyV1
    checkpoint_selection_id: str
    expected_v2_index_hash: str
    expected_compatibility_generation: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "engine",
        "engine_protocol_version",
        "goal",
        "run_id",
        "created_at",
        "request_id",
        "parent_run_id",
        "parent_manifest_hash",
        "source_snapshot_id",
        "source_snapshot_kind",
        "partition_manifest_id",
        "accepted_sources",
        "source_overview_catalog_id",
        "partial_acceptances",
        "input_authority_catalog_id",
        "synthesis_graph_id",
        "synthesis_policy_hash",
        "prosaic_authority_hash",
        "budget_policy",
        "checkpoint_selection_id",
        "expected_v2_index_hash",
        "expected_compatibility_generation",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 6, f"{label}.schema_version")
        _schema(literal, self.engine, "re-v2", f"{label}.engine")
        _schema(literal, self.engine_protocol_version, "2.7", f"{label}.engine_protocol_version")
        _schema(literal, self.goal, "workspace-synthesis", f"{label}.goal")
        _schema(safe_id, self.run_id, f"{label}.run_id")
        _schema(utc_timestamp, self.created_at, f"{label}.created_at")
        _schema(safe_id, self.parent_run_id, f"{label}.parent_run_id")
        _schema(literal, self.source_snapshot_kind, "workspace-git-composite", f"{label}.source_snapshot_kind")
        for field in (
            "request_id",
            "parent_manifest_hash",
            "source_snapshot_id",
            "partition_manifest_id",
            "source_overview_catalog_id",
            "input_authority_catalog_id",
            "synthesis_graph_id",
            "synthesis_policy_hash",
            "prosaic_authority_hash",
            "checkpoint_selection_id",
            "expected_v2_index_hash",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        sources = _typed_tuple(
            self.accepted_sources,
            AcceptedSourceOutcomeV1,
            f"{label}.accepted_sources",
            sort_attribute="source_id",
        )
        if not sources:
            raise Protocol27SchemaError("RunManifestV6 accepted_sources must not be empty")
        source_ids = tuple(item.source_id for item in sources)
        if len(source_ids) != len(set(source_ids)):
            raise Protocol27SchemaError("RunManifestV6 source IDs must be unique")
        acceptances = _typed_tuple(
            self.partial_acceptances,
            PartialSourceAcceptanceV1,
            f"{label}.partial_acceptances",
            sort_attribute="source_id",
        )
        partial_by_id = {
            item.source_id: item for item in sources if item.outcome == "partial"
        }
        if tuple(item.source_id for item in acceptances) != tuple(sorted(partial_by_id)):
            raise Protocol27SchemaError(
                "RunManifestV6 partial acceptance coverage must exactly match partial sources"
            )
        for acceptance in acceptances:
            source = partial_by_id[acceptance.source_id]
            if (
                acceptance.parent_run_id != self.parent_run_id
                or acceptance.parent_manifest_hash != self.parent_manifest_hash
                or acceptance.source_root_key_id != source.source_root_key_id
                or acceptance.source_root_hash != source.source_root_hash
                or acceptance.debt_manifest_hash != source.debt_manifest_hash
                or acceptance.operation_id != self.request_id
            ):
                raise Protocol27SchemaError(
                    "RunManifestV6 partial acceptance authority does not match source/request"
                )
        if not isinstance(self.budget_policy, SynthesisBudgetPolicyV1):
            raise Protocol27SchemaError("RunManifestV6 budget_policy is invalid")
        _schema(
            nonnegative_int,
            self.expected_compatibility_generation,
            f"{label}.expected_compatibility_generation",
        )
        object.__setattr__(self, "accepted_sources", sources)
        object.__setattr__(self, "partial_acceptances", acceptances)

    @property
    def run_manifest_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.run_manifest_id

    @property
    def input_quality(self) -> InputQualityV1:
        return "partial" if self.partial_acceptances else "complete"

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "engine": self.engine,
            "engine_protocol_version": self.engine_protocol_version,
            "goal": self.goal,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "request_id": self.request_id,
            "parent_run_id": self.parent_run_id,
            "parent_manifest_hash": self.parent_manifest_hash,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_kind": self.source_snapshot_kind,
            "partition_manifest_id": self.partition_manifest_id,
            "accepted_sources": [item.to_json_dict() for item in self.accepted_sources],
            "source_overview_catalog_id": self.source_overview_catalog_id,
            "partial_acceptances": [item.to_json_dict() for item in self.partial_acceptances],
            "input_authority_catalog_id": self.input_authority_catalog_id,
            "synthesis_graph_id": self.synthesis_graph_id,
            "synthesis_policy_hash": self.synthesis_policy_hash,
            "prosaic_authority_hash": self.prosaic_authority_hash,
            "budget_policy": self.budget_policy.to_json_dict(),
            "checkpoint_selection_id": self.checkpoint_selection_id,
            "expected_v2_index_hash": self.expected_v2_index_hash,
            "expected_compatibility_generation": self.expected_compatibility_generation,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "RunManifestV6":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        sources = raw["accepted_sources"]
        acceptances = raw["partial_acceptances"]
        if not isinstance(sources, (list, tuple)) or not isinstance(
            acceptances, (list, tuple)
        ):
            raise Protocol27SchemaError(
                "RunManifestV6 source and acceptance fields must be arrays"
            )
        return cls(
            schema_version=raw["schema_version"],
            engine=raw["engine"],
            engine_protocol_version=raw["engine_protocol_version"],
            goal=raw["goal"],
            run_id=raw["run_id"],
            created_at=raw["created_at"],
            request_id=raw["request_id"],
            parent_run_id=raw["parent_run_id"],
            parent_manifest_hash=raw["parent_manifest_hash"],
            source_snapshot_id=raw["source_snapshot_id"],
            source_snapshot_kind=raw["source_snapshot_kind"],
            partition_manifest_id=raw["partition_manifest_id"],
            accepted_sources=tuple(
                AcceptedSourceOutcomeV1.from_json_dict(item) for item in sources
            ),
            source_overview_catalog_id=raw["source_overview_catalog_id"],
            partial_acceptances=tuple(
                PartialSourceAcceptanceV1.from_json_dict(item) for item in acceptances
            ),
            input_authority_catalog_id=raw["input_authority_catalog_id"],
            synthesis_graph_id=raw["synthesis_graph_id"],
            synthesis_policy_hash=raw["synthesis_policy_hash"],
            prosaic_authority_hash=raw["prosaic_authority_hash"],
            budget_policy=SynthesisBudgetPolicyV1.from_json_dict(raw["budget_policy"]),
            checkpoint_selection_id=raw["checkpoint_selection_id"],
            expected_v2_index_hash=raw["expected_v2_index_hash"],
            expected_compatibility_generation=raw["expected_compatibility_generation"],
        )


__all__ = (
    "AcceptedSourceOutcomeV1",
    "AcceptedSourceOverviewCatalogV1",
    "AcceptedSourceOverviewProjectionV1",
    "InputQualityV1",
    "PartialSourceAcceptanceV1",
    "Protocol27SchemaError",
    "PublicationDescriptorV1",
    "RunManifestV6",
    "SourceOutcomeV1",
    "SynthesisArtifactAuthorityV1",
    "SynthesisArtifactDependencyV1",
    "SynthesisArtifactKeyV1",
    "SynthesisBudgetPolicyV1",
    "SynthesisRequestV1",
    "SynthesisRootV1",
    "SynthesisScopeKindV1",
    "SynthesisScopeV1",
    "SynthesisWorkItemV1",
    "SynthesisWorkTemplateV1",
)

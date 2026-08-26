"""Layered L3 policy and shared Prosaic executor authority composition."""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import ClassVar

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.executors import (
    ExecutorContractCatalogV1,
    ExecutorContractEntryV1,
    ExecutorLimitsV1,
    Protocol22ExecutorError,
    RequestRendererAuthorityV1,
    ReservationCalculatorAuthorityV1,
    ResponseSchemaReferenceV1,
    SHARED_AI_CLI_ADAPTER_ID,
    TokenAccountingAuthorityV1,
    VerifierAuthorityV1,
)
from harness.re_v2.protocol_22.policies import (
    ArtifactPolicyCatalogV1,
    ArtifactPolicyEntryV1,
    policy_for,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    positive_int,
    safe_id,
)
from harness.re_v2.protocol_24.policies import build_deepening_v1_policy_catalog

from .findings import FINDING_CLASSES
from .model import Protocol25SchemaError


SEMANTIC_EXECUTOR_FAMILIES = (
    "closure-recheck",
    "semantic-audit",
    "semantic-resolution",
    "source-composition-guard",
)
SEMANTIC_RENDERER_ID = "semantic-compact-renderer-v1"
SEMANTIC_ARTIFACT_KINDS = (
    "audit-closure-root",
    "l3-source-root",
    "semantic-audit-findings",
    "semantic-resolution-overlay",
    "source-composition-assessment",
    "target-closure-assessment",
)
SEMANTIC_PRODUCER_PROTOCOL_BY_ARTIFACT = MappingProxyType(
    {
        "semantic-audit-findings": "protocol-2.5-semantic-audit-v1",
        "semantic-resolution-overlay": "protocol-2.5-semantic-resolution-v1",
        "target-closure-assessment": "protocol-2.5-closure-recheck-v1",
        "source-composition-assessment": "protocol-2.5-source-composition-guard-v1",
    }
)
AUDIT_RULE_IDS = (
    "behavior.incorrect",
    "behavior.missing",
    "claim.contradictory",
    "claim.unsupported",
    "decision.requires-human",
    "evidence.requires-deeper",
    "evidence.scope-gap",
    "source.cross-domain-inconsistency",
)
ASSESSMENT_KINDS = ("source-composition", "target")
SEMANTIC_RESPONSE_SCHEMA_KINDS = frozenset(
    {
        "semantic-audit-findings",
        "semantic-resolution-overlay",
        "semantic-closure-assessment",
    }
)


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol25SchemaError:
        raise
    except (Protocol22SchemaError, Protocol22ExecutorError) as exc:
        raise Protocol25SchemaError(str(exc)) from exc


def _exact_tuple(values: object, expected: tuple[str, ...], field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise Protocol25SchemaError(f"{field} must be an array")
    result = tuple(_schema(safe_id, value, field) for value in values)
    if result != expected:
        raise Protocol25SchemaError(f"{field} does not equal the closed taxonomy")
    return result


@dataclass(frozen=True, slots=True)
class AuditTaxonomyV1:
    schema_version: int
    rule_ids: tuple[str, ...]
    finding_classes: tuple[str, ...]
    assessment_kinds: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "rule_ids",
        "finding_classes",
        "assessment_kinds",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "AuditTaxonomyV1.schema_version")
        object.__setattr__(
            self,
            "rule_ids",
            _exact_tuple(self.rule_ids, AUDIT_RULE_IDS, "audit taxonomy rule_ids"),
        )
        object.__setattr__(
            self,
            "finding_classes",
            _exact_tuple(
                self.finding_classes,
                tuple(sorted(FINDING_CLASSES)),
                "audit taxonomy finding_classes",
            ),
        )
        object.__setattr__(
            self,
            "assessment_kinds",
            _exact_tuple(
                self.assessment_kinds,
                ASSESSMENT_KINDS,
                "audit taxonomy assessment_kinds",
            ),
        )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "rule_ids": list(self.rule_ids),
            "finding_classes": list(self.finding_classes),
            "assessment_kinds": list(self.assessment_kinds),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "AuditTaxonomyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SemanticArtifactPolicyEntryV1:
    schema_version: int
    artifact_kind: str
    layer: str
    producer_family: str
    content_policy_version: str
    max_canonical_json_bytes: int
    max_context_bundle_bytes: int
    max_conservative_input_tokens: int
    evidence_rule_id: str
    ownership_rule_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_kind",
        "layer",
        "producer_family",
        "content_policy_version",
        "max_canonical_json_bytes",
        "max_context_bundle_bytes",
        "max_conservative_input_tokens",
        "evidence_rule_id",
        "ownership_rule_id",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "semantic policy schema_version")
        _schema(safe_id, self.artifact_kind, "semantic policy artifact_kind")
        if self.artifact_kind not in SEMANTIC_ARTIFACT_KINDS:
            raise Protocol25SchemaError("semantic policy artifact_kind is not registered")
        _schema(literal, self.layer, "L3", "semantic policy layer")
        for field in (
            "producer_family",
            "content_policy_version",
            "evidence_rule_id",
            "ownership_rule_id",
        ):
            _schema(safe_id, getattr(self, field), f"semantic policy {field}")
        for field in (
            "max_canonical_json_bytes",
            "max_context_bundle_bytes",
            "max_conservative_input_tokens",
        ):
            _schema(positive_int, getattr(self, field), f"semantic policy {field}")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SemanticArtifactPolicyEntryV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SemanticArtifactPolicyCatalogV1:
    schema_version: int
    inherited_catalog: ArtifactPolicyCatalogV1
    l3_entries: tuple[SemanticArtifactPolicyEntryV1, ...]
    audit_taxonomy: AuditTaxonomyV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "inherited_catalog",
        "l3_entries",
        "audit_taxonomy",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "semantic policy catalog schema_version")
        if not isinstance(self.inherited_catalog, ArtifactPolicyCatalogV1):
            raise Protocol25SchemaError("semantic policy catalog requires inherited policy")
        if not isinstance(self.l3_entries, (list, tuple)) or any(
            not isinstance(item, SemanticArtifactPolicyEntryV1)
            for item in self.l3_entries
        ):
            raise Protocol25SchemaError("semantic policy catalog L3 entries are invalid")
        entries = tuple(self.l3_entries)
        kinds = tuple(item.artifact_kind for item in entries)
        if kinds != SEMANTIC_ARTIFACT_KINDS:
            raise Protocol25SchemaError(
                "semantic policy catalog L3 entries must be exact, sorted and unique"
            )
        if not isinstance(self.audit_taxonomy, AuditTaxonomyV1):
            raise Protocol25SchemaError("semantic policy catalog taxonomy is invalid")
        object.__setattr__(self, "l3_entries", entries)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def entry_for(
        self,
        layer: str,
        artifact_kind: str,
    ) -> ArtifactPolicyEntryV1 | SemanticArtifactPolicyEntryV1:
        if layer != "L3":
            try:
                return policy_for(self.inherited_catalog, layer, artifact_kind)
            except Protocol22SchemaError as exc:
                raise Protocol25SchemaError(str(exc)) from exc
        for entry in self.l3_entries:
            if entry.artifact_kind == artifact_kind:
                return entry
        raise Protocol25SchemaError(
            f"semantic policy catalog has no L3 artifact {artifact_kind!r}"
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "inherited_catalog": self.inherited_catalog.to_json_dict(),
            "l3_entries": [item.to_json_dict() for item in self.l3_entries],
            "audit_taxonomy": self.audit_taxonomy.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SemanticArtifactPolicyCatalogV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        entries = raw["l3_entries"]
        if not isinstance(entries, (list, tuple)):
            raise Protocol25SchemaError("semantic policy catalog L3 entries must be an array")
        return cls(
            schema_version=raw["schema_version"],
            inherited_catalog=ArtifactPolicyCatalogV1.from_json_dict(
                raw["inherited_catalog"]
            ),
            l3_entries=tuple(
                SemanticArtifactPolicyEntryV1.from_json_dict(item) for item in entries
            ),
            audit_taxonomy=AuditTaxonomyV1.from_json_dict(raw["audit_taxonomy"]),
        )


def build_semantic_v1_policy_catalog() -> SemanticArtifactPolicyCatalogV1:
    producer_families = {
        "audit-closure-root": "semantic-closure-root",
        "l3-source-root": "semantic-closure-root",
        "semantic-audit-findings": "semantic-audit",
        "semantic-resolution-overlay": "semantic-resolution",
        "source-composition-assessment": "source-composition-guard",
        "target-closure-assessment": "closure-recheck",
    }
    entries = tuple(
        SemanticArtifactPolicyEntryV1(
            schema_version=1,
            artifact_kind=kind,
            layer="L3",
            producer_family=producer_families[kind],
            content_policy_version="semantic-closure-v1",
            max_canonical_json_bytes=128 * 1024,
            max_context_bundle_bytes=192 * 1024,
            max_conservative_input_tokens=196_608,
            evidence_rule_id="immutable-snapshot-evidence-v1",
            ownership_rule_id="controller-issued-context-v1",
        )
        for kind in SEMANTIC_ARTIFACT_KINDS
    )
    return SemanticArtifactPolicyCatalogV1(
        schema_version=1,
        inherited_catalog=build_deepening_v1_policy_catalog(),
        l3_entries=entries,
        audit_taxonomy=AuditTaxonomyV1(
            schema_version=1,
            rule_ids=AUDIT_RULE_IDS,
            finding_classes=tuple(sorted(FINDING_CLASSES)),
            assessment_kinds=ASSESSMENT_KINDS,
        ),
    )


class SemanticResponseSchemaReferenceV1(ResponseSchemaReferenceV1):
    """Protocol-2.5 schema reference accepted by the shared request envelope."""

    def __post_init__(self) -> None:
        _schema(safe_id, self.artifact_kind, "semantic response schema kind")
        if self.artifact_kind not in SEMANTIC_RESPONSE_SCHEMA_KINDS:
            raise Protocol25SchemaError("semantic response schema kind is unsupported")
        _schema(digest_value, self.schema_hash, "semantic response schema hash")

    @classmethod
    def from_json_dict(cls, value: object) -> "SemanticResponseSchemaReferenceV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(artifact_kind=raw["artifact_kind"], schema_hash=raw["schema_hash"])


class SemanticRequestRendererAuthorityV1(RequestRendererAuthorityV1):
    """Shared renderer authority with one protocol-2.5 response schema."""

    def __post_init__(self) -> None:
        for field in ("renderer_id", "renderer_version"):
            _schema(safe_id, getattr(self, field), f"semantic renderer {field}")
        for field in ("implementation_digest", "agent_contract_hash"):
            _schema(digest_value, getattr(self, field), f"semantic renderer {field}")
        if (
            not isinstance(self.response_schemas, (list, tuple))
            or len(self.response_schemas) != 1
            or not isinstance(
                self.response_schemas[0], SemanticResponseSchemaReferenceV1
            )
        ):
            raise Protocol25SchemaError(
                "semantic renderer requires exactly one semantic response schema"
            )
        object.__setattr__(self, "response_schemas", tuple(self.response_schemas))

    @classmethod
    def from_json_dict(cls, value: object) -> "SemanticRequestRendererAuthorityV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        schemas = raw["response_schemas"]
        if not isinstance(schemas, (list, tuple)):
            raise Protocol25SchemaError("semantic renderer response schemas must be an array")
        return cls(
            renderer_id=raw["renderer_id"],
            renderer_version=raw["renderer_version"],
            implementation_digest=raw["implementation_digest"],
            agent_contract_hash=raw["agent_contract_hash"],
            response_schemas=tuple(
                SemanticResponseSchemaReferenceV1.from_json_dict(item)
                for item in schemas
            ),
        )


@dataclass(frozen=True, slots=True)
class SemanticExecutorAuthorityV1:
    schema_version: int
    producer_family: str
    agent_contract_hash: str
    response_schema_kind: str
    response_schema_hash: str
    verifier_id: str
    verifier_implementation_digest: str
    result_contract_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "producer_family",
        "agent_contract_hash",
        "response_schema_kind",
        "response_schema_hash",
        "verifier_id",
        "verifier_implementation_digest",
        "result_contract_id",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "semantic executor authority schema_version")
        _schema(safe_id, self.producer_family, "semantic executor producer_family")
        if self.producer_family not in SEMANTIC_EXECUTOR_FAMILIES:
            raise Protocol25SchemaError("semantic executor producer family is unsupported")
        for field in (
            "agent_contract_hash",
            "response_schema_hash",
            "verifier_implementation_digest",
        ):
            _schema(digest_value, getattr(self, field), f"semantic executor {field}")
        _schema(safe_id, self.response_schema_kind, "semantic executor response schema kind")
        if self.response_schema_kind not in SEMANTIC_RESPONSE_SCHEMA_KINDS:
            raise Protocol25SchemaError("semantic executor response schema kind is unsupported")
        for field in ("verifier_id", "result_contract_id"):
            _schema(safe_id, getattr(self, field), f"semantic executor {field}")

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SemanticExecutorAuthorityV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SemanticExecutorContractCatalogV1:
    schema_version: int
    inherited_catalog: ExecutorContractCatalogV1
    semantic_entries: tuple[ExecutorContractEntryV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "inherited_catalog",
        "semantic_entries",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "semantic executor catalog schema_version")
        if not isinstance(self.inherited_catalog, ExecutorContractCatalogV1):
            raise Protocol25SchemaError("semantic executor catalog requires inherited authority")
        if not isinstance(self.semantic_entries, (list, tuple)) or any(
            not isinstance(item, ExecutorContractEntryV1)
            for item in self.semantic_entries
        ):
            raise Protocol25SchemaError("semantic executor catalog entries are invalid")
        entries = tuple(self.semantic_entries)
        families = tuple(item.producer_family for item in entries)
        if families != SEMANTIC_EXECUTOR_FAMILIES:
            raise Protocol25SchemaError(
                "semantic executor families must be exactly the closed L3 set"
            )
        try:
            ExecutorContractCatalogV1(schema_version=1, entries=entries)
        except Protocol22ExecutorError as exc:
            raise Protocol25SchemaError(str(exc)) from exc
        object.__setattr__(self, "semantic_entries", entries)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    @property
    def entries(self) -> tuple[ExecutorContractEntryV1, ...]:
        """Expose the layered catalog through the shared authority interface."""
        return tuple(
            sorted(
                (*self.inherited_catalog.entries, *self.semantic_entries),
                key=lambda entry: entry.producer_family,
            )
        )

    def entry_for(self, producer_family: str) -> ExecutorContractEntryV1:
        for entry in self.semantic_entries:
            if entry.producer_family == producer_family:
                return entry
        try:
            return self.inherited_catalog.entry_for(producer_family)
        except Protocol22ExecutorError as exc:
            raise Protocol25SchemaError(str(exc)) from exc

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "inherited_catalog": self.inherited_catalog.to_json_dict(),
            "semantic_entries": [item.to_json_dict() for item in self.semantic_entries],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SemanticExecutorContractCatalogV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        entries = raw["semantic_entries"]
        if not isinstance(entries, (list, tuple)):
            raise Protocol25SchemaError("semantic executor entries must be an array")
        return cls(
            schema_version=raw["schema_version"],
            inherited_catalog=ExecutorContractCatalogV1.from_json_dict(
                raw["inherited_catalog"]
            ),
            semantic_entries=tuple(_decode_semantic_executor_entry(item) for item in entries),
        )


def _decode_semantic_executor_entry(value: object) -> ExecutorContractEntryV1:
    raw = _schema(
        exact_object,
        value,
        frozenset(ExecutorContractEntryV1.FIELDS),
        "semantic executor entry",
    )
    if any(raw[field] is not None for field in ("api_transport", "model", "request_tokenizer", "generation")):
        raise Protocol25SchemaError("semantic executor must remain on shared CLI authority")
    return ExecutorContractEntryV1(
        producer_family=raw["producer_family"],
        execution_mode=raw["execution_mode"],
        provider_id=raw["provider_id"],
        api_transport=None,
        adapter_id=raw["adapter_id"],
        adapter_contract_version=raw["adapter_contract_version"],
        executor_implementation_digest=raw["executor_implementation_digest"],
        producer_protocol_version=raw["producer_protocol_version"],
        result_contract_id=raw["result_contract_id"],
        verifier=VerifierAuthorityV1.from_json_dict(raw["verifier"]),
        model=None,
        request_renderer=SemanticRequestRendererAuthorityV1.from_json_dict(
            raw["request_renderer"]
        ),
        request_tokenizer=None,
        generation=None,
        reservation_calculator=ReservationCalculatorAuthorityV1.from_json_dict(
            raw["reservation_calculator"]
        ),
        token_accounting=TokenAccountingAuthorityV1.from_json_dict(
            raw["token_accounting"]
        ),
        limits=ExecutorLimitsV1.from_json_dict(raw["limits"]),
    )


def build_semantic_executor_catalog(
    inherited: ExecutorContractCatalogV1,
    authorities: tuple[SemanticExecutorAuthorityV1, ...],
    renderer_implementation_digest: str,
) -> SemanticExecutorContractCatalogV1:
    if not isinstance(inherited, ExecutorContractCatalogV1):
        raise Protocol25SchemaError("semantic executor composition requires parent catalog")
    if not isinstance(authorities, (list, tuple)) or any(
        not isinstance(item, SemanticExecutorAuthorityV1) for item in authorities
    ):
        raise Protocol25SchemaError("semantic executor authorities are invalid")
    selected = tuple(authorities)
    _schema(
        digest_value,
        renderer_implementation_digest,
        "semantic renderer implementation digest",
    )
    if tuple(item.producer_family for item in selected) != SEMANTIC_EXECUTOR_FAMILIES:
        raise Protocol25SchemaError(
            "semantic executor authorities must be exactly the closed L3 families"
        )
    try:
        baseline = inherited.entry_for("compact-baseline")
    except Protocol22ExecutorError as exc:
        raise Protocol25SchemaError(str(exc)) from exc
    renderer = baseline.request_renderer
    if (
        baseline.execution_mode != "cli"
        or baseline.adapter_id != SHARED_AI_CLI_ADAPTER_ID
        or renderer is None
    ):
        raise Protocol25SchemaError(
            "semantic executor requires the authenticated shared CLI parent entry"
        )
    entries = tuple(
        replace(
            baseline,
            producer_family=authority.producer_family,
            producer_protocol_version=f"protocol-2.5-{authority.producer_family}-v1",
            result_contract_id=authority.result_contract_id,
            verifier=VerifierAuthorityV1(
                verifier_id=authority.verifier_id,
                verifier_version="v1",
                implementation_digest=authority.verifier_implementation_digest,
            ),
            request_renderer=SemanticRequestRendererAuthorityV1(
                renderer_id=SEMANTIC_RENDERER_ID,
                renderer_version="v1",
                implementation_digest=renderer_implementation_digest,
                agent_contract_hash=authority.agent_contract_hash,
                response_schemas=(
                    SemanticResponseSchemaReferenceV1(
                        artifact_kind=authority.response_schema_kind,
                        schema_hash=authority.response_schema_hash,
                    ),
                ),
            ),
        )
        for authority in selected
    )
    return SemanticExecutorContractCatalogV1(
        schema_version=1,
        inherited_catalog=inherited,
        semantic_entries=entries,
    )


__all__ = (
    "ASSESSMENT_KINDS",
    "AUDIT_RULE_IDS",
    "AuditTaxonomyV1",
    "FINDING_CLASSES",
    "SEMANTIC_ARTIFACT_KINDS",
    "SEMANTIC_EXECUTOR_FAMILIES",
    "SEMANTIC_RENDERER_ID",
    "SemanticArtifactPolicyCatalogV1",
    "SemanticArtifactPolicyEntryV1",
    "SemanticExecutorAuthorityV1",
    "SemanticExecutorContractCatalogV1",
    "SemanticRequestRendererAuthorityV1",
    "SemanticResponseSchemaReferenceV1",
    "build_semantic_executor_catalog",
    "build_semantic_v1_policy_catalog",
)

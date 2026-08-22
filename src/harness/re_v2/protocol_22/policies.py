"""Closed built-in artifact-policy authority for protocol 2.2."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import ClassVar, Literal

from harness.re_v2.canonical import content_digest

from .schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    one_of,
    optional_text,
    positive_int,
    positive_or_none,
    safe_id,
    text_value,
)


class Protocol22PolicyError(Protocol22SchemaError):
    """Raised when a protocol-2.2 artifact policy is not closed and coherent."""


DOMAIN_SURFACES = (
    "responsibilities",
    "entry_points",
    "core_behavior",
    "failure_paths",
    "state_and_data",
    "external_contracts",
    "tests",
    "operational_constraints",
)
SOURCE_OVERVIEW_SURFACES = (
    "purpose",
    "runtime_shape",
    "major_entry_points",
    "intra_source_boundaries",
    "domain_relationships",
)
SOURCE_EVIDENCE_ROLES = (
    "declared_entry_point",
    "build_runtime",
    "explicit_supporting",
    "documentation",
)
DOMAIN_EVIDENCE_ROLES = (
    "explicit_supporting",
    "entry_point",
    "production",
    "test",
    "documentation",
    "other",
)
OMISSION_REASON_CODES = (
    "policy_ineligible",
    "non_text",
    "line_too_large",
    "capacity_exhausted",
)
PROJECTION_SURFACE_PRIORITY = (
    "responsibilities",
    "entry_points",
    "external_contracts",
)
EXPECTED_POLICY_SLOTS = frozenset(
    {
        ("L0", "source-inventory"),
        ("L0", "source-partition"),
        ("L0", "domain-inventory"),
        ("L0", "source-evidence-pack"),
        ("L0", "domain-evidence-pack"),
        ("L1", "domain-context-bundle"),
        ("L1", "source-overview-context-bundle"),
        ("L1", "domain-baseline"),
        ("L1", "source-overview"),
        ("L1", "source-baseline-root"),
    }
)

_ALL_CLASSIFIER_ROLES = frozenset((*SOURCE_EVIDENCE_ROLES, *DOMAIN_EVIDENCE_ROLES))
_GLOB_RE = re.compile(r"[A-Za-z0-9*?._/\[\]-]+\Z")
_POLICY_KIND = {
    "source-inventory": ("L0", "source-inventory-v1", "empty"),
    "source-partition": ("L0", "source-partition-v1", "empty"),
    "domain-inventory": ("L0", "domain-inventory-v1", "empty"),
    "source-evidence-pack": ("L0", "evidence-pack-v1", "source_evidence"),
    "domain-evidence-pack": ("L0", "evidence-pack-v1", "domain_evidence"),
    "domain-context-bundle": ("L1", "context-bundle-v1", "context"),
    "source-overview-context-bundle": ("L1", "context-bundle-v1", "context"),
    "domain-baseline": ("L1", "compact-v1", "compact"),
    "source-overview": ("L1", "compact-v1", "compact"),
    "source-baseline-root": ("L1", "source-baseline-root-v1", "empty"),
}


def _policy_error(message: str) -> None:
    raise Protocol22PolicyError(message)


def _ordered_unique_ids(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        _policy_error(f"{field} must be an array")
    result = tuple(safe_id(value, field) for value in values)
    if len(result) != len(set(result)):
        _policy_error(f"{field} must be unique")
    return result


def _sorted_unique_patterns(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        _policy_error(f"{field} must be an array")
    result: list[str] = []
    for value in values:
        pattern = text_value(value, field)
        if (
            not _GLOB_RE.fullmatch(pattern)
            or pattern.startswith("/")
            or "\\" in pattern
            or "//" in pattern
            or any(part == ".." for part in pattern.split("/"))
        ):
            _policy_error(f"{field} contains an invalid normalized glob pattern")
        result.append(pattern)
    frozen = tuple(result)
    if frozen != tuple(sorted(set(frozen))):
        _policy_error(f"{field} must be sorted and unique")
    return frozen


@dataclass(frozen=True, slots=True)
class PathClassifierV1:
    role: str
    patterns: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = ("role", "patterns")

    def __post_init__(self) -> None:
        one_of(self.role, _ALL_CLASSIFIER_ROLES, "PathClassifierV1.role")
        object.__setattr__(
            self,
            "patterns",
            _sorted_unique_patterns(self.patterns, "PathClassifierV1.patterns"),
        )
        if not self.patterns:
            _policy_error("PathClassifierV1.patterns must not be empty")

    def to_json_dict(self) -> dict[str, object]:
        return {"role": self.role, "patterns": list(self.patterns)}

    @classmethod
    def from_json_dict(cls, value: object) -> "PathClassifierV1":
        raw = exact_object(value, frozenset(cls.FIELDS), "PathClassifierV1")
        return cls(role=raw["role"], patterns=raw["patterns"])


def _validate_evidence_parameters(
    value: object,
    *,
    label: str,
    scope_kind: str,
    roles: tuple[str, ...],
) -> None:
    literal(getattr(value, "parameter_schema"), "evidence-pack-policy-parameters-v1", f"{label}.parameter_schema")
    literal(getattr(value, "scope_kind"), scope_kind, f"{label}.scope_kind")
    literal(getattr(value, "allocation_protocol_id"), "evidence-pack-allocation-v1", f"{label}.allocation_protocol_id")
    priority = _ordered_unique_ids(getattr(value, "role_priority"), f"{label}.role_priority")
    if priority != roles:
        _policy_error(f"{label}.role_priority must equal the literal role order")
    object.__setattr__(value, "role_priority", priority)
    classifiers = getattr(value, "path_classifiers")
    if not isinstance(classifiers, (list, tuple)) or any(
        not isinstance(item, PathClassifierV1) for item in classifiers
    ):
        _policy_error(f"{label}.path_classifiers must contain closed classifiers")
    classifiers = tuple(classifiers)
    object.__setattr__(value, "path_classifiers", classifiers)
    if tuple(item.role for item in classifiers) != roles:
        _policy_error(f"{label}.path_classifiers must occur once in role_priority order")
    reasons = _ordered_unique_ids(
        getattr(value, "omission_reason_codes"),
        f"{label}.omission_reason_codes",
    )
    if reasons != OMISSION_REASON_CODES:
        _policy_error(f"{label}.omission_reason_codes must equal the literal omission order")
    object.__setattr__(value, "omission_reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class SourceEvidencePackPolicyParametersV1:
    parameter_schema: str
    scope_kind: Literal["source"]
    allocation_protocol_id: str
    role_priority: tuple[str, ...]
    path_classifiers: tuple[PathClassifierV1, ...]
    omission_reason_codes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "parameter_schema",
        "scope_kind",
        "allocation_protocol_id",
        "role_priority",
        "path_classifiers",
        "omission_reason_codes",
    )

    def __post_init__(self) -> None:
        _validate_evidence_parameters(
            self,
            label="SourceEvidencePackPolicyParametersV1",
            scope_kind="source",
            roles=SOURCE_EVIDENCE_ROLES,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "parameter_schema": self.parameter_schema,
            "scope_kind": self.scope_kind,
            "allocation_protocol_id": self.allocation_protocol_id,
            "role_priority": list(self.role_priority),
            "path_classifiers": [item.to_json_dict() for item in self.path_classifiers],
            "omission_reason_codes": list(self.omission_reason_codes),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SourceEvidencePackPolicyParametersV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        classifiers = raw["path_classifiers"]
        if not isinstance(classifiers, (list, tuple)):
            _policy_error(f"{cls.__name__}.path_classifiers must be an array")
        return cls(
            parameter_schema=raw["parameter_schema"],
            scope_kind=raw["scope_kind"],
            allocation_protocol_id=raw["allocation_protocol_id"],
            role_priority=raw["role_priority"],
            path_classifiers=tuple(PathClassifierV1.from_json_dict(item) for item in classifiers),
            omission_reason_codes=raw["omission_reason_codes"],
        )


@dataclass(frozen=True, slots=True)
class DomainEvidencePackPolicyParametersV1:
    parameter_schema: str
    scope_kind: Literal["domain"]
    allocation_protocol_id: str
    role_priority: tuple[str, ...]
    path_classifiers: tuple[PathClassifierV1, ...]
    omission_reason_codes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = SourceEvidencePackPolicyParametersV1.FIELDS

    def __post_init__(self) -> None:
        _validate_evidence_parameters(
            self,
            label="DomainEvidencePackPolicyParametersV1",
            scope_kind="domain",
            roles=DOMAIN_EVIDENCE_ROLES,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "parameter_schema": self.parameter_schema,
            "scope_kind": self.scope_kind,
            "allocation_protocol_id": self.allocation_protocol_id,
            "role_priority": list(self.role_priority),
            "path_classifiers": [item.to_json_dict() for item in self.path_classifiers],
            "omission_reason_codes": list(self.omission_reason_codes),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "DomainEvidencePackPolicyParametersV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        classifiers = raw["path_classifiers"]
        if not isinstance(classifiers, (list, tuple)):
            _policy_error(f"{cls.__name__}.path_classifiers must be an array")
        return cls(
            parameter_schema=raw["parameter_schema"],
            scope_kind=raw["scope_kind"],
            allocation_protocol_id=raw["allocation_protocol_id"],
            role_priority=raw["role_priority"],
            path_classifiers=tuple(PathClassifierV1.from_json_dict(item) for item in classifiers),
            omission_reason_codes=raw["omission_reason_codes"],
        )


EvidencePackPolicyParametersV1 = (
    SourceEvidencePackPolicyParametersV1 | DomainEvidencePackPolicyParametersV1
)


@dataclass(frozen=True, slots=True)
class ProjectionPolicyV1:
    protocol_id: str
    surface_priority: tuple[str, ...]
    max_canonical_bytes_per_domain: int
    max_total_canonical_bytes: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "protocol_id",
        "surface_priority",
        "max_canonical_bytes_per_domain",
        "max_total_canonical_bytes",
    )

    def __post_init__(self) -> None:
        literal(self.protocol_id, "domain-projection-v1", "ProjectionPolicyV1.protocol_id")
        priority = _ordered_unique_ids(
            self.surface_priority,
            "ProjectionPolicyV1.surface_priority",
        )
        if priority != PROJECTION_SURFACE_PRIORITY:
            _policy_error("ProjectionPolicyV1.surface_priority must equal the literal priority")
        object.__setattr__(self, "surface_priority", priority)
        literal(
            self.max_canonical_bytes_per_domain,
            2048,
            "ProjectionPolicyV1.max_canonical_bytes_per_domain",
        )
        literal(
            self.max_total_canonical_bytes,
            32768,
            "ProjectionPolicyV1.max_total_canonical_bytes",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "protocol_id": self.protocol_id,
            "surface_priority": list(self.surface_priority),
            "max_canonical_bytes_per_domain": self.max_canonical_bytes_per_domain,
            "max_total_canonical_bytes": self.max_total_canonical_bytes,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ProjectionPolicyV1":
        raw = exact_object(value, frozenset(cls.FIELDS), "ProjectionPolicyV1")
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ContextBundlePolicyParametersV1:
    parameter_schema: str
    target_artifact_kind: Literal["domain-baseline", "source-overview"]
    target_policy_hash: str
    projection: ProjectionPolicyV1 | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "parameter_schema",
        "target_artifact_kind",
        "target_policy_hash",
        "projection",
    )

    def __post_init__(self) -> None:
        literal(
            self.parameter_schema,
            "context-bundle-policy-parameters-v1",
            "ContextBundlePolicyParametersV1.parameter_schema",
        )
        one_of(
            self.target_artifact_kind,
            frozenset({"domain-baseline", "source-overview"}),
            "ContextBundlePolicyParametersV1.target_artifact_kind",
        )
        digest_value(
            self.target_policy_hash,
            "ContextBundlePolicyParametersV1.target_policy_hash",
        )
        if self.target_artifact_kind == "domain-baseline" and self.projection is not None:
            _policy_error("domain-baseline context requires null projection")
        if self.target_artifact_kind == "source-overview" and not isinstance(
            self.projection, ProjectionPolicyV1
        ):
            _policy_error("source-overview context requires the literal projection")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "parameter_schema": self.parameter_schema,
            "target_artifact_kind": self.target_artifact_kind,
            "target_policy_hash": self.target_policy_hash,
            "projection": None if self.projection is None else self.projection.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ContextBundlePolicyParametersV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        projection = raw["projection"]
        return cls(
            parameter_schema=raw["parameter_schema"],
            target_artifact_kind=raw["target_artifact_kind"],
            target_policy_hash=raw["target_policy_hash"],
            projection=None if projection is None else ProjectionPolicyV1.from_json_dict(projection),
        )


@dataclass(frozen=True, slots=True)
class CompactBaselinePolicyParametersV1:
    parameter_schema: str
    artifact_kind: Literal["domain-baseline", "source-overview"]
    surface_order: tuple[str, ...]
    max_claims_per_observed_surface: int
    max_evidence_refs_per_claim: int
    max_unknowns: int
    max_inspected_refs_per_unknown: int
    min_conflicting_evidence_refs: int
    min_statement_utf8_bytes: int
    max_statement_utf8_bytes: int
    min_question_utf8_bytes: int
    max_question_utf8_bytes: int
    raw_candidate_size_multiplier: int
    minimum_utility_rule_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "parameter_schema",
        "artifact_kind",
        "surface_order",
        "max_claims_per_observed_surface",
        "max_evidence_refs_per_claim",
        "max_unknowns",
        "max_inspected_refs_per_unknown",
        "min_conflicting_evidence_refs",
        "min_statement_utf8_bytes",
        "max_statement_utf8_bytes",
        "min_question_utf8_bytes",
        "max_question_utf8_bytes",
        "raw_candidate_size_multiplier",
        "minimum_utility_rule_id",
    )

    def __post_init__(self) -> None:
        literal(
            self.parameter_schema,
            "compact-baseline-policy-parameters-v1",
            "CompactBaselinePolicyParametersV1.parameter_schema",
        )
        one_of(
            self.artifact_kind,
            frozenset({"domain-baseline", "source-overview"}),
            "CompactBaselinePolicyParametersV1.artifact_kind",
        )
        order = _ordered_unique_ids(
            self.surface_order,
            "CompactBaselinePolicyParametersV1.surface_order",
        )
        expected = DOMAIN_SURFACES if self.artifact_kind == "domain-baseline" else SOURCE_OVERVIEW_SURFACES
        if order != expected:
            _policy_error(
                "CompactBaselinePolicyParametersV1.surface_order must equal the literal artifact surface order"
            )
        object.__setattr__(self, "surface_order", order)
        for field in (
            "max_claims_per_observed_surface",
            "max_evidence_refs_per_claim",
            "max_unknowns",
            "max_inspected_refs_per_unknown",
            "min_conflicting_evidence_refs",
            "min_statement_utf8_bytes",
            "max_statement_utf8_bytes",
            "min_question_utf8_bytes",
            "max_question_utf8_bytes",
            "raw_candidate_size_multiplier",
        ):
            positive_int(getattr(self, field), f"CompactBaselinePolicyParametersV1.{field}")
        if self.min_statement_utf8_bytes > self.max_statement_utf8_bytes:
            _policy_error("statement byte limits are reversed")
        if self.min_question_utf8_bytes > self.max_question_utf8_bytes:
            _policy_error("question byte limits are reversed")
        if self.min_conflicting_evidence_refs > self.max_inspected_refs_per_unknown:
            _policy_error("conflicting-evidence minimum exceeds inspected-reference maximum")
        literal(
            self.minimum_utility_rule_id,
            "compact-v1-minimum-utility-v1",
            "CompactBaselinePolicyParametersV1.minimum_utility_rule_id",
        )

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["surface_order"] = list(self.surface_order)
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "CompactBaselinePolicyParametersV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class EmptyPolicyParametersV1:
    FIELDS: ClassVar[tuple[str, ...]] = ()

    def to_json_dict(self) -> dict[str, object]:
        return {}

    @classmethod
    def from_json_dict(cls, value: object) -> "EmptyPolicyParametersV1":
        exact_object(value, frozenset(), cls.__name__)
        return cls()


PolicyParameters = (
    SourceEvidencePackPolicyParametersV1
    | DomainEvidencePackPolicyParametersV1
    | ContextBundlePolicyParametersV1
    | CompactBaselinePolicyParametersV1
    | EmptyPolicyParametersV1
)


@dataclass(frozen=True, slots=True)
class ArtifactPolicyEntryV1:
    artifact_kind: str
    layer: Literal["L0", "L1"]
    content_policy_version: str
    selection_policy_version: str | None
    artifact_schema_version: int
    producer_protocol_version: str
    result_contract_id: str
    canonicalization_id: str
    byte_estimator_id: Literal["utf8-byte-upper-bound-v1"]
    max_canonical_json_bytes: int
    max_rendered_markdown_bytes: int | None
    max_context_bundle_bytes: int | None
    max_conservative_input_tokens: int | None
    required_surfaces: tuple[str, ...]
    evidence_rule_id: str
    ownership_rule_id: str
    minimum_utility_rule_id: str | None
    policy_parameters: PolicyParameters

    FIELDS: ClassVar[tuple[str, ...]] = (
        "artifact_kind",
        "layer",
        "content_policy_version",
        "selection_policy_version",
        "artifact_schema_version",
        "producer_protocol_version",
        "result_contract_id",
        "canonicalization_id",
        "byte_estimator_id",
        "max_canonical_json_bytes",
        "max_rendered_markdown_bytes",
        "max_context_bundle_bytes",
        "max_conservative_input_tokens",
        "required_surfaces",
        "evidence_rule_id",
        "ownership_rule_id",
        "minimum_utility_rule_id",
        "policy_parameters",
    )

    def __post_init__(self) -> None:
        safe_id(self.artifact_kind, "ArtifactPolicyEntryV1.artifact_kind")
        expected = _POLICY_KIND.get(self.artifact_kind)
        if expected is None:
            _policy_error(f"unknown artifact policy kind {self.artifact_kind!r}")
        expected_layer, expected_version, parameter_branch = expected
        literal(self.layer, expected_layer, "ArtifactPolicyEntryV1.layer")
        literal(
            self.content_policy_version,
            expected_version,
            "ArtifactPolicyEntryV1.content_policy_version",
        )
        optional_text(
            self.selection_policy_version,
            "ArtifactPolicyEntryV1.selection_policy_version",
        )
        if parameter_branch in {"source_evidence", "domain_evidence"}:
            literal(
                self.selection_policy_version,
                "evidence-pack-v1",
                "ArtifactPolicyEntryV1.selection_policy_version",
            )
        elif self.selection_policy_version is not None:
            _policy_error("only evidence-pack policies may select content")
        positive_int(
            self.artifact_schema_version,
            "ArtifactPolicyEntryV1.artifact_schema_version",
        )
        for field in (
            "producer_protocol_version",
            "result_contract_id",
            "canonicalization_id",
            "evidence_rule_id",
            "ownership_rule_id",
        ):
            safe_id(getattr(self, field), f"ArtifactPolicyEntryV1.{field}")
        literal(
            self.byte_estimator_id,
            "utf8-byte-upper-bound-v1",
            "ArtifactPolicyEntryV1.byte_estimator_id",
        )
        positive_int(
            self.max_canonical_json_bytes,
            "ArtifactPolicyEntryV1.max_canonical_json_bytes",
        )
        for field in (
            "max_rendered_markdown_bytes",
            "max_context_bundle_bytes",
            "max_conservative_input_tokens",
        ):
            positive_or_none(getattr(self, field), f"ArtifactPolicyEntryV1.{field}")
        surfaces = _ordered_unique_ids(
            self.required_surfaces,
            "ArtifactPolicyEntryV1.required_surfaces",
        )
        object.__setattr__(self, "required_surfaces", surfaces)
        optional_text(
            self.minimum_utility_rule_id,
            "ArtifactPolicyEntryV1.minimum_utility_rule_id",
        )
        branch_types = {
            "source_evidence": SourceEvidencePackPolicyParametersV1,
            "domain_evidence": DomainEvidencePackPolicyParametersV1,
            "context": ContextBundlePolicyParametersV1,
            "compact": CompactBaselinePolicyParametersV1,
            "empty": EmptyPolicyParametersV1,
        }
        if not isinstance(self.policy_parameters, branch_types[parameter_branch]):
            _policy_error(
                f"{self.artifact_kind} requires the closed {parameter_branch} parameter branch"
            )
        if parameter_branch == "compact":
            compact = self.policy_parameters
            assert isinstance(compact, CompactBaselinePolicyParametersV1)
            if compact.artifact_kind != self.artifact_kind:
                _policy_error("compact parameters artifact_kind must match the policy entry")
            if compact.surface_order != self.required_surfaces:
                _policy_error("compact surface_order must equal required_surfaces")
            if compact.minimum_utility_rule_id != self.minimum_utility_rule_id:
                _policy_error("compact minimum utility IDs must match")
        elif self.required_surfaces or self.minimum_utility_rule_id is not None:
            _policy_error("only compact baseline policies declare surfaces or minimum utility")
        if parameter_branch == "context":
            context = self.policy_parameters
            assert isinstance(context, ContextBundlePolicyParametersV1)
            target = (
                "domain-baseline"
                if self.artifact_kind == "domain-context-bundle"
                else "source-overview"
            )
            if context.target_artifact_kind != target:
                _policy_error("context target_artifact_kind does not match the policy entry")

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["required_surfaces"] = list(self.required_surfaces)
        result["policy_parameters"] = self.policy_parameters.to_json_dict()
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "ArtifactPolicyEntryV1":
        try:
            raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
            kind = raw["artifact_kind"]
            if not isinstance(kind, str) or kind not in _POLICY_KIND:
                _policy_error(f"unknown artifact policy kind {kind!r}")
            branch = _POLICY_KIND[kind][2]
            decoder = {
                "source_evidence": SourceEvidencePackPolicyParametersV1.from_json_dict,
                "domain_evidence": DomainEvidencePackPolicyParametersV1.from_json_dict,
                "context": ContextBundlePolicyParametersV1.from_json_dict,
                "compact": CompactBaselinePolicyParametersV1.from_json_dict,
                "empty": EmptyPolicyParametersV1.from_json_dict,
            }[branch]
            data = {field: raw[field] for field in cls.FIELDS}
            data["policy_parameters"] = decoder(data["policy_parameters"])
            return cls(**data)
        except Protocol22PolicyError:
            raise
        except Protocol22SchemaError as exc:
            raise Protocol22PolicyError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ArtifactPolicyCatalogV1:
    schema_version: int
    entries: tuple[ArtifactPolicyEntryV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = ("schema_version", "entries")

    def __post_init__(self) -> None:
        literal(self.schema_version, 1, "ArtifactPolicyCatalogV1.schema_version")
        if not isinstance(self.entries, (list, tuple)) or any(
            not isinstance(entry, ArtifactPolicyEntryV1) for entry in self.entries
        ):
            _policy_error("ArtifactPolicyCatalogV1.entries must contain policy entries")
        object.__setattr__(self, "entries", tuple(self.entries))
        keys = tuple((entry.layer, entry.artifact_kind) for entry in self.entries)
        if keys != tuple(sorted(set(keys))):
            _policy_error("ArtifactPolicyCatalogV1.entries must be sorted and unique")
        if set(keys) != EXPECTED_POLICY_SLOTS:
            _policy_error("ArtifactPolicyCatalogV1.entries must equal the exact graph slots")
        by_kind = {entry.artifact_kind: entry for entry in self.entries}
        for context_kind, target_kind in (
            ("domain-context-bundle", "domain-baseline"),
            ("source-overview-context-bundle", "source-overview"),
        ):
            parameters = by_kind[context_kind].policy_parameters
            assert isinstance(parameters, ContextBundlePolicyParametersV1)
            expected_hash = content_digest(by_kind[target_kind].to_json_dict())
            if parameters.target_policy_hash != expected_hash:
                _policy_error(
                    f"{context_kind} target_policy_hash does not resolve to {target_kind}"
                )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "entries": [entry.to_json_dict() for entry in self.entries],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ArtifactPolicyCatalogV1":
        try:
            raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
            entries = raw["entries"]
            if not isinstance(entries, (list, tuple)):
                _policy_error("ArtifactPolicyCatalogV1.entries must be an array")
            return cls(
                schema_version=raw["schema_version"],
                entries=tuple(ArtifactPolicyEntryV1.from_json_dict(entry) for entry in entries),
            )
        except Protocol22PolicyError:
            raise
        except Protocol22SchemaError as exc:
            raise Protocol22PolicyError(str(exc)) from exc


def layer_policy_hash(entry: ArtifactPolicyEntryV1) -> str:
    if not isinstance(entry, ArtifactPolicyEntryV1):
        _policy_error("layer policy hashing requires an ArtifactPolicyEntryV1")
    return content_digest(entry.to_json_dict())


def policy_for(
    catalog: ArtifactPolicyCatalogV1,
    layer: str,
    artifact_kind: str,
) -> ArtifactPolicyEntryV1:
    for entry in catalog.entries:
        if (entry.layer, entry.artifact_kind) == (layer, artifact_kind):
            return entry
    _policy_error(f"unknown artifact policy slot {(layer, artifact_kind)!r}")


def _classifier(role: str, *patterns: str) -> PathClassifierV1:
    return PathClassifierV1(role=role, patterns=tuple(sorted(patterns)))


def _source_evidence_parameters() -> SourceEvidencePackPolicyParametersV1:
    return SourceEvidencePackPolicyParametersV1(
        parameter_schema="evidence-pack-policy-parameters-v1",
        scope_kind="source",
        allocation_protocol_id="evidence-pack-allocation-v1",
        role_priority=SOURCE_EVIDENCE_ROLES,
        path_classifiers=(
            _classifier(
                "declared_entry_point",
                "**/__main__.py",
                "**/app.*",
                "**/main.*",
                "**/server.*",
                "cmd/**",
            ),
            _classifier(
                "build_runtime",
                "**/Cargo.toml",
                "**/Dockerfile",
                "**/Makefile",
                "**/build.gradle*",
                "**/go.mod",
                "**/package.json",
                "**/pom.xml",
                "**/pyproject.toml",
                "**/requirements*.txt",
            ),
            _classifier(
                "explicit_supporting",
                "**/.env.example",
                "**/config/**",
                "**/migrations/**",
                "**/schema/**",
            ),
            _classifier("documentation", "**/*.md", "**/*.rst", "**/docs/**"),
        ),
        omission_reason_codes=OMISSION_REASON_CODES,
    )


def _domain_evidence_parameters() -> DomainEvidencePackPolicyParametersV1:
    return DomainEvidencePackPolicyParametersV1(
        parameter_schema="evidence-pack-policy-parameters-v1",
        scope_kind="domain",
        allocation_protocol_id="evidence-pack-allocation-v1",
        role_priority=DOMAIN_EVIDENCE_ROLES,
        path_classifiers=(
            _classifier(
                "explicit_supporting",
                "**/.env.example",
                "**/config/**",
                "**/migrations/**",
                "**/schema/**",
            ),
            _classifier(
                "entry_point",
                "**/__main__.py",
                "**/app.*",
                "**/handler.*",
                "**/main.*",
                "**/routes.*",
            ),
            _classifier(
                "production",
                "**/*.c",
                "**/*.cpp",
                "**/*.go",
                "**/*.java",
                "**/*.js",
                "**/*.kt",
                "**/*.php",
                "**/*.pl",
                "**/*.pm",
                "**/*.py",
                "**/*.rb",
                "**/*.rs",
                "**/*.ts",
            ),
            _classifier(
                "test",
                "**/*_test.*",
                "**/*.spec.*",
                "**/*.test.*",
                "**/test/**",
                "**/tests/**",
            ),
            _classifier("documentation", "**/*.md", "**/*.rst", "**/docs/**"),
            _classifier("other", "**"),
        ),
        omission_reason_codes=OMISSION_REASON_CODES,
    )


def _compact_parameters(artifact_kind: str) -> CompactBaselinePolicyParametersV1:
    return CompactBaselinePolicyParametersV1(
        parameter_schema="compact-baseline-policy-parameters-v1",
        artifact_kind=artifact_kind,
        surface_order=(
            DOMAIN_SURFACES
            if artifact_kind == "domain-baseline"
            else SOURCE_OVERVIEW_SURFACES
        ),
        max_claims_per_observed_surface=24,
        max_evidence_refs_per_claim=8,
        max_unknowns=32,
        max_inspected_refs_per_unknown=8,
        min_conflicting_evidence_refs=2,
        min_statement_utf8_bytes=1,
        max_statement_utf8_bytes=1024,
        min_question_utf8_bytes=1,
        max_question_utf8_bytes=512,
        raw_candidate_size_multiplier=2,
        minimum_utility_rule_id="compact-v1-minimum-utility-v1",
    )


def _entry(
    artifact_kind: str,
    *,
    producer_protocol_version: str,
    result_contract_id: str,
    max_json: int,
    parameters: PolicyParameters,
    selection: str | None = None,
    max_markdown: int | None = None,
    max_context: int | None = None,
    max_tokens: int | None = None,
    required_surfaces: tuple[str, ...] = (),
    evidence_rule_id: str,
    ownership_rule_id: str,
    minimum_utility_rule_id: str | None = None,
) -> ArtifactPolicyEntryV1:
    layer, content_version, _branch = _POLICY_KIND[artifact_kind]
    return ArtifactPolicyEntryV1(
        artifact_kind=artifact_kind,
        layer=layer,
        content_policy_version=content_version,
        selection_policy_version=selection,
        artifact_schema_version=1,
        producer_protocol_version=producer_protocol_version,
        result_contract_id=result_contract_id,
        canonicalization_id="re-v2-canonical-json-v1",
        byte_estimator_id="utf8-byte-upper-bound-v1",
        max_canonical_json_bytes=max_json,
        max_rendered_markdown_bytes=max_markdown,
        max_context_bundle_bytes=max_context,
        max_conservative_input_tokens=max_tokens,
        required_surfaces=required_surfaces,
        evidence_rule_id=evidence_rule_id,
        ownership_rule_id=ownership_rule_id,
        minimum_utility_rule_id=minimum_utility_rule_id,
        policy_parameters=parameters,
    )


def build_compact_v1_policy_catalog() -> ArtifactPolicyCatalogV1:
    empty = EmptyPolicyParametersV1()
    domain_compact = _entry(
        "domain-baseline",
        producer_protocol_version="compact-baseline-v1",
        result_contract_id="candidate-ready-v1",
        max_json=32 * 1024,
        max_markdown=96 * 1024,
        max_context=128 * 1024,
        max_tokens=131_072,
        required_surfaces=DOMAIN_SURFACES,
        evidence_rule_id="bounded-context-citations-v1",
        ownership_rule_id="explicit-read-set-v1",
        minimum_utility_rule_id="compact-v1-minimum-utility-v1",
        parameters=_compact_parameters("domain-baseline"),
    )
    source_compact = _entry(
        "source-overview",
        producer_protocol_version="compact-baseline-v1",
        result_contract_id="candidate-ready-v1",
        max_json=48 * 1024,
        max_markdown=96 * 1024,
        max_context=96 * 1024,
        max_tokens=98_304,
        required_surfaces=SOURCE_OVERVIEW_SURFACES,
        evidence_rule_id="bounded-context-citations-v1",
        ownership_rule_id="explicit-read-set-v1",
        minimum_utility_rule_id="compact-v1-minimum-utility-v1",
        parameters=_compact_parameters("source-overview"),
    )
    entries = (
        _entry(
            "source-inventory",
            producer_protocol_version="inventory-v1",
            result_contract_id="deterministic-artifact-v1",
            max_json=16 * 1024 * 1024,
            evidence_rule_id="partition-catalog-copy-v1",
            ownership_rule_id="workspace-partition-catalog-v1",
            parameters=empty,
        ),
        _entry(
            "source-partition",
            producer_protocol_version="partition-v1",
            result_contract_id="deterministic-artifact-v1",
            max_json=4 * 1024 * 1024,
            evidence_rule_id="partition-catalog-copy-v1",
            ownership_rule_id="workspace-partition-catalog-v1",
            parameters=empty,
        ),
        _entry(
            "domain-inventory",
            producer_protocol_version="inventory-v1",
            result_contract_id="deterministic-artifact-v1",
            max_json=16 * 1024 * 1024,
            evidence_rule_id="partition-catalog-copy-v1",
            ownership_rule_id="workspace-partition-catalog-v1",
            parameters=empty,
        ),
        _entry(
            "source-evidence-pack",
            producer_protocol_version="evidence-pack-v1",
            result_contract_id="deterministic-artifact-v1",
            max_json=48 * 1024,
            max_tokens=48 * 1024,
            selection="evidence-pack-v1",
            evidence_rule_id="bounded-original-lines-v1",
            ownership_rule_id="explicit-read-set-v1",
            parameters=_source_evidence_parameters(),
        ),
        _entry(
            "domain-evidence-pack",
            producer_protocol_version="evidence-pack-v1",
            result_contract_id="deterministic-artifact-v1",
            max_json=96 * 1024,
            max_tokens=96 * 1024,
            selection="evidence-pack-v1",
            evidence_rule_id="bounded-original-lines-v1",
            ownership_rule_id="explicit-read-set-v1",
            parameters=_domain_evidence_parameters(),
        ),
        _entry(
            "domain-context-bundle",
            producer_protocol_version="context-bundle-v1",
            result_contract_id="deterministic-artifact-v1",
            max_json=128 * 1024,
            max_context=128 * 1024,
            max_tokens=131_072,
            evidence_rule_id="accepted-evidence-closure-v1",
            ownership_rule_id="explicit-read-set-v1",
            parameters=ContextBundlePolicyParametersV1(
                parameter_schema="context-bundle-policy-parameters-v1",
                target_artifact_kind="domain-baseline",
                target_policy_hash=layer_policy_hash(domain_compact),
                projection=None,
            ),
        ),
        _entry(
            "source-overview-context-bundle",
            producer_protocol_version="context-bundle-v1",
            result_contract_id="deterministic-artifact-v1",
            max_json=96 * 1024,
            max_context=96 * 1024,
            max_tokens=98_304,
            evidence_rule_id="accepted-evidence-closure-v1",
            ownership_rule_id="explicit-read-set-v1",
            parameters=ContextBundlePolicyParametersV1(
                parameter_schema="context-bundle-policy-parameters-v1",
                target_artifact_kind="source-overview",
                target_policy_hash=layer_policy_hash(source_compact),
                projection=ProjectionPolicyV1(
                    protocol_id="domain-projection-v1",
                    surface_priority=PROJECTION_SURFACE_PRIORITY,
                    max_canonical_bytes_per_domain=2048,
                    max_total_canonical_bytes=32768,
                ),
            ),
        ),
        domain_compact,
        source_compact,
        _entry(
            "source-baseline-root",
            producer_protocol_version="source-baseline-root-v1",
            result_contract_id="deterministic-artifact-v1",
            max_json=4 * 1024 * 1024,
            evidence_rule_id="accepted-baseline-dependency-v1",
            ownership_rule_id="workspace-partition-catalog-v1",
            parameters=empty,
        ),
    )
    return ArtifactPolicyCatalogV1(
        schema_version=1,
        entries=tuple(sorted(entries, key=lambda entry: (entry.layer, entry.artifact_kind))),
    )


__all__ = (
    "ArtifactPolicyCatalogV1",
    "ArtifactPolicyEntryV1",
    "CompactBaselinePolicyParametersV1",
    "ContextBundlePolicyParametersV1",
    "DOMAIN_SURFACES",
    "DomainEvidencePackPolicyParametersV1",
    "EmptyPolicyParametersV1",
    "EvidencePackPolicyParametersV1",
    "PathClassifierV1",
    "PolicyParameters",
    "ProjectionPolicyV1",
    "Protocol22PolicyError",
    "SOURCE_OVERVIEW_SURFACES",
    "SourceEvidencePackPolicyParametersV1",
    "build_compact_v1_policy_catalog",
    "layer_policy_hash",
    "policy_for",
)

"""Strict compact-baseline normalization, certification, and rendering."""

from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import ClassVar, Literal, Mapping
import unicodedata

from harness.re_v2.canonical import canonical_json_bytes, content_digest

from .artifacts import (
    ClaimV1,
    ContextBundleV1,
    DepthDebtV1,
    DeterministicAssessmentInputV2,
    EvidenceExcerptV1,
    EvidenceReferenceV1,
)
from .evidence import EvidenceAuthorityDescriptorV1, evidence_authority_id
from .executors import VerifierAuthorityV1
from .model import ArtifactKeyV2, ArtifactScope, WorkItemV2
from .partition import FileRecordV1, WorkspacePartitionCatalogV1
from .policies import (
    DOMAIN_SURFACES,
    SOURCE_OVERVIEW_SURFACES,
    ArtifactPolicyEntryV1,
    CompactBaselinePolicyParametersV1,
    layer_policy_hash,
)
from .schema import (
    Protocol22SchemaError,
    boolean,
    digest_value,
    exact_object,
    nonnegative_int,
    one_of,
    optional_digest,
    positive_int,
    safe_id,
    load_canonical_object,
    sorted_unique_digests,
)


_BASELINE_KINDS = frozenset({"domain-baseline", "source-overview"})
_SURFACE_STATUS = frozenset({"observed", "not_established"})
_NOT_ESTABLISHED_REASONS = frozenset(
    {"not_in_bounded_context", "requires_deeper_analysis"}
)
_UNKNOWN_REASONS = frozenset(
    {
        "not_in_bounded_context",
        "conflicting_evidence",
        "requires_deeper_analysis",
    }
)
_UTILITY_DIAGNOSTICS = (
    "responsibilities_not_observed",
    "entry_or_behavior_not_observed",
    "purpose_not_observed",
    "runtime_shape_not_observed",
    "boundary_or_relationship_not_observed",
    "no_regular_file_cited",
)
_CERTIFICATION_DIAGNOSTIC_LIMIT = 64
_DEBT_REQUIRED_KINDS = frozenset(
    {
        "source-evidence-pack",
        "domain-evidence-pack",
        "domain-context-bundle",
        "source-overview-context-bundle",
    }
)


class CompactCandidateError(Protocol22SchemaError):
    """Raised when provider-authored compact content violates its closed schema."""


class Protocol22CertificationError(Protocol22SchemaError):
    """Raised when controller certification authority is incoherent."""


class _DuplicateKeyError(ValueError):
    pass


class _IdentityValue:
    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())


def _surface_names(artifact_kind: str) -> tuple[str, ...]:
    if artifact_kind == "domain-baseline":
        return DOMAIN_SURFACES
    if artifact_kind == "source-overview":
        return SOURCE_OVERVIEW_SURFACES
    raise CompactCandidateError(
        f"unsupported compact artifact kind: {artifact_kind!r}"
    )


def _exact(
    value: object,
    fields: tuple[str, ...] | frozenset[str],
    label: str,
    *,
    candidate: bool = False,
) -> Mapping[str, object]:
    try:
        return exact_object(value, frozenset(fields), label)
    except Protocol22SchemaError as exc:
        error = CompactCandidateError if candidate else Protocol22CertificationError
        raise error(str(exc)) from exc


def _normalized_diagnostics(
    values: object,
    field: str,
    *,
    require_empty: bool | None = None,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise Protocol22CertificationError(f"{field} must be an array")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise Protocol22CertificationError(
                f"{field} must contain nonempty strings"
            )
        if (
            value.strip() != value
            or "\r" in value
            or len(value.encode("utf-8")) > 1024
        ):
            raise Protocol22CertificationError(
                f"{field} contains a non-normalized diagnostic"
            )
        result.append(value)
    frozen = tuple(result)
    if (
        frozen != tuple(sorted(set(frozen)))
        or len(frozen) > _CERTIFICATION_DIAGNOSTIC_LIMIT
    ):
        raise Protocol22CertificationError(
            f"{field} must be sorted, unique, and bounded"
        )
    if require_empty is True and frozen:
        raise Protocol22CertificationError(f"{field} must be empty")
    if require_empty is False and not frozen:
        raise Protocol22CertificationError(f"{field} must not be empty")
    return frozen


@dataclass(frozen=True, slots=True)
class SurfaceV1:
    status: Literal["observed", "not_established"]
    items: tuple[ClaimV1, ...]
    not_established_reason_code: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "status",
        "items",
        "not_established_reason_code",
    )

    def __post_init__(self) -> None:
        one_of(self.status, _SURFACE_STATUS, "SurfaceV1.status")
        if not isinstance(self.items, (list, tuple)) or any(
            not isinstance(item, ClaimV1) for item in self.items
        ):
            raise Protocol22SchemaError("SurfaceV1.items must contain ClaimV1 values")
        items = tuple(self.items)
        if len(items) > 24:
            raise Protocol22SchemaError("SurfaceV1 permits at most 24 claims")
        identities = tuple(content_digest(item.to_json_dict()) for item in items)
        if len(identities) != len(set(identities)):
            raise Protocol22SchemaError("SurfaceV1 claims must be unique")
        object.__setattr__(self, "items", items)
        if self.status == "observed":
            if not items or self.not_established_reason_code is not None:
                raise Protocol22SchemaError(
                    "observed SurfaceV1 requires claims and null reason"
                )
        else:
            if items:
                raise Protocol22SchemaError(
                    "not-established SurfaceV1 must have no claims"
                )
            one_of(
                self.not_established_reason_code,
                _NOT_ESTABLISHED_REASONS,
                "SurfaceV1.not_established_reason_code",
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "items": [item.to_json_dict() for item in self.items],
            "not_established_reason_code": self.not_established_reason_code,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SurfaceV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        items = raw["items"]
        if not isinstance(items, (list, tuple)):
            raise Protocol22SchemaError("SurfaceV1.items must be an array")
        return cls(
            status=raw["status"],
            items=tuple(ClaimV1.from_json_dict(item) for item in items),
            not_established_reason_code=raw["not_established_reason_code"],
        )


@dataclass(frozen=True, slots=True)
class UnknownV1:
    question: str
    reason_code: str
    inspected_evidence: tuple[EvidenceReferenceV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "question",
        "reason_code",
        "inspected_evidence",
    )

    def __post_init__(self) -> None:
        _validate_normalized_prose(self.question, "UnknownV1.question", 1, 512)
        one_of(self.reason_code, _UNKNOWN_REASONS, "UnknownV1.reason_code")
        if not isinstance(self.inspected_evidence, (list, tuple)) or any(
            not isinstance(item, EvidenceReferenceV1)
            for item in self.inspected_evidence
        ):
            raise Protocol22SchemaError(
                "UnknownV1.inspected_evidence must contain evidence references"
            )
        evidence = tuple(self.inspected_evidence)
        keys = tuple(item.sort_key for item in evidence)
        if keys != tuple(sorted(set(keys))) or len(evidence) > 8:
            raise Protocol22SchemaError(
                "UnknownV1 inspected evidence must be sorted, unique, and at most eight"
            )
        if self.reason_code == "conflicting_evidence" and len(evidence) < 2:
            raise Protocol22SchemaError(
                "conflicting_evidence unknown requires at least two references"
            )
        object.__setattr__(self, "inspected_evidence", evidence)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "question": self.question,
            "reason_code": self.reason_code,
            "inspected_evidence": [
                item.to_json_dict() for item in self.inspected_evidence
            ],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "UnknownV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        evidence = raw["inspected_evidence"]
        if not isinstance(evidence, (list, tuple)):
            raise Protocol22SchemaError(
                "UnknownV1.inspected_evidence must be an array"
            )
        return cls(
            question=raw["question"],
            reason_code=raw["reason_code"],
            inspected_evidence=tuple(
                EvidenceReferenceV1.from_json_dict(item) for item in evidence
            ),
        )


@dataclass(frozen=True, slots=True)
class NormalizedAuthorialPayloadV1:
    schema_version: int
    artifact_kind: Literal["domain-baseline", "source-overview"]
    surfaces: Mapping[str, SurfaceV1]
    unknowns: tuple[UnknownV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "surfaces",
        "unknowns",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22SchemaError(
                "NormalizedAuthorialPayloadV1.schema_version must be 1"
            )
        one_of(self.artifact_kind, _BASELINE_KINDS, "artifact_kind")
        if not isinstance(self.surfaces, Mapping):
            raise Protocol22SchemaError(
                "NormalizedAuthorialPayloadV1.surfaces must be a mapping"
            )
        expected = _surface_names(self.artifact_kind)
        if frozenset(self.surfaces) != frozenset(expected) or any(
            not isinstance(value, SurfaceV1) for value in self.surfaces.values()
        ):
            raise Protocol22SchemaError(
                "NormalizedAuthorialPayloadV1 surfaces do not match artifact kind"
            )
        ordered = {name: self.surfaces[name] for name in expected}
        object.__setattr__(self, "surfaces", MappingProxyType(ordered))
        if not isinstance(self.unknowns, (list, tuple)) or any(
            not isinstance(item, UnknownV1) for item in self.unknowns
        ):
            raise Protocol22SchemaError(
                "NormalizedAuthorialPayloadV1.unknowns must contain UnknownV1"
            )
        unknowns = tuple(self.unknowns)
        if len(unknowns) > 32:
            raise Protocol22SchemaError(
                "NormalizedAuthorialPayloadV1 permits at most 32 unknowns"
            )
        identities = tuple(content_digest(item.to_json_dict()) for item in unknowns)
        if len(identities) != len(set(identities)):
            raise Protocol22SchemaError(
                "NormalizedAuthorialPayloadV1 unknowns must be unique"
            )
        object.__setattr__(self, "unknowns", unknowns)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "surfaces": {
                name: self.surfaces[name].to_json_dict()
                for name in _surface_names(self.artifact_kind)
            },
            "unknowns": [item.to_json_dict() for item in self.unknowns],
        }

    @classmethod
    def from_json_dict(
        cls,
        value: object,
        artifact_kind: str,
        policy: ArtifactPolicyEntryV1,
    ) -> "NormalizedAuthorialPayloadV1":
        return _decode_authorial_value(value, artifact_kind, policy, normalize=False)


@dataclass(frozen=True, slots=True)
class CompactArtifactEnvelopeV1:
    artifact_kind: Literal["domain-baseline", "source-overview"]
    layer: Literal["L1"]
    scope: ArtifactScope
    partition_id: str
    layer_policy_hash: str
    dependency_hashes: tuple[str, ...]
    context_bundle_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "artifact_kind",
        "layer",
        "scope",
        "partition_id",
        "layer_policy_hash",
        "dependency_hashes",
        "context_bundle_hash",
    )

    def __post_init__(self) -> None:
        one_of(self.artifact_kind, _BASELINE_KINDS, "artifact_kind")
        if self.layer != "L1":
            raise Protocol22SchemaError("compact artifact layer must be L1")
        if not isinstance(self.scope, ArtifactScope) or self.scope.content_id is None:
            raise Protocol22SchemaError(
                "compact artifact requires content-bearing ArtifactScope"
            )
        if (self.artifact_kind == "domain-baseline") != self.scope.is_domain:
            raise Protocol22SchemaError(
                "compact artifact scope does not match artifact kind"
            )
        digest_value(self.partition_id, "compact artifact partition_id")
        digest_value(self.layer_policy_hash, "compact artifact layer_policy_hash")
        object.__setattr__(
            self,
            "dependency_hashes",
            sorted_unique_digests(
                self.dependency_hashes,
                "compact artifact dependency_hashes",
            ),
        )
        digest_value(self.context_bundle_hash, "compact artifact context_bundle_hash")
        if self.dependency_hashes != (self.context_bundle_hash,):
            raise Protocol22SchemaError(
                "compact artifact must depend only on its context bundle"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "artifact_kind": self.artifact_kind,
            "layer": self.layer,
            "scope": self.scope.to_json_dict(),
            "partition_id": self.partition_id,
            "layer_policy_hash": self.layer_policy_hash,
            "dependency_hashes": list(self.dependency_hashes),
            "context_bundle_hash": self.context_bundle_hash,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CompactArtifactEnvelopeV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            artifact_kind=raw["artifact_kind"],
            layer=raw["layer"],
            scope=ArtifactScope.from_json_dict(raw["scope"]),
            partition_id=raw["partition_id"],
            layer_policy_hash=raw["layer_policy_hash"],
            dependency_hashes=raw["dependency_hashes"],
            context_bundle_hash=raw["context_bundle_hash"],
        )


@dataclass(frozen=True, slots=True)
class CompactBaselineArtifactV1:
    schema_version: int
    artifact: CompactArtifactEnvelopeV1
    surfaces: Mapping[str, SurfaceV1]
    unknowns: tuple[UnknownV1, ...]
    depth_debt: DepthDebtV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact",
        "surfaces",
        "unknowns",
        "depth_debt",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22SchemaError(
                "CompactBaselineArtifactV1.schema_version must be 1"
            )
        if not isinstance(self.artifact, CompactArtifactEnvelopeV1):
            raise Protocol22SchemaError(
                "CompactBaselineArtifactV1.artifact must be a compact envelope"
            )
        normalized = NormalizedAuthorialPayloadV1(
            schema_version=1,
            artifact_kind=self.artifact.artifact_kind,
            surfaces=self.surfaces,
            unknowns=self.unknowns,
        )
        object.__setattr__(self, "surfaces", normalized.surfaces)
        object.__setattr__(self, "unknowns", normalized.unknowns)
        if not isinstance(self.depth_debt, DepthDebtV1):
            raise Protocol22SchemaError(
                "CompactBaselineArtifactV1.depth_debt must be DepthDebtV1"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact": self.artifact.to_json_dict(),
            "surfaces": {
                name: self.surfaces[name].to_json_dict()
                for name in _surface_names(self.artifact.artifact_kind)
            },
            "unknowns": [item.to_json_dict() for item in self.unknowns],
            "depth_debt": self.depth_debt.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CompactBaselineArtifactV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        artifact = CompactArtifactEnvelopeV1.from_json_dict(raw["artifact"])
        surfaces = exact_object(
            raw["surfaces"],
            frozenset(_surface_names(artifact.artifact_kind)),
            "CompactBaselineArtifactV1.surfaces",
        )
        unknowns = raw["unknowns"]
        if not isinstance(unknowns, (list, tuple)):
            raise Protocol22SchemaError(
                "CompactBaselineArtifactV1.unknowns must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            artifact=artifact,
            surfaces={
                name: SurfaceV1.from_json_dict(surfaces[name])
                for name in _surface_names(artifact.artifact_kind)
            },
            unknowns=tuple(UnknownV1.from_json_dict(item) for item in unknowns),
            depth_debt=DepthDebtV1.from_json_dict(raw["depth_debt"]),
        )


@dataclass(frozen=True, slots=True)
class CountRatioV1:
    numerator: int
    denominator: int

    FIELDS: ClassVar[tuple[str, ...]] = ("numerator", "denominator")

    def __post_init__(self) -> None:
        nonnegative_int(self.numerator, "CountRatioV1.numerator")
        nonnegative_int(self.denominator, "CountRatioV1.denominator")
        if self.denominator == 0 and self.numerator != 0:
            raise Protocol22CertificationError(
                "zero-denominator CountRatioV1 requires zero numerator"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "CountRatioV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(raw["numerator"], raw["denominator"])


_COVERAGE_COUNT_FIELDS = (
    "inventory_file_count",
    "selected_file_count",
    "referenced_file_count",
    "fully_selected_file_count",
    "partially_selected_file_count",
    "omitted_file_count",
    "omitted_range_count",
)


@dataclass(frozen=True, slots=True)
class CoverageRecordV1:
    universe: Literal[
        "direct_read_set",
        "projected_domain_read_sets",
        "combined_evidence_authority",
    ]
    inventory_file_count: int
    selected_file_count: int
    referenced_file_count: int
    fully_selected_file_count: int
    partially_selected_file_count: int
    omitted_file_count: int
    omitted_range_count: int
    selected_over_inventory: CountRatioV1
    referenced_over_inventory: CountRatioV1
    referenced_over_selected: CountRatioV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "universe",
        *_COVERAGE_COUNT_FIELDS,
        "selected_over_inventory",
        "referenced_over_inventory",
        "referenced_over_selected",
    )

    def __post_init__(self) -> None:
        one_of(
            self.universe,
            frozenset(
                {
                    "direct_read_set",
                    "projected_domain_read_sets",
                    "combined_evidence_authority",
                }
            ),
            "CoverageRecordV1.universe",
        )
        for field in _COVERAGE_COUNT_FIELDS:
            nonnegative_int(getattr(self, field), f"CoverageRecordV1.{field}")
        if self.selected_file_count != (
            self.fully_selected_file_count + self.partially_selected_file_count
        ):
            raise Protocol22CertificationError(
                "CoverageRecordV1 selected file counts do not balance"
            )
        if self.inventory_file_count != (
            self.selected_file_count + self.omitted_file_count
        ):
            raise Protocol22CertificationError(
                "CoverageRecordV1 inventory file counts do not balance"
            )
        if self.referenced_file_count > self.selected_file_count:
            raise Protocol22CertificationError(
                "CoverageRecordV1 referenced files exceed selected files"
            )
        expected_ratios = (
            (
                self.selected_over_inventory,
                self.selected_file_count,
                self.inventory_file_count,
            ),
            (
                self.referenced_over_inventory,
                self.referenced_file_count,
                self.inventory_file_count,
            ),
            (
                self.referenced_over_selected,
                self.referenced_file_count,
                self.selected_file_count,
            ),
        )
        for ratio, numerator, denominator in expected_ratios:
            if not isinstance(ratio, CountRatioV1) or (
                ratio.numerator,
                ratio.denominator,
            ) != (numerator, denominator):
                raise Protocol22CertificationError(
                    "CoverageRecordV1 ratios do not repeat exact counts"
                )

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        for field in (
            "selected_over_inventory",
            "referenced_over_inventory",
            "referenced_over_selected",
        ):
            result[field] = getattr(self, field).to_json_dict()
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "CoverageRecordV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            **{
                field: raw[field]
                for field in cls.FIELDS
                if field
                not in {
                    "selected_over_inventory",
                    "referenced_over_inventory",
                    "referenced_over_selected",
                }
            },
            selected_over_inventory=CountRatioV1.from_json_dict(
                raw["selected_over_inventory"]
            ),
            referenced_over_inventory=CountRatioV1.from_json_dict(
                raw["referenced_over_inventory"]
            ),
            referenced_over_selected=CountRatioV1.from_json_dict(
                raw["referenced_over_selected"]
            ),
        )


@dataclass(frozen=True, slots=True)
class CoverageAssessmentV1:
    direct: CoverageRecordV1
    projected_domains: CoverageRecordV1 | None
    combined: CoverageRecordV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "direct",
        "projected_domains",
        "combined",
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.direct, CoverageRecordV1)
            or self.direct.universe != "direct_read_set"
            or not isinstance(self.combined, CoverageRecordV1)
            or self.combined.universe != "combined_evidence_authority"
        ):
            raise Protocol22CertificationError(
                "CoverageAssessmentV1 has invalid direct or combined universe"
            )
        if self.projected_domains is None:
            for field in _COVERAGE_COUNT_FIELDS:
                if getattr(self.combined, field) != getattr(self.direct, field):
                    raise Protocol22CertificationError(
                        "domain combined coverage must equal direct coverage"
                    )
        else:
            if (
                not isinstance(self.projected_domains, CoverageRecordV1)
                or self.projected_domains.universe
                != "projected_domain_read_sets"
            ):
                raise Protocol22CertificationError(
                    "source projected coverage has invalid universe"
                )
            for field in _COVERAGE_COUNT_FIELDS:
                if getattr(self.combined, field) != (
                    getattr(self.direct, field)
                    + getattr(self.projected_domains, field)
                ):
                    raise Protocol22CertificationError(
                        "source combined coverage must sum direct and projected counts"
                    )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "direct": self.direct.to_json_dict(),
            "projected_domains": (
                None
                if self.projected_domains is None
                else self.projected_domains.to_json_dict()
            ),
            "combined": self.combined.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CoverageAssessmentV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        projected = raw["projected_domains"]
        return cls(
            direct=CoverageRecordV1.from_json_dict(raw["direct"]),
            projected_domains=(
                None
                if projected is None
                else CoverageRecordV1.from_json_dict(projected)
            ),
            combined=CoverageRecordV1.from_json_dict(raw["combined"]),
        )


@dataclass(frozen=True, slots=True)
class RequiredSurfaceRecordV1:
    surface: str
    status: Literal["observed", "not_established"]
    claim_count: int
    minimum_utility_requirement: Literal[
        "required",
        "one_of_entry_or_behavior",
        "one_of_boundary_or_relationship",
        "none",
    ]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "surface",
        "status",
        "claim_count",
        "minimum_utility_requirement",
    )

    def __post_init__(self) -> None:
        safe_id(self.surface, "RequiredSurfaceRecordV1.surface")
        one_of(self.status, _SURFACE_STATUS, "RequiredSurfaceRecordV1.status")
        nonnegative_int(self.claim_count, "RequiredSurfaceRecordV1.claim_count")
        one_of(
            self.minimum_utility_requirement,
            frozenset(
                {
                    "required",
                    "one_of_entry_or_behavior",
                    "one_of_boundary_or_relationship",
                    "none",
                }
            ),
            "RequiredSurfaceRecordV1.minimum_utility_requirement",
        )
        if (self.status == "observed") != (self.claim_count > 0):
            raise Protocol22CertificationError(
                "required-surface status and claim count disagree"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "RequiredSurfaceRecordV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class MinimumUtilityAssessmentV1:
    rule_id: Literal["compact-v1-minimum-utility-v1"]
    passed: bool
    diagnostic_codes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "rule_id",
        "passed",
        "diagnostic_codes",
    )

    def __post_init__(self) -> None:
        if self.rule_id != "compact-v1-minimum-utility-v1":
            raise Protocol22CertificationError(
                "MinimumUtilityAssessmentV1 rule_id is unsupported"
            )
        boolean(self.passed, "MinimumUtilityAssessmentV1.passed")
        if not isinstance(self.diagnostic_codes, (list, tuple)):
            raise Protocol22CertificationError(
                "minimum-utility diagnostic codes must be an array"
            )
        codes = tuple(self.diagnostic_codes)
        if any(code not in _UTILITY_DIAGNOSTICS for code in codes):
            raise Protocol22CertificationError(
                "minimum-utility diagnostic code is unsupported"
            )
        order = tuple(_UTILITY_DIAGNOSTICS.index(code) for code in codes)
        if order != tuple(sorted(set(order))) or self.passed != (not codes):
            raise Protocol22CertificationError(
                "minimum-utility diagnostics violate declaration order or verdict"
            )
        object.__setattr__(self, "diagnostic_codes", codes)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "passed": self.passed,
            "diagnostic_codes": list(self.diagnostic_codes),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "MinimumUtilityAssessmentV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(raw["rule_id"], raw["passed"], raw["diagnostic_codes"])


@dataclass(frozen=True, slots=True)
class CompactCertificationAssessmentV2:
    assessment_kind: Literal["compact_baseline"]
    coverage: CoverageAssessmentV1
    depth_debt: DepthDebtV1
    required_surfaces: tuple[RequiredSurfaceRecordV1, ...]
    minimum_utility: MinimumUtilityAssessmentV1
    normalized_diagnostics: tuple[str, ...]
    semantic_status: Literal["unaudited"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "assessment_kind",
        "coverage",
        "depth_debt",
        "required_surfaces",
        "minimum_utility",
        "normalized_diagnostics",
        "semantic_status",
    )

    def __post_init__(self) -> None:
        if self.assessment_kind != "compact_baseline":
            raise Protocol22CertificationError(
                "compact assessment kind must be compact_baseline"
            )
        if not isinstance(self.coverage, CoverageAssessmentV1):
            raise Protocol22CertificationError(
                "compact assessment requires coverage"
            )
        if not isinstance(self.depth_debt, DepthDebtV1):
            raise Protocol22CertificationError(
                "compact assessment requires depth debt"
            )
        if not isinstance(self.required_surfaces, (list, tuple)) or any(
            not isinstance(item, RequiredSurfaceRecordV1)
            for item in self.required_surfaces
        ):
            raise Protocol22CertificationError(
                "compact required_surfaces must contain closed records"
            )
        object.__setattr__(self, "required_surfaces", tuple(self.required_surfaces))
        if not isinstance(self.minimum_utility, MinimumUtilityAssessmentV1):
            raise Protocol22CertificationError(
                "compact assessment requires minimum utility"
            )
        diagnostics = _normalized_diagnostics(
            self.normalized_diagnostics,
            "CompactCertificationAssessmentV2.normalized_diagnostics",
        )
        if self.minimum_utility.passed == (
            "minimum_utility_not_met" in diagnostics
        ):
            raise Protocol22CertificationError(
                "compact diagnostics disagree with minimum utility"
            )
        if self.semantic_status != "unaudited":
            raise Protocol22CertificationError(
                "compact semantic status must be unaudited"
            )
        object.__setattr__(self, "normalized_diagnostics", diagnostics)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "assessment_kind": self.assessment_kind,
            "coverage": self.coverage.to_json_dict(),
            "depth_debt": self.depth_debt.to_json_dict(),
            "required_surfaces": [
                item.to_json_dict() for item in self.required_surfaces
            ],
            "minimum_utility": self.minimum_utility.to_json_dict(),
            "normalized_diagnostics": list(self.normalized_diagnostics),
            "semantic_status": self.semantic_status,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CompactCertificationAssessmentV2":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        required = raw["required_surfaces"]
        if not isinstance(required, (list, tuple)):
            raise Protocol22CertificationError(
                "compact required_surfaces must be an array"
            )
        return cls(
            assessment_kind=raw["assessment_kind"],
            coverage=CoverageAssessmentV1.from_json_dict(raw["coverage"]),
            depth_debt=DepthDebtV1.from_json_dict(raw["depth_debt"]),
            required_surfaces=tuple(
                RequiredSurfaceRecordV1.from_json_dict(item) for item in required
            ),
            minimum_utility=MinimumUtilityAssessmentV1.from_json_dict(
                raw["minimum_utility"]
            ),
            normalized_diagnostics=raw["normalized_diagnostics"],
            semantic_status=raw["semantic_status"],
        )


@dataclass(frozen=True, slots=True)
class DeterministicCertificationAssessmentV2:
    assessment_kind: Literal["deterministic_artifact"]
    artifact_kind: str
    canonical_schema_valid: bool
    dependency_closure_valid: bool
    policy_conformance_valid: bool
    depth_debt: DepthDebtV1 | None
    normalized_diagnostics: tuple[str, ...]
    semantic_status: Literal["not_applicable"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "assessment_kind",
        "artifact_kind",
        "canonical_schema_valid",
        "dependency_closure_valid",
        "policy_conformance_valid",
        "depth_debt",
        "normalized_diagnostics",
        "semantic_status",
    )

    def __post_init__(self) -> None:
        if self.assessment_kind != "deterministic_artifact":
            raise Protocol22CertificationError(
                "deterministic assessment kind is invalid"
            )
        safe_id(self.artifact_kind, "deterministic assessment artifact_kind")
        for field in (
            "canonical_schema_valid",
            "dependency_closure_valid",
            "policy_conformance_valid",
        ):
            boolean(getattr(self, field), f"deterministic assessment {field}")
        if self.depth_debt is not None and not isinstance(self.depth_debt, DepthDebtV1):
            raise Protocol22CertificationError(
                "deterministic assessment depth_debt is invalid"
            )
        passed = (
            self.canonical_schema_valid
            and self.dependency_closure_valid
            and self.policy_conformance_valid
        )
        diagnostics = _normalized_diagnostics(
            self.normalized_diagnostics,
            "DeterministicCertificationAssessmentV2.normalized_diagnostics",
            require_empty=passed,
        )
        if not passed and not diagnostics:
            raise Protocol22CertificationError(
                "rejected deterministic assessment requires diagnostics"
            )
        if self.semantic_status != "not_applicable":
            raise Protocol22CertificationError(
                "deterministic semantic status must be not_applicable"
            )
        object.__setattr__(self, "normalized_diagnostics", diagnostics)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "assessment_kind": self.assessment_kind,
            "artifact_kind": self.artifact_kind,
            "canonical_schema_valid": self.canonical_schema_valid,
            "dependency_closure_valid": self.dependency_closure_valid,
            "policy_conformance_valid": self.policy_conformance_valid,
            "depth_debt": (
                None if self.depth_debt is None else self.depth_debt.to_json_dict()
            ),
            "normalized_diagnostics": list(self.normalized_diagnostics),
            "semantic_status": self.semantic_status,
        }

    @classmethod
    def from_json_dict(
        cls,
        value: object,
    ) -> "DeterministicCertificationAssessmentV2":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        debt = raw["depth_debt"]
        return cls(
            **{
                field: raw[field]
                for field in cls.FIELDS
                if field != "depth_debt"
            },
            depth_debt=None if debt is None else DepthDebtV1.from_json_dict(debt),
        )


CertificationAssessmentV2 = (
    CompactCertificationAssessmentV2 | DeterministicCertificationAssessmentV2
)


@dataclass(frozen=True, slots=True)
class CertificationKeyV2(_IdentityValue):
    identity_schema_version: int
    artifact_hash: str
    artifact_key: ArtifactKeyV2
    verifier_id: str
    verifier_version: str
    verifier_implementation_digest: str
    scoped_content_id: str | None
    audit_epoch_id: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "identity_schema_version",
        "artifact_hash",
        "artifact_key",
        "verifier_id",
        "verifier_version",
        "verifier_implementation_digest",
        "scoped_content_id",
        "audit_epoch_id",
    )

    def __post_init__(self) -> None:
        if self.identity_schema_version != 2 or isinstance(
            self.identity_schema_version, bool
        ):
            raise Protocol22CertificationError(
                "CertificationKeyV2.identity_schema_version must be 2"
            )
        digest_value(self.artifact_hash, "CertificationKeyV2.artifact_hash")
        if not isinstance(self.artifact_key, ArtifactKeyV2):
            raise Protocol22CertificationError(
                "CertificationKeyV2.artifact_key must be ArtifactKeyV2"
            )
        safe_id(self.verifier_id, "CertificationKeyV2.verifier_id")
        safe_id(self.verifier_version, "CertificationKeyV2.verifier_version")
        digest_value(
            self.verifier_implementation_digest,
            "CertificationKeyV2.verifier_implementation_digest",
        )
        optional_digest(self.scoped_content_id, "CertificationKeyV2.scoped_content_id")
        if self.scoped_content_id != self.artifact_key.scope.content_id:
            raise Protocol22CertificationError(
                "CertificationKeyV2 scoped content ID does not match artifact scope"
            )
        if self.audit_epoch_id is not None:
            safe_id(self.audit_epoch_id, "CertificationKeyV2.audit_epoch_id")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "identity_schema_version": self.identity_schema_version,
            "artifact_hash": self.artifact_hash,
            "artifact_key": self.artifact_key.to_json_dict(),
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "verifier_implementation_digest": self.verifier_implementation_digest,
            "scoped_content_id": self.scoped_content_id,
            "audit_epoch_id": self.audit_epoch_id,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CertificationKeyV2":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            **{
                field: raw[field]
                for field in cls.FIELDS
                if field != "artifact_key"
            },
            artifact_key=ArtifactKeyV2.from_json_dict(raw["artifact_key"]),
        )


@dataclass(frozen=True, slots=True)
class CertificationReceiptV2(_IdentityValue):
    schema_version: int
    certification_key: CertificationKeyV2
    verdict: Literal["accepted", "rejected"]
    assessment: CertificationAssessmentV2

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "certification_key",
        "verdict",
        "assessment",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 2 or isinstance(self.schema_version, bool):
            raise Protocol22CertificationError(
                "CertificationReceiptV2.schema_version must be 2"
            )
        if not isinstance(self.certification_key, CertificationKeyV2):
            raise Protocol22CertificationError(
                "CertificationReceiptV2 requires CertificationKeyV2"
            )
        one_of(self.verdict, frozenset({"accepted", "rejected"}), "verdict")
        if not isinstance(
            self.assessment,
            (CompactCertificationAssessmentV2, DeterministicCertificationAssessmentV2),
        ):
            raise Protocol22CertificationError(
                "CertificationReceiptV2 assessment branch is invalid"
            )
        kind = self.certification_key.artifact_key.artifact_kind
        if isinstance(self.assessment, CompactCertificationAssessmentV2):
            if kind not in _BASELINE_KINDS:
                raise Protocol22CertificationError(
                    "compact assessment requires a compact artifact kind"
                )
            accepted = (
                not self.assessment.normalized_diagnostics
                and self.assessment.minimum_utility.passed
            )
        else:
            if self.assessment.artifact_kind != kind or kind in _BASELINE_KINDS:
                raise Protocol22CertificationError(
                    "deterministic assessment artifact kind mismatch"
                )
            accepted = (
                self.assessment.canonical_schema_valid
                and self.assessment.dependency_closure_valid
                and self.assessment.policy_conformance_valid
            )
        if (self.verdict == "accepted") != accepted:
            raise Protocol22CertificationError(
                "CertificationReceiptV2 verdict disagrees with assessment"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "certification_key": self.certification_key.to_json_dict(),
            "verdict": self.verdict,
            "assessment": self.assessment.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CertificationReceiptV2":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        assessment = raw["assessment"]
        if not isinstance(assessment, Mapping):
            raise Protocol22CertificationError(
                "CertificationReceiptV2.assessment must be an object"
            )
        branch = assessment.get("assessment_kind")
        decoder = (
            CompactCertificationAssessmentV2.from_json_dict
            if branch == "compact_baseline"
            else DeterministicCertificationAssessmentV2.from_json_dict
            if branch == "deterministic_artifact"
            else None
        )
        if decoder is None:
            raise Protocol22CertificationError(
                "CertificationReceiptV2 assessment kind is unsupported"
            )
        return cls(
            schema_version=raw["schema_version"],
            certification_key=CertificationKeyV2.from_json_dict(
                raw["certification_key"]
            ),
            verdict=raw["verdict"],
            assessment=decoder(assessment),
        )


@dataclass(frozen=True, slots=True)
class CandidateAssessmentReceiptV1(_IdentityValue):
    schema_version: int
    candidate_id: str
    work_item_id: str
    execution_capture_hash: str
    normalized_authorial_payload_hash: str | None
    artifact_hash: str | None
    certification_receipt_id: str | None
    outcome: Literal[
        "certified",
        "rejected_before_artifact",
        "rejected_after_artifact",
    ]
    normalized_diagnostics: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "candidate_id",
        "work_item_id",
        "execution_capture_hash",
        "normalized_authorial_payload_hash",
        "artifact_hash",
        "certification_receipt_id",
        "outcome",
        "normalized_diagnostics",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22CertificationError(
                "CandidateAssessmentReceiptV1.schema_version must be 1"
            )
        for field in ("candidate_id", "work_item_id", "execution_capture_hash"):
            digest_value(getattr(self, field), f"CandidateAssessmentReceiptV1.{field}")
        for field in (
            "normalized_authorial_payload_hash",
            "artifact_hash",
            "certification_receipt_id",
        ):
            optional_digest(getattr(self, field), f"CandidateAssessmentReceiptV1.{field}")
        one_of(
            self.outcome,
            frozenset(
                {
                    "certified",
                    "rejected_before_artifact",
                    "rejected_after_artifact",
                }
            ),
            "CandidateAssessmentReceiptV1.outcome",
        )
        diagnostics = _normalized_diagnostics(
            self.normalized_diagnostics,
            "CandidateAssessmentReceiptV1.normalized_diagnostics",
            require_empty=self.outcome == "certified",
        )
        if self.outcome != "certified" and not diagnostics:
            raise Protocol22CertificationError(
                "rejected candidate assessment requires diagnostics"
            )
        if self.outcome == "rejected_before_artifact":
            if self.artifact_hash is not None or self.certification_receipt_id is not None:
                raise Protocol22CertificationError(
                    "pre-artifact rejection requires null artifact and certification"
                )
        elif self.artifact_hash is None or self.certification_receipt_id is None:
            raise Protocol22CertificationError(
                "post-artifact outcomes require artifact and certification IDs"
            )
        if (
            self.normalized_authorial_payload_hash is None
            and self.outcome != "rejected_before_artifact"
        ):
            raise Protocol22CertificationError(
                "post-normalization outcome requires normalized authorial payload hash"
            )
        object.__setattr__(self, "normalized_diagnostics", diagnostics)

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["normalized_diagnostics"] = list(self.normalized_diagnostics)
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "CandidateAssessmentReceiptV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ArtifactAcceptanceReceiptV2(_IdentityValue):
    schema_version: int
    artifact_key: ArtifactKeyV2
    artifact_hash: str
    certification_receipt_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_key",
        "artifact_hash",
        "certification_receipt_id",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 2 or isinstance(self.schema_version, bool):
            raise Protocol22CertificationError(
                "ArtifactAcceptanceReceiptV2.schema_version must be 2"
            )
        if not isinstance(self.artifact_key, ArtifactKeyV2):
            raise Protocol22CertificationError(
                "ArtifactAcceptanceReceiptV2 requires ArtifactKeyV2"
            )
        digest_value(self.artifact_hash, "ArtifactAcceptanceReceiptV2.artifact_hash")
        digest_value(
            self.certification_receipt_id,
            "ArtifactAcceptanceReceiptV2.certification_receipt_id",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_key": self.artifact_key.to_json_dict(),
            "artifact_hash": self.artifact_hash,
            "certification_receipt_id": self.certification_receipt_id,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ArtifactAcceptanceReceiptV2":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            artifact_key=ArtifactKeyV2.from_json_dict(raw["artifact_key"]),
            artifact_hash=raw["artifact_hash"],
            certification_receipt_id=raw["certification_receipt_id"],
        )


@dataclass(frozen=True, slots=True)
class CompactCandidateInputV1:
    candidate_id: str
    execution_capture_hash: str
    authorial_payload: NormalizedAuthorialPayloadV1

    def __post_init__(self) -> None:
        digest_value(self.candidate_id, "CompactCandidateInputV1.candidate_id")
        digest_value(
            self.execution_capture_hash,
            "CompactCandidateInputV1.execution_capture_hash",
        )
        if not isinstance(self.authorial_payload, NormalizedAuthorialPayloadV1):
            raise Protocol22CertificationError(
                "CompactCandidateInputV1 requires normalized authorial payload"
            )


@dataclass(frozen=True, slots=True)
class CompactCertificationResultV2:
    artifact_bytes: bytes
    certification: CertificationReceiptV2
    candidate_assessment: CandidateAssessmentReceiptV1

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_bytes, bytes):
            raise Protocol22CertificationError(
                "CompactCertificationResultV2.artifact_bytes must be bytes"
            )
        if not isinstance(self.certification, CertificationReceiptV2):
            raise Protocol22CertificationError(
                "CompactCertificationResultV2.certification is invalid"
            )
        if not isinstance(self.candidate_assessment, CandidateAssessmentReceiptV1):
            raise Protocol22CertificationError(
                "CompactCertificationResultV2.candidate_assessment is invalid"
            )
        artifact_hash = content_digest(self.artifact_bytes)
        if (
            self.certification.certification_key.artifact_hash != artifact_hash
            or self.candidate_assessment.artifact_hash != artifact_hash
            or self.candidate_assessment.certification_receipt_id
            != self.certification.identity
        ):
            raise Protocol22CertificationError(
                "compact certification result links do not match artifact bytes"
            )


def parse_authorial_candidate(
    raw: bytes,
    artifact_kind: str,
    policy: ArtifactPolicyEntryV1,
) -> NormalizedAuthorialPayloadV1:
    """Strictly parse and normalize only the provider-owned compact payload."""
    if not isinstance(raw, bytes):
        raise CompactCandidateError("raw candidate must be bytes")
    _validate_compact_policy(artifact_kind, policy, candidate=True)
    parameters = policy.policy_parameters
    if not isinstance(parameters, CompactBaselinePolicyParametersV1):
        raise CompactCandidateError("compact policy parameters are unavailable")
    raw_limit = parameters.raw_candidate_size_multiplier * policy.max_canonical_json_bytes
    if len(raw) > raw_limit:
        raise CompactCandidateError("raw candidate exceeds its pre-parse size limit")
    value = _load_strict_json(raw)
    normalized = _decode_authorial_value(value, artifact_kind, policy, normalize=True)
    if len(canonical_json_bytes(normalized.to_json_dict())) > policy.max_canonical_json_bytes:
        raise CompactCandidateError(
            "normalized authorial payload exceeds final artifact byte limit"
        )
    return normalized


def _load_strict_json(raw: bytes) -> object:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CompactCandidateError("candidate is not strict UTF-8") from exc

    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateKeyError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        return json.loads(
            text,
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except _DuplicateKeyError as exc:
        raise CompactCandidateError(str(exc)) from exc
    except (ValueError, TypeError, RecursionError) as exc:
        raise CompactCandidateError(f"invalid finite candidate JSON: {exc}") from exc


def _validate_compact_policy(
    artifact_kind: str,
    policy: ArtifactPolicyEntryV1,
    *,
    candidate: bool,
) -> None:
    error = CompactCandidateError if candidate else Protocol22CertificationError
    if artifact_kind not in _BASELINE_KINDS:
        raise error(f"unsupported compact artifact kind: {artifact_kind!r}")
    if not isinstance(policy, ArtifactPolicyEntryV1):
        raise error("compact operation requires ArtifactPolicyEntryV1")
    if (
        policy.artifact_kind != artifact_kind
        or policy.layer != "L1"
        or policy.content_policy_version != "compact-v1"
        or not isinstance(policy.policy_parameters, CompactBaselinePolicyParametersV1)
    ):
        raise error("compact policy does not match artifact kind")


def _decode_authorial_value(
    value: object,
    artifact_kind: str,
    policy: ArtifactPolicyEntryV1,
    *,
    normalize: bool,
) -> NormalizedAuthorialPayloadV1:
    _validate_compact_policy(artifact_kind, policy, candidate=True)
    parameters = policy.policy_parameters
    if not isinstance(parameters, CompactBaselinePolicyParametersV1):
        raise CompactCandidateError("compact policy parameters are invalid")
    raw = _exact(
        value,
        NormalizedAuthorialPayloadV1.FIELDS,
        "authorial candidate",
        candidate=True,
    )
    if raw["schema_version"] != 1 or isinstance(raw["schema_version"], bool):
        raise CompactCandidateError("authorial schema_version must be 1")
    surface_values = _exact(
        raw["surfaces"],
        parameters.surface_order,
        "authorial candidate surfaces",
        candidate=True,
    )
    surfaces = {
        surface: _decode_candidate_surface(
            surface_values[surface],
            surface,
            parameters,
            normalize=normalize,
        )
        for surface in parameters.surface_order
    }
    unknown_values = raw["unknowns"]
    if not isinstance(unknown_values, (list, tuple)):
        raise CompactCandidateError("authorial unknowns must be an array")
    if len(unknown_values) > parameters.max_unknowns:
        raise CompactCandidateError(
            f"authorial candidate permits at most {parameters.max_unknowns} unknowns"
        )
    unknowns = tuple(
        _decode_candidate_unknown(item, parameters, normalize=normalize)
        for item in unknown_values
    )
    identities = tuple(content_digest(item.to_json_dict()) for item in unknowns)
    if len(identities) != len(set(identities)):
        raise CompactCandidateError(
            "authorial candidate has duplicate unknowns after normalization"
        )
    try:
        return NormalizedAuthorialPayloadV1(
            schema_version=1,
            artifact_kind=artifact_kind,
            surfaces=surfaces,
            unknowns=unknowns,
        )
    except Protocol22SchemaError as exc:
        raise CompactCandidateError(str(exc)) from exc


def _decode_candidate_surface(
    value: object,
    surface: str,
    policy: CompactBaselinePolicyParametersV1,
    *,
    normalize: bool,
) -> SurfaceV1:
    raw = _exact(
        value,
        SurfaceV1.FIELDS,
        f"authorial surface {surface}",
        candidate=True,
    )
    status = raw["status"]
    if not isinstance(status, str) or status not in _SURFACE_STATUS:
        raise CompactCandidateError(f"authorial surface {surface} has invalid status")
    items = raw["items"]
    if not isinstance(items, (list, tuple)):
        raise CompactCandidateError(
            f"authorial surface {surface} items must be an array"
        )
    if len(items) > policy.max_claims_per_observed_surface:
        raise CompactCandidateError(
            f"authorial surface {surface} exceeds 24 claim limit"
        )
    claims = tuple(
        _decode_candidate_claim(item, policy, normalize=normalize) for item in items
    )
    identities = tuple(content_digest(item.to_json_dict()) for item in claims)
    if len(identities) != len(set(identities)):
        raise CompactCandidateError(
            f"authorial surface {surface} has duplicate claims after normalization"
        )
    reason = raw["not_established_reason_code"]
    if status == "observed":
        if not claims or reason is not None:
            raise CompactCandidateError(
                f"observed authorial surface {surface} requires claims and null reason"
            )
    elif claims or reason not in _NOT_ESTABLISHED_REASONS:
        raise CompactCandidateError(
            f"not-established authorial surface {surface} has invalid claims or reason"
        )
    try:
        return SurfaceV1(status, claims, reason)
    except Protocol22SchemaError as exc:
        raise CompactCandidateError(str(exc)) from exc


def _decode_candidate_claim(
    value: object,
    policy: CompactBaselinePolicyParametersV1,
    *,
    normalize: bool,
) -> ClaimV1:
    raw = _exact(value, ClaimV1.FIELDS, "authorial claim", candidate=True)
    statement = _candidate_prose(
        raw["statement"],
        "claim statement",
        policy.min_statement_utf8_bytes,
        policy.max_statement_utf8_bytes,
        normalize=normalize,
    )
    evidence = _decode_candidate_evidence_array(
        raw["evidence"],
        "claim evidence",
        maximum=policy.max_evidence_refs_per_claim,
        minimum=1,
    )
    try:
        return ClaimV1(statement=statement, evidence=evidence)
    except Protocol22SchemaError as exc:
        raise CompactCandidateError(str(exc)) from exc


def _decode_candidate_unknown(
    value: object,
    policy: CompactBaselinePolicyParametersV1,
    *,
    normalize: bool,
) -> UnknownV1:
    raw = _exact(value, UnknownV1.FIELDS, "authorial unknown", candidate=True)
    question = _candidate_prose(
        raw["question"],
        "unknown question",
        policy.min_question_utf8_bytes,
        policy.max_question_utf8_bytes,
        normalize=normalize,
    )
    reason = raw["reason_code"]
    if not isinstance(reason, str) or reason not in _UNKNOWN_REASONS:
        raise CompactCandidateError("authorial unknown reason_code is invalid")
    minimum = policy.min_conflicting_evidence_refs if reason == "conflicting_evidence" else 0
    evidence = _decode_candidate_evidence_array(
        raw["inspected_evidence"],
        "unknown inspected evidence",
        maximum=policy.max_inspected_refs_per_unknown,
        minimum=minimum,
    )
    try:
        return UnknownV1(question, reason, evidence)
    except Protocol22SchemaError as exc:
        raise CompactCandidateError(str(exc)) from exc


def _decode_candidate_evidence_array(
    value: object,
    field: str,
    *,
    maximum: int,
    minimum: int,
) -> tuple[EvidenceReferenceV1, ...]:
    if not isinstance(value, (list, tuple)):
        raise CompactCandidateError(f"{field} must be an array")
    if not minimum <= len(value) <= maximum:
        qualifier = "two" if minimum == 2 else str(minimum)
        raise CompactCandidateError(
            f"{field} requires {qualifier} to {maximum} evidence references"
        )
    try:
        evidence = tuple(EvidenceReferenceV1.from_json_dict(item) for item in value)
    except Protocol22SchemaError as exc:
        raise CompactCandidateError(str(exc)) from exc
    ordered = tuple(sorted(evidence, key=lambda item: item.sort_key))
    if len({item.sort_key for item in ordered}) != len(ordered):
        raise CompactCandidateError(f"{field} contains duplicate references")
    return ordered


def _candidate_prose(
    value: object,
    field: str,
    minimum: int,
    maximum: int,
    *,
    normalize: bool,
) -> str:
    if not isinstance(value, str):
        raise CompactCandidateError(f"{field} must be a string")
    try:
        text = (
            unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
            if normalize
            else value
        )
        _validate_normalized_prose(text, field, minimum, maximum)
    except (UnicodeError, Protocol22SchemaError) as exc:
        raise CompactCandidateError(str(exc)) from exc
    return text


def _validate_normalized_prose(
    value: object,
    field: str,
    minimum: int,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise Protocol22SchemaError(f"{field} must be a string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise Protocol22SchemaError(f"{field} contains an invalid Unicode surrogate") from exc
    if (
        not minimum <= len(encoded) <= maximum
        or value.strip() != value
        or "\r" in value
        or unicodedata.normalize("NFC", value) != value
    ):
        raise Protocol22SchemaError(
            f"{field} must be nonempty normalized prose within {maximum} UTF-8 bytes"
        )
    if any(unicodedata.category(character) == "Cc" and character != "\n" for character in value):
        raise Protocol22SchemaError(f"{field} contains a disallowed control character")
    return value


@dataclass(frozen=True, slots=True)
class _EvidenceAuthority:
    source_id: str
    excerpt: EvidenceExcerptV1
    record: FileRecordV1

    @property
    def authority_kind(self) -> Literal["direct", "domain_projection"]:
        return (
            "domain_projection"
            if self.excerpt.ownership == "domain_projection"
            else "direct"
        )

    @property
    def key(self) -> tuple[str, str, str, str | None]:
        return (
            self.source_id,
            self.excerpt.source_relative_path,
            self.authority_kind,
            self.excerpt.origin_domain_key,
        )


def certify_compact_candidate(
    candidate: CompactCandidateInputV1,
    work_item: WorkItemV2,
    context: ContextBundleV1,
    snapshot: object,
    verifier: VerifierAuthorityV1,
) -> CompactCertificationResultV2:
    """Construct and deterministically certify one normalized compact candidate."""
    _validate_compact_invocation(candidate, work_item, context, snapshot, verifier)
    policy = context.target_artifact_policy
    context_bytes = canonical_json_bytes(context.to_json_dict())
    context_hash = content_digest(context_bytes)
    artifact = CompactBaselineArtifactV1(
        schema_version=1,
        artifact=CompactArtifactEnvelopeV1(
            artifact_kind=work_item.output_key.artifact_kind,
            layer="L1",
            scope=work_item.output_key.scope,
            partition_id=work_item.output_key.partition_id,
            layer_policy_hash=work_item.output_key.layer_policy_hash,
            dependency_hashes=work_item.output_key.dependency_hashes,
            context_bundle_hash=context_hash,
        ),
        surfaces=candidate.authorial_payload.surfaces,
        unknowns=candidate.authorial_payload.unknowns,
        depth_debt=context.depth_debt,
    )
    artifact_bytes = canonical_json_bytes(artifact.to_json_dict())

    authorities, invalid_evidence = _validate_context_and_references(
        candidate.authorial_payload,
        context,
        snapshot,
    )
    referenced_keys = _referenced_authority_keys(
        candidate.authorial_payload,
        authorities,
    )
    coverage = _coverage_assessment(context, referenced_keys)
    required_surfaces, minimum_utility = _minimum_utility(
        candidate.authorial_payload,
        context,
        bool(referenced_keys),
    )

    diagnostics: list[str] = []
    if len(artifact_bytes) > policy.max_canonical_json_bytes:
        diagnostics.append("artifact_bound_exceeded")
    if invalid_evidence:
        diagnostics.append("evidence_contract_invalid")
    if not minimum_utility.passed:
        diagnostics.append("minimum_utility_not_met")
    normalized_diagnostics = tuple(sorted(diagnostics))
    assessment = CompactCertificationAssessmentV2(
        assessment_kind="compact_baseline",
        coverage=coverage,
        depth_debt=context.depth_debt,
        required_surfaces=required_surfaces,
        minimum_utility=minimum_utility,
        normalized_diagnostics=normalized_diagnostics,
        semantic_status="unaudited",
    )
    artifact_hash = content_digest(artifact_bytes)
    certification = CertificationReceiptV2(
        schema_version=2,
        certification_key=_certification_key(work_item, artifact_hash, verifier),
        verdict="accepted" if not normalized_diagnostics else "rejected",
        assessment=assessment,
    )
    candidate_assessment = CandidateAssessmentReceiptV1(
        schema_version=1,
        candidate_id=candidate.candidate_id,
        work_item_id=work_item.work_item_id,
        execution_capture_hash=candidate.execution_capture_hash,
        normalized_authorial_payload_hash=content_digest(
            candidate.authorial_payload.to_json_dict()
        ),
        artifact_hash=artifact_hash,
        certification_receipt_id=certification.identity,
        outcome=(
            "certified"
            if certification.verdict == "accepted"
            else "rejected_after_artifact"
        ),
        normalized_diagnostics=normalized_diagnostics,
    )
    return CompactCertificationResultV2(
        artifact_bytes=artifact_bytes,
        certification=certification,
        candidate_assessment=candidate_assessment,
    )


def _validate_compact_invocation(
    candidate: CompactCandidateInputV1,
    work_item: WorkItemV2,
    context: ContextBundleV1,
    snapshot: object,
    verifier: VerifierAuthorityV1,
) -> None:
    if not isinstance(candidate, CompactCandidateInputV1):
        raise Protocol22CertificationError(
            "compact certification requires CompactCandidateInputV1"
        )
    if not isinstance(work_item, WorkItemV2):
        raise Protocol22CertificationError(
            "compact certification requires WorkItemV2"
        )
    if not isinstance(context, ContextBundleV1):
        raise Protocol22CertificationError(
            "compact certification requires ContextBundleV1"
        )
    if not isinstance(verifier, VerifierAuthorityV1):
        raise Protocol22CertificationError(
            "compact certification requires VerifierAuthorityV1"
        )
    if not callable(getattr(snapshot, "read_file", None)) or not isinstance(
        getattr(snapshot, "partition", None),
        WorkspacePartitionCatalogV1,
    ):
        raise Protocol22CertificationError(
            "compact certification requires a partition-bound snapshot reader"
        )

    kind = work_item.output_key.artifact_kind
    _validate_compact_policy(kind, context.target_artifact_policy, candidate=False)
    if candidate.authorial_payload.artifact_kind != kind:
        raise Protocol22CertificationError(
            "candidate artifact kind does not match work item"
        )
    context_hash = content_digest(context.to_json_dict())
    expected = {
        "goal_id": "baseline",
        "producer_id": "compact-baseline-producer-v1",
        "producer_family": "compact-baseline",
        "producer_protocol_version": context.target_artifact_policy.producer_protocol_version,
        "result_contract_id": context.target_artifact_policy.result_contract_id,
    }
    for field, value in expected.items():
        if getattr(work_item, field) != value:
            raise Protocol22CertificationError(
                f"work item {field} does not match compact policy"
            )
    if (
        work_item.output_key.layer != "L1"
        or work_item.output_key.scope != context.scope
        or work_item.output_key.partition_id is None
        or work_item.output_key.layer_policy_hash != context.target_policy_hash
        or work_item.output_key.layer_policy_hash
        != layer_policy_hash(context.target_artifact_policy)
        or work_item.required_artifact_hashes != (context_hash,)
        or context.target_artifact_kind != kind
    ):
        raise Protocol22CertificationError(
            "context authority does not match compact work item"
        )
    _validate_verifier(work_item, verifier)
    source = _source_descriptor(snapshot.partition, context.scope.source_id)
    expected_partition = (
        _domain_descriptor(source, context.scope.domain_key).domain_partition_id
        if context.scope.is_domain
        else source.source_partition_id
    )
    if work_item.output_key.partition_id != expected_partition:
        raise Protocol22CertificationError(
            "compact work item partition does not match snapshot authority"
        )
    if context.scope.content_id != (
        _domain_descriptor(source, context.scope.domain_key).domain_content_id
        if context.scope.is_domain
        else source.source_content_id
    ):
        raise Protocol22CertificationError(
            "compact scope content identity does not match snapshot authority"
        )


def _validate_verifier(
    work_item: WorkItemV2,
    verifier: VerifierAuthorityV1,
) -> None:
    fields = (
        (work_item.verifier_id, verifier.verifier_id),
        (work_item.verifier_version, verifier.verifier_version),
        (
            work_item.verifier_implementation_digest,
            verifier.implementation_digest,
        ),
    )
    if any(expected != actual for expected, actual in fields):
        raise Protocol22CertificationError(
            "verifier authority does not match work item"
        )


def _source_descriptor(
    partition: WorkspacePartitionCatalogV1,
    source_id: str,
) -> object:
    matches = tuple(source for source in partition.sources if source.source_id == source_id)
    if len(matches) != 1:
        raise Protocol22CertificationError(
            "compact scope source is absent from partition authority"
        )
    return matches[0]


def _domain_descriptor(source: object, domain_key_value: str | None) -> object:
    matches = tuple(
        domain
        for domain in source.domains
        if domain.domain_key == domain_key_value
    )
    if len(matches) != 1:
        raise Protocol22CertificationError(
            "compact scope domain is absent from partition authority"
        )
    return matches[0]


def _validate_context_and_references(
    payload: NormalizedAuthorialPayloadV1,
    context: ContextBundleV1,
    snapshot: object,
) -> tuple[Mapping[str, _EvidenceAuthority], bool]:
    authorities: dict[str, _EvidenceAuthority] = {}
    invalid = False
    source = _source_descriptor(snapshot.partition, context.scope.source_id)
    located_excerpts = tuple(
        (excerpt, "direct") for excerpt in context.evidence
    ) + tuple(
        (excerpt, "domain_projection")
        for projection in context.domain_projections
        for excerpt in projection.evidence
    )
    for excerpt, location in located_excerpts:
        try:
            expected_location = (
                "domain_projection"
                if excerpt.ownership == "domain_projection"
                else "direct"
            )
            if location != expected_location:
                raise Protocol22CertificationError(
                    "evidence excerpt is stored in the wrong context branch"
                )
            authority = _reconstruct_evidence_authority(
                context,
                source,
                excerpt,
                snapshot,
            )
        except Protocol22SchemaError:
            invalid = True
            continue
        previous = authorities.get(excerpt.evidence_authority_id)
        if previous is not None and previous.key != authority.key:
            invalid = True
            continue
        if previous is not None:
            invalid = True
            continue
        authorities[excerpt.evidence_authority_id] = authority

    for reference in _all_references(payload):
        authority = authorities.get(reference.evidence_authority_id)
        if authority is None or not _reference_within(reference, authority.excerpt):
            invalid = True
    return MappingProxyType(authorities), invalid


def _reconstruct_evidence_authority(
    context: ContextBundleV1,
    source: object,
    excerpt: EvidenceExcerptV1,
    snapshot: object,
) -> _EvidenceAuthority:
    records = tuple(
        record
        for record in source.files
        if record.source_relative_path == excerpt.source_relative_path
    )
    if len(records) != 1:
        raise Protocol22CertificationError("evidence path is absent from source")
    record = records[0]
    if record.object_kind != "regular" or record.text_status != "eligible_utf8":
        raise Protocol22CertificationError("evidence path is not eligible regular text")
    _validate_evidence_ownership(context, source, excerpt)
    authority_kind = (
        "domain_projection"
        if excerpt.ownership == "domain_projection"
        else "direct"
    )
    descriptor = EvidenceAuthorityDescriptorV1(
        source_id=context.scope.source_id,
        source_relative_path=excerpt.source_relative_path,
        authority_kind=authority_kind,
        origin_domain_key=excerpt.origin_domain_key,
    )
    if evidence_authority_id(descriptor) != excerpt.evidence_authority_id:
        raise Protocol22CertificationError("evidence authority digest mismatch")
    try:
        payload = snapshot.read_file(
            context.scope.source_id,
            excerpt.source_relative_path,
            record,
        )
    except Exception as exc:
        raise Protocol22CertificationError("pinned snapshot read failed") from exc
    if not isinstance(payload, bytes):
        raise Protocol22CertificationError("snapshot reader returned non-bytes")
    lines = _raw_lines(payload)
    try:
        decoded = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise Protocol22CertificationError("snapshot evidence is not UTF-8") from exc
    if (
        b"\x00" in payload
        or decoded.encode("utf-8") != payload
        or content_digest(payload) != record.content_hash
        or len(payload) != record.byte_count
        or len(lines) != record.line_count
        or excerpt.mode != record.mode
        or excerpt.source_blob_hash != record.content_hash
        or excerpt.end_line > len(lines)
    ):
        raise Protocol22CertificationError("snapshot evidence metadata mismatch")
    raw = b"".join(lines[excerpt.start_line - 1 : excerpt.end_line])
    if (
        content_digest(raw) != excerpt.raw_excerpt_hash
        or raw.decode("utf-8", errors="strict").replace("\r\n", "\n")
        != excerpt.text_lf
        or excerpt.complete_file
        != (excerpt.start_line == 1 and excerpt.end_line == len(lines))
    ):
        raise Protocol22CertificationError("evidence excerpt reconstruction mismatch")
    return _EvidenceAuthority(context.scope.source_id, excerpt, record)


def _validate_evidence_ownership(
    context: ContextBundleV1,
    source: object,
    excerpt: EvidenceExcerptV1,
) -> None:
    path = excerpt.source_relative_path
    if context.scope.is_domain:
        domain = _domain_descriptor(source, context.scope.domain_key)
        if (
            excerpt.ownership not in {"owned", "shared_supporting"}
            or excerpt.origin_domain_key != domain.domain_key
        ):
            raise Protocol22CertificationError("domain evidence ownership mismatch")
        owned_paths = _owned_source_paths(domain)
        if (
            excerpt.ownership == "owned"
            and path not in owned_paths
            or excerpt.ownership == "shared_supporting"
            and path not in domain.supporting_source_relative_paths
        ):
            raise Protocol22CertificationError("domain evidence path is unauthorized")
        return
    if excerpt.ownership == "source":
        if excerpt.origin_domain_key is not None:
            raise Protocol22CertificationError("source evidence has domain origin")
        return
    if excerpt.ownership != "domain_projection":
        raise Protocol22CertificationError("source overview evidence ownership mismatch")
    domain = _domain_descriptor(source, excerpt.origin_domain_key)
    if path not in _owned_source_paths(domain) and path not in (
        domain.supporting_source_relative_paths
    ):
        raise Protocol22CertificationError("projected evidence path is unauthorized")
    projection_keys = {item.domain_key for item in context.domain_projections}
    if domain.domain_key not in projection_keys:
        raise Protocol22CertificationError("evidence belongs to an unprojected domain")


def _owned_source_paths(domain: object) -> frozenset[str]:
    prefix = "" if domain.source_relative_root == "." else (
        domain.source_relative_root + "/"
    )
    return frozenset(prefix + path for path in domain.owned_domain_relative_paths)


def _raw_lines(payload: bytes) -> tuple[bytes, ...]:
    if not payload:
        return ()
    lines: list[bytes] = []
    start = 0
    while True:
        delimiter = payload.find(b"\n", start)
        if delimiter < 0:
            if start < len(payload):
                lines.append(payload[start:])
            break
        lines.append(payload[start : delimiter + 1])
        start = delimiter + 1
        if start == len(payload):
            break
    return tuple(lines)


def _all_references(
    payload: NormalizedAuthorialPayloadV1,
) -> tuple[EvidenceReferenceV1, ...]:
    claim_refs = tuple(
        reference
        for surface in payload.surfaces.values()
        for claim in surface.items
        for reference in claim.evidence
    )
    unknown_refs = tuple(
        reference
        for unknown in payload.unknowns
        for reference in unknown.inspected_evidence
    )
    return (*claim_refs, *unknown_refs)


def _reference_within(
    reference: EvidenceReferenceV1,
    excerpt: EvidenceExcerptV1,
) -> bool:
    return (
        reference.path == excerpt.source_relative_path
        and excerpt.start_line <= reference.start_line <= reference.end_line
        and reference.end_line <= excerpt.end_line
    )


def _referenced_authority_keys(
    payload: NormalizedAuthorialPayloadV1,
    authorities: Mapping[str, _EvidenceAuthority],
) -> frozenset[tuple[str, str, str, str | None]]:
    result: set[tuple[str, str, str, str | None]] = set()
    for surface in payload.surfaces.values():
        for claim in surface.items:
            for reference in claim.evidence:
                authority = authorities.get(reference.evidence_authority_id)
                if authority is not None and _reference_within(
                    reference,
                    authority.excerpt,
                ):
                    result.add(authority.key)
    return frozenset(result)


def _coverage_assessment(
    context: ContextBundleV1,
    referenced: frozenset[tuple[str, str, str, str | None]],
) -> CoverageAssessmentV1:
    debt = context.depth_debt
    direct_referenced = sum(key[2] == "direct" for key in referenced)
    direct = _coverage_record(
        "direct_read_set",
        inventory=debt.inventory_file_count,
        selected=debt.fully_selected_file_count + debt.partially_selected_file_count,
        referenced=direct_referenced,
        fully=debt.fully_selected_file_count,
        partially=debt.partially_selected_file_count,
        omitted=debt.omitted_file_count,
        omitted_ranges=debt.omitted_range_count,
    )
    if context.target_artifact_kind == "domain-baseline":
        return CoverageAssessmentV1(
            direct=direct,
            projected_domains=None,
            combined=_coverage_record(
                "combined_evidence_authority",
                **_coverage_counts(direct),
            ),
        )

    rollup = debt.domain_depth_debt_rollup
    if rollup is None:
        raise Protocol22CertificationError(
            "source overview context lacks domain depth-debt rollup"
        )
    projected_excerpts = tuple(
        excerpt
        for projection in context.domain_projections
        for excerpt in projection.evidence
    )
    projected_keys = {
        (
            context.scope.source_id,
            excerpt.source_relative_path,
            "domain_projection",
            excerpt.origin_domain_key,
        )
        for excerpt in projected_excerpts
    }
    selected = len(projected_keys)
    partially = len(
        {
            (
                context.scope.source_id,
                excerpt.source_relative_path,
                excerpt.origin_domain_key,
            )
            for excerpt in projected_excerpts
            if not excerpt.complete_file
        }
    )
    projected = _coverage_record(
        "projected_domain_read_sets",
        inventory=rollup.inventory_read_set_entry_count,
        selected=selected,
        referenced=sum(key[2] == "domain_projection" for key in referenced),
        fully=selected - partially,
        partially=partially,
        omitted=rollup.inventory_read_set_entry_count - selected,
        omitted_ranges=partially,
    )
    combined_counts = {
        field: _coverage_counts(direct)[field] + _coverage_counts(projected)[field]
        for field in _coverage_counts(direct)
    }
    return CoverageAssessmentV1(
        direct=direct,
        projected_domains=projected,
        combined=_coverage_record(
            "combined_evidence_authority",
            **combined_counts,
        ),
    )


def _coverage_counts(record: CoverageRecordV1) -> dict[str, int]:
    return {
        "inventory": record.inventory_file_count,
        "selected": record.selected_file_count,
        "referenced": record.referenced_file_count,
        "fully": record.fully_selected_file_count,
        "partially": record.partially_selected_file_count,
        "omitted": record.omitted_file_count,
        "omitted_ranges": record.omitted_range_count,
    }


def _coverage_record(
    universe: str,
    *,
    inventory: int,
    selected: int,
    referenced: int,
    fully: int,
    partially: int,
    omitted: int,
    omitted_ranges: int,
) -> CoverageRecordV1:
    return CoverageRecordV1(
        universe=universe,
        inventory_file_count=inventory,
        selected_file_count=selected,
        referenced_file_count=referenced,
        fully_selected_file_count=fully,
        partially_selected_file_count=partially,
        omitted_file_count=omitted,
        omitted_range_count=omitted_ranges,
        selected_over_inventory=CountRatioV1(selected, inventory),
        referenced_over_inventory=CountRatioV1(referenced, inventory),
        referenced_over_selected=CountRatioV1(referenced, selected),
    )


def _minimum_utility(
    payload: NormalizedAuthorialPayloadV1,
    context: ContextBundleV1,
    has_regular_file_citation: bool,
) -> tuple[tuple[RequiredSurfaceRecordV1, ...], MinimumUtilityAssessmentV1]:
    domain_count = (
        0
        if context.depth_debt.domain_depth_debt_rollup is None
        else context.depth_debt.domain_depth_debt_rollup.domain_count
    )
    requirements: dict[str, str] = {name: "none" for name in payload.surfaces}
    diagnostics: list[str] = []
    if payload.artifact_kind == "domain-baseline":
        requirements["responsibilities"] = "required"
        requirements["entry_points"] = "one_of_entry_or_behavior"
        requirements["core_behavior"] = "one_of_entry_or_behavior"
        if payload.surfaces["responsibilities"].status != "observed":
            diagnostics.append("responsibilities_not_observed")
        if not any(
            payload.surfaces[name].status == "observed"
            for name in ("entry_points", "core_behavior")
        ):
            diagnostics.append("entry_or_behavior_not_observed")
    else:
        requirements["purpose"] = "required"
        requirements["runtime_shape"] = "required"
        if domain_count > 1:
            requirements["intra_source_boundaries"] = (
                "one_of_boundary_or_relationship"
            )
            requirements["domain_relationships"] = (
                "one_of_boundary_or_relationship"
            )
        if payload.surfaces["purpose"].status != "observed":
            diagnostics.append("purpose_not_observed")
        if payload.surfaces["runtime_shape"].status != "observed":
            diagnostics.append("runtime_shape_not_observed")
        if domain_count > 1 and not any(
            payload.surfaces[name].status == "observed"
            for name in ("intra_source_boundaries", "domain_relationships")
        ):
            diagnostics.append("boundary_or_relationship_not_observed")
    if not has_regular_file_citation:
        diagnostics.append("no_regular_file_cited")
    records = tuple(
        RequiredSurfaceRecordV1(
            surface=name,
            status=payload.surfaces[name].status,
            claim_count=len(payload.surfaces[name].items),
            minimum_utility_requirement=requirements[name],
        )
        for name in _surface_names(payload.artifact_kind)
    )
    utility = MinimumUtilityAssessmentV1(
        rule_id="compact-v1-minimum-utility-v1",
        passed=not diagnostics,
        diagnostic_codes=tuple(diagnostics),
    )
    return records, utility


def _certification_key(
    work_item: WorkItemV2,
    artifact_hash: str,
    verifier: VerifierAuthorityV1,
) -> CertificationKeyV2:
    return CertificationKeyV2(
        identity_schema_version=2,
        artifact_hash=artifact_hash,
        artifact_key=work_item.output_key,
        verifier_id=verifier.verifier_id,
        verifier_version=verifier.verifier_version,
        verifier_implementation_digest=verifier.implementation_digest,
        scoped_content_id=work_item.output_key.scope.content_id,
        audit_epoch_id=None,
    )


def certify_deterministic_artifact(
    work_item: WorkItemV2,
    artifact_hash: str,
    assessment: DeterministicAssessmentInputV2,
    verifier: VerifierAuthorityV1,
) -> CertificationReceiptV2:
    """Certify one already-constructed deterministic protocol-2.2 artifact."""
    if not isinstance(work_item, WorkItemV2):
        raise Protocol22CertificationError(
            "deterministic certification requires WorkItemV2"
        )
    if not isinstance(assessment, DeterministicAssessmentInputV2):
        raise Protocol22CertificationError(
            "deterministic certification requires DeterministicAssessmentInputV2"
        )
    if not isinstance(verifier, VerifierAuthorityV1):
        raise Protocol22CertificationError(
            "deterministic certification requires VerifierAuthorityV1"
        )
    digest_value(artifact_hash, "deterministic artifact_hash")
    kind = work_item.output_key.artifact_kind
    if kind in _BASELINE_KINDS:
        raise Protocol22CertificationError(
            "compact artifacts require compact certification"
        )
    _validate_verifier(work_item, verifier)
    requires_debt = kind in _DEBT_REQUIRED_KINDS
    if requires_debt != (assessment.depth_debt is not None):
        qualifier = "requires" if requires_debt else "forbids"
        raise Protocol22CertificationError(
            f"{kind} {qualifier} depth debt in deterministic certification"
        )
    closed = DeterministicCertificationAssessmentV2(
        assessment_kind="deterministic_artifact",
        artifact_kind=kind,
        canonical_schema_valid=assessment.canonical_schema_valid,
        dependency_closure_valid=assessment.dependency_closure_valid,
        policy_conformance_valid=assessment.policy_conformance_valid,
        depth_debt=assessment.depth_debt,
        normalized_diagnostics=assessment.normalized_diagnostics,
        semantic_status="not_applicable",
    )
    accepted = (
        assessment.canonical_schema_valid
        and assessment.dependency_closure_valid
        and assessment.policy_conformance_valid
    )
    return CertificationReceiptV2(
        schema_version=2,
        certification_key=_certification_key(work_item, artifact_hash, verifier),
        verdict="accepted" if accepted else "rejected",
        assessment=closed,
    )


def render_baseline_markdown(artifact_bytes: bytes) -> bytes:
    """Render canonical compact baseline bytes without adding semantic authority."""
    try:
        artifact = load_canonical_object(
            artifact_bytes,
            CompactBaselineArtifactV1.from_json_dict,
        )
    except Protocol22SchemaError as exc:
        raise CompactCandidateError(f"invalid compact artifact: {exc}") from exc
    title = (
        "Domain Baseline"
        if artifact.artifact.artifact_kind == "domain-baseline"
        else "Source Overview"
    )
    lines = [f"# {title}", ""]
    for name in _surface_names(artifact.artifact.artifact_kind):
        surface = artifact.surfaces[name]
        lines.extend((f"## {name.replace('_', ' ').title()}", ""))
        if surface.status == "not_established":
            lines.extend(
                (
                    f"Not established: `{surface.not_established_reason_code}`.",
                    "",
                )
            )
            continue
        for claim in surface.items:
            statement_lines = claim.statement.split("\n")
            lines.append(f"- {statement_lines[0]}")
            lines.extend(f"  {line}" for line in statement_lines[1:])
            for reference in claim.evidence:
                lines.append(
                    "  - Evidence: "
                    f"`{reference.path}:{reference.start_line}-{reference.end_line}` "
                    f"(`{reference.evidence_authority_id}`)"
                )
        lines.append("")
    lines.extend(("## Unknowns", ""))
    if artifact.unknowns:
        for unknown in artifact.unknowns:
            question_lines = unknown.question.split("\n")
            lines.append(f"- {question_lines[0]} (`{unknown.reason_code}`)")
            lines.extend(f"  {line}" for line in question_lines[1:])
    else:
        lines.append("- None recorded.")
    debt = artifact.depth_debt
    lines.extend(
        (
            "",
            "## Depth debt",
            "",
            f"- Inventory files: {debt.inventory_file_count}",
            f"- Fully selected files: {debt.fully_selected_file_count}",
            f"- Partially selected files: {debt.partially_selected_file_count}",
            f"- Omitted files: {debt.omitted_file_count}",
            f"- Omitted ranges: {debt.omitted_range_count}",
            "",
            "Semantic audit: not run.",
            "",
        )
    )
    rendered = "\n".join(lines).encode("utf-8")
    if len(rendered) > 96 * 1024:
        raise CompactCandidateError("rendered compact baseline exceeds 96 KiB")
    return rendered


__all__ = (
    "ArtifactAcceptanceReceiptV2",
    "CandidateAssessmentReceiptV1",
    "CertificationKeyV2",
    "CertificationReceiptV2",
    "CompactBaselineArtifactV1",
    "CompactCandidateError",
    "CompactCandidateInputV1",
    "CompactCertificationAssessmentV2",
    "CompactCertificationResultV2",
    "CountRatioV1",
    "CoverageAssessmentV1",
    "CoverageRecordV1",
    "DeterministicCertificationAssessmentV2",
    "MinimumUtilityAssessmentV1",
    "NormalizedAuthorialPayloadV1",
    "Protocol22CertificationError",
    "RequiredSurfaceRecordV1",
    "SurfaceV1",
    "UnknownV1",
    "certify_compact_candidate",
    "certify_deterministic_artifact",
    "parse_authorial_candidate",
    "render_baseline_markdown",
)

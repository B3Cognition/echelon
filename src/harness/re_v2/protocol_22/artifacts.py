"""Closed deterministic artifact values shared by protocol-2.2 producers."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar, Literal, Mapping
import unicodedata

from harness.re_v2.canonical import canonical_json_bytes, content_digest

from .graph import AcceptedArtifactV2
from .model import ArtifactScope
from .policies import ArtifactPolicyEntryV1, layer_policy_hash
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
    safe_relative_path,
    sorted_unique_digests,
    text_value,
)


_DIRECT_OWNERSHIP = frozenset({"source", "owned", "shared_supporting"})
_EVIDENCE_OWNERSHIP = frozenset((*_DIRECT_OWNERSHIP, "domain_projection"))
_OMISSION_REASONS = frozenset(
    {"policy_ineligible", "non_text", "line_too_large", "capacity_exhausted"}
)
_CONTEXT_KINDS = frozenset(
    {"domain-context-bundle", "source-overview-context-bundle"}
)
_TARGET_KINDS = frozenset({"domain-baseline", "source-overview"})
_PROJECTION_SURFACES = {
    "responsibilities": 0,
    "entry_points": 1,
    "external_contracts": 2,
}


def _exact(value: object, fields: tuple[str, ...], label: str) -> Mapping[str, object]:
    return exact_object(value, frozenset(fields), label)


def _optional_positive(value: object, field: str) -> int | None:
    if value is None:
        return None
    return positive_int(value, field)


def _tuple_of(value: object, expected: type, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, expected) for item in value
    ):
        raise Protocol22SchemaError(
            f"{field} must contain closed {expected.__name__} values"
        )
    return tuple(value)


def _zero_null(count: int, value: str | None, field: str) -> None:
    if (count == 0) != (value is None):
        raise Protocol22SchemaError(
            f"{field} must be null exactly when its count is zero"
        )


@dataclass(frozen=True, slots=True)
class DomainDepthDebtRollupV1:
    domain_count: int
    inventory_read_set_entry_count: int
    fully_selected_read_set_entry_count: int
    partially_selected_read_set_entry_count: int
    omitted_read_set_entry_count: int
    omitted_range_count: int
    domain_debt_descriptor_hash: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "domain_count",
        "inventory_read_set_entry_count",
        "fully_selected_read_set_entry_count",
        "partially_selected_read_set_entry_count",
        "omitted_read_set_entry_count",
        "omitted_range_count",
        "domain_debt_descriptor_hash",
    )

    def __post_init__(self) -> None:
        for field in self.FIELDS[:-1]:
            nonnegative_int(getattr(self, field), f"DomainDepthDebtRollupV1.{field}")
        optional_digest(
            self.domain_debt_descriptor_hash,
            "DomainDepthDebtRollupV1.domain_debt_descriptor_hash",
        )
        if (
            self.fully_selected_read_set_entry_count
            + self.partially_selected_read_set_entry_count
            + self.omitted_read_set_entry_count
            != self.inventory_read_set_entry_count
        ):
            raise Protocol22SchemaError(
                "DomainDepthDebtRollupV1 read-set counts do not balance"
            )
        _zero_null(
            self.domain_count,
            self.domain_debt_descriptor_hash,
            "DomainDepthDebtRollupV1.domain_debt_descriptor_hash",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "DomainDepthDebtRollupV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class DepthDebtV1:
    inventory_file_count: int
    fully_selected_file_count: int
    partially_selected_file_count: int
    omitted_file_count: int
    omitted_range_count: int
    omitted_descriptor_hash: str | None
    domain_depth_debt_rollup: DomainDepthDebtRollupV1 | None
    omitted_domain_summary_count: int
    omitted_domain_descriptor_hash: str | None
    retained_projected_claim_count: int
    omitted_projected_claim_count: int
    omitted_projected_claim_descriptor_hash: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "inventory_file_count",
        "fully_selected_file_count",
        "partially_selected_file_count",
        "omitted_file_count",
        "omitted_range_count",
        "omitted_descriptor_hash",
        "domain_depth_debt_rollup",
        "omitted_domain_summary_count",
        "omitted_domain_descriptor_hash",
        "retained_projected_claim_count",
        "omitted_projected_claim_count",
        "omitted_projected_claim_descriptor_hash",
    )

    def __post_init__(self) -> None:
        count_fields = (
            "inventory_file_count",
            "fully_selected_file_count",
            "partially_selected_file_count",
            "omitted_file_count",
            "omitted_range_count",
            "omitted_domain_summary_count",
            "retained_projected_claim_count",
            "omitted_projected_claim_count",
        )
        for field in count_fields:
            nonnegative_int(getattr(self, field), f"DepthDebtV1.{field}")
        for field in (
            "omitted_descriptor_hash",
            "omitted_domain_descriptor_hash",
            "omitted_projected_claim_descriptor_hash",
        ):
            optional_digest(getattr(self, field), f"DepthDebtV1.{field}")
        if self.domain_depth_debt_rollup is not None and not isinstance(
            self.domain_depth_debt_rollup, DomainDepthDebtRollupV1
        ):
            raise Protocol22SchemaError(
                "DepthDebtV1.domain_depth_debt_rollup must be a closed rollup or null"
            )
        if (
            self.fully_selected_file_count
            + self.partially_selected_file_count
            + self.omitted_file_count
            != self.inventory_file_count
        ):
            raise Protocol22SchemaError("DepthDebtV1 file counts do not balance")
        descriptor_count = self.omitted_file_count + self.omitted_range_count
        _zero_null(
            descriptor_count,
            self.omitted_descriptor_hash,
            "DepthDebtV1.omitted_descriptor_hash",
        )
        _zero_null(
            self.omitted_domain_summary_count,
            self.omitted_domain_descriptor_hash,
            "DepthDebtV1.omitted_domain_descriptor_hash",
        )
        _zero_null(
            self.omitted_projected_claim_count,
            self.omitted_projected_claim_descriptor_hash,
            "DepthDebtV1.omitted_projected_claim_descriptor_hash",
        )
        if self.domain_depth_debt_rollup is None and (
            self.omitted_domain_summary_count
            or self.retained_projected_claim_count
            or self.omitted_projected_claim_count
        ):
            raise Protocol22SchemaError(
                "DepthDebtV1 projection counts require domain_depth_debt_rollup"
            )
        if (
            self.domain_depth_debt_rollup is not None
            and self.omitted_domain_summary_count
            > self.domain_depth_debt_rollup.domain_count
        ):
            raise Protocol22SchemaError(
                "DepthDebtV1 omitted domains exceed the domain rollup"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "inventory_file_count": self.inventory_file_count,
            "fully_selected_file_count": self.fully_selected_file_count,
            "partially_selected_file_count": self.partially_selected_file_count,
            "omitted_file_count": self.omitted_file_count,
            "omitted_range_count": self.omitted_range_count,
            "omitted_descriptor_hash": self.omitted_descriptor_hash,
            "domain_depth_debt_rollup": (
                None
                if self.domain_depth_debt_rollup is None
                else self.domain_depth_debt_rollup.to_json_dict()
            ),
            "omitted_domain_summary_count": self.omitted_domain_summary_count,
            "omitted_domain_descriptor_hash": self.omitted_domain_descriptor_hash,
            "retained_projected_claim_count": self.retained_projected_claim_count,
            "omitted_projected_claim_count": self.omitted_projected_claim_count,
            "omitted_projected_claim_descriptor_hash": (
                self.omitted_projected_claim_descriptor_hash
            ),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "DepthDebtV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        rollup = raw["domain_depth_debt_rollup"]
        return cls(
            **{
                field: raw[field]
                for field in cls.FIELDS
                if field != "domain_depth_debt_rollup"
            },
            domain_depth_debt_rollup=(
                None
                if rollup is None
                else DomainDepthDebtRollupV1.from_json_dict(rollup)
            ),
        )


@dataclass(frozen=True, slots=True)
class OmittedEvidenceDescriptorV1:
    descriptor_kind: Literal["file", "line_range"]
    source_relative_path: str
    ownership: Literal["source", "owned", "shared_supporting"]
    origin_domain_key: str | None
    start_line: int | None
    end_line: int | None
    reason_code: Literal[
        "policy_ineligible", "non_text", "line_too_large", "capacity_exhausted"
    ]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "descriptor_kind",
        "source_relative_path",
        "ownership",
        "origin_domain_key",
        "start_line",
        "end_line",
        "reason_code",
    )

    def __post_init__(self) -> None:
        one_of(
            self.descriptor_kind,
            frozenset({"file", "line_range"}),
            "OmittedEvidenceDescriptorV1.descriptor_kind",
        )
        safe_relative_path(
            self.source_relative_path,
            "OmittedEvidenceDescriptorV1.source_relative_path",
        )
        one_of(
            self.ownership,
            _DIRECT_OWNERSHIP,
            "OmittedEvidenceDescriptorV1.ownership",
        )
        optional_digest(
            self.origin_domain_key,
            "OmittedEvidenceDescriptorV1.origin_domain_key",
        )
        one_of(
            self.reason_code,
            _OMISSION_REASONS,
            "OmittedEvidenceDescriptorV1.reason_code",
        )
        if self.ownership == "source":
            if self.origin_domain_key is not None:
                raise Protocol22SchemaError(
                    "source omission requires null origin_domain_key"
                )
        elif self.origin_domain_key is None:
            raise Protocol22SchemaError(
                "owned/shared omission requires origin_domain_key"
            )
        if self.descriptor_kind == "file":
            if self.start_line is not None or self.end_line is not None:
                raise Protocol22SchemaError(
                    "file omission line fields must be null"
                )
        else:
            start = _optional_positive(
                self.start_line,
                "OmittedEvidenceDescriptorV1.start_line",
            )
            end = _optional_positive(
                self.end_line,
                "OmittedEvidenceDescriptorV1.end_line",
            )
            if start is None or end is None or start > end:
                raise Protocol22SchemaError(
                    "line_range omission requires ordered positive line fields"
                )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "OmittedEvidenceDescriptorV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class OmittedDomainDescriptorV1:
    domain_key: str
    baseline_artifact_hash: str
    reason_code: Literal["capacity_exhausted"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "domain_key",
        "baseline_artifact_hash",
        "reason_code",
    )

    def __post_init__(self) -> None:
        digest_value(self.domain_key, "OmittedDomainDescriptorV1.domain_key")
        digest_value(
            self.baseline_artifact_hash,
            "OmittedDomainDescriptorV1.baseline_artifact_hash",
        )
        if self.reason_code != "capacity_exhausted":
            raise Protocol22SchemaError(
                "OmittedDomainDescriptorV1.reason_code must be capacity_exhausted"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "OmittedDomainDescriptorV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class OmittedProjectedClaimDescriptorV1:
    domain_key: str
    surface: str
    claim_index: int
    claim_hash: str
    reason_code: Literal["capacity_exhausted"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "domain_key",
        "surface",
        "claim_index",
        "claim_hash",
        "reason_code",
    )

    def __post_init__(self) -> None:
        digest_value(
            self.domain_key,
            "OmittedProjectedClaimDescriptorV1.domain_key",
        )
        safe_id(self.surface, "OmittedProjectedClaimDescriptorV1.surface")
        nonnegative_int(
            self.claim_index,
            "OmittedProjectedClaimDescriptorV1.claim_index",
        )
        digest_value(
            self.claim_hash,
            "OmittedProjectedClaimDescriptorV1.claim_hash",
        )
        if self.reason_code != "capacity_exhausted":
            raise Protocol22SchemaError(
                "OmittedProjectedClaimDescriptorV1.reason_code must be capacity_exhausted"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "OmittedProjectedClaimDescriptorV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class EvidenceExcerptV1:
    evidence_authority_id: str
    source_relative_path: str
    ownership: Literal[
        "source", "owned", "shared_supporting", "domain_projection"
    ]
    origin_domain_key: str | None
    mode: Literal["100644", "100755"]
    source_blob_hash: str
    start_line: int
    end_line: int
    raw_excerpt_hash: str
    text_lf: str
    complete_file: bool

    FIELDS: ClassVar[tuple[str, ...]] = (
        "evidence_authority_id",
        "source_relative_path",
        "ownership",
        "origin_domain_key",
        "mode",
        "source_blob_hash",
        "start_line",
        "end_line",
        "raw_excerpt_hash",
        "text_lf",
        "complete_file",
    )

    def __post_init__(self) -> None:
        digest_value(
            self.evidence_authority_id,
            "EvidenceExcerptV1.evidence_authority_id",
        )
        safe_relative_path(
            self.source_relative_path,
            "EvidenceExcerptV1.source_relative_path",
        )
        one_of(self.ownership, _EVIDENCE_OWNERSHIP, "EvidenceExcerptV1.ownership")
        optional_digest(
            self.origin_domain_key,
            "EvidenceExcerptV1.origin_domain_key",
        )
        if self.mode not in {"100644", "100755"}:
            raise Protocol22SchemaError(
                "EvidenceExcerptV1.mode must be a regular file mode"
            )
        digest_value(self.source_blob_hash, "EvidenceExcerptV1.source_blob_hash")
        start = positive_int(self.start_line, "EvidenceExcerptV1.start_line")
        end = positive_int(self.end_line, "EvidenceExcerptV1.end_line")
        if start > end:
            raise Protocol22SchemaError("EvidenceExcerptV1 line range is reversed")
        digest_value(self.raw_excerpt_hash, "EvidenceExcerptV1.raw_excerpt_hash")
        text_value(self.text_lf, "EvidenceExcerptV1.text_lf", allow_empty=True)
        boolean(self.complete_file, "EvidenceExcerptV1.complete_file")
        if self.ownership == "source":
            if self.origin_domain_key is not None:
                raise Protocol22SchemaError(
                    "source evidence requires null origin_domain_key"
                )
        elif self.origin_domain_key is None:
            raise Protocol22SchemaError(
                "owned, shared, and projected evidence require origin_domain_key"
            )

    @property
    def sort_key(self) -> tuple[object, ...]:
        return (
            self.source_relative_path.encode("utf-8"),
            self.start_line,
            self.end_line,
            self.ownership,
            "" if self.origin_domain_key is None else self.origin_domain_key,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "EvidenceExcerptV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class EvidencePackV1:
    schema_version: int
    artifact_kind: Literal["source-evidence-pack", "domain-evidence-pack"]
    scope: ArtifactScope
    layer_policy_hash: str
    inventory_artifact_hash: str
    byte_estimator_id: Literal["utf8-byte-upper-bound-v1"]
    max_canonical_json_bytes: int
    max_conservative_input_tokens: int
    excerpts: tuple[EvidenceExcerptV1, ...]
    depth_debt: DepthDebtV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_kind",
        "scope",
        "layer_policy_hash",
        "inventory_artifact_hash",
        "byte_estimator_id",
        "max_canonical_json_bytes",
        "max_conservative_input_tokens",
        "excerpts",
        "depth_debt",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22SchemaError("EvidencePackV1.schema_version must be 1")
        one_of(
            self.artifact_kind,
            frozenset({"source-evidence-pack", "domain-evidence-pack"}),
            "EvidencePackV1.artifact_kind",
        )
        if not isinstance(self.scope, ArtifactScope):
            raise Protocol22SchemaError("EvidencePackV1.scope must be ArtifactScope")
        if (self.artifact_kind == "domain-evidence-pack") != self.scope.is_domain:
            raise Protocol22SchemaError(
                "EvidencePackV1 scope domain_key does not match artifact kind"
            )
        digest_value(self.layer_policy_hash, "EvidencePackV1.layer_policy_hash")
        digest_value(
            self.inventory_artifact_hash,
            "EvidencePackV1.inventory_artifact_hash",
        )
        if self.byte_estimator_id != "utf8-byte-upper-bound-v1":
            raise Protocol22SchemaError(
                "EvidencePackV1.byte_estimator_id is unsupported"
            )
        positive_int(
            self.max_canonical_json_bytes,
            "EvidencePackV1.max_canonical_json_bytes",
        )
        positive_int(
            self.max_conservative_input_tokens,
            "EvidencePackV1.max_conservative_input_tokens",
        )
        excerpts = _tuple_of(
            self.excerpts,
            EvidenceExcerptV1,
            "EvidencePackV1.excerpts",
        )
        keys = tuple(item.sort_key for item in excerpts)
        if keys != tuple(sorted(set(keys))):
            raise Protocol22SchemaError(
                "EvidencePackV1.excerpts must be sorted and unique"
            )
        object.__setattr__(self, "excerpts", excerpts)
        if not isinstance(self.depth_debt, DepthDebtV1):
            raise Protocol22SchemaError(
                "EvidencePackV1.depth_debt must be DepthDebtV1"
            )
        if self.artifact_kind == "source-evidence-pack":
            if any(item.ownership != "source" for item in excerpts):
                raise Protocol22SchemaError(
                    "source evidence pack may contain only source ownership"
                )
        elif any(
            item.ownership not in {"owned", "shared_supporting"}
            or item.origin_domain_key != self.scope.domain_key
            for item in excerpts
        ):
            raise Protocol22SchemaError(
                "domain evidence pack excerpt ownership does not match its scope"
            )
        byte_count = len(canonical_json_bytes(self.to_json_dict()))
        if byte_count > self.max_canonical_json_bytes:
            raise Protocol22SchemaError(
                "EvidencePackV1 exceeds max_canonical_json_bytes"
            )
        if byte_count > self.max_conservative_input_tokens:
            raise Protocol22SchemaError(
                "EvidencePackV1 exceeds max_conservative_input_tokens"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_kind": self.artifact_kind,
            "scope": self.scope.to_json_dict(),
            "layer_policy_hash": self.layer_policy_hash,
            "inventory_artifact_hash": self.inventory_artifact_hash,
            "byte_estimator_id": self.byte_estimator_id,
            "max_canonical_json_bytes": self.max_canonical_json_bytes,
            "max_conservative_input_tokens": self.max_conservative_input_tokens,
            "excerpts": [item.to_json_dict() for item in self.excerpts],
            "depth_debt": self.depth_debt.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "EvidencePackV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        excerpts = raw["excerpts"]
        if not isinstance(excerpts, (list, tuple)):
            raise Protocol22SchemaError("EvidencePackV1.excerpts must be an array")
        return cls(
            schema_version=raw["schema_version"],
            artifact_kind=raw["artifact_kind"],
            scope=ArtifactScope.from_json_dict(raw["scope"]),
            layer_policy_hash=raw["layer_policy_hash"],
            inventory_artifact_hash=raw["inventory_artifact_hash"],
            byte_estimator_id=raw["byte_estimator_id"],
            max_canonical_json_bytes=raw["max_canonical_json_bytes"],
            max_conservative_input_tokens=raw["max_conservative_input_tokens"],
            excerpts=tuple(EvidenceExcerptV1.from_json_dict(item) for item in excerpts),
            depth_debt=DepthDebtV1.from_json_dict(raw["depth_debt"]),
        )


@dataclass(frozen=True, slots=True)
class ArtifactDependencyV1:
    artifact_kind: str
    artifact_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = ("artifact_kind", "artifact_hash")

    def __post_init__(self) -> None:
        safe_id(self.artifact_kind, "ArtifactDependencyV1.artifact_kind")
        digest_value(self.artifact_hash, "ArtifactDependencyV1.artifact_hash")

    def to_json_dict(self) -> dict[str, object]:
        return {"artifact_kind": self.artifact_kind, "artifact_hash": self.artifact_hash}

    @classmethod
    def from_json_dict(cls, value: object) -> "ArtifactDependencyV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(raw["artifact_kind"], raw["artifact_hash"])


@dataclass(frozen=True, slots=True)
class EvidenceReferenceV1:
    evidence_authority_id: str
    path: str
    start_line: int
    end_line: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "evidence_authority_id",
        "path",
        "start_line",
        "end_line",
    )

    def __post_init__(self) -> None:
        digest_value(
            self.evidence_authority_id,
            "EvidenceReferenceV1.evidence_authority_id",
        )
        safe_relative_path(self.path, "EvidenceReferenceV1.path")
        start = positive_int(self.start_line, "EvidenceReferenceV1.start_line")
        end = positive_int(self.end_line, "EvidenceReferenceV1.end_line")
        if start > end:
            raise Protocol22SchemaError("EvidenceReferenceV1 line range is reversed")

    @property
    def sort_key(self) -> tuple[object, ...]:
        return (
            self.evidence_authority_id,
            self.path.encode("utf-8"),
            self.start_line,
            self.end_line,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "EvidenceReferenceV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ClaimV1:
    statement: str
    evidence: tuple[EvidenceReferenceV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = ("statement", "evidence")

    def __post_init__(self) -> None:
        statement = text_value(self.statement, "ClaimV1.statement")
        if (
            statement.strip() != statement
            or "\r" in statement
            or unicodedata.normalize("NFC", statement) != statement
            or len(statement.encode("utf-8")) > 1024
        ):
            raise Protocol22SchemaError(
                "ClaimV1.statement must be normalized bounded text"
            )
        evidence = _tuple_of(self.evidence, EvidenceReferenceV1, "ClaimV1.evidence")
        if not 1 <= len(evidence) <= 8:
            raise Protocol22SchemaError("ClaimV1 requires one to eight evidence refs")
        keys = tuple(item.sort_key for item in evidence)
        if keys != tuple(sorted(set(keys))):
            raise Protocol22SchemaError("ClaimV1.evidence must be sorted and unique")
        object.__setattr__(self, "evidence", evidence)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "statement": self.statement,
            "evidence": [item.to_json_dict() for item in self.evidence],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ClaimV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        evidence = raw["evidence"]
        if not isinstance(evidence, (list, tuple)):
            raise Protocol22SchemaError("ClaimV1.evidence must be an array")
        return cls(
            statement=raw["statement"],
            evidence=tuple(EvidenceReferenceV1.from_json_dict(item) for item in evidence),
        )


@dataclass(frozen=True, slots=True)
class ProjectedClaimV1:
    surface: str
    claim: ClaimV1

    FIELDS: ClassVar[tuple[str, ...]] = ("surface", "claim")

    def __post_init__(self) -> None:
        if self.surface not in _PROJECTION_SURFACES:
            raise Protocol22SchemaError("ProjectedClaimV1.surface is not projectable")
        if not isinstance(self.claim, ClaimV1):
            raise Protocol22SchemaError("ProjectedClaimV1.claim must be ClaimV1")

    def to_json_dict(self) -> dict[str, object]:
        return {"surface": self.surface, "claim": self.claim.to_json_dict()}

    @classmethod
    def from_json_dict(cls, value: object) -> "ProjectedClaimV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(raw["surface"], ClaimV1.from_json_dict(raw["claim"]))


@dataclass(frozen=True, slots=True)
class DomainProjectionV1:
    domain_key: str
    presentation_domain_id: str
    baseline_artifact_hash: str
    baseline_depth_debt: DepthDebtV1
    baseline_depth_debt_hash: str
    claims: tuple[ProjectedClaimV1, ...]
    evidence: tuple[EvidenceExcerptV1, ...]
    retained_claim_count: int
    omitted_claim_count: int
    omitted_claim_descriptor_hash: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "domain_key",
        "presentation_domain_id",
        "baseline_artifact_hash",
        "baseline_depth_debt",
        "baseline_depth_debt_hash",
        "claims",
        "evidence",
        "retained_claim_count",
        "omitted_claim_count",
        "omitted_claim_descriptor_hash",
    )

    def __post_init__(self) -> None:
        digest_value(self.domain_key, "DomainProjectionV1.domain_key")
        safe_id(
            self.presentation_domain_id,
            "DomainProjectionV1.presentation_domain_id",
        )
        digest_value(
            self.baseline_artifact_hash,
            "DomainProjectionV1.baseline_artifact_hash",
        )
        if not isinstance(self.baseline_depth_debt, DepthDebtV1):
            raise Protocol22SchemaError(
                "DomainProjectionV1.baseline_depth_debt must be DepthDebtV1"
            )
        digest_value(
            self.baseline_depth_debt_hash,
            "DomainProjectionV1.baseline_depth_debt_hash",
        )
        if self.baseline_depth_debt_hash != content_digest(
            self.baseline_depth_debt.to_json_dict()
        ):
            raise Protocol22SchemaError(
                "DomainProjectionV1 baseline depth-debt hash mismatch"
            )
        claims = _tuple_of(self.claims, ProjectedClaimV1, "DomainProjectionV1.claims")
        surface_order = tuple(_PROJECTION_SURFACES[item.surface] for item in claims)
        if surface_order != tuple(sorted(surface_order)):
            raise Protocol22SchemaError(
                "DomainProjectionV1.claims violate projection surface priority"
            )
        object.__setattr__(self, "claims", claims)
        evidence = _tuple_of(
            self.evidence,
            EvidenceExcerptV1,
            "DomainProjectionV1.evidence",
        )
        evidence_keys = tuple(item.sort_key for item in evidence)
        if evidence_keys != tuple(sorted(set(evidence_keys))):
            raise Protocol22SchemaError(
                "DomainProjectionV1.evidence must be sorted and unique"
            )
        if any(
            item.ownership != "domain_projection"
            or item.origin_domain_key != self.domain_key
            for item in evidence
        ):
            raise Protocol22SchemaError(
                "DomainProjectionV1 evidence must match its projected domain"
            )
        object.__setattr__(self, "evidence", evidence)
        nonnegative_int(
            self.retained_claim_count,
            "DomainProjectionV1.retained_claim_count",
        )
        nonnegative_int(
            self.omitted_claim_count,
            "DomainProjectionV1.omitted_claim_count",
        )
        optional_digest(
            self.omitted_claim_descriptor_hash,
            "DomainProjectionV1.omitted_claim_descriptor_hash",
        )
        if self.retained_claim_count != len(claims):
            raise Protocol22SchemaError(
                "DomainProjectionV1.retained_claim_count must equal claims"
            )
        _zero_null(
            self.omitted_claim_count,
            self.omitted_claim_descriptor_hash,
            "DomainProjectionV1.omitted_claim_descriptor_hash",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "domain_key": self.domain_key,
            "presentation_domain_id": self.presentation_domain_id,
            "baseline_artifact_hash": self.baseline_artifact_hash,
            "baseline_depth_debt": self.baseline_depth_debt.to_json_dict(),
            "baseline_depth_debt_hash": self.baseline_depth_debt_hash,
            "claims": [item.to_json_dict() for item in self.claims],
            "evidence": [item.to_json_dict() for item in self.evidence],
            "retained_claim_count": self.retained_claim_count,
            "omitted_claim_count": self.omitted_claim_count,
            "omitted_claim_descriptor_hash": self.omitted_claim_descriptor_hash,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "DomainProjectionV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        claims = raw["claims"]
        evidence = raw["evidence"]
        if not isinstance(claims, (list, tuple)) or not isinstance(
            evidence, (list, tuple)
        ):
            raise Protocol22SchemaError(
                "DomainProjectionV1 claims and evidence must be arrays"
            )
        return cls(
            domain_key=raw["domain_key"],
            presentation_domain_id=raw["presentation_domain_id"],
            baseline_artifact_hash=raw["baseline_artifact_hash"],
            baseline_depth_debt=DepthDebtV1.from_json_dict(
                raw["baseline_depth_debt"]
            ),
            baseline_depth_debt_hash=raw["baseline_depth_debt_hash"],
            claims=tuple(ProjectedClaimV1.from_json_dict(item) for item in claims),
            evidence=tuple(EvidenceExcerptV1.from_json_dict(item) for item in evidence),
            retained_claim_count=raw["retained_claim_count"],
            omitted_claim_count=raw["omitted_claim_count"],
            omitted_claim_descriptor_hash=raw["omitted_claim_descriptor_hash"],
        )


@dataclass(frozen=True, slots=True)
class ContextBundleV1:
    schema_version: int
    artifact_kind: Literal[
        "domain-context-bundle", "source-overview-context-bundle"
    ]
    target_artifact_kind: Literal["domain-baseline", "source-overview"]
    scope: ArtifactScope
    context_policy_hash: str
    target_policy_hash: str
    target_artifact_policy: ArtifactPolicyEntryV1
    dependencies: tuple[ArtifactDependencyV1, ...]
    evidence_pack_hash: str
    evidence: tuple[EvidenceExcerptV1, ...]
    domain_projections: tuple[DomainProjectionV1, ...]
    depth_debt: DepthDebtV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_kind",
        "target_artifact_kind",
        "scope",
        "context_policy_hash",
        "target_policy_hash",
        "target_artifact_policy",
        "dependencies",
        "evidence_pack_hash",
        "evidence",
        "domain_projections",
        "depth_debt",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22SchemaError("ContextBundleV1.schema_version must be 1")
        one_of(self.artifact_kind, _CONTEXT_KINDS, "ContextBundleV1.artifact_kind")
        one_of(
            self.target_artifact_kind,
            _TARGET_KINDS,
            "ContextBundleV1.target_artifact_kind",
        )
        expected_target = (
            "domain-baseline"
            if self.artifact_kind == "domain-context-bundle"
            else "source-overview"
        )
        if self.target_artifact_kind != expected_target:
            raise Protocol22SchemaError(
                "ContextBundleV1 target artifact does not match context kind"
            )
        if not isinstance(self.scope, ArtifactScope):
            raise Protocol22SchemaError("ContextBundleV1.scope must be ArtifactScope")
        if (self.artifact_kind == "domain-context-bundle") != self.scope.is_domain:
            raise Protocol22SchemaError(
                "ContextBundleV1 scope does not match context kind"
            )
        digest_value(self.context_policy_hash, "ContextBundleV1.context_policy_hash")
        digest_value(self.target_policy_hash, "ContextBundleV1.target_policy_hash")
        if not isinstance(self.target_artifact_policy, ArtifactPolicyEntryV1):
            raise Protocol22SchemaError(
                "ContextBundleV1.target_artifact_policy must be a closed policy"
            )
        if (
            self.target_artifact_policy.artifact_kind != self.target_artifact_kind
            or layer_policy_hash(self.target_artifact_policy)
            != self.target_policy_hash
        ):
            raise Protocol22SchemaError("ContextBundleV1 target policy hash mismatch")
        dependencies = _tuple_of(
            self.dependencies,
            ArtifactDependencyV1,
            "ContextBundleV1.dependencies",
        )
        keys = tuple((item.artifact_kind, item.artifact_hash) for item in dependencies)
        if keys != tuple(sorted(set(keys))):
            raise Protocol22SchemaError(
                "ContextBundleV1.dependencies must be sorted and unique"
            )
        if len({item.artifact_hash for item in dependencies}) != len(dependencies):
            raise Protocol22SchemaError(
                "ContextBundleV1 dependency hashes must be unique"
            )
        object.__setattr__(self, "dependencies", dependencies)
        digest_value(self.evidence_pack_hash, "ContextBundleV1.evidence_pack_hash")
        if sum(
            item.artifact_hash == self.evidence_pack_hash for item in dependencies
        ) != 1:
            raise Protocol22SchemaError(
                "ContextBundleV1 evidence pack must occur exactly once in dependencies"
            )
        evidence = _tuple_of(
            self.evidence,
            EvidenceExcerptV1,
            "ContextBundleV1.evidence",
        )
        evidence_keys = tuple(item.sort_key for item in evidence)
        if evidence_keys != tuple(sorted(set(evidence_keys))):
            raise Protocol22SchemaError(
                "ContextBundleV1.evidence must be sorted and unique"
            )
        object.__setattr__(self, "evidence", evidence)
        projections = _tuple_of(
            self.domain_projections,
            DomainProjectionV1,
            "ContextBundleV1.domain_projections",
        )
        domain_keys = tuple(item.domain_key for item in projections)
        if domain_keys != tuple(sorted(set(domain_keys))):
            raise Protocol22SchemaError(
                "ContextBundleV1.domain_projections must be sorted and unique"
            )
        if self.artifact_kind == "domain-context-bundle" and projections:
            raise Protocol22SchemaError(
                "domain ContextBundleV1 must not contain domain projections"
            )
        object.__setattr__(self, "domain_projections", projections)
        if not isinstance(self.depth_debt, DepthDebtV1):
            raise Protocol22SchemaError(
                "ContextBundleV1.depth_debt must be DepthDebtV1"
            )
        maximum = self.target_artifact_policy.max_context_bundle_bytes
        if maximum is None:
            raise Protocol22SchemaError(
                "ContextBundleV1 target policy lacks a context-byte ceiling"
            )
        if len(canonical_json_bytes(self.to_json_dict())) > maximum:
            raise Protocol22SchemaError(
                "ContextBundleV1 exceeds target context-byte ceiling"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_kind": self.artifact_kind,
            "target_artifact_kind": self.target_artifact_kind,
            "scope": self.scope.to_json_dict(),
            "context_policy_hash": self.context_policy_hash,
            "target_policy_hash": self.target_policy_hash,
            "target_artifact_policy": self.target_artifact_policy.to_json_dict(),
            "dependencies": [item.to_json_dict() for item in self.dependencies],
            "evidence_pack_hash": self.evidence_pack_hash,
            "evidence": [item.to_json_dict() for item in self.evidence],
            "domain_projections": [
                item.to_json_dict() for item in self.domain_projections
            ],
            "depth_debt": self.depth_debt.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ContextBundleV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        dependencies = raw["dependencies"]
        evidence = raw["evidence"]
        projections = raw["domain_projections"]
        if not all(isinstance(value, (list, tuple)) for value in (
            dependencies,
            evidence,
            projections,
        )):
            raise Protocol22SchemaError(
                "ContextBundleV1 dependency, evidence, and projection fields must be arrays"
            )
        return cls(
            schema_version=raw["schema_version"],
            artifact_kind=raw["artifact_kind"],
            target_artifact_kind=raw["target_artifact_kind"],
            scope=ArtifactScope.from_json_dict(raw["scope"]),
            context_policy_hash=raw["context_policy_hash"],
            target_policy_hash=raw["target_policy_hash"],
            target_artifact_policy=ArtifactPolicyEntryV1.from_json_dict(
                raw["target_artifact_policy"]
            ),
            dependencies=tuple(
                ArtifactDependencyV1.from_json_dict(item) for item in dependencies
            ),
            evidence_pack_hash=raw["evidence_pack_hash"],
            evidence=tuple(EvidenceExcerptV1.from_json_dict(item) for item in evidence),
            domain_projections=tuple(
                DomainProjectionV1.from_json_dict(item) for item in projections
            ),
            depth_debt=DepthDebtV1.from_json_dict(raw["depth_debt"]),
        )


@dataclass(frozen=True, slots=True)
class ArtifactEnvelopeV1:
    artifact_kind: str
    layer: Literal["L0", "L1"]
    scope: ArtifactScope
    partition_id: str
    layer_policy_hash: str
    dependency_hashes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "artifact_kind",
        "layer",
        "scope",
        "partition_id",
        "layer_policy_hash",
        "dependency_hashes",
    )

    def __post_init__(self) -> None:
        safe_id(self.artifact_kind, "ArtifactEnvelopeV1.artifact_kind")
        one_of(self.layer, frozenset({"L0", "L1"}), "ArtifactEnvelopeV1.layer")
        if not isinstance(self.scope, ArtifactScope):
            raise Protocol22SchemaError("ArtifactEnvelopeV1.scope must be ArtifactScope")
        digest_value(self.partition_id, "ArtifactEnvelopeV1.partition_id")
        digest_value(
            self.layer_policy_hash,
            "ArtifactEnvelopeV1.layer_policy_hash",
        )
        object.__setattr__(
            self,
            "dependency_hashes",
            sorted_unique_digests(
                self.dependency_hashes,
                "ArtifactEnvelopeV1.dependency_hashes",
            ),
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "artifact_kind": self.artifact_kind,
            "layer": self.layer,
            "scope": self.scope.to_json_dict(),
            "partition_id": self.partition_id,
            "layer_policy_hash": self.layer_policy_hash,
            "dependency_hashes": list(self.dependency_hashes),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ArtifactEnvelopeV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(
            artifact_kind=raw["artifact_kind"],
            layer=raw["layer"],
            scope=ArtifactScope.from_json_dict(raw["scope"]),
            partition_id=raw["partition_id"],
            layer_policy_hash=raw["layer_policy_hash"],
            dependency_hashes=raw["dependency_hashes"],
        )


@dataclass(frozen=True, slots=True)
class SourceBaselineDomainV1:
    domain_key: str
    presentation_domain_id: str
    baseline_artifact_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "domain_key",
        "presentation_domain_id",
        "baseline_artifact_hash",
    )

    def __post_init__(self) -> None:
        digest_value(self.domain_key, "SourceBaselineDomainV1.domain_key")
        safe_id(
            self.presentation_domain_id,
            "SourceBaselineDomainV1.presentation_domain_id",
        )
        digest_value(
            self.baseline_artifact_hash,
            "SourceBaselineDomainV1.baseline_artifact_hash",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SourceBaselineDomainV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SourceBaselineRootV1:
    schema_version: int
    artifact: ArtifactEnvelopeV1
    overview_artifact_hash: str
    domains: tuple[SourceBaselineDomainV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact",
        "overview_artifact_hash",
        "domains",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22SchemaError("SourceBaselineRootV1.schema_version must be 1")
        if not isinstance(self.artifact, ArtifactEnvelopeV1):
            raise Protocol22SchemaError(
                "SourceBaselineRootV1.artifact must be ArtifactEnvelopeV1"
            )
        if (
            self.artifact.artifact_kind != "source-baseline-root"
            or self.artifact.layer != "L1"
            or self.artifact.scope.is_domain
        ):
            raise Protocol22SchemaError(
                "SourceBaselineRootV1 requires a source-scoped L1 root envelope"
            )
        digest_value(
            self.overview_artifact_hash,
            "SourceBaselineRootV1.overview_artifact_hash",
        )
        domains = _tuple_of(
            self.domains,
            SourceBaselineDomainV1,
            "SourceBaselineRootV1.domains",
        )
        keys = tuple(item.domain_key for item in domains)
        if keys != tuple(sorted(set(keys))):
            raise Protocol22SchemaError(
                "SourceBaselineRootV1.domains must be sorted and unique"
            )
        object.__setattr__(self, "domains", domains)
        expected_dependencies = tuple(
            sorted(
                (
                    self.overview_artifact_hash,
                    *(item.baseline_artifact_hash for item in domains),
                )
            )
        )
        if self.artifact.dependency_hashes != expected_dependencies:
            raise Protocol22SchemaError(
                "SourceBaselineRootV1 dependency hashes do not equal overview and domains"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact": self.artifact.to_json_dict(),
            "overview_artifact_hash": self.overview_artifact_hash,
            "domains": [item.to_json_dict() for item in self.domains],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SourceBaselineRootV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        domains = raw["domains"]
        if not isinstance(domains, (list, tuple)):
            raise Protocol22SchemaError(
                "SourceBaselineRootV1.domains must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            artifact=ArtifactEnvelopeV1.from_json_dict(raw["artifact"]),
            overview_artifact_hash=raw["overview_artifact_hash"],
            domains=tuple(SourceBaselineDomainV1.from_json_dict(item) for item in domains),
        )


@dataclass(frozen=True, slots=True)
class AcceptedDependencySetV2:
    by_role: Mapping[str, AcceptedArtifactV2]
    payloads_by_hash: Mapping[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.by_role, Mapping):
            raise Protocol22SchemaError(
                "AcceptedDependencySetV2.by_role must be a mapping"
            )
        copied: dict[str, AcceptedArtifactV2] = {}
        for role, artifact in self.by_role.items():
            safe_id(role, "AcceptedDependencySetV2 role")
            if not isinstance(artifact, AcceptedArtifactV2):
                raise Protocol22SchemaError(
                    "AcceptedDependencySetV2 values must be AcceptedArtifactV2"
                )
            copied[role] = artifact
        object.__setattr__(
            self,
            "by_role",
            MappingProxyType(dict(sorted(copied.items()))),
        )
        if not isinstance(self.payloads_by_hash, Mapping):
            raise Protocol22SchemaError(
                "AcceptedDependencySetV2.payloads_by_hash must be a mapping"
            )
        payloads: dict[str, bytes] = {}
        for artifact_hash, payload in self.payloads_by_hash.items():
            digest_value(
                artifact_hash,
                "AcceptedDependencySetV2 payload content address",
            )
            if not isinstance(payload, bytes):
                raise Protocol22SchemaError(
                    "AcceptedDependencySetV2 payload values must be bytes"
                )
            if content_digest(payload) != artifact_hash:
                raise Protocol22SchemaError(
                    "dependency payload does not match its content address"
                )
            payloads[artifact_hash] = payload
        object.__setattr__(
            self,
            "payloads_by_hash",
            MappingProxyType(dict(sorted(payloads.items()))),
        )

    def payload_for_role(self, role: str) -> bytes:
        artifact = self.by_role.get(role)
        if artifact is None:
            raise Protocol22SchemaError(
                f"accepted dependency role is missing: {role}"
            )
        payload = self.payloads_by_hash.get(artifact.artifact_hash)
        if payload is None:
            raise Protocol22SchemaError(
                f"accepted dependency payload is missing for role: {role}"
            )
        return payload

    def payload_for_hash(self, artifact_hash: str) -> bytes:
        digest_value(
            artifact_hash,
            "AcceptedDependencySetV2 requested payload hash",
        )
        payload = self.payloads_by_hash.get(artifact_hash)
        if payload is None:
            raise Protocol22SchemaError(
                f"accepted dependency closure payload is missing: {artifact_hash}"
            )
        return payload


@dataclass(frozen=True, slots=True)
class DeterministicAssessmentInputV2:
    canonical_schema_valid: bool
    dependency_closure_valid: bool
    policy_conformance_valid: bool
    depth_debt: DepthDebtV1 | None
    normalized_diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in (
            "canonical_schema_valid",
            "dependency_closure_valid",
            "policy_conformance_valid",
        ):
            boolean(getattr(self, field), f"DeterministicAssessmentInputV2.{field}")
        if self.depth_debt is not None and not isinstance(self.depth_debt, DepthDebtV1):
            raise Protocol22SchemaError(
                "DeterministicAssessmentInputV2.depth_debt must be DepthDebtV1 or null"
            )
        if not isinstance(self.normalized_diagnostics, (list, tuple)):
            raise Protocol22SchemaError(
                "DeterministicAssessmentInputV2.normalized_diagnostics must be an array"
            )
        diagnostics: list[str] = []
        for item in self.normalized_diagnostics:
            text = text_value(
                item,
                "DeterministicAssessmentInputV2.normalized_diagnostics",
            )
            if text.strip() != text or len(text.encode("utf-8")) > 1024:
                raise Protocol22SchemaError(
                    "deterministic diagnostic must be normalized bounded text"
                )
            diagnostics.append(text)
        frozen = tuple(diagnostics)
        if frozen != tuple(sorted(set(frozen))) or len(frozen) > 64:
            raise Protocol22SchemaError(
                "deterministic diagnostics must be sorted, unique, and bounded"
            )
        passed = (
            self.canonical_schema_valid
            and self.dependency_closure_valid
            and self.policy_conformance_valid
        )
        if passed != (not frozen):
            raise Protocol22SchemaError(
                "deterministic validation truth values and diagnostics disagree"
            )
        object.__setattr__(self, "normalized_diagnostics", frozen)


__all__ = (
    "AcceptedDependencySetV2",
    "ArtifactDependencyV1",
    "ArtifactEnvelopeV1",
    "ClaimV1",
    "ContextBundleV1",
    "DepthDebtV1",
    "DeterministicAssessmentInputV2",
    "DomainDepthDebtRollupV1",
    "DomainProjectionV1",
    "EvidenceExcerptV1",
    "EvidencePackV1",
    "EvidenceReferenceV1",
    "OmittedDomainDescriptorV1",
    "OmittedEvidenceDescriptorV1",
    "OmittedProjectedClaimDescriptorV1",
    "ProjectedClaimV1",
    "SourceBaselineDomainV1",
    "SourceBaselineRootV1",
)

"""Closed producer and independent-verifier artifacts for protocol 2.8."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Mapping, TypeVar

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    nonnegative_int,
    one_of,
    positive_int,
    safe_id,
    safe_relative_path,
    sorted_unique_digests,
    text_value,
)
from harness.re_v2.protocol_28.evidence import SnapshotEvidenceCatalogV1
from harness.re_v2.protocol_28.planning import SlicePlanEntryV1, SliceSpecV1
from harness.re_v2.protocol_28.policies import ExhaustivePolicyV1


_TARGET_KINDS = frozenset({"domain", "source"})
_CLAIM_KINDS = frozenset(
    {"behavioral", "boundary", "failure", "invariant", "configuration", "security", "operational", "negative-space"}
)
_OBSERVATION_DISPOSITIONS = frozenset({"applicable", "not-applicable", "unknown", "unresolved"})
_VERDICTS = frozenset({"PASS", "REPAIR"})
_DIAGNOSTIC_CLASSES = frozenset(
    {
        "missing-planned-coverage",
        "unsupported-claim",
        "contradictory-claim",
        "invalid-or-insufficient-evidence",
        "incomplete-boundary-behavior",
        "incomplete-failure-recovery-behavior",
        "incomplete-negative-space",
        "unresolved-assigned-l3-finding",
        "malformed-result-contract",
    }
)
_T = TypeVar("_T")


class Protocol28ArtifactError(Protocol22SchemaError):
    """Raised when provider evidence escapes its exact frozen slice contract."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "malformed-result-contract",
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol28ArtifactError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol28ArtifactError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(canonical_json_bytes(value))


def _digests(value: object, field: str) -> tuple[str, ...]:
    return _schema(sorted_unique_digests, value, field)


def _typed(value: object, cls: type[_T], field: str) -> tuple[_T, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, cls) for item in value):
        raise Protocol28ArtifactError(f"{field} must contain {cls.__name__} values")
    result = tuple(value)
    ids = tuple(item.identity for item in result)  # type: ignore[attr-defined]
    if ids != tuple(sorted(set(ids))):
        raise Protocol28ArtifactError(f"{field} must be canonically sorted and unique")
    return result


def _bounded_text(value: object, field: str, maximum: int) -> str:
    text = _schema(text_value, value, field)
    if len(text.encode("utf-8")) > maximum:
        raise Protocol28ArtifactError(f"{field} exceeds {maximum} UTF-8 bytes")
    return text


def _ordered_provider_digest_set(value: object) -> object:
    """Canonicalize order for a provider-emitted set without hiding bad values."""
    if isinstance(value, (list, tuple)) and all(
        isinstance(item, str) for item in value
    ):
        return tuple(sorted(value))
    return value


def _ordered_provider_fields(
    value: object,
    fields: tuple[str, ...],
    digest_fields: frozenset[str],
    owner: str,
) -> dict[str, object]:
    raw = _schema(exact_object, value, frozenset(fields), owner)
    return {
        field: (
            _ordered_provider_digest_set(raw[field])
            if field in digest_fields
            else raw[field]
        )
        for field in fields
    }


@dataclass(frozen=True, slots=True)
class EvidenceAnchorV1:
    schema_version: int
    evidence_id: str
    source_id: str
    source_relative_path: str
    byte_start: int
    byte_end: int
    raw_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "evidence_id", "source_id", "source_relative_path",
        "byte_start", "byte_end", "raw_hash",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "EvidenceAnchorV1.schema_version")
        _schema(digest_value, self.evidence_id, "EvidenceAnchorV1.evidence_id")
        _schema(safe_id, self.source_id, "EvidenceAnchorV1.source_id")
        _schema(safe_relative_path, self.source_relative_path, "EvidenceAnchorV1.source_relative_path")
        _schema(nonnegative_int, self.byte_start, "EvidenceAnchorV1.byte_start")
        _schema(nonnegative_int, self.byte_end, "EvidenceAnchorV1.byte_end")
        if self.byte_end < self.byte_start:
            raise Protocol28ArtifactError("EvidenceAnchorV1 byte range is reversed")
        _schema(digest_value, self.raw_hash, "EvidenceAnchorV1.raw_hash")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "EvidenceAnchorV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ExhaustiveClaimV1:
    schema_version: int
    claim_kind: str
    subject_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    statement: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "claim_kind", "subject_ids", "evidence_anchor_ids", "statement",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ExhaustiveClaimV1.schema_version")
        _schema(one_of, self.claim_kind, _CLAIM_KINDS, "ExhaustiveClaimV1.claim_kind")
        subjects = _digests(self.subject_ids, "ExhaustiveClaimV1.subject_ids")
        anchors = _digests(self.evidence_anchor_ids, "ExhaustiveClaimV1.evidence_anchor_ids")
        if not subjects or not anchors:
            raise Protocol28ArtifactError("exhaustive claim requires subjects and evidence anchors")
        object.__setattr__(self, "subject_ids", subjects)
        object.__setattr__(self, "evidence_anchor_ids", anchors)
        object.__setattr__(self, "statement", _bounded_text(self.statement, "ExhaustiveClaimV1.statement", 4096))

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "claim_kind": self.claim_kind,
            "subject_ids": list(self.subject_ids), "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "statement": self.statement,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveClaimV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ExhaustiveObservationV1:
    schema_version: int
    disposition: str
    category_id: str
    subject_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    detail: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "disposition", "category_id", "subject_ids", "evidence_ids",
        "finding_ids", "detail",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ExhaustiveObservationV1.schema_version")
        _schema(one_of, self.disposition, _OBSERVATION_DISPOSITIONS, "ExhaustiveObservationV1.disposition")
        _schema(safe_id, self.category_id, "ExhaustiveObservationV1.category_id")
        for field in ("subject_ids", "evidence_ids", "finding_ids"):
            object.__setattr__(self, field, _digests(getattr(self, field), f"ExhaustiveObservationV1.{field}"))
        object.__setattr__(self, "detail", _bounded_text(self.detail, "ExhaustiveObservationV1.detail", 4096))

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "disposition": self.disposition,
            "category_id": self.category_id, "subject_ids": list(self.subject_ids),
            "evidence_ids": list(self.evidence_ids), "finding_ids": list(self.finding_ids),
            "detail": self.detail,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveObservationV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ExhaustiveEvidenceSliceV1:
    schema_version: int
    slice_spec_id: str
    plan_entry_id: str
    target_kind: Literal["domain", "source"]
    source_id: str
    target_id: str
    category_id: str
    covered_primary_subject_ids: tuple[str, ...]
    covered_primary_source_record_ids: tuple[str, ...]
    covered_primary_evidence_ids: tuple[str, ...]
    evidence_anchors: tuple[EvidenceAnchorV1, ...]
    claims: tuple[ExhaustiveClaimV1, ...]
    observations: tuple[ExhaustiveObservationV1, ...]
    addressed_finding_ids: tuple[str, ...]
    unresolved_finding_ids: tuple[str, ...]
    rendered_markdown: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "slice_spec_id", "plan_entry_id", "target_kind", "source_id",
        "target_id", "category_id", "covered_primary_subject_ids",
        "covered_primary_source_record_ids", "covered_primary_evidence_ids",
        "evidence_anchors", "claims", "observations", "addressed_finding_ids",
        "unresolved_finding_ids", "rendered_markdown",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ExhaustiveEvidenceSliceV1.schema_version")
        for field in ("slice_spec_id", "plan_entry_id"):
            _schema(digest_value, getattr(self, field), f"ExhaustiveEvidenceSliceV1.{field}")
        _schema(one_of, self.target_kind, _TARGET_KINDS, "ExhaustiveEvidenceSliceV1.target_kind")
        for field in ("source_id", "target_id", "category_id"):
            _schema(safe_id, getattr(self, field), f"ExhaustiveEvidenceSliceV1.{field}")
        for field in (
            "covered_primary_subject_ids", "covered_primary_source_record_ids",
            "covered_primary_evidence_ids", "addressed_finding_ids", "unresolved_finding_ids",
        ):
            object.__setattr__(self, field, _digests(getattr(self, field), f"ExhaustiveEvidenceSliceV1.{field}"))
        if not set(self.unresolved_finding_ids).issubset(self.addressed_finding_ids):
            raise Protocol28ArtifactError(
                "unresolved findings must be addressed by the slice",
                reason_code="unresolved-findings-not-addressed",
            )
        object.__setattr__(self, "evidence_anchors", _typed(self.evidence_anchors, EvidenceAnchorV1, "evidence_anchors"))
        object.__setattr__(self, "claims", _typed(self.claims, ExhaustiveClaimV1, "claims"))
        object.__setattr__(self, "observations", _typed(self.observations, ExhaustiveObservationV1, "observations"))
        if not self.claims and not self.observations:
            raise Protocol28ArtifactError("exhaustive evidence slice cannot be empty")
        object.__setattr__(self, "rendered_markdown", _bounded_text(
            self.rendered_markdown, "ExhaustiveEvidenceSliceV1.rendered_markdown", 98_304
        ))

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        repeated = {
            "covered_primary_subject_ids", "covered_primary_source_record_ids",
            "covered_primary_evidence_ids", "addressed_finding_ids", "unresolved_finding_ids",
        }
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field not in repeated | {"evidence_anchors", "claims", "observations"}
            },
            **{field: list(getattr(self, field)) for field in repeated},
            "evidence_anchors": [item.to_json_dict() for item in self.evidence_anchors],
            "claims": [item.to_json_dict() for item in self.claims],
            "observations": [item.to_json_dict() for item in self.observations],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveEvidenceSliceV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        for field in ("evidence_anchors", "claims", "observations"):
            if not isinstance(raw[field], (list, tuple)):
                raise Protocol28ArtifactError(f"ExhaustiveEvidenceSliceV1.{field} must be an array")
        return cls(
            **{field: raw[field] for field in cls.FIELDS if field not in {"evidence_anchors", "claims", "observations"}},
            evidence_anchors=tuple(EvidenceAnchorV1.from_json_dict(item) for item in raw["evidence_anchors"]),
            claims=tuple(ExhaustiveClaimV1.from_json_dict(item) for item in raw["claims"]),
            observations=tuple(ExhaustiveObservationV1.from_json_dict(item) for item in raw["observations"]),
        )


def normalize_candidate_result(
    value: object,
    *,
    slice_spec: SliceSpecV1 | None = None,
    plan_entry: SlicePlanEntryV1 | None = None,
) -> ExhaustiveEvidenceSliceV1:
    """Normalize provider transport and collection order into canonical authority.

    A provider may omit fields whose values are already frozen by the controller or
    use the former ``rendered_explanation`` name for rendered prose. Those
    mechanical transport defects are repaired only when both frozen authorities
    are supplied. Provider-authored coverage and semantic content remain strict.
    """
    if (slice_spec is None) != (plan_entry is None):
        raise Protocol28ArtifactError(
            "candidate transport normalization requires both frozen authorities"
        )
    if slice_spec is not None and plan_entry is not None:
        if not isinstance(slice_spec, SliceSpecV1) or not isinstance(
            plan_entry, SlicePlanEntryV1
        ):
            raise Protocol28ArtifactError(
                "candidate transport normalization requires typed frozen authorities"
            )
        if slice_spec.plan_entry_id != plan_entry.identity:
            raise Protocol28ArtifactError("slice spec does not realize plan entry")
        if not isinstance(value, Mapping) or any(
            not isinstance(key, str) for key in value
        ):
            raise Protocol28ArtifactError(
                "ExhaustiveEvidenceSliceV1 must be an object with string fields"
            )
        repaired = dict(value)
        if (
            "rendered_markdown" not in repaired
            and "rendered_explanation" in repaired
        ):
            repaired["rendered_markdown"] = repaired.pop("rendered_explanation")
        frozen_fields: dict[str, object] = {
            "schema_version": 1,
            "slice_spec_id": slice_spec.identity,
            "plan_entry_id": plan_entry.identity,
            "target_kind": plan_entry.target_kind,
            "source_id": plan_entry.source_id,
            "target_id": plan_entry.target_id,
            "category_id": plan_entry.category_id,
        }
        for field, expected in frozen_fields.items():
            repaired.setdefault(field, expected)
        value = repaired
    raw = _schema(
        exact_object,
        value,
        frozenset(ExhaustiveEvidenceSliceV1.FIELDS),
        ExhaustiveEvidenceSliceV1.__name__,
    )
    collections = {
        "evidence_anchors": (
            EvidenceAnchorV1,
            frozenset(),
        ),
        "claims": (
            ExhaustiveClaimV1,
            frozenset({"subject_ids", "evidence_anchor_ids"}),
        ),
        "observations": (
            ExhaustiveObservationV1,
            frozenset({"subject_ids", "evidence_ids", "finding_ids"}),
        ),
    }
    normalized: dict[str, tuple[object, ...]] = {}
    for field, (model, digest_fields) in collections.items():
        items = raw[field]
        if not isinstance(items, (list, tuple)):
            raise Protocol28ArtifactError(
                f"ExhaustiveEvidenceSliceV1.{field} must be an array"
            )
        decoded = tuple(
            model.from_json_dict(
                _ordered_provider_fields(
                    item,
                    model.FIELDS,
                    digest_fields,
                    model.__name__,
                )
            )
            for item in items
        )
        normalized[field] = tuple(sorted(decoded, key=lambda item: item.identity))
    repeated = frozenset(
        {
            "covered_primary_subject_ids",
            "covered_primary_source_record_ids",
            "covered_primary_evidence_ids",
            "addressed_finding_ids",
            "unresolved_finding_ids",
        }
    )
    return ExhaustiveEvidenceSliceV1(
        **{
            field: (
                _ordered_provider_digest_set(raw[field])
                if field in repeated
                else raw[field]
            )
            for field in ExhaustiveEvidenceSliceV1.FIELDS
            if field not in collections
        },
        **normalized,
    )


@dataclass(frozen=True, slots=True)
class ExhaustiveDiagnosticV1:
    schema_version: int
    candidate_id: str
    verifier_policy_id: str
    diagnostic_class: str
    subject_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    detail: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "candidate_id", "verifier_policy_id", "diagnostic_class",
        "subject_ids", "evidence_ids", "finding_ids", "detail",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ExhaustiveDiagnosticV1.schema_version")
        for field in ("candidate_id", "verifier_policy_id"):
            _schema(digest_value, getattr(self, field), f"ExhaustiveDiagnosticV1.{field}")
        _schema(one_of, self.diagnostic_class, _DIAGNOSTIC_CLASSES, "ExhaustiveDiagnosticV1.diagnostic_class")
        for field in ("subject_ids", "evidence_ids", "finding_ids"):
            object.__setattr__(self, field, _digests(getattr(self, field), f"ExhaustiveDiagnosticV1.{field}"))
        object.__setattr__(self, "detail", _bounded_text(self.detail, "ExhaustiveDiagnosticV1.detail", 4096))

    @property
    def identity(self) -> str:
        # Candidate binding and prose are checked separately; the normalized
        # semantic defect identity must remain stable across repair attempts.
        return _identity(
            {
                field: value
                for field, value in self.to_json_dict().items()
                if field not in {"candidate_id", "detail"}
            }
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "candidate_id": self.candidate_id,
            "verifier_policy_id": self.verifier_policy_id,
            "diagnostic_class": self.diagnostic_class, "subject_ids": list(self.subject_ids),
            "evidence_ids": list(self.evidence_ids), "finding_ids": list(self.finding_ids),
            "detail": self.detail,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveDiagnosticV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ExhaustiveVerificationV1:
    schema_version: int
    slice_spec_id: str
    candidate_id: str
    verifier_policy_id: str
    verdict: Literal["PASS", "REPAIR"]
    diagnostics: tuple[ExhaustiveDiagnosticV1, ...]
    verified_primary_evidence_ids: tuple[str, ...]
    assessed_finding_ids: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "slice_spec_id", "candidate_id", "verifier_policy_id", "verdict",
        "diagnostics", "verified_primary_evidence_ids", "assessed_finding_ids",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ExhaustiveVerificationV1.schema_version")
        for field in ("slice_spec_id", "candidate_id", "verifier_policy_id"):
            _schema(digest_value, getattr(self, field), f"ExhaustiveVerificationV1.{field}")
        _schema(one_of, self.verdict, _VERDICTS, "ExhaustiveVerificationV1.verdict")
        object.__setattr__(self, "diagnostics", _typed(self.diagnostics, ExhaustiveDiagnosticV1, "diagnostics"))
        for field in ("verified_primary_evidence_ids", "assessed_finding_ids"):
            object.__setattr__(self, field, _digests(getattr(self, field), f"ExhaustiveVerificationV1.{field}"))

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "slice_spec_id": self.slice_spec_id,
            "candidate_id": self.candidate_id, "verifier_policy_id": self.verifier_policy_id,
            "verdict": self.verdict, "diagnostics": [item.to_json_dict() for item in self.diagnostics],
            "verified_primary_evidence_ids": list(self.verified_primary_evidence_ids),
            "assessed_finding_ids": list(self.assessed_finding_ids),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveVerificationV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        if not isinstance(raw["diagnostics"], (list, tuple)):
            raise Protocol28ArtifactError("ExhaustiveVerificationV1.diagnostics must be an array")
        return cls(
            **{field: raw[field] for field in cls.FIELDS if field != "diagnostics"},
            diagnostics=tuple(ExhaustiveDiagnosticV1.from_json_dict(item) for item in raw["diagnostics"]),
        )


def normalize_verification_result(value: object) -> ExhaustiveVerificationV1:
    """Normalize provider diagnostic order before creating canonical authority."""
    raw = _schema(
        exact_object,
        value,
        frozenset(ExhaustiveVerificationV1.FIELDS),
        ExhaustiveVerificationV1.__name__,
    )
    diagnostics = raw["diagnostics"]
    if not isinstance(diagnostics, (list, tuple)):
        raise Protocol28ArtifactError(
            "ExhaustiveVerificationV1.diagnostics must be an array"
        )
    decoded = tuple(
        ExhaustiveDiagnosticV1.from_json_dict(
            _ordered_provider_fields(
                item,
                ExhaustiveDiagnosticV1.FIELDS,
                frozenset({"subject_ids", "evidence_ids", "finding_ids"}),
                ExhaustiveDiagnosticV1.__name__,
            )
        )
        for item in diagnostics
    )
    repeated = frozenset({"verified_primary_evidence_ids", "assessed_finding_ids"})
    return ExhaustiveVerificationV1(
        **{
            field: (
                _ordered_provider_digest_set(raw[field])
                if field in repeated
                else raw[field]
            )
            for field in ExhaustiveVerificationV1.FIELDS
            if field != "diagnostics"
        },
        diagnostics=tuple(sorted(decoded, key=lambda item: item.identity)),
    )


@dataclass(frozen=True, slots=True)
class ExhaustiveRepairPacketV1:
    schema_version: int
    slice_spec_id: str
    rejected_candidate_id: str
    diagnostic_ids: tuple[str, ...]
    permitted_evidence_ids: tuple[str, ...]
    producer_attempt_number: int

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ExhaustiveRepairPacketV1.schema_version")
        for field in ("slice_spec_id", "rejected_candidate_id"):
            _schema(digest_value, getattr(self, field), f"ExhaustiveRepairPacketV1.{field}")
        for field in ("diagnostic_ids", "permitted_evidence_ids"):
            values = _digests(getattr(self, field), f"ExhaustiveRepairPacketV1.{field}")
            if not values:
                raise Protocol28ArtifactError(f"ExhaustiveRepairPacketV1.{field} must be nonempty")
            object.__setattr__(self, field, values)
        _schema(positive_int, self.producer_attempt_number, "ExhaustiveRepairPacketV1.producer_attempt_number")
        if self.producer_attempt_number not in {2, 3}:
            raise Protocol28ArtifactError("repair producer attempt number must be 2 or 3")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "slice_spec_id": self.slice_spec_id,
            "rejected_candidate_id": self.rejected_candidate_id,
            "diagnostic_ids": list(self.diagnostic_ids),
            "permitted_evidence_ids": list(self.permitted_evidence_ids),
            "producer_attempt_number": self.producer_attempt_number,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveRepairPacketV1":
        fields = (
            "schema_version", "slice_spec_id", "rejected_candidate_id", "diagnostic_ids",
            "permitted_evidence_ids", "producer_attempt_number",
        )
        raw = _schema(exact_object, value, frozenset(fields), cls.__name__)
        return cls(**{field: raw[field] for field in fields})


def validate_candidate(
    slice_spec: SliceSpecV1,
    plan_entry: SlicePlanEntryV1,
    evidence_catalog: SnapshotEvidenceCatalogV1,
    raw: object,
    policy: ExhaustivePolicyV1,
) -> ExhaustiveEvidenceSliceV1:
    if not isinstance(slice_spec, SliceSpecV1) or not isinstance(plan_entry, SlicePlanEntryV1):
        raise Protocol28ArtifactError("candidate validation requires a realized slice and plan entry")
    if slice_spec.plan_entry_id != plan_entry.identity:
        raise Protocol28ArtifactError("slice spec does not realize plan entry")
    if not isinstance(evidence_catalog, SnapshotEvidenceCatalogV1) or not isinstance(policy, ExhaustivePolicyV1):
        raise Protocol28ArtifactError("candidate evidence or policy authority is invalid")
    candidate = normalize_candidate_result(
        raw, slice_spec=slice_spec, plan_entry=plan_entry
    )
    if (
        candidate.slice_spec_id != slice_spec.identity
        or candidate.plan_entry_id != plan_entry.identity
        or (candidate.target_kind, candidate.source_id, candidate.target_id, candidate.category_id)
        != (plan_entry.target_kind, plan_entry.source_id, plan_entry.target_id, plan_entry.category_id)
    ):
        raise Protocol28ArtifactError("candidate scope does not match frozen slice")
    exact = (
        (candidate.covered_primary_subject_ids, plan_entry.primary_subject_ids, "primary subjects"),
        (candidate.covered_primary_source_record_ids, plan_entry.primary_source_record_ids, "primary records"),
        (candidate.covered_primary_evidence_ids, plan_entry.primary_snapshot_evidence_ids, "primary evidence"),
        (candidate.addressed_finding_ids, plan_entry.assigned_finding_ids, "assigned findings"),
    )
    for observed, expected, label in exact:
        if observed != expected:
            raise Protocol28ArtifactError(f"candidate {label} do not exactly match the plan")
    permitted_subjects = set(plan_entry.primary_subject_ids + plan_entry.supporting_subject_ids)
    permitted_evidence = set(
        plan_entry.primary_snapshot_evidence_ids + plan_entry.supporting_snapshot_evidence_ids
    )
    shard_by_id = {item.identity: item for item in evidence_catalog.shards}
    empty_by_id = {item.identity: item for item in evidence_catalog.empty_receipts}
    nontext_by_id = {item.identity: item for item in evidence_catalog.nontext_dispositions}
    anchor_ids: set[str] = set()
    acknowledged: set[str] = set()
    for anchor in candidate.evidence_anchors:
        if anchor.evidence_id not in permitted_evidence:
            raise Protocol28ArtifactError("candidate anchor references unknown evidence")
        if anchor.evidence_id in shard_by_id:
            item = shard_by_id[anchor.evidence_id]
            expected_range = (item.byte_start, item.byte_end)
            expected_hash = item.raw_hash
        elif anchor.evidence_id in empty_by_id:
            item = empty_by_id[anchor.evidence_id]
            expected_range = (0, 0)
            expected_hash = item.file_content_hash
        elif anchor.evidence_id in nontext_by_id:
            item = nontext_by_id[anchor.evidence_id]
            expected_range = (0, item.byte_count)
            expected_hash = item.file_content_hash
        else:
            raise Protocol28ArtifactError("candidate anchor references unavailable evidence")
        if (
            anchor.source_id != item.source_id
            or anchor.source_relative_path != item.source_relative_path
            or (anchor.byte_start, anchor.byte_end) != expected_range
            or anchor.raw_hash != expected_hash
        ):
            raise Protocol28ArtifactError("candidate anchor byte range or source identity is invalid")
        anchor_ids.add(anchor.identity)
        acknowledged.add(anchor.evidence_id)
    if not set(plan_entry.primary_snapshot_evidence_ids).issubset(acknowledged):
        raise Protocol28ArtifactError(
            "candidate primary evidence lacks exact anchors",
            reason_code="missing-primary-evidence-anchors",
        )
    for claim in candidate.claims:
        if not set(claim.subject_ids).issubset(permitted_subjects) or not set(claim.evidence_anchor_ids).issubset(anchor_ids):
            raise Protocol28ArtifactError("candidate claim exceeds subject or evidence boundary")
    for observation in candidate.observations:
        if observation.category_id != plan_entry.category_id:
            raise Protocol28ArtifactError("candidate observation has wrong category")
        if not set(observation.subject_ids).issubset(permitted_subjects):
            raise Protocol28ArtifactError("candidate observation references unknown subject")
        if not set(observation.evidence_ids).issubset(permitted_evidence):
            raise Protocol28ArtifactError("candidate observation references unknown evidence")
        if not set(observation.finding_ids).issubset(plan_entry.assigned_finding_ids):
            raise Protocol28ArtifactError("candidate observation references unknown finding")
    if len(candidate.rendered_markdown.encode("utf-8")) > policy.max_rendered_markdown_bytes:
        raise Protocol28ArtifactError("candidate rendered Markdown exceeds policy")
    structured = candidate.to_json_dict()
    # Rendered Markdown is a separately bounded derived view; it does not steal
    # capacity from the closed structured candidate payload.
    structured["rendered_markdown"] = ""
    if len(canonical_json_bytes(structured)) > policy.max_candidate_output_bytes:
        raise Protocol28ArtifactError("candidate canonical output exceeds policy")
    return candidate


def validate_verification(
    slice_spec: SliceSpecV1,
    plan_entry: SlicePlanEntryV1,
    candidate: ExhaustiveEvidenceSliceV1,
    raw: object,
) -> ExhaustiveVerificationV1:
    if not isinstance(candidate, ExhaustiveEvidenceSliceV1):
        raise Protocol28ArtifactError("verification requires validated candidate")
    verification = normalize_verification_result(raw)
    if (
        verification.slice_spec_id != slice_spec.identity
        or verification.candidate_id != candidate.identity
        or verification.verifier_policy_id != plan_entry.verifier_contract_hash
    ):
        raise Protocol28ArtifactError("verification does not authenticate frozen slice and candidate")
    if verification.verified_primary_evidence_ids != candidate.covered_primary_evidence_ids:
        raise Protocol28ArtifactError("verification primary evidence coverage is incomplete")
    if verification.assessed_finding_ids != candidate.addressed_finding_ids:
        raise Protocol28ArtifactError("verification finding assessment is incomplete")
    for diagnostic in verification.diagnostics:
        if diagnostic.candidate_id != candidate.identity or diagnostic.verifier_policy_id != plan_entry.verifier_contract_hash:
            raise Protocol28ArtifactError("verification diagnostic authority mismatch")
        if (
            not set(diagnostic.subject_ids).issubset(
                plan_entry.primary_subject_ids + plan_entry.supporting_subject_ids
            )
            or not set(diagnostic.evidence_ids).issubset(
                plan_entry.primary_snapshot_evidence_ids
                + plan_entry.supporting_snapshot_evidence_ids
            )
            or not set(diagnostic.finding_ids).issubset(plan_entry.assigned_finding_ids)
        ):
            raise Protocol28ArtifactError("verification diagnostic exceeds frozen boundary")
    unresolved = bool(candidate.unresolved_finding_ids) or any(
        item.disposition in {"unknown", "unresolved"} for item in candidate.observations
    )
    if verification.verdict == "PASS":
        if verification.diagnostics:
            raise Protocol28ArtifactError("PASS verification cannot contain diagnostics")
        if unresolved:
            raise Protocol28ArtifactError("PASS verification cannot accept unresolved observations")
    elif not verification.diagnostics:
        raise Protocol28ArtifactError("REPAIR verification requires a normalized diagnostic")
    return verification


__all__ = (
    "EvidenceAnchorV1", "ExhaustiveClaimV1", "ExhaustiveDiagnosticV1",
    "ExhaustiveEvidenceSliceV1", "ExhaustiveObservationV1", "ExhaustiveRepairPacketV1",
    "ExhaustiveVerificationV1", "Protocol28ArtifactError",
    "normalize_candidate_result", "normalize_verification_result",
    "validate_candidate", "validate_verification",
)

"""Canonical subject normalization and exhaustive plan construction for 2.8."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, TypeVar

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    nonnegative_int,
    one_of,
    safe_id,
    sorted_unique_digests,
)
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.authority import (
    L3TargetAuthorityProjectionV1,
    L3TargetProjectionCatalogV1,
    ParentAuthorityBundleV3,
)
from harness.re_v2.protocol_28.evidence import (
    SnapshotEvidenceCatalogV1,
    TargetSnapshotEvidenceProjectionV1,
)
from harness.re_v2.protocol_28.policies import ExhaustivePolicyV1, ExhaustivePolicyV2


_TARGET_KINDS = frozenset({"domain", "source"})
_T = TypeVar("_T")


class Protocol28PlanningError(Protocol22SchemaError):
    """Raised before activation when exhaustive work cannot be proven complete."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol28PlanningError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol28PlanningError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(canonical_json_bytes(value))


def _digests(value: object, field: str) -> tuple[str, ...]:
    return _schema(sorted_unique_digests, value, field)


def _safe_ids(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise Protocol28PlanningError(f"{field} must be an array")
    result = tuple(_schema(safe_id, item, field) for item in value)
    if result != tuple(sorted(set(result), key=lambda item: item.encode("utf-8"))):
        raise Protocol28PlanningError(f"{field} must be canonically sorted and unique")
    return result


def _typed(value: object, cls: type[_T], field: str, *, key) -> tuple[_T, ...]:  # type: ignore[no-untyped-def]
    if not isinstance(value, (tuple, list)) or any(not isinstance(item, cls) for item in value):
        raise Protocol28PlanningError(f"{field} must contain {cls.__name__} values")
    result = tuple(value)
    keys = tuple(key(item) for item in result)
    if keys != tuple(sorted(set(keys))):
        raise Protocol28PlanningError(f"{field} must be canonically sorted and unique")
    return result


@dataclass(frozen=True, slots=True)
class ExhaustiveSubjectV1:
    schema_version: int
    target_kind: Literal["domain", "source"]
    source_id: str
    target_id: str
    subject_id: str
    category_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    lower_authority_ids: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "target_kind", "source_id", "target_id", "subject_id",
        "category_ids", "evidence_ids", "finding_ids", "lower_authority_ids",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(one_of, self.target_kind, _TARGET_KINDS, f"{label}.target_kind")
        for field in ("source_id", "target_id", "subject_id"):
            _schema(safe_id, getattr(self, field), f"{label}.{field}")
        if self.target_kind == "source" and self.target_id != self.source_id:
            raise Protocol28PlanningError("source subject target_id must equal source_id")
        categories = _safe_ids(self.category_ids, f"{label}.category_ids")
        if not categories:
            raise Protocol28PlanningError("ExhaustiveSubjectV1 requires a category")
        object.__setattr__(self, "category_ids", categories)
        for field in ("evidence_ids", "finding_ids", "lower_authority_ids"):
            object.__setattr__(self, field, _digests(getattr(self, field), f"{label}.{field}"))

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        return self.source_id, self.target_kind, self.target_id, self.subject_id

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{field: getattr(self, field) for field in self.FIELDS[:5]},
            **{field: list(getattr(self, field)) for field in self.FIELDS[5:]},
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveSubjectV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ExhaustiveSubjectCatalogV1:
    schema_version: int
    source_snapshot_id: str
    partition_manifest_id: str
    l3_projection_catalog_id: str
    subjects: tuple[ExhaustiveSubjectV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "source_snapshot_id", "partition_manifest_id",
        "l3_projection_catalog_id", "subjects",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ExhaustiveSubjectCatalogV1.schema_version")
        for field in self.FIELDS[1:4]:
            _schema(digest_value, getattr(self, field), f"ExhaustiveSubjectCatalogV1.{field}")
        object.__setattr__(self, "subjects", _typed(
            self.subjects, ExhaustiveSubjectV1, "ExhaustiveSubjectCatalogV1.subjects",
            key=lambda item: item.sort_key,
        ))

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_snapshot_id": self.source_snapshot_id,
            "partition_manifest_id": self.partition_manifest_id,
            "l3_projection_catalog_id": self.l3_projection_catalog_id,
            "subjects": [item.to_json_dict() for item in self.subjects],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveSubjectCatalogV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        if not isinstance(raw["subjects"], (tuple, list)):
            raise Protocol28PlanningError("ExhaustiveSubjectCatalogV1.subjects must be an array")
        return cls(
            raw["schema_version"], raw["source_snapshot_id"], raw["partition_manifest_id"],
            raw["l3_projection_catalog_id"],
            tuple(ExhaustiveSubjectV1.from_json_dict(item) for item in raw["subjects"]),
        )


def build_exhaustive_subject_catalog(
    source_snapshot_id: str,
    partition_manifest_id: str,
    l3_projection_catalog_id: str,
    subjects: tuple[ExhaustiveSubjectV1, ...],
) -> ExhaustiveSubjectCatalogV1:
    """Normalize authenticated lower-layer subjects without model discovery."""
    return ExhaustiveSubjectCatalogV1(
        1, source_snapshot_id, partition_manifest_id, l3_projection_catalog_id,
        tuple(sorted(subjects, key=lambda item: item.sort_key)),
    )


@dataclass(frozen=True, slots=True)
class CategoryVacancyReceiptV1:
    schema_version: int
    target_kind: Literal["domain", "source"]
    source_id: str
    target_id: str
    category_id: str
    coverage_ledger_seed_id: str

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "CategoryVacancyReceiptV1.schema_version")
        _schema(one_of, self.target_kind, _TARGET_KINDS, "CategoryVacancyReceiptV1.target_kind")
        for field in ("source_id", "target_id", "category_id"):
            _schema(safe_id, getattr(self, field), f"CategoryVacancyReceiptV1.{field}")
        _schema(digest_value, self.coverage_ledger_seed_id, "CategoryVacancyReceiptV1.coverage_ledger_seed_id")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in (
            "schema_version", "target_kind", "source_id", "target_id", "category_id",
            "coverage_ledger_seed_id",
        )}

    @classmethod
    def from_json_dict(cls, value: object) -> "CategoryVacancyReceiptV1":
        if cls is CategoryVacancyReceiptV1 and isinstance(value, dict) and 'reviewed_disposition_id' in value:
            return ReviewedCategoryVacancyReceiptV1.from_json_dict(value)
        fields = frozenset(
            {"schema_version", "target_kind", "source_id", "target_id", "category_id", "coverage_ledger_seed_id"}
        )
        raw = _schema(exact_object, value, fields, cls.__name__)
        return cls(**{field: raw[field] for field in fields})


@dataclass(frozen=True, slots=True)
class ReviewedCategoryVacancyReceiptV1(CategoryVacancyReceiptV1):
    """Only this explicit vacancy subtype can omit reviewed category work."""
    reviewed_disposition_id: str

    def __post_init__(self):
        super(ReviewedCategoryVacancyReceiptV1, self).__post_init__()
        _schema(digest_value, self.reviewed_disposition_id, 'reviewed_disposition_id')

    def to_json_dict(self):
        return {**super(ReviewedCategoryVacancyReceiptV1, self).to_json_dict(),
                'reviewed_disposition_id': self.reviewed_disposition_id}

    @classmethod
    def from_json_dict(cls, value):
        names = {'schema_version', 'target_kind', 'source_id', 'target_id', 'category_id',
                 'coverage_ledger_seed_id', 'reviewed_disposition_id'}
        raw = _schema(exact_object, value, frozenset(names), cls.__name__)
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class SlicePlanEntryV1:
    schema_version: int
    target_kind: Literal["domain", "source"]
    source_id: str
    target_id: str
    category_id: str
    ordinal: int
    target_l3_projection_id: str
    target_evidence_projection_id: str
    primary_subject_ids: tuple[str, ...]
    supporting_subject_ids: tuple[str, ...]
    primary_source_record_ids: tuple[str, ...]
    supporting_source_record_ids: tuple[str, ...]
    primary_snapshot_evidence_ids: tuple[str, ...]
    supporting_snapshot_evidence_ids: tuple[str, ...]
    assigned_finding_ids: tuple[str, ...]
    required_lower_authority_ids: tuple[str, ...]
    planned_dependency_root_ids: tuple[str, ...]
    producer_contract_hash: str
    verifier_contract_hash: str
    canonical_context_bytes: int
    conservative_tokens: int

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(one_of, self.target_kind, _TARGET_KINDS, f"{label}.target_kind")
        for field in ("source_id", "target_id", "category_id"):
            _schema(safe_id, getattr(self, field), f"{label}.{field}")
        _schema(nonnegative_int, self.ordinal, f"{label}.ordinal")
        digest_fields = (
            "target_l3_projection_id", "target_evidence_projection_id",
            "producer_contract_hash", "verifier_contract_hash",
        )
        for field in digest_fields:
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        for field in (
            "primary_subject_ids", "supporting_subject_ids", "primary_source_record_ids",
            "supporting_source_record_ids", "primary_snapshot_evidence_ids",
            "supporting_snapshot_evidence_ids", "assigned_finding_ids",
            "required_lower_authority_ids", "planned_dependency_root_ids",
        ):
            object.__setattr__(self, field, _digests(getattr(self, field), f"{label}.{field}"))
        for field in ("canonical_context_bytes", "conservative_tokens"):
            _schema(nonnegative_int, getattr(self, field), f"{label}.{field}")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def plan_entry_id(self) -> str:
        return self.identity

    def to_json_dict(self) -> dict[str, object]:
        repeated = {
            "primary_subject_ids", "supporting_subject_ids", "primary_source_record_ids",
            "supporting_source_record_ids", "primary_snapshot_evidence_ids",
            "supporting_snapshot_evidence_ids", "assigned_finding_ids",
            "required_lower_authority_ids", "planned_dependency_root_ids",
        }
        fields = tuple(self.__dataclass_fields__)  # type: ignore[attr-defined]
        return {
            **{field: getattr(self, field) for field in fields if field not in repeated},
            **{field: list(getattr(self, field)) for field in repeated},
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SlicePlanEntryV1":
        fields = tuple(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        raw = _schema(exact_object, value, frozenset(fields), cls.__name__)
        repeated = {
            "primary_subject_ids", "supporting_subject_ids", "primary_source_record_ids",
            "supporting_source_record_ids", "primary_snapshot_evidence_ids",
            "supporting_snapshot_evidence_ids", "assigned_finding_ids",
            "required_lower_authority_ids", "planned_dependency_root_ids",
        }
        return cls(**{
            field: tuple(raw[field]) if field in repeated and isinstance(raw[field], (list, tuple)) else raw[field]
            for field in fields
        })


@dataclass(frozen=True, slots=True)
class SliceSpecV1:
    schema_version: int
    plan_entry_id: str
    accepted_dependency_artifact_ids: tuple[str, ...]
    output_artifact_key_id: str

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "SliceSpecV1.schema_version")
        _schema(digest_value, self.plan_entry_id, "SliceSpecV1.plan_entry_id")
        object.__setattr__(self, "accepted_dependency_artifact_ids", _digests(
            self.accepted_dependency_artifact_ids, "SliceSpecV1.accepted_dependency_artifact_ids"
        ))
        _schema(digest_value, self.output_artifact_key_id, "SliceSpecV1.output_artifact_key_id")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_entry_id": self.plan_entry_id,
            "accepted_dependency_artifact_ids": list(self.accepted_dependency_artifact_ids),
            "output_artifact_key_id": self.output_artifact_key_id,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SliceSpecV1":
        fields = frozenset({
            "schema_version", "plan_entry_id", "accepted_dependency_artifact_ids",
            "output_artifact_key_id",
        })
        raw = _schema(exact_object, value, fields, cls.__name__)
        dependencies = raw["accepted_dependency_artifact_ids"]
        return cls(
            raw["schema_version"], raw["plan_entry_id"],
            tuple(dependencies) if isinstance(dependencies, (list, tuple)) else dependencies,
            raw["output_artifact_key_id"],
        )


def realize_slice(
    plan_entry: SlicePlanEntryV1,
    accepted_dependencies: dict[str, str],
) -> SliceSpecV1:
    """Bind a frozen plan entry to all exact accepted planned dependencies."""
    if not isinstance(plan_entry, SlicePlanEntryV1):
        raise Protocol28PlanningError("slice realization requires SlicePlanEntryV1")
    expected = set(plan_entry.planned_dependency_root_ids)
    if set(accepted_dependencies) != expected:
        raise Protocol28PlanningError("accepted dependencies do not exactly realize planned roots")
    accepted = tuple(sorted(accepted_dependencies.values()))
    _digests(accepted, "accepted_dependencies")
    output_key = content_digest({"plan_entry_id": plan_entry.identity, "kind": "l4-evidence-slice"})
    return SliceSpecV1(1, plan_entry.identity, accepted, output_key)


@dataclass(frozen=True, slots=True)
class TargetCoverageLedgerV1:
    schema_version: int
    subject_assignment_ids: tuple[str, ...]
    primary_source_record_ids: tuple[str, ...]
    primary_snapshot_evidence_ids: tuple[str, ...]
    assigned_finding_ids: tuple[str, ...]
    category_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "TargetCoverageLedgerV1.schema_version")
        for field in (
            "subject_assignment_ids", "primary_source_record_ids",
            "primary_snapshot_evidence_ids", "assigned_finding_ids",
        ):
            object.__setattr__(self, field, _digests(getattr(self, field), f"TargetCoverageLedgerV1.{field}"))
        object.__setattr__(self, "category_ids", _safe_ids(self.category_ids, "TargetCoverageLedgerV1.category_ids"))

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "subject_assignment_ids": list(self.subject_assignment_ids),
            "primary_source_record_ids": list(self.primary_source_record_ids),
            "primary_snapshot_evidence_ids": list(self.primary_snapshot_evidence_ids),
            "assigned_finding_ids": list(self.assigned_finding_ids),
            "category_ids": list(self.category_ids),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "TargetCoverageLedgerV1":
        fields = (
            "schema_version", "subject_assignment_ids", "primary_source_record_ids",
            "primary_snapshot_evidence_ids", "assigned_finding_ids", "category_ids",
        )
        raw = _schema(exact_object, value, frozenset(fields), cls.__name__)
        return cls(**{
            field: tuple(raw[field]) if field != "schema_version" and isinstance(raw[field], (list, tuple)) else raw[field]
            for field in fields
        })


@dataclass(frozen=True, slots=True)
class ExhaustiveTargetPlanV1:
    schema_version: int
    target_kind: Literal["domain", "source"]
    source_id: str
    target_id: str
    target_partition_id: str
    target_content_id: str
    l3_projection_id: str
    evidence_projection_id: str
    entries: tuple[SlicePlanEntryV1, ...]
    vacancy_receipts: tuple[CategoryVacancyReceiptV1, ...]
    coverage_ledger: TargetCoverageLedgerV1

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ExhaustiveTargetPlanV1.schema_version")
        _schema(one_of, self.target_kind, _TARGET_KINDS, "ExhaustiveTargetPlanV1.target_kind")
        for field in ("source_id", "target_id"):
            _schema(safe_id, getattr(self, field), f"ExhaustiveTargetPlanV1.{field}")
        for field in ("target_partition_id", "target_content_id", "l3_projection_id", "evidence_projection_id"):
            _schema(digest_value, getattr(self, field), f"ExhaustiveTargetPlanV1.{field}")
        object.__setattr__(self, "entries", _typed(
            self.entries, SlicePlanEntryV1, "ExhaustiveTargetPlanV1.entries",
            key=lambda item: (item.category_id, item.ordinal),
        ))
        object.__setattr__(self, "vacancy_receipts", _typed(
            self.vacancy_receipts, CategoryVacancyReceiptV1,
            "ExhaustiveTargetPlanV1.vacancy_receipts", key=lambda item: item.category_id,
        ))
        if not isinstance(self.coverage_ledger, TargetCoverageLedgerV1):
            raise Protocol28PlanningError("target plan requires a coverage ledger")

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return self.source_id, self.target_kind, self.target_id

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "target_kind": self.target_kind,
            "source_id": self.source_id, "target_id": self.target_id,
            "target_partition_id": self.target_partition_id,
            "target_content_id": self.target_content_id,
            "l3_projection_id": self.l3_projection_id,
            "evidence_projection_id": self.evidence_projection_id,
            "entries": [item.to_json_dict() for item in self.entries],
            "vacancy_receipts": [item.to_json_dict() for item in self.vacancy_receipts],
            "coverage_ledger": self.coverage_ledger.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveTargetPlanV1":
        fields = (
            "schema_version", "target_kind", "source_id", "target_id",
            "target_partition_id", "target_content_id", "l3_projection_id",
            "evidence_projection_id", "entries", "vacancy_receipts", "coverage_ledger",
        )
        raw = _schema(exact_object, value, frozenset(fields), cls.__name__)
        if not isinstance(raw["entries"], (list, tuple)) or not isinstance(
            raw["vacancy_receipts"], (list, tuple)
        ):
            raise Protocol28PlanningError("target plan entries and vacancies must be arrays")
        return cls(
            **{field: raw[field] for field in fields[:8]},
            entries=tuple(SlicePlanEntryV1.from_json_dict(item) for item in raw["entries"]),
            vacancy_receipts=tuple(
                CategoryVacancyReceiptV1.from_json_dict(item) for item in raw["vacancy_receipts"]
            ),
            coverage_ledger=TargetCoverageLedgerV1.from_json_dict(raw["coverage_ledger"]),
        )


DomainExhaustivePlanV1 = ExhaustiveTargetPlanV1
SourceExhaustivePlanV1 = ExhaustiveTargetPlanV1


@dataclass(frozen=True, slots=True)
class ExhaustivePlanV1:
    schema_version: int
    source_snapshot_id: str
    partition_manifest_id: str
    selection_id: str
    parent_authority_bundle_id: str
    l3_projection_catalog_id: str
    evidence_catalog_id: str
    subject_catalog_id: str
    policy_id: str
    completion_scope: Literal["selected-scope", "all-scope"]
    target_plans: tuple[ExhaustiveTargetPlanV1, ...]

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ExhaustivePlanV1.schema_version")
        for field in self.__dataclass_fields__:  # type: ignore[attr-defined]
            if field not in {"schema_version", "completion_scope", "target_plans"}:
                _schema(digest_value, getattr(self, field), f"ExhaustivePlanV1.{field}")
        _schema(
            one_of,
            self.completion_scope,
            frozenset({"selected-scope", "all-scope"}),
            "ExhaustivePlanV1.completion_scope",
        )
        object.__setattr__(self, "target_plans", _typed(
            self.target_plans, ExhaustiveTargetPlanV1, "ExhaustivePlanV1.target_plans",
            key=lambda item: item.sort_key,
        ))

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{
                field: getattr(self, field)
                for field in self.__dataclass_fields__  # type: ignore[attr-defined]
                if field != "target_plans"
            },
            "target_plans": [item.to_json_dict() for item in self.target_plans],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustivePlanV1":
        fields = tuple(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        raw = _schema(exact_object, value, frozenset(fields), cls.__name__)
        if not isinstance(raw["target_plans"], (list, tuple)):
            raise Protocol28PlanningError("ExhaustivePlanV1.target_plans must be an array")
        return cls(
            **{field: raw[field] for field in fields if field != "target_plans"},
            target_plans=tuple(
                ExhaustiveTargetPlanV1.from_json_dict(item) for item in raw["target_plans"]
            ),
        )


def _all_evidence_ids(projection: TargetSnapshotEvidenceProjectionV1) -> tuple[str, ...]:
    return tuple(sorted(set(
        projection.primary_shard_ids
        + projection.primary_empty_receipt_ids
        + projection.primary_nontext_disposition_ids
    )))


def _record_for_evidence(catalog: SnapshotEvidenceCatalogV1) -> dict[str, str]:
    return {
        **{item.shard_id: item.file_record_hash for item in catalog.shards},
        **{item.receipt_id: item.file_record_hash for item in catalog.empty_receipts},
        **{item.disposition_id: item.file_record_hash for item in catalog.nontext_dispositions},
    }


def _supporting_subjects_for_evidence(
    subjects: tuple[ExhaustiveSubjectV1, ...],
    primary_subjects: tuple[ExhaustiveSubjectV1, ...],
    evidence_ids: tuple[str, ...],
) -> tuple[ExhaustiveSubjectV1, ...]:
    """Choose deterministic, relevant support without duplicating primary ownership."""
    covered = {item for subject in primary_subjects for item in subject.evidence_ids}
    chosen: dict[str, ExhaustiveSubjectV1] = {}
    ordered = sorted(subjects, key=lambda subject: subject.identity)
    for evidence_id in sorted(set(evidence_ids) - covered):
        if evidence_id in covered:
            continue
        subject = next((item for item in ordered if evidence_id in item.evidence_ids), None)
        if subject is None:
            raise Protocol28PlanningError("snapshot evidence has no relevant subject mapping")
        chosen[subject.identity] = subject
        covered.update(subject.evidence_ids)
    return tuple(chosen[key] for key in sorted(chosen))


def _entry(
    *, target: L3TargetAuthorityProjectionV1,
    evidence: TargetSnapshotEvidenceProjectionV1,
    category: str,
    ordinal: int,
    subjects: tuple[ExhaustiveSubjectV1, ...],
    primary_evidence: tuple[str, ...],
    primary_records: tuple[str, ...],
    finding_ids: tuple[str, ...],
    policy: ExhaustivePolicyV1,
    evidence_sizes: dict[str, int],
    planned_dependency_root_ids: tuple[str, ...] = (),
    global_lower_authority_ids: tuple[str, ...] = (),
    supporting_subjects: tuple[ExhaustiveSubjectV1, ...] = (),
    supporting_evidence: tuple[str, ...] = (),
    supporting_records: tuple[str, ...] = (),
) -> SlicePlanEntryV1:
    context_bytes = sum(
        len(canonical_json_bytes(item.to_json_dict()))
        for item in (*subjects, *supporting_subjects)
    ) + sum(evidence_sizes.get(item, 0) for item in (*primary_evidence, *supporting_evidence))
    if context_bytes > policy.max_context_bytes:
        raise Protocol28PlanningError("unsplittable canonical context exceeds policy")
    if len(subjects) > policy.max_primary_subjects:
        raise Protocol28PlanningError("primary subject bin exceeds policy")
    if len(primary_records) > policy.max_primary_records:
        raise Protocol28PlanningError("primary source record bin exceeds policy")
    if len(supporting_subjects) > policy.max_supporting_subjects:
        raise Protocol28PlanningError("supporting subject bin exceeds policy")
    if len(supporting_records) > policy.max_supporting_records:
        raise Protocol28PlanningError("supporting source record bin exceeds policy")
    subject_ids = tuple(sorted(item.identity for item in subjects))
    lower_ids = tuple(
        sorted(
            {
                target.candidate_authority_hash,
                *target.relevant_l2_root_ids,
                *global_lower_authority_ids,
                *(
                    lower_id
                    for subject in (*subjects, *supporting_subjects)
                    for lower_id in subject.lower_authority_ids
                ),
            }
        )
    )
    return SlicePlanEntryV1(
        1, target.target_kind, target.source_id, target.target_id, category, ordinal,
        target.identity, evidence.identity, subject_ids,
        tuple(sorted(item.identity for item in supporting_subjects)),
        primary_records, supporting_records,
        primary_evidence, supporting_evidence, finding_ids, lower_ids, planned_dependency_root_ids,
        policy.producer_contract_hash, policy.verifier_contract_hash,
        context_bytes, context_bytes,
    )


def _target_plan(
    target: L3TargetAuthorityProjectionV1,
    evidence_projection: TargetSnapshotEvidenceProjectionV1,
    subjects: tuple[ExhaustiveSubjectV1, ...],
    policy: ExhaustivePolicyV1,
    evidence_catalog: SnapshotEvidenceCatalogV1,
    composition_dependency_root_ids: tuple[str, ...] = (),
    required_finding_ids: tuple[str, ...] = (),
    global_lower_authority_ids: tuple[str, ...] = (),
    reviewed_categories=None,
    disposed_evidence_ids=frozenset(),
    reviewed_owners=None,
) -> ExhaustiveTargetPlanV1:
    categories = policy.domain_categories if target.target_kind == "domain" else policy.source_categories
    allowed = set(categories)
    for subject in subjects:
        if not set(subject.category_ids).issubset(allowed):
            raise Protocol28PlanningError("subject category is not applicable to target kind")

    permitted = set(_all_evidence_ids(evidence_projection)) - set(disposed_evidence_ids)
    supporting = set(
        evidence_projection.supporting_shard_ids
        + evidence_projection.supporting_empty_receipt_ids
        + evidence_projection.supporting_nontext_disposition_ids
    )
    for subject in subjects:
        unknown = set(subject.evidence_ids) - permitted - supporting
        if unknown:
            raise Protocol28PlanningError("subject references unknown target evidence")
        if not set(subject.finding_ids).issubset(target.finding_ids):
            raise Protocol28PlanningError("subject references unknown target finding")

    subject_categories: dict[str, list[ExhaustiveSubjectV1]] = {item: [] for item in categories}
    for subject in subjects:
        for category in subject.category_ids:
            subject_categories[category].append(subject)

    repaired = isinstance(policy, ExhaustivePolicyV2)
    if repaired:
        unassessed = sorted(category for category, items in subject_categories.items() if not items
                            and (reviewed_categories is None or category not in reviewed_categories
                                 or reviewed_categories[category].disposition not in {'not-applicable', 'outside-requested-depth'}))
        if unassessed:
            raise Protocol28PlanningError(
                "unassessed categories require reviewed discovery before activation: "
                f"source={target.source_id} target={target.target_id} categories={','.join(unassessed)}"
            )
        if permitted - {item for subject in subjects for item in subject.evidence_ids}:
            raise Protocol28PlanningError("snapshot evidence has no relevant subject mapping")

    evidence_category: dict[str, str] = {}
    for evidence_id in sorted(permitted):
        candidates_for_evidence = subjects
        if reviewed_owners is not None:
            owner = reviewed_owners.get(evidence_id)
            if owner is None or owner not in subjects or evidence_id not in owner.evidence_ids:
                raise Protocol28PlanningError('reviewed primary evidence owner is absent from target')
            candidates_for_evidence = (owner,)
        candidates = sorted(
            category for subject in candidates_for_evidence if evidence_id in subject.evidence_ids
            for category in subject.category_ids
        )
        evidence_category[evidence_id] = candidates[0] if candidates else categories[-1]

    finding_category: dict[str, str] = {}
    if not set(required_finding_ids).issubset(target.finding_ids):
        raise Protocol28PlanningError("required deeper finding is absent from target authority")
    for finding_id in required_finding_ids:
        candidates = sorted(
            category for subject in subjects if finding_id in subject.finding_ids
            for category in subject.category_ids
        )
        finding_category[finding_id] = candidates[0] if candidates else categories[-1]

    record_for = _record_for_evidence(evidence_catalog)
    record_category: dict[str, str] = {}
    for evidence_id, category in evidence_category.items():
        record_category.setdefault(record_for[evidence_id], category)

    sizes = {item.shard_id: len(item.raw_bytes) for item in evidence_catalog.shards}
    entries: list[SlicePlanEntryV1] = []
    vacancies: list[CategoryVacancyReceiptV1] = []
    subject_assignment_ids: list[str] = []
    coverage_seed = content_digest({
        "target": target.identity,
        "evidence": evidence_projection.identity,
        "subjects": [item.identity for item in subjects],
        "categories": list(categories),
    })
    for category in categories:
        category_subjects = tuple(sorted(subject_categories[category], key=lambda item: item.identity))
        assessment = reviewed_categories.get(category) if reviewed_categories is not None else None
        if assessment is not None and assessment.disposition != 'analyze':
            if category_subjects or assessment.disposition not in {'not-applicable', 'outside-requested-depth'}:
                raise Protocol28PlanningError('unknown or inconsistent reviewed category blocks planning')
            vacancies.append(ReviewedCategoryVacancyReceiptV1(1, target.target_kind, target.source_id,
                target.target_id, category, coverage_seed, assessment.identity))
            continue
        primary_evidence = tuple(sorted(item for item, assigned in evidence_category.items() if assigned == category))

        def supporting_for(primary_subjects, evidence_ids):
            # Overflow may repeat an owner as support, but no other citing
            # subject can replace the owner of primary work in this slice.
            required = {reviewed_owners[item].identity: reviewed_owners[item]
                        for item in evidence_ids if reviewed_owners is not None and item in primary_evidence}
            for subject in primary_subjects:
                required.pop(subject.identity, None)
            extra = _supporting_subjects_for_evidence(category_subjects,
                (*primary_subjects, *required.values()), evidence_ids)
            required.update((subject.identity, subject) for subject in extra)
            return tuple(required[key] for key in sorted(required))
        primary_records = tuple(sorted(item for item, assigned in record_category.items() if assigned == category))
        findings = tuple(sorted(item for item, assigned in finding_category.items() if assigned == category))
        if not category_subjects and not primary_evidence and not primary_records and not findings:
            vacancies.append(CategoryVacancyReceiptV1(
                1, target.target_kind, target.source_id, target.target_id, category, coverage_seed
            ))
            continue
        # Greedily pack canonical subject bytes, then exact primary evidence, in
        # stable identity order. No model decision can influence a boundary.
        bins: list[dict[str, list[object] | int]] = []

        def new_bin() -> dict[str, list[object] | int]:
            value: dict[str, list[object] | int] = {
                "subjects": [], "evidence": [], "records": [], "bytes": 0,
            }
            bins.append(value)
            return value

        current = new_bin()
        for subject in category_subjects:
            size = len(canonical_json_bytes(subject.to_json_dict()))
            if size > policy.max_context_bytes:
                raise Protocol28PlanningError("unsplittable subject context exceeds policy")
            current_subjects = current["subjects"]
            assert isinstance(current_subjects, list)
            current_bytes = current["bytes"]
            assert isinstance(current_bytes, int)
            if current_subjects and (
                len(current_subjects) >= policy.max_primary_subjects
                or current_bytes + size > policy.max_context_bytes
            ):
                current = new_bin()
                current_subjects = current["subjects"]
                current_bytes = current["bytes"]
                assert isinstance(current_subjects, list) and isinstance(current_bytes, int)
            current_subjects.append(subject)
            current["bytes"] = current_bytes + size

        unassigned_records = set(primary_records)
        packing_evidence = (
            tuple(sorted(set(primary_evidence) | {
                item for subject in category_subjects for item in subject.evidence_ids
            })) if repaired else primary_evidence
        )
        for evidence_id in packing_evidence:
            size = sizes.get(evidence_id, 0)
            if size > policy.max_context_bytes:
                raise Protocol28PlanningError("unsplittable snapshot evidence exceeds policy")
            record_id = record_for[evidence_id]
            current_evidence = current["evidence"]
            current_records = current["records"]
            current_bytes = current["bytes"]
            assert isinstance(current_evidence, list)
            assert isinstance(current_records, list)
            assert isinstance(current_bytes, int)
            adds_record = record_id in unassigned_records

            def exceeds_bound() -> bool:
                support = supporting_for(
                    tuple(current["subjects"]),  # type: ignore[arg-type]
                    tuple((*current_evidence, evidence_id)),
                ) if repaired else ()
                support_bytes = sum(len(canonical_json_bytes(item.to_json_dict())) for item in support)
                support_records = {
                    record_for[item] for item in (*current_evidence, evidence_id)
                } - set(current_records) - ({record_id} if adds_record else set())
                return (
                    current_bytes + size + support_bytes > policy.max_context_bytes
                    or (adds_record and len(current_records) >= policy.max_primary_records)
                    or len(support) > policy.max_supporting_subjects
                    or (repaired and len(support_records) > policy.max_supporting_records)
                )

            if exceeds_bound():
                current = new_bin()
                current_evidence = current["evidence"]
                current_records = current["records"]
                current_bytes = current["bytes"]
                assert isinstance(current_evidence, list)
                assert isinstance(current_records, list)
                assert isinstance(current_bytes, int)
            if repaired and exceeds_bound():
                raise Protocol28PlanningError("unsplittable grounded evidence context exceeds policy")
            current_evidence.append(evidence_id)
            current["bytes"] = current_bytes + size
            if adds_record:
                current_records.append(record_id)
                unassigned_records.remove(record_id)
        if unassigned_records:
            raise Protocol28PlanningError("primary source records could not be assigned")

        nonempty_bins = [
            item for item in bins
            if item["subjects"] or item["evidence"] or item["records"]
        ] or bins[:1]
        for ordinal, packed in enumerate(nonempty_bins):
            packed_subjects = packed["subjects"]
            packed_evidence = packed["evidence"]
            packed_records = packed["records"]
            assert isinstance(packed_subjects, list)
            assert isinstance(packed_evidence, list)
            assert isinstance(packed_records, list)
            bound_support = supporting_for(
                tuple(packed_subjects), tuple(packed_evidence),
            ) if repaired else ()
            owned_evidence = tuple(item for item in packed_evidence if item in primary_evidence)
            support_evidence = tuple(item for item in packed_evidence if item not in primary_evidence)
            entries.append(_entry(
                target=target, evidence=evidence_projection, category=category, ordinal=ordinal,
                subjects=tuple(packed_subjects),
                primary_evidence=owned_evidence,
                primary_records=tuple(sorted(packed_records)),
                supporting_subjects=bound_support,
                supporting_evidence=support_evidence,
                supporting_records=tuple(sorted({
                    record_for[item] for item in packed_evidence
                } - set(packed_records))) if repaired else (),
                finding_ids=(),
                policy=policy, evidence_sizes=sizes,
                planned_dependency_root_ids=(
                    composition_dependency_root_ids
                    if category == "source-composition"
                    else ()
                ),
                global_lower_authority_ids=global_lower_authority_ids,
            ))
            subject_assignment_ids.extend(
                content_digest({"subject_id": item.identity, "category_id": category})
                for item in packed_subjects
            )
        # A target-wide finding is not a first-bin obligation. Evaluate it in
        # its own bounded context, with all declared supporting evidence, while
        # retaining exactly-once primary coverage in the discovery slices.
        for offset, finding_id in enumerate(findings):
            finding_subjects = tuple(
                subject for subject in subjects if finding_id in subject.finding_ids
            )
            required_evidence = {
                item for subject in finding_subjects for item in subject.evidence_ids
            }
            # Generated indexes are chunks of a target, not semantic evidence
            # mappings. Never mistake a finding-only chunk for proof of absence.
            if not required_evidence or any(
                subject.subject_id.startswith("authenticated-evidence")
                for subject in finding_subjects
            ):
                required_evidence = permitted | supporting
            try:
                if not finding_subjects:
                    raise Protocol28PlanningError("finding has no declared subject mapping")
                entries.append(_entry(
                    target=target, evidence=evidence_projection,
                    category=category, ordinal=len(nonempty_bins) + offset,
                    subjects=(), primary_evidence=(), primary_records=(),
                    finding_ids=(finding_id,), policy=policy, evidence_sizes=sizes,
                    supporting_subjects=finding_subjects,
                    supporting_evidence=tuple(sorted(required_evidence)),
                    supporting_records=tuple(sorted({record_for[item] for item in required_evidence})),
                    planned_dependency_root_ids=(
                        composition_dependency_root_ids if category == "source-composition" else ()
                    ),
                    global_lower_authority_ids=global_lower_authority_ids,
                ))
            except Protocol28PlanningError as exc:
                raise Protocol28PlanningError(
                    "finding closure requires a bounded evidence context before dispatch: "
                    f"source={target.source_id} target={target.target_id} finding={finding_id}; "
                    "provide a narrower evidence-to-finding mapping or a bounded synthesis stage"
                ) from exc
    if len(entries) > policy.max_entries_per_target:
        raise Protocol28PlanningError("target plan exceeds entry cap")
    assigned_evidence = tuple(sorted(
        item for entry in entries for item in entry.primary_snapshot_evidence_ids
    ))
    if assigned_evidence != tuple(sorted(permitted)) or len(assigned_evidence) != len(set(assigned_evidence)):
        raise Protocol28PlanningError("primary snapshot evidence assignment is not exact")
    ledger = TargetCoverageLedgerV1(
        1, tuple(sorted(subject_assignment_ids)), tuple(sorted(record_category)),
        assigned_evidence, tuple(sorted(required_finding_ids)), tuple(sorted(categories)),
    )
    return ExhaustiveTargetPlanV1(
        1, target.target_kind, target.source_id, target.target_id,
        evidence_projection.target_partition_id, target.target_content_id,
        target.identity, evidence_projection.identity,
        tuple(sorted(entries, key=lambda item: (item.category_id, item.ordinal))),
        tuple(sorted(vacancies, key=lambda item: item.category_id)), ledger,
    )


def _reviewed_plan_rows(reviewed, subjects, evidence):
    if reviewed is None:
        return {}, set(), None
    from harness.re_v2.knowledge_activation import load_reviewed_discovery
    import json
    if not isinstance(reviewed, tuple) or not reviewed:
        raise Protocol28PlanningError('reviewed planning authority is required')
    checked = []
    for bundle in reviewed:
        l3 = L3TargetProjectionCatalogV1.from_json_dict(json.loads(
            bundle.objects[bundle.subject_catalog.l3_projection_catalog_id]))
        checked.append(load_reviewed_discovery(bundle.authority, bundle.objects, l3, evidence))
    if (len({b.authority.source_id for b in checked}) != len(checked)
            or {b.authority.source_id for b in checked} != {p.source_id for p in evidence.projections}
            or tuple(sorted((s for b in checked for s in b.subject_catalog.subjects), key=lambda s: s.sort_key)) != subjects.subjects):
        raise Protocol28PlanningError('reviewed source or subject closure differs')
    rows = {}
    for bundle in checked:
        for row in bundle.category_assessments:
            if row.disposition == 'unknown':
                raise Protocol28PlanningError('unknown reviewed obligation blocks planning')
            key = (row.source_id, row.target_kind, row.target_id)
            rows.setdefault(key, {})[row.category_id] = row
    disposed = {i for b in checked for r in b.inventory_assessments
                if r.disposition in {'excluded', 'non-behavioral'} for i in r.raw_evidence_ids}
    by_subject = {subject.identity: subject for subject in subjects.subjects}
    owners = {}
    for bundle in checked:
        for row in bundle.inventory_assessments:
            if row.disposition == 'owned':
                for raw_id in row.raw_evidence_ids:
                    if raw_id in owners or raw_id in disposed:
                        raise Protocol28PlanningError('duplicate reviewed primary evidence ownership')
                    owners[raw_id] = by_subject[row.subject_id]
    return rows, disposed, owners


def build_exhaustive_plan(
    parent: ParentAuthorityBundleV3,
    l3: L3TargetProjectionCatalogV1,
    evidence: SnapshotEvidenceCatalogV1,
    subjects: ExhaustiveSubjectCatalogV1,
    policy: ExhaustivePolicyV1,
    selection: SelectionScopeV1,
    *, reviewed=None,
) -> ExhaustivePlanV1:
    """Build a deterministic, exact-coverage L4 plan or reject preactivation."""
    if not all((
        isinstance(parent, ParentAuthorityBundleV3),
        isinstance(l3, L3TargetProjectionCatalogV1),
        isinstance(evidence, SnapshotEvidenceCatalogV1),
        isinstance(subjects, ExhaustiveSubjectCatalogV1),
        isinstance(policy, ExhaustivePolicyV1),
        isinstance(selection, SelectionScopeV1),
    )):
        raise Protocol28PlanningError("exhaustive planning inputs have invalid types")
    if (
        parent.source_snapshot_id != l3.source_snapshot_id
        or parent.partition_manifest_id != l3.partition_manifest_id
        or parent.selection_id != selection.identity
        or parent.l3_projection_catalog_id != l3.identity
        or evidence.source_snapshot_id != parent.source_snapshot_id
        or evidence.partition_catalog_id != parent.workspace_partition_catalog_id
        or evidence.selection_id != selection.identity
        or subjects.source_snapshot_id != parent.source_snapshot_id
        or subjects.partition_manifest_id != parent.partition_manifest_id
        or subjects.l3_projection_catalog_id != l3.identity
    ):
        raise Protocol28PlanningError("exhaustive planning authority identities do not match")
    l3_by_target = {(item.source_id, item.target_kind, item.target_id): item for item in l3.projections}
    evidence_by_target = {
        (item.source_id, item.target_kind, item.target_id): item
        for item in evidence.projections
    }
    if set(l3_by_target) != set(evidence_by_target):
        raise Protocol28PlanningError("L3 and snapshot evidence target sets differ")
    subjects_by_target: dict[tuple[str, str, str], list[ExhaustiveSubjectV1]] = {
        key: [] for key in l3_by_target
    }
    for subject in subjects.subjects:
        key = (subject.source_id, subject.target_kind, subject.target_id)
        if key not in subjects_by_target:
            raise Protocol28PlanningError("subject references unknown selected target")
        subjects_by_target[key].append(subject)
    finding_targets: dict[str, tuple[str, str, str]] = {}
    for finding_id in parent.unresolved_deeper_finding_ids:
        matches = tuple(
            key for key, target in l3_by_target.items() if finding_id in target.finding_ids
        )
        if len(matches) != 1:
            raise Protocol28PlanningError(
                "deeper finding must belong to exactly one selected L3 target"
            )
        finding_targets[finding_id] = matches[0]
    findings_by_target = {
        key: tuple(sorted(
            finding_id for finding_id, finding_target in finding_targets.items()
            if finding_target == key
        ))
        for key in l3_by_target
    }
    common_lower_authority_ids = tuple(
        sorted(
            set.intersection(
                *(set(item.lower_authority_ids) for item in subjects.subjects)
            )
        )
    ) if subjects.subjects else ()
    reviewed_categories, disposed, owners = _reviewed_plan_rows(reviewed, subjects, evidence)
    domain_plans = tuple(
        _target_plan(
            l3_by_target[key], evidence_by_target[key],
            tuple(subjects_by_target[key]), policy, evidence,
            required_finding_ids=findings_by_target[key],
            global_lower_authority_ids=common_lower_authority_ids,
            reviewed_categories=reviewed_categories.get(key), disposed_evidence_ids=disposed,
            reviewed_owners=owners,
        )
        for key in sorted(l3_by_target)
        if key[1] == "domain"
    )
    source_plans = tuple(
        _target_plan(
            l3_by_target[key], evidence_by_target[key],
            tuple(subjects_by_target[key]), policy, evidence,
            tuple(sorted(
                item.identity for item in domain_plans if item.source_id == key[0]
            )),
            findings_by_target[key],
            common_lower_authority_ids,
            reviewed_categories=reviewed_categories.get(key), disposed_evidence_ids=disposed,
            reviewed_owners=owners,
        )
        for key in sorted(l3_by_target)
        if key[1] == "source"
    )
    plans = tuple(sorted((*domain_plans, *source_plans), key=lambda item: item.sort_key))
    if sum(len(item.entries) for item in plans) > policy.max_entries_per_run:
        raise Protocol28PlanningError("exhaustive plan exceeds run entry cap")
    plan = ExhaustivePlanV1(
        1, parent.source_snapshot_id, parent.partition_manifest_id, selection.identity,
        parent.identity, l3.identity, evidence.identity, subjects.identity, policy.identity,
        "all-scope" if selection.all_sources else "selected-scope", plans,
    )
    validate_exhaustive_plan_coverage(plan, subjects, evidence, policy, reviewed=reviewed)
    return plan


def validate_exhaustive_plan_coverage(
    plan: ExhaustivePlanV1,
    subjects: ExhaustiveSubjectCatalogV1,
    evidence: SnapshotEvidenceCatalogV1,
    policy: ExhaustivePolicyV1,
    *, reviewed=None,
) -> None:
    """Reject structural false completeness under the pinned repaired contract."""
    if not isinstance(policy, ExhaustivePolicyV2):
        if reviewed is not None:
            raise Protocol28PlanningError('reviewed planning requires repaired policy')
        return
    reviewed_categories, disposed, owners = _reviewed_plan_rows(reviewed, subjects, evidence)
    if owners is not None:
        primary = [raw_id for target in plan.target_plans for entry in target.entries
                   for raw_id in entry.primary_snapshot_evidence_ids]
        if sorted(primary) != sorted(owners):
            raise Protocol28PlanningError('reviewed primary ownership requires exactly one work assignment')
    projections = {
        (item.source_id, item.target_kind, item.target_id): item for item in evidence.projections
    }
    if {item.sort_key for item in plan.target_plans} != set(projections):
        raise Protocol28PlanningError("repaired plan target coverage differs from snapshot")
    by_subject = {item.identity: item for item in subjects.subjects}
    record_for = _record_for_evidence(evidence)
    if sum(len(target.entries) for target in plan.target_plans) > policy.max_entries_per_run:
        raise Protocol28PlanningError("repaired plan exceeds run entry cap")
    for target in plan.target_plans:
        categories = set(policy.domain_categories if target.target_kind == "domain" else policy.source_categories)
        assessed = reviewed_categories.get(target.sort_key)
        vacant = {r.category_id for r in target.vacancy_receipts}
        if assessed is not None:
            expected_vacant = {c for c, row in assessed.items() if row.disposition != 'analyze'}
            if vacant != expected_vacant or len(vacant) != len(target.vacancy_receipts):
                raise Protocol28PlanningError('reviewed category vacancy closure differs')
            for receipt in target.vacancy_receipts:
                if (not isinstance(receipt, ReviewedCategoryVacancyReceiptV1)
                        or receipt.reviewed_disposition_id != assessed[receipt.category_id].identity
                        or (receipt.source_id, receipt.target_kind, receipt.target_id) != target.sort_key):
                    raise Protocol28PlanningError('unauthenticated reviewed vacancy')
        if ((assessed is None and target.vacancy_receipts)
                or {entry.category_id for entry in target.entries} != categories - vacant):
            raise Protocol28PlanningError("unassessed categories cannot certify repaired coverage")
        projection = projections[target.sort_key]
        if target.evidence_projection_id != projection.identity:
            raise Protocol28PlanningError("repaired target evidence projection differs from snapshot")
        target_subjects = tuple(
            item for item in subjects.subjects
            if (item.source_id, item.target_kind, item.target_id) == target.sort_key
        )
        permitted = set(_all_evidence_ids(projection)) - disposed
        available = permitted | set(
            projection.supporting_shard_ids + projection.supporting_empty_receipt_ids
            + projection.supporting_nontext_disposition_ids
        )
        assigned = [item for entry in target.entries for item in entry.primary_snapshot_evidence_ids]
        if sorted(assigned) != sorted(permitted):
            raise Protocol28PlanningError("repaired primary evidence coverage is not exact")
        subject_assignments = sorted(
            content_digest({"subject_id": subject_id, "category_id": entry.category_id})
            for entry in target.entries for subject_id in entry.primary_subject_ids
        )
        expected_assignments = sorted(
            content_digest({"subject_id": subject.identity, "category_id": category})
            for subject in target_subjects for category in subject.category_ids
        )
        if subject_assignments != expected_assignments:
            raise Protocol28PlanningError("repaired primary subjects are not assigned exactly once per category")
        records = sorted(item for entry in target.entries for item in entry.primary_source_record_ids)
        if records != sorted({record_for[item] for item in permitted}):
            raise Protocol28PlanningError("repaired primary source record coverage is not exact")
        ledger = target.coverage_ledger
        if (
            list(ledger.subject_assignment_ids) != subject_assignments
            or list(ledger.primary_source_record_ids) != records
            or list(ledger.primary_snapshot_evidence_ids) != sorted(assigned)
            or list(ledger.category_ids) != sorted(categories)
            or list(ledger.assigned_finding_ids) != sorted(
                item for entry in target.entries for item in entry.assigned_finding_ids
            )
        ):
            raise Protocol28PlanningError("repaired coverage ledger does not match actual obligations")
        if len(target.entries) > policy.max_entries_per_target:
            raise Protocol28PlanningError("repaired target exceeds entry cap")
        for category in categories:
            required = {item for subject in target_subjects if category in subject.category_ids
                        for item in subject.evidence_ids}
            delivered = {item for entry in target.entries if entry.category_id == category
                         for item in entry.primary_snapshot_evidence_ids + entry.supporting_snapshot_evidence_ids}
            if required - delivered:
                raise Protocol28PlanningError("repaired category omits required supporting evidence")
        for entry in target.entries:
            if (
                (entry.source_id, entry.target_kind, entry.target_id) != target.sort_key
                or entry.target_l3_projection_id != target.l3_projection_id
                or entry.target_evidence_projection_id != target.evidence_projection_id
                or entry.producer_contract_hash != policy.producer_contract_hash
                or entry.verifier_contract_hash != policy.verifier_contract_hash
            ):
                raise Protocol28PlanningError("repaired slice differs from its frozen target contract")
            attached = entry.primary_subject_ids + entry.supporting_subject_ids
            if owners is not None:
                for raw_id in entry.primary_snapshot_evidence_ids:
                    owner = owners[raw_id]
                    if (owner.identity not in attached or entry.category_id not in owner.category_ids
                            or (owner.source_id, owner.target_kind, owner.target_id) != target.sort_key):
                        raise Protocol28PlanningError('primary work differs from authenticated reviewed owner')
            if not attached or len(attached) != len(set(attached)):
                raise Protocol28PlanningError("repaired slice requires distinct relevant subjects")
            bound = []
            for subject_id in attached:
                subject = by_subject.get(subject_id)
                if subject is None or (
                    subject.source_id, subject.target_kind, subject.target_id
                ) != target.sort_key or entry.category_id not in subject.category_ids:
                    raise Protocol28PlanningError("repaired slice subject is outside target/category")
                bound.append(subject)
            entry_evidence = set(entry.primary_snapshot_evidence_ids + entry.supporting_snapshot_evidence_ids)
            if set(entry.primary_snapshot_evidence_ids) & set(entry.supporting_snapshot_evidence_ids):
                raise Protocol28PlanningError("repaired evidence cannot be both primary and supporting")
            if entry_evidence - available or entry_evidence - {
                item for subject in bound for item in subject.evidence_ids
            }:
                raise Protocol28PlanningError("repaired slice evidence lacks a relevant subject binding")
            if (
                len(entry.primary_subject_ids) > policy.max_primary_subjects
                or len(entry.supporting_subject_ids) > policy.max_supporting_subjects
                or len(entry.primary_source_record_ids) > policy.max_primary_records
                or len(entry.supporting_source_record_ids) > policy.max_supporting_records
                or entry.canonical_context_bytes > policy.max_context_bytes
                or entry.conservative_tokens > policy.max_conservative_tokens
            ):
                raise Protocol28PlanningError("repaired slice exceeds frozen policy bounds")

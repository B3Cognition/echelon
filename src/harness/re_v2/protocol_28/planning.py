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
from harness.re_v2.protocol_28.policies import ExhaustivePolicyV1


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
        fields = frozenset(
            {"schema_version", "target_kind", "source_id", "target_id", "category_id", "coverage_ledger_seed_id"}
        )
        raw = _schema(exact_object, value, fields, cls.__name__)
        return cls(**{field: raw[field] for field in fields})


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
) -> SlicePlanEntryV1:
    context_bytes = sum(
        len(canonical_json_bytes(item.to_json_dict())) for item in subjects
    ) + sum(evidence_sizes.get(item, 0) for item in primary_evidence)
    if context_bytes > policy.max_context_bytes:
        raise Protocol28PlanningError("unsplittable canonical context exceeds policy")
    if len(subjects) > policy.max_primary_subjects:
        raise Protocol28PlanningError("primary subject bin exceeds policy")
    if len(primary_records) > policy.max_primary_records:
        raise Protocol28PlanningError("primary source record bin exceeds policy")
    subject_ids = tuple(sorted(item.identity for item in subjects))
    lower_ids = tuple(
        sorted(
            {
                target.candidate_authority_hash,
                *target.relevant_l2_root_ids,
                *global_lower_authority_ids,
                *(
                    lower_id
                    for subject in subjects
                    for lower_id in subject.lower_authority_ids
                ),
            }
        )
    )
    return SlicePlanEntryV1(
        1, target.target_kind, target.source_id, target.target_id, category, ordinal,
        target.identity, evidence.identity, subject_ids, (), primary_records, (),
        primary_evidence, (), finding_ids, lower_ids, planned_dependency_root_ids,
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
) -> ExhaustiveTargetPlanV1:
    categories = policy.domain_categories if target.target_kind == "domain" else policy.source_categories
    allowed = set(categories)
    for subject in subjects:
        if not set(subject.category_ids).issubset(allowed):
            raise Protocol28PlanningError("subject category is not applicable to target kind")

    permitted = set(_all_evidence_ids(evidence_projection))
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

    evidence_category: dict[str, str] = {}
    for evidence_id in sorted(permitted):
        candidates = sorted(
            category for subject in subjects if evidence_id in subject.evidence_ids
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
        primary_evidence = tuple(sorted(item for item, assigned in evidence_category.items() if assigned == category))
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
        for evidence_id in primary_evidence:
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
            if current_evidence and (
                current_bytes + size > policy.max_context_bytes
                or (adds_record and len(current_records) >= policy.max_primary_records)
            ):
                current = new_bin()
                current_evidence = current["evidence"]
                current_records = current["records"]
                current_bytes = current["bytes"]
                assert isinstance(current_evidence, list)
                assert isinstance(current_records, list)
                assert isinstance(current_bytes, int)
            elif current_bytes + size > policy.max_context_bytes:
                current = new_bin()
                current_evidence = current["evidence"]
                current_records = current["records"]
                current_bytes = current["bytes"]
                assert isinstance(current_evidence, list)
                assert isinstance(current_records, list)
                assert isinstance(current_bytes, int)
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
            current_findings = findings if ordinal == 0 else ()
            entries.append(_entry(
                target=target, evidence=evidence_projection, category=category, ordinal=ordinal,
                subjects=tuple(packed_subjects),
                primary_evidence=tuple(packed_evidence),
                primary_records=tuple(sorted(packed_records)),
                finding_ids=current_findings,
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


def build_exhaustive_plan(
    parent: ParentAuthorityBundleV3,
    l3: L3TargetProjectionCatalogV1,
    evidence: SnapshotEvidenceCatalogV1,
    subjects: ExhaustiveSubjectCatalogV1,
    policy: ExhaustivePolicyV1,
    selection: SelectionScopeV1,
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
    domain_plans = tuple(
        _target_plan(
            l3_by_target[key], evidence_by_target[key],
            tuple(subjects_by_target[key]), policy, evidence,
            required_finding_ids=findings_by_target[key],
            global_lower_authority_ids=common_lower_authority_ids,
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
        )
        for key in sorted(l3_by_target)
        if key[1] == "source"
    )
    plans = tuple(sorted((*domain_plans, *source_plans), key=lambda item: item.sort_key))
    if sum(len(item.entries) for item in plans) > policy.max_entries_per_run:
        raise Protocol28PlanningError("exhaustive plan exceeds run entry cap")
    return ExhaustivePlanV1(
        1, parent.source_snapshot_id, parent.partition_manifest_id, selection.identity,
        parent.identity, l3.identity, evidence.identity, subjects.identity, policy.identity,
        "all-scope" if selection.all_sources else "selected-scope", plans,
    )

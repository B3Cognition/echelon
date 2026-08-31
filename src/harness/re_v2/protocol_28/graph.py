"""Exact L4 authority roots and deterministic semantic closure for 2.8."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, TypeVar

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    one_of,
    safe_id,
    sorted_unique_digests,
)
from harness.re_v2.protocol_28.authority import ParentAuthorityBundleV3
from harness.re_v2.protocol_28.planning import (
    ExhaustivePlanV1,
    ExhaustiveTargetPlanV1,
)


_TARGET_KINDS = frozenset({"domain", "source"})
_COMPLETION_SCOPES = frozenset({"selected-scope", "all-scope"})
_T = TypeVar("_T")


class Protocol28GraphError(Protocol22SchemaError):
    """Raised when incomplete or inconsistent work cannot create L4 authority."""


class Protocol28ClosureIntegrityError(Protocol28GraphError):
    """Deterministic closure failure that must never become semantic success."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol28GraphError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol28GraphError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(canonical_json_bytes(value))


def _digests(value: object, field: str, *, nonempty: bool = False) -> tuple[str, ...]:
    result = _schema(sorted_unique_digests, value, field)
    if nonempty and not result:
        raise Protocol28GraphError(f"{field} must be nonempty")
    return result


def _typed(value: object, cls: type[_T], field: str, *, key) -> tuple[_T, ...]:  # type: ignore[no-untyped-def]
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, cls) for item in value):
        raise Protocol28GraphError(f"{field} must contain {cls.__name__} values")
    result = tuple(value)
    keys = tuple(key(item) for item in result)
    if keys != tuple(sorted(set(keys))):
        raise Protocol28GraphError(f"{field} must be canonically sorted and unique")
    return result


@dataclass(frozen=True, slots=True)
class AcceptedExhaustiveSliceV1:
    schema_version: int
    plan_entry_id: str
    slice_spec_id: str
    output_artifact_key_id: str
    candidate_hash: str
    producer_execution_capture_hash: str
    verifier_result_hash: str
    verifier_execution_capture_hash: str
    certification_receipt_hash: str
    acceptance_receipt_hash: str
    addressed_finding_ids: tuple[str, ...]
    verdict: Literal["PASS"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "plan_entry_id", "slice_spec_id", "output_artifact_key_id",
        "candidate_hash", "producer_execution_capture_hash", "verifier_result_hash",
        "verifier_execution_capture_hash", "certification_receipt_hash",
        "acceptance_receipt_hash", "addressed_finding_ids", "verdict",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "AcceptedExhaustiveSliceV1.schema_version")
        for field in self.FIELDS[1:10]:
            _schema(digest_value, getattr(self, field), f"AcceptedExhaustiveSliceV1.{field}")
        object.__setattr__(self, "addressed_finding_ids", _digests(
            self.addressed_finding_ids, "AcceptedExhaustiveSliceV1.addressed_finding_ids"
        ))
        _schema(literal, self.verdict, "PASS", "AcceptedExhaustiveSliceV1.verdict")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{field: getattr(self, field) for field in self.FIELDS if field != "addressed_finding_ids"},
            "addressed_finding_ids": list(self.addressed_finding_ids),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "AcceptedExhaustiveSliceV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{
            field: tuple(raw[field]) if field == "addressed_finding_ids" and isinstance(raw[field], (list, tuple)) else raw[field]
            for field in cls.FIELDS
        })


@dataclass(frozen=True, slots=True)
class ExhaustiveVerificationReceiptV1:
    schema_version: int
    accepted_slice_id: str
    plan_entry_id: str
    verifier_result_hash: str
    verifier_execution_capture_hash: str
    assessed_finding_ids: tuple[str, ...]
    verdict: Literal["PASS"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "accepted_slice_id", "plan_entry_id", "verifier_result_hash",
        "verifier_execution_capture_hash", "assessed_finding_ids", "verdict",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ExhaustiveVerificationReceiptV1.schema_version")
        for field in self.FIELDS[1:5]:
            _schema(digest_value, getattr(self, field), f"ExhaustiveVerificationReceiptV1.{field}")
        object.__setattr__(self, "assessed_finding_ids", _digests(
            self.assessed_finding_ids, "ExhaustiveVerificationReceiptV1.assessed_finding_ids"
        ))
        _schema(literal, self.verdict, "PASS", "ExhaustiveVerificationReceiptV1.verdict")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{field: getattr(self, field) for field in self.FIELDS if field != "assessed_finding_ids"},
            "assessed_finding_ids": list(self.assessed_finding_ids),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveVerificationReceiptV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{
            field: tuple(raw[field]) if field == "assessed_finding_ids" and isinstance(raw[field], (list, tuple)) else raw[field]
            for field in cls.FIELDS
        })


@dataclass(frozen=True, slots=True)
class L4TargetRootV1:
    schema_version: int
    target_kind: Literal["domain", "source"]
    source_id: str
    target_id: str
    target_plan_id: str
    target_l3_projection_id: str
    target_evidence_projection_id: str
    coverage_ledger_id: str
    plan_entry_ids: tuple[str, ...]
    accepted_slice_ids: tuple[str, ...]
    verifier_result_hashes: tuple[str, ...]
    acceptance_receipt_hashes: tuple[str, ...]
    addressed_finding_ids: tuple[str, ...]
    state: Literal["complete"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "target_kind", "source_id", "target_id", "target_plan_id",
        "target_l3_projection_id", "target_evidence_projection_id", "coverage_ledger_id",
        "plan_entry_ids", "accepted_slice_ids", "verifier_result_hashes",
        "acceptance_receipt_hashes", "addressed_finding_ids", "state",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4TargetRootV1.schema_version")
        _schema(one_of, self.target_kind, _TARGET_KINDS, "L4TargetRootV1.target_kind")
        for field in ("source_id", "target_id"):
            _schema(safe_id, getattr(self, field), f"L4TargetRootV1.{field}")
        for field in self.FIELDS[4:8]:
            _schema(digest_value, getattr(self, field), f"L4TargetRootV1.{field}")
        for field in self.FIELDS[8:13]:
            object.__setattr__(self, field, _digests(getattr(self, field), f"L4TargetRootV1.{field}"))
        _schema(literal, self.state, "complete", "L4TargetRootV1.state")

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return self.source_id, self.target_kind, self.target_id

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        repeated = set(self.FIELDS[8:13])
        return {
            **{field: getattr(self, field) for field in self.FIELDS if field not in repeated},
            **{field: list(getattr(self, field)) for field in repeated},
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L4TargetRootV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        repeated = set(cls.FIELDS[8:13])
        return cls(**{
            field: tuple(raw[field]) if field in repeated and isinstance(raw[field], (list, tuple)) else raw[field]
            for field in cls.FIELDS
        })


L4DomainRootV1 = L4TargetRootV1
L4SourceCompositionRootV1 = L4TargetRootV1


@dataclass(frozen=True, slots=True)
class L4SourceRootV1:
    schema_version: int
    source_id: str
    source_composition_root_id: str
    selected_domain_keys: tuple[str, ...]
    intentionally_unselected_domain_keys: tuple[str, ...]
    selected_domain_root_ids: tuple[str, ...]
    coverage_mode: Literal["selected-domains", "full-source"]
    source_l3_projection_id: str
    state: Literal["complete"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "source_id", "source_composition_root_id", "selected_domain_keys",
        "intentionally_unselected_domain_keys", "selected_domain_root_ids", "coverage_mode",
        "source_l3_projection_id", "state",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4SourceRootV1.schema_version")
        _schema(safe_id, self.source_id, "L4SourceRootV1.source_id")
        for field in ("source_composition_root_id", "source_l3_projection_id"):
            _schema(digest_value, getattr(self, field), f"L4SourceRootV1.{field}")
        for field in ("selected_domain_keys", "intentionally_unselected_domain_keys", "selected_domain_root_ids"):
            object.__setattr__(self, field, _digests(getattr(self, field), f"L4SourceRootV1.{field}"))
        if set(self.selected_domain_keys) & set(self.intentionally_unselected_domain_keys):
            raise Protocol28GraphError("source root selected and unselected domains overlap")
        _schema(one_of, self.coverage_mode, frozenset({"selected-domains", "full-source"}), "L4SourceRootV1.coverage_mode")
        if self.coverage_mode == "full-source" and self.intentionally_unselected_domain_keys:
            raise Protocol28GraphError("full-source root cannot retain unselected domains")
        _schema(literal, self.state, "complete", "L4SourceRootV1.state")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "source_id": self.source_id,
            "source_composition_root_id": self.source_composition_root_id,
            "selected_domain_keys": list(self.selected_domain_keys),
            "intentionally_unselected_domain_keys": list(self.intentionally_unselected_domain_keys),
            "selected_domain_root_ids": list(self.selected_domain_root_ids),
            "coverage_mode": self.coverage_mode,
            "source_l3_projection_id": self.source_l3_projection_id, "state": self.state,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L4SourceRootV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        repeated = {"selected_domain_keys", "intentionally_unselected_domain_keys", "selected_domain_root_ids"}
        return cls(**{
            field: tuple(raw[field]) if field in repeated and isinstance(raw[field], (list, tuple)) else raw[field]
            for field in cls.FIELDS
        })


@dataclass(frozen=True, slots=True)
class L4RunRootV1:
    schema_version: int
    source_snapshot_id: str
    partition_manifest_id: str
    selection_id: str
    parent_authority_bundle_id: str
    exhaustive_plan_id: str
    exhaustive_policy_id: str
    target_root_ids: tuple[str, ...]
    source_root_ids: tuple[str, ...]
    accepted_slice_ids: tuple[str, ...]
    completion_scope: Literal["selected-scope", "all-scope"]
    state: Literal["complete"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "source_snapshot_id", "partition_manifest_id", "selection_id",
        "parent_authority_bundle_id", "exhaustive_plan_id", "exhaustive_policy_id",
        "target_root_ids", "source_root_ids", "accepted_slice_ids", "completion_scope", "state",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4RunRootV1.schema_version")
        for field in self.FIELDS[1:7]:
            _schema(digest_value, getattr(self, field), f"L4RunRootV1.{field}")
        for field in self.FIELDS[7:10]:
            object.__setattr__(self, field, _digests(getattr(self, field), f"L4RunRootV1.{field}"))
        _schema(one_of, self.completion_scope, _COMPLETION_SCOPES, "L4RunRootV1.completion_scope")
        _schema(literal, self.state, "complete", "L4RunRootV1.state")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        repeated = {"target_root_ids", "source_root_ids", "accepted_slice_ids"}
        return {
            **{field: getattr(self, field) for field in self.FIELDS if field not in repeated},
            **{field: list(getattr(self, field)) for field in repeated},
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L4RunRootV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        repeated = {"target_root_ids", "source_root_ids", "accepted_slice_ids"}
        return cls(**{
            field: tuple(raw[field]) if field in repeated and isinstance(raw[field], (list, tuple)) else raw[field]
            for field in cls.FIELDS
        })


@dataclass(frozen=True, slots=True)
class L4FindingClosureReceiptV1:
    schema_version: int
    finding_id: str
    primary_accepted_slice_id: str
    supporting_accepted_slice_ids: tuple[str, ...]
    verification_receipt_ids: tuple[str, ...]
    l4_run_root_id: str

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4FindingClosureReceiptV1.schema_version")
        for field in ("finding_id", "primary_accepted_slice_id", "l4_run_root_id"):
            _schema(digest_value, getattr(self, field), f"L4FindingClosureReceiptV1.{field}")
        for field in ("supporting_accepted_slice_ids", "verification_receipt_ids"):
            object.__setattr__(self, field, _digests(getattr(self, field), f"L4FindingClosureReceiptV1.{field}"))

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "finding_id": self.finding_id,
            "primary_accepted_slice_id": self.primary_accepted_slice_id,
            "supporting_accepted_slice_ids": list(self.supporting_accepted_slice_ids),
            "verification_receipt_ids": list(self.verification_receipt_ids),
            "l4_run_root_id": self.l4_run_root_id,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L4FindingClosureReceiptV1":
        fields = (
            "schema_version", "finding_id", "primary_accepted_slice_id",
            "supporting_accepted_slice_ids", "verification_receipt_ids", "l4_run_root_id",
        )
        raw = _schema(exact_object, value, frozenset(fields), cls.__name__)
        repeated = {"supporting_accepted_slice_ids", "verification_receipt_ids"}
        return cls(**{
            field: tuple(raw[field]) if field in repeated and isinstance(raw[field], (list, tuple)) else raw[field]
            for field in fields
        })


@dataclass(frozen=True, slots=True)
class L4SemanticClosureRootV1:
    schema_version: int
    parent_authority_bundle_id: str
    frozen_l3_epoch_id: str
    l4_run_root_id: str
    finding_closure_receipt_ids: tuple[str, ...]
    verification_receipt_ids: tuple[str, ...]
    state: Literal["complete"]

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4SemanticClosureRootV1.schema_version")
        for field in ("parent_authority_bundle_id", "frozen_l3_epoch_id", "l4_run_root_id"):
            _schema(digest_value, getattr(self, field), f"L4SemanticClosureRootV1.{field}")
        for field in ("finding_closure_receipt_ids", "verification_receipt_ids"):
            object.__setattr__(self, field, _digests(getattr(self, field), f"L4SemanticClosureRootV1.{field}"))
        _schema(literal, self.state, "complete", "L4SemanticClosureRootV1.state")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "parent_authority_bundle_id": self.parent_authority_bundle_id,
            "frozen_l3_epoch_id": self.frozen_l3_epoch_id,
            "l4_run_root_id": self.l4_run_root_id,
            "finding_closure_receipt_ids": list(self.finding_closure_receipt_ids),
            "verification_receipt_ids": list(self.verification_receipt_ids),
            "state": self.state,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L4SemanticClosureRootV1":
        fields = (
            "schema_version", "parent_authority_bundle_id", "frozen_l3_epoch_id",
            "l4_run_root_id", "finding_closure_receipt_ids", "verification_receipt_ids", "state",
        )
        raw = _schema(exact_object, value, frozenset(fields), cls.__name__)
        repeated = {"finding_closure_receipt_ids", "verification_receipt_ids"}
        return cls(**{
            field: tuple(raw[field]) if field in repeated and isinstance(raw[field], (list, tuple)) else raw[field]
            for field in fields
        })


def build_target_root(
    plan: ExhaustiveTargetPlanV1,
    accepted_slices: tuple[AcceptedExhaustiveSliceV1, ...],
) -> L4TargetRootV1:
    if not isinstance(plan, ExhaustiveTargetPlanV1):
        raise Protocol28GraphError("target root requires ExhaustiveTargetPlanV1")
    accepted = _typed(
        accepted_slices, AcceptedExhaustiveSliceV1, "accepted_slices",
        key=lambda item: item.plan_entry_id,
    )
    entries = {item.identity: item for item in plan.entries}
    actual = {item.plan_entry_id: item for item in accepted}
    if set(actual) != set(entries):
        raise Protocol28GraphError("target root requires exact plan closure")
    for entry_id, item in actual.items():
        if item.addressed_finding_ids != entries[entry_id].assigned_finding_ids:
            raise Protocol28GraphError("accepted slice finding assignment mismatch")
    return L4TargetRootV1(
        1, plan.target_kind, plan.source_id, plan.target_id, plan.identity,
        plan.l3_projection_id, plan.evidence_projection_id, plan.coverage_ledger.identity,
        tuple(sorted(entries)), tuple(sorted(item.identity for item in accepted)),
        tuple(sorted(item.verifier_result_hash for item in accepted)),
        tuple(sorted(item.acceptance_receipt_hash for item in accepted)),
        tuple(sorted({finding for item in accepted for finding in item.addressed_finding_ids})),
        "complete",
    )


def build_source_root(
    source_plan: ExhaustiveTargetPlanV1,
    source_composition_root: L4TargetRootV1,
    selected_domain_roots: tuple[L4TargetRootV1, ...],
    intentionally_unselected_domain_keys: tuple[str, ...],
    coverage_mode: Literal["selected-domains", "full-source"],
) -> L4SourceRootV1:
    if source_plan.target_kind != "source" or source_composition_root.target_plan_id != source_plan.identity:
        raise Protocol28GraphError("source composition root does not match source plan")
    roots = _typed(
        selected_domain_roots, L4TargetRootV1, "selected_domain_roots",
        key=lambda item: item.target_id,
    )
    if any(item.target_kind != "domain" or item.source_id != source_plan.source_id for item in roots):
        raise Protocol28GraphError("source root contains an invalid selected domain root")
    planned_domain_ids = {
        dependency
        for entry in source_plan.entries
        if entry.category_id == "source-composition"
        for dependency in entry.planned_dependency_root_ids
    }
    if {item.target_plan_id for item in roots} != planned_domain_ids:
        raise Protocol28GraphError("source root selected domains differ from frozen composition plan")
    return L4SourceRootV1(
        1, source_plan.source_id, source_composition_root.identity,
        tuple(sorted(item.target_id for item in roots)),
        tuple(sorted(intentionally_unselected_domain_keys)),
        tuple(sorted(item.identity for item in roots)), coverage_mode,
        source_plan.l3_projection_id, "complete",
    )


def build_run_root(
    plan: ExhaustivePlanV1,
    target_roots: tuple[L4TargetRootV1, ...],
    source_roots: tuple[L4SourceRootV1, ...],
    completion_scope: Literal["selected-scope", "all-scope"],
) -> L4RunRootV1:
    if not isinstance(plan, ExhaustivePlanV1):
        raise Protocol28GraphError("run root requires ExhaustivePlanV1")
    targets = _typed(target_roots, L4TargetRootV1, "target_roots", key=lambda item: item.sort_key)
    expected = {item.identity: item for item in plan.target_plans}
    actual = {item.target_plan_id: item for item in targets}
    if set(actual) != set(expected):
        raise Protocol28GraphError("run root requires exact target root closure")
    for plan_id, root in actual.items():
        target = expected[plan_id]
        if (
            root.sort_key != target.sort_key
            or root.coverage_ledger_id != target.coverage_ledger.identity
            or root.target_l3_projection_id != target.l3_projection_id
            or root.target_evidence_projection_id != target.evidence_projection_id
            or root.plan_entry_ids != tuple(sorted(item.identity for item in target.entries))
            or root.addressed_finding_ids != target.coverage_ledger.assigned_finding_ids
        ):
            raise Protocol28GraphError("target root does not authenticate its plan")
    sources = _typed(source_roots, L4SourceRootV1, "source_roots", key=lambda item: item.source_id)
    expected_source_ids = {item.source_id for item in plan.target_plans if item.target_kind == "source"}
    if {item.source_id for item in sources} != expected_source_ids:
        raise Protocol28GraphError("run root requires exact source root closure")
    source_target_roots = {item.source_id: item for item in targets if item.target_kind == "source"}
    if any(item.source_composition_root_id != source_target_roots[item.source_id].identity for item in sources):
        raise Protocol28GraphError("source root composition authority mismatch")
    if completion_scope != plan.completion_scope:
        raise Protocol28GraphError("run root completion scope does not match frozen selection")
    return L4RunRootV1(
        1, plan.source_snapshot_id, plan.partition_manifest_id, plan.selection_id,
        plan.parent_authority_bundle_id, plan.identity, plan.policy_id,
        tuple(sorted(item.identity for item in targets)),
        tuple(sorted(item.identity for item in sources)),
        tuple(sorted(slice_id for item in targets for slice_id in item.accepted_slice_ids)),
        completion_scope, "complete",
    )


def build_l4_semantic_closure(
    parent: ParentAuthorityBundleV3,
    run_root: L4RunRootV1,
    accepted_slices: tuple[AcceptedExhaustiveSliceV1, ...],
    verifier_receipts: tuple[ExhaustiveVerificationReceiptV1, ...],
) -> L4SemanticClosureRootV1:
    if not isinstance(parent, ParentAuthorityBundleV3) or not isinstance(run_root, L4RunRootV1):
        raise Protocol28ClosureIntegrityError("closure_parent_mismatch", "closure authority types are invalid")
    if parent.identity != run_root.parent_authority_bundle_id:
        raise Protocol28ClosureIntegrityError("closure_parent_mismatch", "L4 run root has different parent authority")
    accepted = tuple(accepted_slices)
    if any(not isinstance(item, AcceptedExhaustiveSliceV1) for item in accepted):
        raise Protocol28ClosureIntegrityError("closure_slice_invalid", "closure accepted slice is invalid")
    if tuple(sorted(item.identity for item in accepted)) != run_root.accepted_slice_ids:
        raise Protocol28ClosureIntegrityError("closure_slice_set_mismatch", "closure slice set differs from L4 run root")
    receipts = tuple(verifier_receipts)
    if any(not isinstance(item, ExhaustiveVerificationReceiptV1) for item in receipts):
        raise Protocol28ClosureIntegrityError("closure_verifier_receipt_invalid", "closure verifier receipt is invalid")
    by_slice = {item.accepted_slice_id: item for item in receipts}
    if len(by_slice) != len(receipts) or set(by_slice) != {item.identity for item in accepted}:
        raise Protocol28ClosureIntegrityError(
            "closure_verifier_receipt_missing",
            "closure requires exactly one independent verifier receipt per accepted slice",
        )
    for item in accepted:
        receipt = by_slice[item.identity]
        if (
            receipt.plan_entry_id != item.plan_entry_id
            or receipt.verifier_result_hash != item.verifier_result_hash
            or receipt.verifier_execution_capture_hash != item.verifier_execution_capture_hash
            or receipt.assessed_finding_ids != item.addressed_finding_ids
        ):
            raise Protocol28ClosureIntegrityError(
                "closure_verifier_receipt_mismatch", "verifier receipt does not authenticate accepted slice"
            )
    finding_slices: dict[str, list[AcceptedExhaustiveSliceV1]] = {}
    for item in accepted:
        for finding in item.addressed_finding_ids:
            finding_slices.setdefault(finding, []).append(item)
    expected_findings = set(parent.unresolved_deeper_finding_ids)
    if set(finding_slices) != expected_findings:
        raise Protocol28ClosureIntegrityError(
            "closure_finding_set_mismatch", "accepted slices do not exactly resolve inherited deeper findings"
        )
    closure_receipts: list[L4FindingClosureReceiptV1] = []
    for finding_id in sorted(expected_findings):
        resolving = sorted(finding_slices[finding_id], key=lambda item: item.identity)
        if len(resolving) != 1:
            raise Protocol28ClosureIntegrityError(
                "closure_finding_primary_ambiguous",
                "deeper finding must have exactly one primary resolving slice",
            )
        primary, *supporting = resolving
        closure_receipts.append(L4FindingClosureReceiptV1(
            1, finding_id, primary.identity, tuple(item.identity for item in supporting),
            tuple(sorted(by_slice[item.identity].identity for item in resolving)), run_root.identity,
        ))
    return L4SemanticClosureRootV1(
        1, parent.identity, parent.frozen_epoch_id, run_root.identity,
        tuple(sorted(item.identity for item in closure_receipts)),
        tuple(sorted(item.identity for item in receipts)), "complete",
    )

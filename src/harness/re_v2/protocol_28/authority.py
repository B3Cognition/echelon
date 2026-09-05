"""Target-local L3 and parent authority for protocol 2.8."""

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
from harness.re_v2.protocol_24.model import SelectionScopeV1


_TARGET_KINDS = frozenset({"domain", "source"})
_TARGET_STATES = frozenset({"complete", "deeper-evidence-blocked"})
_TERMINAL_STATES = frozenset({"complete", "blocked"})
_T = TypeVar("_T")


class Protocol28AuthorityError(Protocol22SchemaError):
    """Raised when L3 or L4 authority cannot be composed safely."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol28AuthorityError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol28AuthorityError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(canonical_json_bytes(value))


def _safe_ids(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol28AuthorityError(f"{field} must be an array")
    result = tuple(_schema(safe_id, item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise Protocol28AuthorityError(f"{field} must be sorted and unique")
    return result


def _unique_digests(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol28AuthorityError(f"{field} must be an array")
    result = tuple(_schema(digest_value, item, field) for item in value)
    if len(result) != len(set(result)):
        raise Protocol28AuthorityError(f"{field} must be unique")
    return result


def _typed_tuple(
    value: object,
    expected_type: type[_T],
    field: str,
    *,
    key,
) -> tuple[_T, ...]:  # type: ignore[no-untyped-def]
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, expected_type) for item in value
    ):
        raise Protocol28AuthorityError(
            f"{field} must contain {expected_type.__name__} values"
        )
    result = tuple(value)
    keys = tuple(key(item) for item in result)
    if keys != tuple(sorted(set(keys))):
        raise Protocol28AuthorityError(f"{field} must be canonically sorted and unique")
    return result


@dataclass(frozen=True, slots=True)
class ValidatedL3TargetV1:
    """Normalized exact target authority loaded from a terminal protocol-2.5 epoch."""

    schema_version: int
    target_kind: Literal["domain", "source"]
    source_id: str
    target_id: str
    target_content_id: str
    candidate_authority_hash: str
    finding_ids: tuple[str, ...]
    unresolved_finding_ids: tuple[str, ...]
    resolution_overlay_ids: tuple[str, ...]
    closure_receipt_ids: tuple[str, ...]
    closure_state: Literal["complete", "deeper-evidence-blocked"]
    relevant_l2_root_ids: tuple[str, ...]
    audit_policy_id: str
    executor_policy_id: str
    frozen_epoch_id: str
    epoch_target_entry_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "target_kind",
        "source_id",
        "target_id",
        "target_content_id",
        "candidate_authority_hash",
        "finding_ids",
        "unresolved_finding_ids",
        "resolution_overlay_ids",
        "closure_receipt_ids",
        "closure_state",
        "relevant_l2_root_ids",
        "audit_policy_id",
        "executor_policy_id",
        "frozen_epoch_id",
        "epoch_target_entry_hash",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        kind = _schema(one_of, self.target_kind, _TARGET_KINDS, f"{label}.target_kind")
        _schema(safe_id, self.source_id, f"{label}.source_id")
        _schema(safe_id, self.target_id, f"{label}.target_id")
        if kind == "source" and self.target_id != self.source_id:
            raise Protocol28AuthorityError(
                "ValidatedL3TargetV1 source target_id must equal source_id"
            )
        for field in (
            "target_content_id",
            "candidate_authority_hash",
            "audit_policy_id",
            "executor_policy_id",
            "frozen_epoch_id",
            "epoch_target_entry_hash",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        for field in (
            "finding_ids",
            "unresolved_finding_ids",
            "resolution_overlay_ids",
            "closure_receipt_ids",
            "relevant_l2_root_ids",
        ):
            values = _schema(
                sorted_unique_digests,
                getattr(self, field),
                f"{label}.{field}",
            )
            object.__setattr__(self, field, values)
        if not self.relevant_l2_root_ids:
            raise Protocol28AuthorityError(
                "ValidatedL3TargetV1 requires relevant L2 root authority"
            )
        if not set(self.unresolved_finding_ids).issubset(self.finding_ids):
            raise Protocol28AuthorityError(
                "unresolved findings must belong to target finding authority"
            )
        state = _schema(
            one_of, self.closure_state, _TARGET_STATES, f"{label}.closure_state"
        )
        if state == "complete" and self.unresolved_finding_ids:
            raise Protocol28AuthorityError(
                "complete L3 target cannot retain unresolved findings"
            )
        if state == "deeper-evidence-blocked" and not self.unresolved_finding_ids:
            raise Protocol28AuthorityError(
                "deeper-evidence-blocked target requires unresolved findings"
            )

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return self.source_id, self.target_kind, self.target_id

    def to_json_dict(self) -> dict[str, object]:
        repeated = {
            "finding_ids",
            "unresolved_finding_ids",
            "resolution_overlay_ids",
            "closure_receipt_ids",
            "relevant_l2_root_ids",
        }
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field not in repeated
            },
            **{field: list(getattr(self, field)) for field in repeated},
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ValidatedL3TargetV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ValidatedL3ParentV1:
    schema_version: int
    run_id: str
    manifest_hash: str
    terminal_event_hash: str
    source_snapshot_id: str
    partition_manifest_id: str
    selection_id: str
    frozen_epoch_id: str
    terminal_state: Literal["complete", "blocked"]
    blocker_classes: tuple[str, ...]
    workspace_partition_catalog_id: str
    inherited_artifact_policy_catalog_id: str
    lower_l0_l2_authority_ids: tuple[str, ...]
    targets: tuple[ValidatedL3TargetV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "run_id",
        "manifest_hash",
        "terminal_event_hash",
        "source_snapshot_id",
        "partition_manifest_id",
        "selection_id",
        "frozen_epoch_id",
        "terminal_state",
        "blocker_classes",
        "workspace_partition_catalog_id",
        "inherited_artifact_policy_catalog_id",
        "lower_l0_l2_authority_ids",
        "targets",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(safe_id, self.run_id, f"{label}.run_id")
        for field in (
            "manifest_hash",
            "terminal_event_hash",
            "source_snapshot_id",
            "partition_manifest_id",
            "selection_id",
            "frozen_epoch_id",
            "workspace_partition_catalog_id",
            "inherited_artifact_policy_catalog_id",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        state = _schema(
            one_of, self.terminal_state, _TERMINAL_STATES, f"{label}.terminal_state"
        )
        blockers = _safe_ids(self.blocker_classes, f"{label}.blocker_classes")
        if state == "complete" and blockers:
            raise Protocol28AuthorityError(
                "complete L3 parent cannot carry blocker classes"
            )
        if state == "blocked" and not blockers:
            raise Protocol28AuthorityError("blocked L3 parent requires blocker classes")
        lower = _schema(
            sorted_unique_digests,
            self.lower_l0_l2_authority_ids,
            f"{label}.lower_l0_l2_authority_ids",
        )
        if not lower:
            raise Protocol28AuthorityError(
                "ValidatedL3ParentV1 requires lower L0-L2 authority"
            )
        targets = _typed_tuple(
            self.targets,
            ValidatedL3TargetV1,
            f"{label}.targets",
            key=lambda item: item.sort_key,
        )
        if not targets:
            raise Protocol28AuthorityError("ValidatedL3ParentV1 targets must not be empty")
        object.__setattr__(self, "blocker_classes", blockers)
        object.__setattr__(self, "lower_l0_l2_authority_ids", lower)
        object.__setattr__(self, "targets", targets)

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field
                not in {"blocker_classes", "lower_l0_l2_authority_ids", "targets"}
            },
            "blocker_classes": list(self.blocker_classes),
            "lower_l0_l2_authority_ids": list(self.lower_l0_l2_authority_ids),
            "targets": [item.to_json_dict() for item in self.targets],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ValidatedL3ParentV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        targets = raw["targets"]
        if not isinstance(targets, (list, tuple)):
            raise Protocol28AuthorityError(
                "ValidatedL3ParentV1.targets must be an array"
            )
        return cls(
            **{field: raw[field] for field in cls.FIELDS if field != "targets"},
            targets=tuple(ValidatedL3TargetV1.from_json_dict(item) for item in targets),
        )


@dataclass(frozen=True, slots=True)
class ValidatedL3ParentV2:
    """L3 parent plus exact accepted residual-debt authority, when present."""

    parent: ValidatedL3ParentV1
    input_quality: Literal["complete", "partial"]
    residual_debt_acceptance_hash: str | None
    unresolved_finding_ids: tuple[str, ...]
    deferred_observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.parent, ValidatedL3ParentV1):
            raise Protocol28AuthorityError(
                "ValidatedL3ParentV2 requires ValidatedL3ParentV1 authority"
            )
        quality = _schema(
            one_of,
            self.input_quality,
            frozenset({"complete", "partial"}),
            "ValidatedL3ParentV2.input_quality",
        )
        unresolved = _schema(
            sorted_unique_digests,
            self.unresolved_finding_ids,
            "ValidatedL3ParentV2.unresolved_finding_ids",
        )
        deferred = _schema(
            sorted_unique_digests,
            self.deferred_observation_ids,
            "ValidatedL3ParentV2.deferred_observation_ids",
        )
        target_unresolved = tuple(
            sorted(
                {
                    finding_id
                    for target in self.parent.targets
                    for finding_id in target.unresolved_finding_ids
                }
            )
        )
        if unresolved != target_unresolved:
            raise Protocol28AuthorityError(
                "ValidatedL3ParentV2 unresolved findings differ from parent authority"
            )
        if quality == "complete":
            if (
                self.residual_debt_acceptance_hash is not None
                or unresolved
                or deferred
                or self.parent.terminal_state != "complete"
            ):
                raise Protocol28AuthorityError(
                    "complete L3 input cannot carry residual-debt authority"
                )
        else:
            if self.residual_debt_acceptance_hash is None:
                raise Protocol28AuthorityError(
                    "partial L3 input requires residual-debt acceptance"
                )
            _schema(
                digest_value,
                self.residual_debt_acceptance_hash,
                "ValidatedL3ParentV2.residual_debt_acceptance_hash",
            )
            if self.parent.terminal_state != "blocked" or not unresolved:
                raise Protocol28AuthorityError(
                    "partial L3 input requires exact unresolved blocked authority"
                )
        object.__setattr__(self, "unresolved_finding_ids", unresolved)
        object.__setattr__(self, "deferred_observation_ids", deferred)

    def __getattr__(self, name: str) -> object:
        """Keep the V1 authority surface readable while carrying quality metadata."""
        parent = object.__getattribute__(self, "parent")
        try:
            return getattr(parent, name)
        except AttributeError as exc:
            raise AttributeError(name) from exc


def _validated_l3_parent_v1(
    parent: ValidatedL3ParentV1 | ValidatedL3ParentV2,
) -> ValidatedL3ParentV1:
    if isinstance(parent, ValidatedL3ParentV2):
        return parent.parent
    if isinstance(parent, ValidatedL3ParentV1):
        return parent
    raise Protocol28AuthorityError("validated L3 parent authority is invalid")


@dataclass(frozen=True, slots=True)
class L3TargetAuthorityProjectionV1:
    schema_version: int
    target_kind: Literal["domain", "source"]
    source_id: str
    target_id: str
    target_content_id: str
    candidate_authority_hash: str
    finding_ids: tuple[str, ...]
    unresolved_finding_ids: tuple[str, ...]
    resolution_overlay_ids: tuple[str, ...]
    closure_receipt_ids: tuple[str, ...]
    closure_state: Literal["complete", "deeper-evidence-blocked"]
    relevant_l2_root_ids: tuple[str, ...]
    audit_policy_id: str
    executor_policy_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "target_kind",
        "source_id",
        "target_id",
        "target_content_id",
        "candidate_authority_hash",
        "finding_ids",
        "unresolved_finding_ids",
        "resolution_overlay_ids",
        "closure_receipt_ids",
        "closure_state",
        "relevant_l2_root_ids",
        "audit_policy_id",
        "executor_policy_id",
    )

    def __post_init__(self) -> None:
        normalized = ValidatedL3TargetV1(
            **{field: getattr(self, field) for field in self.FIELDS},
            frozen_epoch_id=content_digest(b"projection-validation-epoch"),
            epoch_target_entry_hash=content_digest(b"projection-validation-entry"),
        )
        for field in self.FIELDS:
            object.__setattr__(self, field, getattr(normalized, field))

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return self.source_id, self.target_kind, self.target_id

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        repeated = {
            "finding_ids",
            "unresolved_finding_ids",
            "resolution_overlay_ids",
            "closure_receipt_ids",
            "relevant_l2_root_ids",
        }
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field not in repeated
            },
            **{field: list(getattr(self, field)) for field in repeated},
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L3TargetAuthorityProjectionV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class L3TargetEpochMembershipV1:
    schema_version: int
    target_projection_id: str
    frozen_epoch_id: str
    epoch_target_entry_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "target_projection_id",
        "frozen_epoch_id",
        "epoch_target_entry_hash",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L3TargetEpochMembershipV1.schema_version")
        for field in self.FIELDS[1:]:
            _schema(
                digest_value,
                getattr(self, field),
                f"L3TargetEpochMembershipV1.{field}",
            )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "L3TargetEpochMembershipV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class L3TargetProjectionCatalogV1:
    schema_version: int
    parent_manifest_hash: str
    parent_terminal_event_hash: str
    source_snapshot_id: str
    partition_manifest_id: str
    selection_id: str
    frozen_epoch_id: str
    projections: tuple[L3TargetAuthorityProjectionV1, ...]
    memberships: tuple[L3TargetEpochMembershipV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "parent_manifest_hash",
        "parent_terminal_event_hash",
        "source_snapshot_id",
        "partition_manifest_id",
        "selection_id",
        "frozen_epoch_id",
        "projections",
        "memberships",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        for field in self.FIELDS[1:7]:
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        projections = _typed_tuple(
            self.projections,
            L3TargetAuthorityProjectionV1,
            f"{label}.projections",
            key=lambda item: item.sort_key,
        )
        memberships = _typed_tuple(
            self.memberships,
            L3TargetEpochMembershipV1,
            f"{label}.memberships",
            key=lambda item: item.target_projection_id,
        )
        projection_ids = {item.identity for item in projections}
        if {item.target_projection_id for item in memberships} != projection_ids:
            raise Protocol28AuthorityError(
                "L3 target epoch membership must exactly cover projections"
            )
        if any(item.frozen_epoch_id != self.frozen_epoch_id for item in memberships):
            raise Protocol28AuthorityError(
                "L3 target epoch membership disagrees with catalog epoch"
            )
        object.__setattr__(self, "projections", projections)
        object.__setattr__(self, "memberships", memberships)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def for_domain(self, domain_key: str) -> L3TargetAuthorityProjectionV1:
        matches = tuple(
            item
            for item in self.projections
            if item.target_kind == "domain" and item.target_id == domain_key
        )
        if len(matches) != 1:
            raise Protocol28AuthorityError(
                f"L3 domain projection {domain_key!r} is missing or ambiguous"
            )
        return matches[0]

    def membership_for(self, projection_id: str) -> L3TargetEpochMembershipV1:
        matches = tuple(
            item
            for item in self.memberships
            if item.target_projection_id == projection_id
        )
        if len(matches) != 1:
            raise Protocol28AuthorityError(
                f"L3 target membership {projection_id!r} is missing or ambiguous"
            )
        return matches[0]

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field not in {"projections", "memberships"}
            },
            "projections": [item.to_json_dict() for item in self.projections],
            "memberships": [item.to_json_dict() for item in self.memberships],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L3TargetProjectionCatalogV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        if not isinstance(raw["projections"], (list, tuple)) or not isinstance(
            raw["memberships"], (list, tuple)
        ):
            raise Protocol28AuthorityError(
                "L3TargetProjectionCatalogV1 projection fields must be arrays"
            )
        return cls(
            **{
                field: raw[field]
                for field in cls.FIELDS
                if field not in {"projections", "memberships"}
            },
            projections=tuple(
                L3TargetAuthorityProjectionV1.from_json_dict(item)
                for item in raw["projections"]
            ),
            memberships=tuple(
                L3TargetEpochMembershipV1.from_json_dict(item)
                for item in raw["memberships"]
            ),
        )


@dataclass(frozen=True, slots=True)
class ParentAuthorityBundleV3:
    schema_version: int
    source_snapshot_id: str
    partition_manifest_id: str
    selection_id: str
    workspace_partition_catalog_id: str
    inherited_artifact_policy_catalog_id: str
    lower_l0_l2_authority_ids: tuple[str, ...]
    l3_run_id: str
    l3_manifest_hash: str
    l3_terminal_event_hash: str
    frozen_epoch_id: str
    l3_projection_catalog_id: str
    selected_projection_ids: tuple[str, ...]
    selected_epoch_membership_ids: tuple[str, ...]
    unresolved_deeper_finding_ids: tuple[str, ...]
    staged_checkpoint_provenance_ids: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "source_snapshot_id",
        "partition_manifest_id",
        "selection_id",
        "workspace_partition_catalog_id",
        "inherited_artifact_policy_catalog_id",
        "lower_l0_l2_authority_ids",
        "l3_run_id",
        "l3_manifest_hash",
        "l3_terminal_event_hash",
        "frozen_epoch_id",
        "l3_projection_catalog_id",
        "selected_projection_ids",
        "selected_epoch_membership_ids",
        "unresolved_deeper_finding_ids",
        "staged_checkpoint_provenance_ids",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 3, f"{label}.schema_version")
        _schema(safe_id, self.l3_run_id, f"{label}.l3_run_id")
        for field in (
            "source_snapshot_id",
            "partition_manifest_id",
            "selection_id",
            "workspace_partition_catalog_id",
            "inherited_artifact_policy_catalog_id",
            "l3_manifest_hash",
            "l3_terminal_event_hash",
            "frozen_epoch_id",
            "l3_projection_catalog_id",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        lower = _schema(
            sorted_unique_digests,
            self.lower_l0_l2_authority_ids,
            f"{label}.lower_l0_l2_authority_ids",
        )
        if not lower:
            raise Protocol28AuthorityError(
                "ParentAuthorityBundleV3 requires lower L0-L2 authority"
            )
        for field in (
            "selected_projection_ids",
            "selected_epoch_membership_ids",
        ):
            values = _unique_digests(getattr(self, field), f"{label}.{field}")
            if not values:
                raise Protocol28AuthorityError(f"{label}.{field} must be nonempty")
            object.__setattr__(self, field, values)
        for field in (
            "unresolved_deeper_finding_ids",
            "staged_checkpoint_provenance_ids",
        ):
            object.__setattr__(
                self,
                field,
                _schema(
                    sorted_unique_digests,
                    getattr(self, field),
                    f"{label}.{field}",
                ),
            )
        object.__setattr__(self, "lower_l0_l2_authority_ids", lower)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        repeated = {
            "lower_l0_l2_authority_ids",
            "selected_projection_ids",
            "selected_epoch_membership_ids",
            "unresolved_deeper_finding_ids",
            "staged_checkpoint_provenance_ids",
        }
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field not in repeated
            },
            **{field: list(getattr(self, field)) for field in repeated},
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ParentAuthorityBundleV3":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class L4ClosureParentBundleV1:
    schema_version: int
    selection_id: str
    source_snapshot_id: str
    partition_manifest_id: str
    l3_run_id: str
    l3_manifest_hash: str
    l3_terminal_event_hash: str
    frozen_epoch_id: str
    l4_run_id: str
    l4_manifest_hash: str
    l4_terminal_event_hash: str
    l4_run_root_id: str
    l4_run_root_state: Literal["complete"]
    assigned_target_projection_ids: tuple[str, ...]
    accepted_slice_ids: tuple[str, ...]
    verification_receipt_ids: tuple[str, ...]
    target_root_ids: tuple[str, ...]
    immutable_object_ids: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "selection_id",
        "source_snapshot_id",
        "partition_manifest_id",
        "l3_run_id",
        "l3_manifest_hash",
        "l3_terminal_event_hash",
        "frozen_epoch_id",
        "l4_run_id",
        "l4_manifest_hash",
        "l4_terminal_event_hash",
        "l4_run_root_id",
        "l4_run_root_state",
        "assigned_target_projection_ids",
        "accepted_slice_ids",
        "verification_receipt_ids",
        "target_root_ids",
        "immutable_object_ids",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        for field in ("l3_run_id", "l4_run_id"):
            _schema(safe_id, getattr(self, field), f"{label}.{field}")
        for field in (
            "selection_id",
            "source_snapshot_id",
            "partition_manifest_id",
            "l3_manifest_hash",
            "l3_terminal_event_hash",
            "frozen_epoch_id",
            "l4_manifest_hash",
            "l4_terminal_event_hash",
            "l4_run_root_id",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        _schema(
            literal,
            self.l4_run_root_state,
            "complete",
            f"{label}.l4_run_root_state",
        )
        for field in self.FIELDS[13:]:
            values = _schema(
                sorted_unique_digests,
                getattr(self, field),
                f"{label}.{field}",
            )
            if not values:
                raise Protocol28AuthorityError(f"{label}.{field} must be nonempty")
            object.__setattr__(self, field, values)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        repeated = set(self.FIELDS[13:])
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field not in repeated
            },
            **{field: list(getattr(self, field)) for field in repeated},
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L4ClosureParentBundleV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


def build_l3_target_projections(
    parent: ValidatedL3ParentV1 | ValidatedL3ParentV2,
    selection: SelectionScopeV1,
) -> L3TargetProjectionCatalogV1:
    parent = _validated_l3_parent_v1(parent)
    if not isinstance(selection, SelectionScopeV1):
        raise Protocol28AuthorityError("L3 target projection selection is invalid")
    selected_source_ids = (
        {item.source_id for item in parent.targets}
        if selection.all_sources
        else set(selection.source_ids)
    )
    selected_domain_ids = set(selection.domain_keys)
    selected = tuple(
        item
        for item in parent.targets
        if item.source_id in selected_source_ids
        and (
            item.target_kind == "source"
            or not selected_domain_ids
            or item.target_id in selected_domain_ids
        )
    )
    expected_domain_ids = (
        {
            item.target_id
            for item in parent.targets
            if item.target_kind == "domain" and item.source_id in selected_source_ids
        }
        if not selected_domain_ids
        else selected_domain_ids
    )
    observed_domain_ids = {
        item.target_id for item in selected if item.target_kind == "domain"
    }
    observed_source_ids = {
        item.source_id for item in selected if item.target_kind == "source"
    }
    if observed_domain_ids != expected_domain_ids or observed_source_ids != selected_source_ids:
        raise Protocol28AuthorityError(
            "selected L3 targets are incomplete for requested sources/domains"
        )
    if any(item.frozen_epoch_id != parent.frozen_epoch_id for item in selected):
        raise Protocol28AuthorityError("selected L3 targets contain mixed audit epoch authority")

    projections: list[L3TargetAuthorityProjectionV1] = []
    memberships: list[L3TargetEpochMembershipV1] = []
    for target in selected:
        projection = L3TargetAuthorityProjectionV1(
            **{field: getattr(target, field) for field in L3TargetAuthorityProjectionV1.FIELDS}
        )
        membership = L3TargetEpochMembershipV1(
            schema_version=1,
            target_projection_id=projection.identity,
            frozen_epoch_id=parent.frozen_epoch_id,
            epoch_target_entry_hash=target.epoch_target_entry_hash,
        )
        projections.append(projection)
        memberships.append(membership)
    return L3TargetProjectionCatalogV1(
        schema_version=1,
        parent_manifest_hash=parent.manifest_hash,
        parent_terminal_event_hash=parent.terminal_event_hash,
        source_snapshot_id=parent.source_snapshot_id,
        partition_manifest_id=parent.partition_manifest_id,
        selection_id=selection.identity,
        frozen_epoch_id=parent.frozen_epoch_id,
        projections=tuple(sorted(projections, key=lambda item: item.sort_key)),
        memberships=tuple(
            sorted(memberships, key=lambda item: item.target_projection_id)
        ),
    )


def build_parent_authority_bundle_v3(
    parent: ValidatedL3ParentV1 | ValidatedL3ParentV2,
    projections: L3TargetProjectionCatalogV1,
) -> ParentAuthorityBundleV3:
    accepted_partial = (
        isinstance(parent, ValidatedL3ParentV2)
        and parent.input_quality == "partial"
    )
    parent = _validated_l3_parent_v1(parent)
    if not isinstance(projections, L3TargetProjectionCatalogV1):
        raise Protocol28AuthorityError(
            "parent bundle requires validated L3 parent and projection catalog"
        )
    if (
        projections.parent_manifest_hash != parent.manifest_hash
        or projections.parent_terminal_event_hash != parent.terminal_event_hash
        or projections.source_snapshot_id != parent.source_snapshot_id
        or projections.partition_manifest_id != parent.partition_manifest_id
        or projections.frozen_epoch_id != parent.frozen_epoch_id
    ):
        raise Protocol28AuthorityError(
            "L3 target projection catalog does not match parent authority"
        )
    blockers = set(parent.blocker_classes)
    if parent.terminal_state == "blocked" and not accepted_partial and blockers != {
        "requires_deeper_evidence"
    }:
        raise Protocol28AuthorityError(
            "L3 parent blocker classes are ineligible for L4: "
            + ",".join(parent.blocker_classes)
        )
    unresolved = tuple(
        sorted(
            {
                finding_id
                for projection in projections.projections
                for finding_id in projection.unresolved_finding_ids
            }
        )
    )
    if parent.terminal_state == "complete" and unresolved:
        raise Protocol28AuthorityError(
            "complete L3 parent cannot carry unresolved selected findings"
        )
    if parent.terminal_state == "blocked" and not unresolved:
        raise Protocol28AuthorityError(
            "deeper-evidence-blocked parent has no selected unresolved findings"
        )
    membership_by_projection = {
        item.target_projection_id: item for item in projections.memberships
    }
    projection_ids = tuple(item.identity for item in projections.projections)
    return ParentAuthorityBundleV3(
        schema_version=3,
        source_snapshot_id=parent.source_snapshot_id,
        partition_manifest_id=parent.partition_manifest_id,
        selection_id=projections.selection_id,
        workspace_partition_catalog_id=parent.workspace_partition_catalog_id,
        inherited_artifact_policy_catalog_id=parent.inherited_artifact_policy_catalog_id,
        lower_l0_l2_authority_ids=parent.lower_l0_l2_authority_ids,
        l3_run_id=parent.run_id,
        l3_manifest_hash=parent.manifest_hash,
        l3_terminal_event_hash=parent.terminal_event_hash,
        frozen_epoch_id=parent.frozen_epoch_id,
        l3_projection_catalog_id=projections.identity,
        selected_projection_ids=projection_ids,
        selected_epoch_membership_ids=tuple(
            membership_by_projection[item].identity for item in projection_ids
        ),
        unresolved_deeper_finding_ids=unresolved,
        staged_checkpoint_provenance_ids=(),
    )


__all__ = (
    "L3TargetAuthorityProjectionV1",
    "L3TargetEpochMembershipV1",
    "L3TargetProjectionCatalogV1",
    "L4ClosureParentBundleV1",
    "ParentAuthorityBundleV3",
    "Protocol28AuthorityError",
    "ValidatedL3ParentV1",
    "ValidatedL3ParentV2",
    "ValidatedL3TargetV1",
    "build_l3_target_projections",
    "build_parent_authority_bundle_v3",
)

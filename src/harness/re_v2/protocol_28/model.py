"""Closed protocol-2.8 request, lineage, budget, and manifest values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, TypeAlias

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    positive_or_none,
    safe_id,
    sorted_unique_digests,
    utc_timestamp,
)
from harness.re_v2.protocol_24.model import ParentLineageV1, SelectionScopeV1


class Protocol28SchemaError(Protocol22SchemaError):
    """Raised when protocol-2.8 authority violates its closed schema."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol28SchemaError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol28SchemaError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(canonical_json_bytes(value))


def _exact_tuple(
    value: object,
    expected: tuple[str, ...],
    field: str,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or tuple(value) != expected:
        raise Protocol28SchemaError(f"{field} must be exactly {list(expected)!r}")
    return expected


@dataclass(frozen=True, slots=True)
class ExhaustiveBudgetPolicyV1:
    schema_version: int
    token_limit: int | None
    active_ms_limit: int | None
    producer_attempt_limit: int
    producer_contract_retry_limit: int
    verifier_contract_retry_limit: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "token_limit",
        "active_ms_limit",
        "producer_attempt_limit",
        "producer_contract_retry_limit",
        "verifier_contract_retry_limit",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(positive_or_none, self.token_limit, f"{label}.token_limit")
        _schema(positive_or_none, self.active_ms_limit, f"{label}.active_ms_limit")
        _schema(literal, self.producer_attempt_limit, 3, f"{label}.producer_attempt_limit")
        _schema(
            literal,
            self.producer_contract_retry_limit,
            0,
            f"{label}.producer_contract_retry_limit",
        )
        _schema(
            literal,
            self.verifier_contract_retry_limit,
            1,
            f"{label}.verifier_contract_retry_limit",
        )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveBudgetPolicyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ExhaustiveRequestV1:
    schema_version: int
    selection_id: str
    parent_authority_bundle_id: str
    l3_target_projection_catalog_id: str
    snapshot_evidence_catalog_id: str
    exhaustive_policy_catalog_id: str
    executor_catalog_id: str
    source_snapshot_id: str
    partition_manifest_id: str
    exhaustive_plan_id: str | None = None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "selection_id",
        "parent_authority_bundle_id",
        "l3_target_projection_catalog_id",
        "snapshot_evidence_catalog_id",
        "exhaustive_policy_catalog_id",
        "executor_catalog_id",
        "source_snapshot_id",
        "partition_manifest_id",
        "exhaustive_plan_id",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        for field in self.FIELDS[1:-1]:
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        if self.exhaustive_plan_id is not None:
            _schema(
                digest_value,
                self.exhaustive_plan_id,
                f"{label}.exhaustive_plan_id",
            )

    @property
    def request_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.request_id

    def to_json_dict(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in self.FIELDS
            if field != "exhaustive_plan_id" or self.exhaustive_plan_id is not None
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveRequestV1":
        if not isinstance(value, dict):
            raise Protocol28SchemaError("ExhaustiveRequestV1 must be an object")
        fields = frozenset(cls.FIELDS)
        legacy_fields = fields - {"exhaustive_plan_id"}
        selected = fields if set(value) == fields else legacy_fields
        raw = _schema(exact_object, value, selected, cls.__name__)
        return cls(
            **{field: raw[field] for field in selected},
            **(
                {}
                if "exhaustive_plan_id" in selected
                else {"exhaustive_plan_id": None}
            ),
        )


@dataclass(frozen=True, slots=True)
class L4ClosureRequestV1:
    schema_version: int
    blocked_l3_manifest_hash: str
    blocked_l3_terminal_event_hash: str
    frozen_epoch_id: str
    unresolved_finding_ids: tuple[str, ...]
    l4_run_root_id: str
    l4_target_root_ids: tuple[str, ...]
    verification_receipt_ids: tuple[str, ...]
    closure_policy_id: str
    source_snapshot_id: str
    partition_manifest_id: str
    selection_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "blocked_l3_manifest_hash",
        "blocked_l3_terminal_event_hash",
        "frozen_epoch_id",
        "unresolved_finding_ids",
        "l4_run_root_id",
        "l4_target_root_ids",
        "verification_receipt_ids",
        "closure_policy_id",
        "source_snapshot_id",
        "partition_manifest_id",
        "selection_id",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        for field in (
            "blocked_l3_manifest_hash",
            "blocked_l3_terminal_event_hash",
            "frozen_epoch_id",
            "l4_run_root_id",
            "closure_policy_id",
            "source_snapshot_id",
            "partition_manifest_id",
            "selection_id",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        findings = _schema(
            sorted_unique_digests,
            self.unresolved_finding_ids,
            f"{label}.unresolved_finding_ids",
        )
        targets = _schema(
            sorted_unique_digests,
            self.l4_target_root_ids,
            f"{label}.l4_target_root_ids",
        )
        receipts = _schema(
            sorted_unique_digests,
            self.verification_receipt_ids,
            f"{label}.verification_receipt_ids",
        )
        if not findings or not targets or not receipts:
            raise Protocol28SchemaError(
                "L4ClosureRequestV1 findings, target roots, and verification receipts must not be empty"
            )
        object.__setattr__(self, "unresolved_finding_ids", findings)
        object.__setattr__(self, "l4_target_root_ids", targets)
        object.__setattr__(self, "verification_receipt_ids", receipts)

    @property
    def request_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.request_id

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field
                not in {
                    "unresolved_finding_ids",
                    "l4_target_root_ids",
                    "verification_receipt_ids",
                }
            },
            "unresolved_finding_ids": list(self.unresolved_finding_ids),
            "l4_target_root_ids": list(self.l4_target_root_ids),
            "verification_receipt_ids": list(self.verification_receipt_ids),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L4ClosureRequestV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class L4ClosureLineageV1:
    schema_version: int
    l3_run_id: str
    l3_manifest_hash: str
    l3_terminal_event_hash: str
    l4_run_id: str
    l4_manifest_hash: str
    l4_terminal_event_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "l3_run_id",
        "l3_manifest_hash",
        "l3_terminal_event_hash",
        "l4_run_id",
        "l4_manifest_hash",
        "l4_terminal_event_hash",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        for field in ("l3_run_id", "l4_run_id"):
            _schema(safe_id, getattr(self, field), f"{label}.{field}")
        for field in self.FIELDS[2:4] + self.FIELDS[5:]:
            _schema(digest_value, getattr(self, field), f"{label}.{field}")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "L4ClosureLineageV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


_COMMON_MANIFEST_FIELDS = (
    "schema_version",
    "engine",
    "engine_protocol_version",
    "run_mode",
    "requested_goals",
    "target_layer",
    "run_id",
    "created_at",
    "source_snapshot_id",
    "source_snapshot_kind",
    "partition_manifest_id",
    "selection",
    "lineage",
)


def _validate_manifest_envelope(instance: object, expected_mode: str) -> None:
    label = type(instance).__name__
    _schema(literal, getattr(instance, "schema_version"), 7, f"{label}.schema_version")
    _schema(literal, getattr(instance, "engine"), "re-v2", f"{label}.engine")
    _schema(
        literal,
        getattr(instance, "engine_protocol_version"),
        "2.8",
        f"{label}.engine_protocol_version",
    )
    _schema(literal, getattr(instance, "run_mode"), expected_mode, f"{label}.run_mode")
    _schema(literal, getattr(instance, "target_layer"), "L4", f"{label}.target_layer")
    _schema(safe_id, getattr(instance, "run_id"), f"{label}.run_id")
    _schema(utc_timestamp, getattr(instance, "created_at"), f"{label}.created_at")
    _schema(digest_value, getattr(instance, "source_snapshot_id"), f"{label}.source_snapshot_id")
    _schema(
        literal,
        getattr(instance, "source_snapshot_kind"),
        "workspace-git-composite",
        f"{label}.source_snapshot_kind",
    )
    _schema(
        digest_value,
        getattr(instance, "partition_manifest_id"),
        f"{label}.partition_manifest_id",
    )
    if not isinstance(getattr(instance, "selection"), SelectionScopeV1):
        raise Protocol28SchemaError(f"{label}.selection is invalid")


@dataclass(frozen=True, slots=True)
class ExhaustiveRunManifestV7:
    schema_version: int
    engine: Literal["re-v2"]
    engine_protocol_version: Literal["2.8"]
    run_mode: Literal["exhaustive-depth"]
    requested_goals: tuple[str, ...]
    target_layer: Literal["L4"]
    run_id: str
    created_at: str
    source_snapshot_id: str
    source_snapshot_kind: Literal["workspace-git-composite"]
    partition_manifest_id: str
    selection: SelectionScopeV1
    lineage: ParentLineageV1
    workspace_partition_catalog_id: str
    inherited_artifact_policy_catalog_id: str
    parent_authority_bundle_id: str
    l3_target_projection_catalog_id: str
    snapshot_evidence_catalog_id: str
    exhaustive_request: ExhaustiveRequestV1
    exhaustive_plan_id: str
    exhaustive_policy_catalog_id: str
    executor_catalog_id: str
    attempt_policy_id: str
    budget_policy: ExhaustiveBudgetPolicyV1

    FIELDS: ClassVar[tuple[str, ...]] = _COMMON_MANIFEST_FIELDS + (
        "workspace_partition_catalog_id",
        "inherited_artifact_policy_catalog_id",
        "parent_authority_bundle_id",
        "l3_target_projection_catalog_id",
        "snapshot_evidence_catalog_id",
        "exhaustive_request",
        "exhaustive_plan_id",
        "exhaustive_policy_catalog_id",
        "executor_catalog_id",
        "attempt_policy_id",
        "budget_policy",
    )

    def __post_init__(self) -> None:
        _validate_manifest_envelope(self, "exhaustive-depth")
        label = type(self).__name__
        goals = _exact_tuple(
            self.requested_goals,
            ("selective-exhaustive-depth",),
            f"{label}.requested_goals",
        )
        if not isinstance(self.lineage, ParentLineageV1):
            raise Protocol28SchemaError(f"{label}.lineage is invalid")
        for field in self.FIELDS[13:23]:
            if field not in {"exhaustive_request", "budget_policy"}:
                _schema(digest_value, getattr(self, field), f"{label}.{field}")
        if not isinstance(self.exhaustive_request, ExhaustiveRequestV1):
            raise Protocol28SchemaError(f"{label}.exhaustive_request is invalid")
        if not isinstance(self.budget_policy, ExhaustiveBudgetPolicyV1):
            raise Protocol28SchemaError(f"{label}.budget_policy is invalid")
        request = self.exhaustive_request
        expected = (
            (request.selection_id, self.selection.identity),
            (request.parent_authority_bundle_id, self.parent_authority_bundle_id),
            (request.l3_target_projection_catalog_id, self.l3_target_projection_catalog_id),
            (request.snapshot_evidence_catalog_id, self.snapshot_evidence_catalog_id),
            (request.exhaustive_policy_catalog_id, self.exhaustive_policy_catalog_id),
            (request.executor_catalog_id, self.executor_catalog_id),
            (request.source_snapshot_id, self.source_snapshot_id),
            (request.partition_manifest_id, self.partition_manifest_id),
        )
        if any(left != right for left, right in expected):
            raise Protocol28SchemaError(
                "ExhaustiveRunManifestV7 request authority does not match manifest"
            )
        object.__setattr__(self, "requested_goals", goals)

    @property
    def run_manifest_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.run_manifest_id

    def to_json_dict(self) -> dict[str, object]:
        nested = {"selection", "lineage", "exhaustive_request", "budget_policy"}
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field not in nested | {"requested_goals"}
            },
            "requested_goals": list(self.requested_goals),
            "selection": self.selection.to_json_dict(),
            "lineage": self.lineage.to_json_dict(),
            "exhaustive_request": self.exhaustive_request.to_json_dict(),
            "budget_policy": self.budget_policy.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExhaustiveRunManifestV7":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            **{
                field: raw[field]
                for field in cls.FIELDS
                if field not in {"selection", "lineage", "exhaustive_request", "budget_policy"}
            },
            selection=SelectionScopeV1.from_json_dict(raw["selection"]),
            lineage=ParentLineageV1.from_json_dict(raw["lineage"]),
            exhaustive_request=ExhaustiveRequestV1.from_json_dict(raw["exhaustive_request"]),
            budget_policy=ExhaustiveBudgetPolicyV1.from_json_dict(raw["budget_policy"]),
        )


@dataclass(frozen=True, slots=True)
class L4ClosureRunManifestV7:
    schema_version: int
    engine: Literal["re-v2"]
    engine_protocol_version: Literal["2.8"]
    run_mode: Literal["l4-closure-successor"]
    requested_goals: tuple[str, ...]
    target_layer: Literal["L4"]
    run_id: str
    created_at: str
    source_snapshot_id: str
    source_snapshot_kind: Literal["workspace-git-composite"]
    partition_manifest_id: str
    selection: SelectionScopeV1
    lineage: L4ClosureLineageV1
    closure_parent_bundle_id: str
    closure_request: L4ClosureRequestV1
    l4_run_root_id: str
    closure_policy_id: str

    FIELDS: ClassVar[tuple[str, ...]] = _COMMON_MANIFEST_FIELDS + (
        "closure_parent_bundle_id",
        "closure_request",
        "l4_run_root_id",
        "closure_policy_id",
    )

    def __post_init__(self) -> None:
        _validate_manifest_envelope(self, "l4-closure-successor")
        label = type(self).__name__
        goals = _exact_tuple(
            self.requested_goals,
            ("l4-evidence-closure",),
            f"{label}.requested_goals",
        )
        if not isinstance(self.lineage, L4ClosureLineageV1):
            raise Protocol28SchemaError(f"{label}.lineage is invalid")
        if not isinstance(self.closure_request, L4ClosureRequestV1):
            raise Protocol28SchemaError(f"{label}.closure_request is invalid")
        for field in ("closure_parent_bundle_id", "l4_run_root_id", "closure_policy_id"):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        request = self.closure_request
        expected = (
            (request.blocked_l3_manifest_hash, self.lineage.l3_manifest_hash),
            (request.blocked_l3_terminal_event_hash, self.lineage.l3_terminal_event_hash),
            (request.l4_run_root_id, self.l4_run_root_id),
            (request.closure_policy_id, self.closure_policy_id),
            (request.source_snapshot_id, self.source_snapshot_id),
            (request.partition_manifest_id, self.partition_manifest_id),
            (request.selection_id, self.selection.identity),
        )
        if any(left != right for left, right in expected):
            raise Protocol28SchemaError(
                "L4ClosureRunManifestV7 request authority does not match manifest"
            )
        object.__setattr__(self, "requested_goals", goals)

    @property
    def run_manifest_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.run_manifest_id

    def to_json_dict(self) -> dict[str, object]:
        nested = {"selection", "lineage", "closure_request"}
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field not in nested | {"requested_goals"}
            },
            "requested_goals": list(self.requested_goals),
            "selection": self.selection.to_json_dict(),
            "lineage": self.lineage.to_json_dict(),
            "closure_request": self.closure_request.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L4ClosureRunManifestV7":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            **{
                field: raw[field]
                for field in cls.FIELDS
                if field not in {"selection", "lineage", "closure_request"}
            },
            selection=SelectionScopeV1.from_json_dict(raw["selection"]),
            lineage=L4ClosureLineageV1.from_json_dict(raw["lineage"]),
            closure_request=L4ClosureRequestV1.from_json_dict(raw["closure_request"]),
        )


RunManifestV7: TypeAlias = ExhaustiveRunManifestV7 | L4ClosureRunManifestV7


def decode_run_manifest_v7(value: object) -> RunManifestV7:
    if not isinstance(value, dict):
        raise Protocol28SchemaError("RunManifestV7 must be an object")
    mode = value.get("run_mode")
    if mode == "exhaustive-depth":
        return ExhaustiveRunManifestV7.from_json_dict(value)
    if mode == "l4-closure-successor":
        return L4ClosureRunManifestV7.from_json_dict(value)
    raise Protocol28SchemaError("RunManifestV7.run_mode is unsupported")


__all__ = (
    "ExhaustiveBudgetPolicyV1",
    "ExhaustiveRequestV1",
    "ExhaustiveRunManifestV7",
    "L4ClosureLineageV1",
    "L4ClosureRequestV1",
    "L4ClosureRunManifestV7",
    "Protocol28SchemaError",
    "RunManifestV7",
    "decode_run_manifest_v7",
)

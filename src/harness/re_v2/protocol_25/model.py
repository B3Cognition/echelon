"""Closed schema-4 values for RE v2 protocol 2.5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.model import BudgetPolicyV2, CatalogReferenceV1
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    one_of,
    positive_or_none,
    safe_id,
    utc_timestamp,
)
from harness.re_v2.protocol_24.model import ParentLineageV1, SelectionScopeV1


RunModeV1 = Literal[
    "new-audit-epoch",
    "audit-successor",
    "closure-successor",
]

_RUN_MODES = frozenset(
    {"new-audit-epoch", "audit-successor", "closure-successor"}
)


class Protocol25SchemaError(Protocol22SchemaError):
    """Raised when protocol-2.5 authority violates its closed schema."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol25SchemaError:
        raise
    except Protocol22SchemaError as exc:
        raise Protocol25SchemaError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class SemanticClosurePolicyV1:
    schema_version: int
    token_limit: int | None
    active_ms_limit: int | None
    max_rounds_per_target: int
    consecutive_no_reduction_limit: int
    provider_attempt_limit: int
    contract_retry_limit: int
    unknown_usage_policy: Literal["shared-conservative-reservation-v1"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "token_limit",
        "active_ms_limit",
        "max_rounds_per_target",
        "consecutive_no_reduction_limit",
        "provider_attempt_limit",
        "contract_retry_limit",
        "unknown_usage_policy",
    )

    def __post_init__(self) -> None:
        _schema(
            literal,
            self.schema_version,
            1,
            "SemanticClosurePolicyV1.schema_version",
        )
        _schema(
            positive_or_none,
            self.token_limit,
            "SemanticClosurePolicyV1.token_limit",
        )
        _schema(
            positive_or_none,
            self.active_ms_limit,
            "SemanticClosurePolicyV1.active_ms_limit",
        )
        for field, expected in (
            ("max_rounds_per_target", 3),
            ("consecutive_no_reduction_limit", 2),
            ("provider_attempt_limit", 2),
            ("contract_retry_limit", 1),
        ):
            _schema(
                literal,
                getattr(self, field),
                expected,
                f"SemanticClosurePolicyV1.{field}",
            )
        _schema(
            literal,
            self.unknown_usage_policy,
            "shared-conservative-reservation-v1",
            "SemanticClosurePolicyV1.unknown_usage_policy",
        )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SemanticClosurePolicyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class RunManifestV4:
    schema_version: int
    engine: Literal["re-v2"]
    engine_protocol_version: Literal["2.5"]
    run_id: str
    created_at: str
    source_snapshot_id: str
    source_snapshot_kind: Literal["workspace-git-composite"]
    partition_manifest_id: str
    workspace_partition_catalog: CatalogReferenceV1
    artifact_policy_catalog: CatalogReferenceV1
    executor_contract_catalog: CatalogReferenceV1
    audit_policy_catalog: CatalogReferenceV1
    parent_authority_bundle: CatalogReferenceV1
    parent_lineage: ParentLineageV1
    requested_goals: tuple[Literal["semantic-audit-closure"], ...]
    target_layer: Literal["L3"]
    selection: SelectionScopeV1
    run_mode: RunModeV1
    frozen_audit_epoch: CatalogReferenceV1 | None
    human_guidance: CatalogReferenceV1 | None
    semantic_request_id: str
    initial_budget_policy: BudgetPolicyV2
    semantic_closure_policy: SemanticClosurePolicyV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "engine",
        "engine_protocol_version",
        "run_id",
        "created_at",
        "source_snapshot_id",
        "source_snapshot_kind",
        "partition_manifest_id",
        "workspace_partition_catalog",
        "artifact_policy_catalog",
        "executor_contract_catalog",
        "audit_policy_catalog",
        "parent_authority_bundle",
        "parent_lineage",
        "requested_goals",
        "target_layer",
        "selection",
        "run_mode",
        "frozen_audit_epoch",
        "human_guidance",
        "semantic_request_id",
        "initial_budget_policy",
        "semantic_closure_policy",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 4, "RunManifestV4.schema_version")
        _schema(literal, self.engine, "re-v2", "RunManifestV4.engine")
        _schema(
            literal,
            self.engine_protocol_version,
            "2.5",
            "RunManifestV4.engine_protocol_version",
        )
        _schema(safe_id, self.run_id, "RunManifestV4.run_id")
        _schema(utc_timestamp, self.created_at, "RunManifestV4.created_at")
        _schema(
            digest_value,
            self.source_snapshot_id,
            "RunManifestV4.source_snapshot_id",
        )
        _schema(
            literal,
            self.source_snapshot_kind,
            "workspace-git-composite",
            "RunManifestV4.source_snapshot_kind",
        )
        _schema(
            digest_value,
            self.partition_manifest_id,
            "RunManifestV4.partition_manifest_id",
        )
        references = (
            self.workspace_partition_catalog,
            self.artifact_policy_catalog,
            self.executor_contract_catalog,
            self.audit_policy_catalog,
            self.parent_authority_bundle,
        )
        if any(not isinstance(item, CatalogReferenceV1) for item in references):
            raise Protocol25SchemaError(
                "RunManifestV4 catalog references must be CatalogReferenceV1 values"
            )
        if (
            len({item.relative_path for item in references}) != len(references)
            or len({item.object_hash for item in references}) != len(references)
        ):
            raise Protocol25SchemaError(
                "RunManifestV4 catalog references must be distinct"
            )
        if not isinstance(self.parent_lineage, ParentLineageV1):
            raise Protocol25SchemaError("RunManifestV4.parent_lineage is invalid")
        goals = tuple(self.requested_goals)
        if goals != ("semantic-audit-closure",):
            raise Protocol25SchemaError(
                "RunManifestV4.requested_goals must be semantic-audit-closure"
            )
        _schema(literal, self.target_layer, "L3", "RunManifestV4.target_layer")
        if not isinstance(self.selection, SelectionScopeV1):
            raise Protocol25SchemaError("RunManifestV4.selection is invalid")
        mode = _schema(one_of, self.run_mode, _RUN_MODES, "RunManifestV4.run_mode")
        for field in ("frozen_audit_epoch", "human_guidance"):
            value = getattr(self, field)
            if value is not None and not isinstance(value, CatalogReferenceV1):
                raise Protocol25SchemaError(
                    f"RunManifestV4.{field} must be CatalogReferenceV1 or null"
                )
        if mode == "new-audit-epoch":
            if self.frozen_audit_epoch is not None:
                raise Protocol25SchemaError(
                    "new audit epoch must not pin a frozen audit epoch"
                )
            if self.human_guidance is not None:
                raise Protocol25SchemaError(
                    "new audit epoch must not pin human guidance"
                )
        elif mode == "audit-successor":
            if self.frozen_audit_epoch is not None:
                raise Protocol25SchemaError(
                    "audit successor must not pin a frozen audit epoch"
                )
            if self.human_guidance is None:
                raise Protocol25SchemaError("audit successor requires human guidance")
        else:
            if self.frozen_audit_epoch is None:
                raise Protocol25SchemaError(
                    "closure successor requires a frozen audit epoch"
                )
            if self.human_guidance is None:
                raise Protocol25SchemaError("closure successor requires human guidance")
        optional_references = tuple(
            item
            for item in (self.frozen_audit_epoch, self.human_guidance)
            if item is not None
        )
        all_references = references + optional_references
        if (
            len({item.relative_path for item in all_references})
            != len(all_references)
            or len({item.object_hash for item in all_references})
            != len(all_references)
        ):
            raise Protocol25SchemaError(
                "RunManifestV4 immutable references must be distinct"
            )
        _schema(
            digest_value,
            self.semantic_request_id,
            "RunManifestV4.semantic_request_id",
        )
        if not isinstance(self.initial_budget_policy, BudgetPolicyV2):
            raise Protocol25SchemaError(
                "RunManifestV4.initial_budget_policy must be BudgetPolicyV2"
            )
        if not self.initial_budget_policy.matches_goal("semantic-audit-closure"):
            raise Protocol25SchemaError(
                "RunManifestV4 run-wide budget does not match semantic-audit-closure"
            )
        if not isinstance(self.semantic_closure_policy, SemanticClosurePolicyV1):
            raise Protocol25SchemaError(
                "RunManifestV4.semantic_closure_policy is invalid"
            )
        object.__setattr__(self, "requested_goals", goals)

    @property
    def parent_run_id(self) -> str:
        return self.parent_lineage.direct_parent_run_id

    @property
    def run_manifest_id(self) -> str:
        return content_digest(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.run_manifest_id

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "engine": self.engine,
            "engine_protocol_version": self.engine_protocol_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_kind": self.source_snapshot_kind,
            "partition_manifest_id": self.partition_manifest_id,
            "workspace_partition_catalog": self.workspace_partition_catalog.to_json_dict(),
            "artifact_policy_catalog": self.artifact_policy_catalog.to_json_dict(),
            "executor_contract_catalog": self.executor_contract_catalog.to_json_dict(),
            "audit_policy_catalog": self.audit_policy_catalog.to_json_dict(),
            "parent_authority_bundle": self.parent_authority_bundle.to_json_dict(),
            "parent_lineage": self.parent_lineage.to_json_dict(),
            "requested_goals": list(self.requested_goals),
            "target_layer": self.target_layer,
            "selection": self.selection.to_json_dict(),
            "run_mode": self.run_mode,
            "frozen_audit_epoch": (
                None
                if self.frozen_audit_epoch is None
                else self.frozen_audit_epoch.to_json_dict()
            ),
            "human_guidance": (
                None
                if self.human_guidance is None
                else self.human_guidance.to_json_dict()
            ),
            "semantic_request_id": self.semantic_request_id,
            "initial_budget_policy": self.initial_budget_policy.to_json_dict(),
            "semantic_closure_policy": self.semantic_closure_policy.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "RunManifestV4":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)

        def optional_reference(field: str) -> CatalogReferenceV1 | None:
            item = raw[field]
            return None if item is None else CatalogReferenceV1.from_json_dict(item)

        try:
            return cls(
                schema_version=raw["schema_version"],
                engine=raw["engine"],
                engine_protocol_version=raw["engine_protocol_version"],
                run_id=raw["run_id"],
                created_at=raw["created_at"],
                source_snapshot_id=raw["source_snapshot_id"],
                source_snapshot_kind=raw["source_snapshot_kind"],
                partition_manifest_id=raw["partition_manifest_id"],
                workspace_partition_catalog=CatalogReferenceV1.from_json_dict(
                    raw["workspace_partition_catalog"]
                ),
                artifact_policy_catalog=CatalogReferenceV1.from_json_dict(
                    raw["artifact_policy_catalog"]
                ),
                executor_contract_catalog=CatalogReferenceV1.from_json_dict(
                    raw["executor_contract_catalog"]
                ),
                audit_policy_catalog=CatalogReferenceV1.from_json_dict(
                    raw["audit_policy_catalog"]
                ),
                parent_authority_bundle=CatalogReferenceV1.from_json_dict(
                    raw["parent_authority_bundle"]
                ),
                parent_lineage=ParentLineageV1.from_json_dict(
                    raw["parent_lineage"]
                ),
                requested_goals=raw["requested_goals"],
                target_layer=raw["target_layer"],
                selection=SelectionScopeV1.from_json_dict(raw["selection"]),
                run_mode=raw["run_mode"],
                frozen_audit_epoch=optional_reference("frozen_audit_epoch"),
                human_guidance=optional_reference("human_guidance"),
                semantic_request_id=raw["semantic_request_id"],
                initial_budget_policy=BudgetPolicyV2.from_json_dict(
                    raw["initial_budget_policy"]
                ),
                semantic_closure_policy=SemanticClosurePolicyV1.from_json_dict(
                    raw["semantic_closure_policy"]
                ),
            )
        except Protocol25SchemaError:
            raise
        except Protocol22SchemaError as exc:
            raise Protocol25SchemaError(str(exc)) from exc


__all__ = (
    "Protocol25SchemaError",
    "RunManifestV4",
    "RunModeV1",
    "SemanticClosurePolicyV1",
)

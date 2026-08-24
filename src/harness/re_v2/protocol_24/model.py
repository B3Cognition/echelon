"""Closed schema-3 values for RE v2 protocol 2.4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.model import BudgetPolicyV2, CatalogReferenceV1
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    boolean,
    digest_value,
    exact_object,
    literal,
    optional_digest,
    safe_id,
    sorted_unique_digests,
    utc_timestamp,
)


class Protocol24SchemaError(Protocol22SchemaError):
    """Raised when protocol-2.4 authority violates its closed schema."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol24SchemaError:
        raise
    except Protocol22SchemaError as exc:
        raise Protocol24SchemaError(str(exc)) from exc


def _safe_ids(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise Protocol24SchemaError(f"{field} must be an array")
    result = tuple(_schema(safe_id, value, field) for value in values)
    if result != tuple(sorted(set(result))):
        raise Protocol24SchemaError(f"{field} must be sorted and unique")
    return result


@dataclass(frozen=True, slots=True)
class SelectionScopeV1:
    schema_version: int
    all_sources: bool
    source_ids: tuple[str, ...]
    domain_keys: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "all_sources",
        "source_ids",
        "domain_keys",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "SelectionScopeV1.schema_version")
        _schema(boolean, self.all_sources, "SelectionScopeV1.all_sources")
        sources = _safe_ids(self.source_ids, "SelectionScopeV1.source_ids")
        domains = _schema(
            sorted_unique_digests,
            self.domain_keys,
            "SelectionScopeV1.domain_keys",
        )
        if self.all_sources and (sources or domains):
            raise Protocol24SchemaError(
                "SelectionScopeV1 all-sources selection requires empty source/domain arrays"
            )
        if not self.all_sources and not sources:
            raise Protocol24SchemaError(
                "SelectionScopeV1 scoped selection requires at least one source"
            )
        if domains and len(sources) != 1:
            raise Protocol24SchemaError(
                "SelectionScopeV1 domains require exactly one source"
            )
        object.__setattr__(self, "source_ids", sources)
        object.__setattr__(self, "domain_keys", domains)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "all_sources": self.all_sources,
            "source_ids": list(self.source_ids),
            "domain_keys": list(self.domain_keys),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SelectionScopeV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ParentLineageV1:
    schema_version: int
    direct_parent_run_id: str
    direct_parent_manifest_hash: str
    direct_parent_terminal_event_hash: str
    lineage_root_run_id: str
    lineage_root_manifest_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "direct_parent_run_id",
        "direct_parent_manifest_hash",
        "direct_parent_terminal_event_hash",
        "lineage_root_run_id",
        "lineage_root_manifest_hash",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ParentLineageV1.schema_version")
        for field in ("direct_parent_run_id", "lineage_root_run_id"):
            _schema(safe_id, getattr(self, field), f"ParentLineageV1.{field}")
        for field in (
            "direct_parent_manifest_hash",
            "direct_parent_terminal_event_hash",
            "lineage_root_manifest_hash",
        ):
            _schema(digest_value, getattr(self, field), f"ParentLineageV1.{field}")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ParentLineageV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class AdoptedArtifactAuthorityV1:
    schema_version: int
    artifact_key_id: str
    artifact_hash: str
    dependency_hashes: tuple[str, ...]
    certification_receipt_id: str
    candidate_assessment_id: str | None
    artifact_acceptance_receipt_id: str
    source_run_id: str
    source_ledger_entry_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_key_id",
        "artifact_hash",
        "dependency_hashes",
        "certification_receipt_id",
        "candidate_assessment_id",
        "artifact_acceptance_receipt_id",
        "source_run_id",
        "source_ledger_entry_hash",
    )

    def __post_init__(self) -> None:
        _schema(
            literal,
            self.schema_version,
            1,
            "AdoptedArtifactAuthorityV1.schema_version",
        )
        for field in (
            "artifact_key_id",
            "artifact_hash",
            "certification_receipt_id",
            "artifact_acceptance_receipt_id",
            "source_ledger_entry_hash",
        ):
            _schema(
                digest_value,
                getattr(self, field),
                f"AdoptedArtifactAuthorityV1.{field}",
            )
        _schema(
            optional_digest,
            self.candidate_assessment_id,
            "AdoptedArtifactAuthorityV1.candidate_assessment_id",
        )
        dependencies = _schema(
            sorted_unique_digests,
            self.dependency_hashes,
            "AdoptedArtifactAuthorityV1.dependency_hashes",
        )
        _schema(
            safe_id,
            self.source_run_id,
            "AdoptedArtifactAuthorityV1.source_run_id",
        )
        object.__setattr__(self, "dependency_hashes", dependencies)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["dependency_hashes"] = list(self.dependency_hashes)
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "AdoptedArtifactAuthorityV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ParentAuthorityBundleV1:
    schema_version: int
    direct_parent_run_id: str
    source_manifest_hash: str
    source_event_chain_hash: str
    source_terminal_event_hash: str
    source_ledger_chain_hash: str
    lineage_root_run_id: str
    ancestor_bundle_hashes: tuple[str, ...]
    artifacts: tuple[AdoptedArtifactAuthorityV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "direct_parent_run_id",
        "source_manifest_hash",
        "source_event_chain_hash",
        "source_terminal_event_hash",
        "source_ledger_chain_hash",
        "lineage_root_run_id",
        "ancestor_bundle_hashes",
        "artifacts",
    )

    def __post_init__(self) -> None:
        _schema(
            literal,
            self.schema_version,
            1,
            "ParentAuthorityBundleV1.schema_version",
        )
        for field in ("direct_parent_run_id", "lineage_root_run_id"):
            _schema(safe_id, getattr(self, field), f"ParentAuthorityBundleV1.{field}")
        for field in (
            "source_manifest_hash",
            "source_event_chain_hash",
            "source_terminal_event_hash",
            "source_ledger_chain_hash",
        ):
            _schema(
                digest_value,
                getattr(self, field),
                f"ParentAuthorityBundleV1.{field}",
            )
        ancestors = _schema(
            sorted_unique_digests,
            self.ancestor_bundle_hashes,
            "ParentAuthorityBundleV1.ancestor_bundle_hashes",
        )
        if not isinstance(self.artifacts, (list, tuple)) or any(
            not isinstance(item, AdoptedArtifactAuthorityV1)
            for item in self.artifacts
        ):
            raise Protocol24SchemaError(
                "ParentAuthorityBundleV1.artifacts must contain adopted artifact authority"
            )
        artifacts = tuple(self.artifacts)
        keys = tuple(item.artifact_key_id for item in artifacts)
        if not artifacts or keys != tuple(sorted(set(keys))):
            raise Protocol24SchemaError(
                "ParentAuthorityBundleV1.artifacts must be nonempty, sorted and unique"
            )
        object.__setattr__(self, "ancestor_bundle_hashes", ancestors)
        object.__setattr__(self, "artifacts", artifacts)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "direct_parent_run_id": self.direct_parent_run_id,
            "source_manifest_hash": self.source_manifest_hash,
            "source_event_chain_hash": self.source_event_chain_hash,
            "source_terminal_event_hash": self.source_terminal_event_hash,
            "source_ledger_chain_hash": self.source_ledger_chain_hash,
            "lineage_root_run_id": self.lineage_root_run_id,
            "ancestor_bundle_hashes": list(self.ancestor_bundle_hashes),
            "artifacts": [item.to_json_dict() for item in self.artifacts],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ParentAuthorityBundleV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        artifacts = raw["artifacts"]
        if not isinstance(artifacts, (list, tuple)):
            raise Protocol24SchemaError(
                "ParentAuthorityBundleV1.artifacts must be an array"
            )
        return cls(
            **{
                field: raw[field]
                for field in cls.FIELDS
                if field != "artifacts"
            },
            artifacts=tuple(
                AdoptedArtifactAuthorityV1.from_json_dict(item)
                for item in artifacts
            ),
        )


@dataclass(frozen=True, slots=True)
class RunManifestV3:
    schema_version: int
    engine: Literal["re-v2"]
    engine_protocol_version: Literal["2.4"]
    run_id: str
    created_at: str
    source_snapshot_id: str
    source_snapshot_kind: Literal["workspace-git-composite"]
    partition_manifest_id: str
    workspace_partition_catalog: CatalogReferenceV1
    artifact_policy_catalog: CatalogReferenceV1
    executor_contract_catalog: CatalogReferenceV1
    parent_authority_bundle: CatalogReferenceV1
    parent_lineage: ParentLineageV1
    requested_goals: tuple[Literal["selective-deepening"], ...]
    target_layer: Literal["L2"]
    selection: SelectionScopeV1
    semantic_request_id: str
    initial_budget_policy: BudgetPolicyV2

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
        "parent_authority_bundle",
        "parent_lineage",
        "requested_goals",
        "target_layer",
        "selection",
        "semantic_request_id",
        "initial_budget_policy",
    )
    ATTEMPT_POLICY: ClassVar[tuple[int, ...]] = (2, 2, 0, 1, 1, 1)

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 3, "RunManifestV3.schema_version")
        _schema(literal, self.engine, "re-v2", "RunManifestV3.engine")
        _schema(
            literal,
            self.engine_protocol_version,
            "2.4",
            "RunManifestV3.engine_protocol_version",
        )
        _schema(safe_id, self.run_id, "RunManifestV3.run_id")
        _schema(utc_timestamp, self.created_at, "RunManifestV3.created_at")
        _schema(
            digest_value,
            self.source_snapshot_id,
            "RunManifestV3.source_snapshot_id",
        )
        _schema(
            literal,
            self.source_snapshot_kind,
            "workspace-git-composite",
            "RunManifestV3.source_snapshot_kind",
        )
        _schema(
            digest_value,
            self.partition_manifest_id,
            "RunManifestV3.partition_manifest_id",
        )
        references = (
            self.workspace_partition_catalog,
            self.artifact_policy_catalog,
            self.executor_contract_catalog,
            self.parent_authority_bundle,
        )
        if any(not isinstance(item, CatalogReferenceV1) for item in references):
            raise Protocol24SchemaError(
                "RunManifestV3 catalog references must be CatalogReferenceV1 values"
            )
        if (
            len({item.relative_path for item in references}) != len(references)
            or len({item.object_hash for item in references}) != len(references)
        ):
            raise Protocol24SchemaError(
                "RunManifestV3 catalog references must be distinct"
            )
        if not isinstance(self.parent_lineage, ParentLineageV1):
            raise Protocol24SchemaError("RunManifestV3.parent_lineage is invalid")
        goals = tuple(self.requested_goals)
        if goals != ("selective-deepening",):
            raise Protocol24SchemaError(
                "RunManifestV3.requested_goals must be selective-deepening"
            )
        _schema(literal, self.target_layer, "L2", "RunManifestV3.target_layer")
        if not isinstance(self.selection, SelectionScopeV1):
            raise Protocol24SchemaError("RunManifestV3.selection is invalid")
        _schema(
            digest_value,
            self.semantic_request_id,
            "RunManifestV3.semantic_request_id",
        )
        if not isinstance(self.initial_budget_policy, BudgetPolicyV2):
            raise Protocol24SchemaError(
                "RunManifestV3.initial_budget_policy must be BudgetPolicyV2"
            )
        attempts = tuple(
            getattr(self.initial_budget_policy, field)
            for field in BudgetPolicyV2.ATTEMPT_FIELDS
        )
        if attempts != self.ATTEMPT_POLICY:
            raise Protocol24SchemaError(
                "RunManifestV3 attempt policy must be (2, 2, 0, 1, 1, 1)"
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
            "parent_authority_bundle": self.parent_authority_bundle.to_json_dict(),
            "parent_lineage": self.parent_lineage.to_json_dict(),
            "requested_goals": list(self.requested_goals),
            "target_layer": self.target_layer,
            "selection": self.selection.to_json_dict(),
            "semantic_request_id": self.semantic_request_id,
            "initial_budget_policy": self.initial_budget_policy.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "RunManifestV3":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
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
            parent_authority_bundle=CatalogReferenceV1.from_json_dict(
                raw["parent_authority_bundle"]
            ),
            parent_lineage=ParentLineageV1.from_json_dict(raw["parent_lineage"]),
            requested_goals=raw["requested_goals"],
            target_layer=raw["target_layer"],
            selection=SelectionScopeV1.from_json_dict(raw["selection"]),
            semantic_request_id=raw["semantic_request_id"],
            initial_budget_policy=BudgetPolicyV2.from_json_dict(
                raw["initial_budget_policy"]
            ),
        )


__all__ = (
    "AdoptedArtifactAuthorityV1",
    "ParentAuthorityBundleV1",
    "ParentLineageV1",
    "Protocol24SchemaError",
    "RunManifestV3",
    "SelectionScopeV1",
)


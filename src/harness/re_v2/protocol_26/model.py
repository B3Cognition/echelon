"""Closed protocol-2.6 checkpoint and schema-5 manifest values."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Literal, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.model import (
    CatalogReferenceV1,
    RunManifestV2,
    WorkItemV2,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    nonnegative_int,
    one_of,
    optional_digest,
    safe_id,
    sorted_unique_digests,
    utc_timestamp,
)
from harness.re_v2.protocol_24.model import (
    AdoptedArtifactAuthorityV1,
    RunManifestV3,
)
from harness.re_v2.protocol_25.model import RunManifestV4

if TYPE_CHECKING:
    from harness.re_v2.protocol_22.baseline import (
        ArtifactAcceptanceReceiptV2,
        CandidateAssessmentReceiptV1,
        CertificationReceiptV2,
    )
    from harness.re_v2.protocol_25.artifacts import SemanticCertificationReceiptV1


TargetLayerV1 = Literal["L1", "L2", "L3"]
CheckpointSourceKindV1 = Literal["direct_parent", "workspace_checkpoint"]
CheckpointDispositionKindV1 = Literal["not_selected", "rejected", "quarantined"]
LayerManifestV1 = RunManifestV2 | RunManifestV3 | RunManifestV4

_TARGET_LAYERS = frozenset({"L1", "L2", "L3"})
_SOURCE_KINDS = frozenset({"direct_parent", "workspace_checkpoint"})
_DISPOSITIONS = frozenset({"not_selected", "rejected", "quarantined"})
_ORIGIN_SCHEMA_PROTOCOLS = frozenset(
    {
        (1, "2.0"),
        (1, "2.1"),
        (2, "2.2"),
        (2, "2.3"),
        (3, "2.4"),
        (4, "2.5"),
        (5, "2.6"),
    }
)
_CONTROLLED_REASONS = frozenset(
    {
        "direct_parent_precedence",
        "checkpoint_rank_winner",
        "checkpoint_rank_hash_tiebreak",
        "checkpoint_incompatible",
        "checkpoint_dependency_missing",
        "checkpoint_origin_unstable",
        "checkpoint_manifest_invalid",
        "checkpoint_receipt_invalid",
        "checkpoint_object_missing",
        "checkpoint_object_hash_mismatch",
        "checkpoint_authority_conflict",
        "checkpoint_rank_invalid",
        "checkpoint_cycle_detected",
    }
)


class Protocol26SchemaError(Protocol22SchemaError):
    """Raised when protocol-2.6 authority violates its closed schema."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol26SchemaError:
        raise
    except (Protocol22SchemaError, ValueError) as exc:
        raise Protocol26SchemaError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(canonical_json_bytes(value))


def _target_layer_for_manifest(manifest: LayerManifestV1) -> TargetLayerV1:
    if isinstance(manifest, RunManifestV2):
        return "L1"
    if isinstance(manifest, RunManifestV3):
        return "L2"
    if isinstance(manifest, RunManifestV4):
        return "L3"
    raise Protocol26SchemaError(
        "LayerExecutionContractV1.layer_manifest must be RunManifestV2, "
        "RunManifestV3, or RunManifestV4"
    )


def _decode_layer_manifest(value: object) -> LayerManifestV1:
    if not isinstance(value, Mapping):
        raise Protocol26SchemaError(
            "LayerExecutionContractV1.layer_manifest must be an object"
        )
    pair = (value.get("schema_version"), value.get("engine_protocol_version"))
    try:
        if pair[0] == 2 and pair[1] in {"2.2", "2.3"}:
            return RunManifestV2.from_json_dict(value)
        if pair == (3, "2.4"):
            return RunManifestV3.from_json_dict(value)
        if pair == (4, "2.5"):
            return RunManifestV4.from_json_dict(value)
    except Protocol22SchemaError as exc:
        raise Protocol26SchemaError(str(exc)) from exc
    raise Protocol26SchemaError(
        f"unsupported layer execution manifest schema/protocol {pair!r}"
    )


def _receipt_types():  # type: ignore[no-untyped-def]
    from harness.re_v2.protocol_22.baseline import (
        ArtifactAcceptanceReceiptV2,
        CandidateAssessmentReceiptV1,
        CertificationReceiptV2,
    )
    from harness.re_v2.protocol_25.artifacts import SemanticCertificationReceiptV1

    return (
        CertificationReceiptV2,
        CandidateAssessmentReceiptV1,
        ArtifactAcceptanceReceiptV2,
        SemanticCertificationReceiptV1,
    )


def _tuple_of(
    values: object,
    expected_type: type,
    field: str,
    *,
    sorted_by_identity: bool = False,
) -> tuple[object, ...]:
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(value, expected_type) for value in values
    ):
        raise Protocol26SchemaError(
            f"{field} must be an array of {expected_type.__name__} values"
        )
    result = tuple(values)
    identities = tuple(getattr(value, "identity") for value in result)
    if len(identities) != len(set(identities)):
        raise Protocol26SchemaError(f"{field} must be unique")
    if sorted_by_identity and identities != tuple(sorted(identities)):
        raise Protocol26SchemaError(f"{field} must be sorted by identity")
    return result


@dataclass(frozen=True, slots=True)
class LayerExecutionContractV1:
    schema_version: int
    target_layer: TargetLayerV1
    layer_manifest: LayerManifestV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "target_layer",
        "layer_manifest",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, f"{type(self).__name__}.schema_version")
        target = _schema(one_of, self.target_layer, _TARGET_LAYERS, f"{type(self).__name__}.target_layer")
        observed = _target_layer_for_manifest(self.layer_manifest)
        if target != observed:
            raise Protocol26SchemaError(
                "LayerExecutionContractV1.target_layer disagrees with layer_manifest"
            )

    @classmethod
    def from_layer_manifest(cls, layer_manifest: LayerManifestV1) -> "LayerExecutionContractV1":
        return cls(
            schema_version=1,
            target_layer=_target_layer_for_manifest(layer_manifest),
            layer_manifest=layer_manifest,
        )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target_layer": self.target_layer,
            "layer_manifest": self.layer_manifest.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "LayerExecutionContractV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            target_layer=raw["target_layer"],
            layer_manifest=_decode_layer_manifest(raw["layer_manifest"]),
        )


@dataclass(frozen=True, slots=True)
class CheckpointRankV1:
    schema_version: int
    policy_id: str
    policy_hash: str
    vector: tuple[int, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "policy_id",
        "policy_hash",
        "vector",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, f"{type(self).__name__}.schema_version")
        _schema(safe_id, self.policy_id, f"{type(self).__name__}.policy_id")
        _schema(digest_value, self.policy_hash, f"{type(self).__name__}.policy_hash")
        if (
            not isinstance(self.vector, (list, tuple))
            or not self.vector
            or len(self.vector) > 32
        ):
            raise Protocol26SchemaError(
                "CheckpointRankV1.vector must be a nonempty bounded array"
            )
        vector = tuple(
            _schema(nonnegative_int, item, "CheckpointRankV1.vector")
            for item in self.vector
        )
        object.__setattr__(self, "vector", vector)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_hash": self.policy_hash,
            "vector": list(self.vector),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointRankV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class CheckpointArtifactDependencyV1:
    schema_version: int
    artifact_key_id: str
    artifact_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_key_id",
        "artifact_hash",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, f"{type(self).__name__}.schema_version")
        _schema(digest_value, self.artifact_key_id, f"{type(self).__name__}.artifact_key_id")
        _schema(digest_value, self.artifact_hash, f"{type(self).__name__}.artifact_hash")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointArtifactDependencyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class CheckpointManifestV1:
    schema_version: int
    origin_run_id: str
    origin_manifest_hash: str
    origin_engine_protocol_version: str
    origin_run_schema_version: int
    origin_acceptance_event_hash: str
    origin_event_prefix_hash: str
    origin_ledger_record_hash: str
    origin_ledger_prefix_hash: str
    work_item: WorkItemV2
    artifact_key_id: str
    artifact_hash: str
    certification_receipt: CertificationReceiptV2 | SemanticCertificationReceiptV1
    candidate_assessment: CandidateAssessmentReceiptV1 | None
    artifact_acceptance_receipt: ArtifactAcceptanceReceiptV2
    adopted_artifact_authority: AdoptedArtifactAuthorityV1
    accepted_artifact_dependencies: tuple[CheckpointArtifactDependencyV1, ...]
    non_artifact_dependency_hashes: tuple[str, ...]
    immutable_object_hashes: tuple[str, ...]
    immutable_object_byte_counts: Mapping[str, int]
    audit_epoch_id: str | None
    semantic_authority_ids: tuple[str, ...]
    rank: CheckpointRankV1
    rank_policy_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "origin_run_id",
        "origin_manifest_hash",
        "origin_engine_protocol_version",
        "origin_run_schema_version",
        "origin_acceptance_event_hash",
        "origin_event_prefix_hash",
        "origin_ledger_record_hash",
        "origin_ledger_prefix_hash",
        "work_item",
        "artifact_key_id",
        "artifact_hash",
        "certification_receipt",
        "candidate_assessment",
        "artifact_acceptance_receipt",
        "adopted_artifact_authority",
        "accepted_artifact_dependencies",
        "non_artifact_dependency_hashes",
        "immutable_object_hashes",
        "immutable_object_byte_counts",
        "audit_epoch_id",
        "semantic_authority_ids",
        "rank",
        "rank_policy_hash",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        (
            certification_type,
            candidate_type,
            acceptance_type,
            semantic_certification_type,
        ) = _receipt_types()
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(safe_id, self.origin_run_id, f"{label}.origin_run_id")
        for field in (
            "origin_manifest_hash",
            "origin_acceptance_event_hash",
            "origin_event_prefix_hash",
            "origin_ledger_record_hash",
            "origin_ledger_prefix_hash",
            "artifact_key_id",
            "artifact_hash",
            "rank_policy_hash",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        if (
            not isinstance(self.origin_run_schema_version, int)
            or isinstance(self.origin_run_schema_version, bool)
            or (self.origin_run_schema_version, self.origin_engine_protocol_version)
            not in _ORIGIN_SCHEMA_PROTOCOLS
        ):
            raise Protocol26SchemaError(
                "CheckpointManifestV1 origin schema/protocol is unsupported"
            )
        if not isinstance(self.work_item, WorkItemV2):
            raise Protocol26SchemaError(
                "CheckpointManifestV1.work_item must be WorkItemV2"
            )
        if not isinstance(
            self.certification_receipt,
            (certification_type, semantic_certification_type),
        ):
            raise Protocol26SchemaError(
                "CheckpointManifestV1.certification_receipt is invalid"
            )
        if self.candidate_assessment is not None and not isinstance(
            self.candidate_assessment, candidate_type
        ):
            raise Protocol26SchemaError(
                "CheckpointManifestV1.candidate_assessment is invalid"
            )
        if not isinstance(
            self.artifact_acceptance_receipt, acceptance_type
        ):
            raise Protocol26SchemaError(
                "CheckpointManifestV1.artifact_acceptance_receipt is invalid"
            )
        if not isinstance(
            self.adopted_artifact_authority, AdoptedArtifactAuthorityV1
        ):
            raise Protocol26SchemaError(
                "CheckpointManifestV1.adopted_artifact_authority is invalid"
            )
        if not isinstance(self.rank, CheckpointRankV1):
            raise Protocol26SchemaError("CheckpointManifestV1.rank is invalid")
        dependencies = _tuple_of(
            self.accepted_artifact_dependencies,
            CheckpointArtifactDependencyV1,
            "CheckpointManifestV1.accepted_artifact_dependencies",
            sorted_by_identity=True,
        )
        non_artifact = _schema(
            sorted_unique_digests,
            self.non_artifact_dependency_hashes,
            "CheckpointManifestV1.non_artifact_dependency_hashes",
        )
        immutable = _schema(
            sorted_unique_digests,
            self.immutable_object_hashes,
            "CheckpointManifestV1.immutable_object_hashes",
        )
        if not isinstance(self.immutable_object_byte_counts, Mapping):
            raise Protocol26SchemaError(
                "CheckpointManifestV1.immutable_object_byte_counts must be an object"
            )
        byte_counts: dict[str, int] = {}
        for object_hash, byte_count in self.immutable_object_byte_counts.items():
            digest = _schema(
                digest_value,
                object_hash,
                "CheckpointManifestV1.immutable_object_byte_counts key",
            )
            byte_counts[digest] = _schema(
                nonnegative_int,
                byte_count,
                "CheckpointManifestV1.immutable_object_byte_counts value",
            )
        if set(byte_counts) != set(immutable):
            raise Protocol26SchemaError(
                "CheckpointManifestV1 object byte counts disagree with immutable inventory"
            )
        audit_epoch = _schema(
            optional_digest,
            self.audit_epoch_id,
            "CheckpointManifestV1.audit_epoch_id",
        )
        semantic = _schema(
            sorted_unique_digests,
            self.semantic_authority_ids,
            "CheckpointManifestV1.semantic_authority_ids",
        )
        object.__setattr__(self, "accepted_artifact_dependencies", dependencies)
        object.__setattr__(self, "non_artifact_dependency_hashes", non_artifact)
        object.__setattr__(self, "immutable_object_hashes", immutable)
        object.__setattr__(
            self,
            "immutable_object_byte_counts",
            MappingProxyType(dict(sorted(byte_counts.items()))),
        )
        object.__setattr__(self, "semantic_authority_ids", semantic)
        if self.artifact_key_id != self.work_item.output_key.identity:
            raise Protocol26SchemaError(
                "CheckpointManifestV1 artifact_key_id disagrees with work_item"
            )
        acceptance = self.artifact_acceptance_receipt
        authority = self.adopted_artifact_authority
        semantic_certification = isinstance(
            self.certification_receipt, semantic_certification_type
        )
        if semantic_certification:
            certification_artifact_key_id = self.certification_receipt.artifact_key_id
            certification_artifact_hash = self.certification_receipt.artifact_hash
        else:
            certification_artifact_key_id = (
                self.certification_receipt.certification_key.artifact_key.identity
            )
            certification_artifact_hash = (
                self.certification_receipt.certification_key.artifact_hash
            )
            certification_key = self.certification_receipt.certification_key
            if (
                certification_key.artifact_key != self.work_item.output_key
                or certification_key.verifier_id != self.work_item.verifier_id
                or certification_key.verifier_version
                != self.work_item.verifier_version
                or certification_key.verifier_implementation_digest
                != self.work_item.verifier_implementation_digest
            ):
                raise Protocol26SchemaError(
                    "CheckpointManifestV1 certification differs from work item"
                )
        if (
            self.certification_receipt.verdict != "accepted"
            or certification_artifact_key_id != self.work_item.output_key.identity
            or certification_artifact_hash != self.artifact_hash
            or acceptance.artifact_key != self.work_item.output_key
            or acceptance.artifact_hash != self.artifact_hash
            or acceptance.certification_receipt_id
            != self.certification_receipt.identity
            or authority.artifact_key_id != self.artifact_key_id
            or authority.artifact_hash != self.artifact_hash
            or authority.certification_receipt_id
            != self.certification_receipt.identity
            or authority.artifact_acceptance_receipt_id != acceptance.identity
            or authority.source_run_id != self.origin_run_id
            or authority.source_ledger_entry_hash != self.origin_ledger_record_hash
        ):
            raise Protocol26SchemaError(
                "CheckpointManifestV1 artifact_hash or receipt authority is cross-bound"
            )
        candidate = self.candidate_assessment
        if candidate is None:
            if authority.candidate_assessment_id is not None:
                raise Protocol26SchemaError(
                    "CheckpointManifestV1 candidate authority is missing"
                )
        elif (
            candidate.outcome != "certified"
            or candidate.work_item_id != self.work_item.work_item_id
            or candidate.artifact_hash != self.artifact_hash
            or candidate.certification_receipt_id != self.certification_receipt.identity
            or authority.candidate_assessment_id != candidate.identity
        ):
            raise Protocol26SchemaError(
                "CheckpointManifestV1 candidate authority is cross-bound"
            )
        dependency_hashes = {
            item.artifact_hash for item in dependencies
        } | set(non_artifact)
        if dependency_hashes != set(self.work_item.output_key.dependency_hashes):
            raise Protocol26SchemaError(
                "CheckpointManifestV1 dependency authority disagrees with work_item"
            )
        required_objects = {
            self.origin_manifest_hash,
            self.origin_event_prefix_hash,
            self.origin_ledger_prefix_hash,
            self.work_item.work_item_id,
            self.artifact_hash,
            self.certification_receipt.identity,
            acceptance.identity,
        }
        required_objects.update(non_artifact)
        required_objects.update(
            dependency.artifact_hash for dependency in dependencies
        )
        if candidate is not None:
            required_objects.add(candidate.identity)
            required_objects.add(candidate.execution_capture_hash)
            if candidate.normalized_authorial_payload_hash is not None:
                required_objects.add(candidate.normalized_authorial_payload_hash)
        required_objects.update(semantic)
        if not required_objects <= set(immutable):
            raise Protocol26SchemaError(
                "CheckpointManifestV1 immutable object inventory is incomplete"
            )
        if self.rank_policy_hash != self.rank.policy_hash:
            raise Protocol26SchemaError(
                "CheckpointManifestV1 rank_policy_hash disagrees with rank"
            )
        if semantic_certification:
            if self.work_item.output_key.layer != "L3":
                raise Protocol26SchemaError(
                    "CheckpointManifestV1 semantic certification requires L3"
                )
            if audit_epoch != self.certification_receipt.audit_epoch_id:
                raise Protocol26SchemaError(
                    "CheckpointManifestV1 audit_epoch_id disagrees with semantic certification"
                )
            required_semantic = {self.certification_receipt.identity}
            if audit_epoch is not None:
                required_semantic.add(audit_epoch)
            if not required_semantic <= set(semantic):
                raise Protocol26SchemaError(
                    "CheckpointManifestV1 semantic authority inventory is incomplete"
                )
        elif self.work_item.output_key.layer == "L3":
            raise Protocol26SchemaError(
                "CheckpointManifestV1 L3 authority requires semantic certification"
            )
        elif audit_epoch is not None or semantic:
            raise Protocol26SchemaError(
                "CheckpointManifestV1 non-L3 authority cannot carry semantic authority"
            )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "origin_run_id": self.origin_run_id,
            "origin_manifest_hash": self.origin_manifest_hash,
            "origin_engine_protocol_version": self.origin_engine_protocol_version,
            "origin_run_schema_version": self.origin_run_schema_version,
            "origin_acceptance_event_hash": self.origin_acceptance_event_hash,
            "origin_event_prefix_hash": self.origin_event_prefix_hash,
            "origin_ledger_record_hash": self.origin_ledger_record_hash,
            "origin_ledger_prefix_hash": self.origin_ledger_prefix_hash,
            "work_item": self.work_item.to_json_dict(),
            "artifact_key_id": self.artifact_key_id,
            "artifact_hash": self.artifact_hash,
            "certification_receipt": self.certification_receipt.to_json_dict(),
            "candidate_assessment": (
                None
                if self.candidate_assessment is None
                else self.candidate_assessment.to_json_dict()
            ),
            "artifact_acceptance_receipt": self.artifact_acceptance_receipt.to_json_dict(),
            "adopted_artifact_authority": self.adopted_artifact_authority.to_json_dict(),
            "accepted_artifact_dependencies": [
                item.to_json_dict() for item in self.accepted_artifact_dependencies
            ],
            "non_artifact_dependency_hashes": list(
                self.non_artifact_dependency_hashes
            ),
            "immutable_object_hashes": list(self.immutable_object_hashes),
            "immutable_object_byte_counts": dict(self.immutable_object_byte_counts),
            "audit_epoch_id": self.audit_epoch_id,
            "semantic_authority_ids": list(self.semantic_authority_ids),
            "rank": self.rank.to_json_dict(),
            "rank_policy_hash": self.rank_policy_hash,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointManifestV1":
        from harness.re_v2.protocol_22.baseline import (
            ArtifactAcceptanceReceiptV2,
            CandidateAssessmentReceiptV1,
            CertificationReceiptV2,
        )
        from harness.re_v2.protocol_25.artifacts import (
            SemanticCertificationReceiptV1,
        )

        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        dependencies = raw["accepted_artifact_dependencies"]
        if not isinstance(dependencies, (list, tuple)):
            raise Protocol26SchemaError(
                "CheckpointManifestV1.accepted_artifact_dependencies must be an array"
            )
        candidate = raw["candidate_assessment"]
        return cls(
            schema_version=raw["schema_version"],
            origin_run_id=raw["origin_run_id"],
            origin_manifest_hash=raw["origin_manifest_hash"],
            origin_engine_protocol_version=raw["origin_engine_protocol_version"],
            origin_run_schema_version=raw["origin_run_schema_version"],
            origin_acceptance_event_hash=raw["origin_acceptance_event_hash"],
            origin_event_prefix_hash=raw["origin_event_prefix_hash"],
            origin_ledger_record_hash=raw["origin_ledger_record_hash"],
            origin_ledger_prefix_hash=raw["origin_ledger_prefix_hash"],
            work_item=WorkItemV2.from_json_dict(raw["work_item"]),
            artifact_key_id=raw["artifact_key_id"],
            artifact_hash=raw["artifact_hash"],
            certification_receipt=(
                CertificationReceiptV2.from_json_dict(raw["certification_receipt"])
                if isinstance(raw["certification_receipt"], Mapping)
                and "certification_key" in raw["certification_receipt"]
                else SemanticCertificationReceiptV1.from_json_dict(
                    raw["certification_receipt"]
                )
            ),
            candidate_assessment=(
                None
                if candidate is None
                else CandidateAssessmentReceiptV1.from_json_dict(candidate)
            ),
            artifact_acceptance_receipt=ArtifactAcceptanceReceiptV2.from_json_dict(
                raw["artifact_acceptance_receipt"]
            ),
            adopted_artifact_authority=AdoptedArtifactAuthorityV1.from_json_dict(
                raw["adopted_artifact_authority"]
            ),
            accepted_artifact_dependencies=tuple(
                CheckpointArtifactDependencyV1.from_json_dict(item)
                for item in dependencies
            ),
            non_artifact_dependency_hashes=raw["non_artifact_dependency_hashes"],
            immutable_object_hashes=raw["immutable_object_hashes"],
            immutable_object_byte_counts=raw["immutable_object_byte_counts"],
            audit_epoch_id=raw["audit_epoch_id"],
            semantic_authority_ids=raw["semantic_authority_ids"],
            rank=CheckpointRankV1.from_json_dict(raw["rank"]),
            rank_policy_hash=raw["rank_policy_hash"],
        )


@dataclass(frozen=True, slots=True)
class CheckpointSelectionEntryV1:
    schema_version: int
    expected_work_item_id: str
    source_kind: CheckpointSourceKindV1
    checkpoint_manifest_id: str | None
    adopted_artifact_authority: AdoptedArtifactAuthorityV1
    dependency_artifact_key_ids: tuple[str, ...]
    copied_object_ids: tuple[str, ...]
    copied_byte_count: int
    rank: CheckpointRankV1 | None
    origin_run_id: str
    selection_reason: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "expected_work_item_id",
        "source_kind",
        "checkpoint_manifest_id",
        "adopted_artifact_authority",
        "dependency_artifact_key_ids",
        "copied_object_ids",
        "copied_byte_count",
        "rank",
        "origin_run_id",
        "selection_reason",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(digest_value, self.expected_work_item_id, f"{label}.expected_work_item_id")
        kind = _schema(one_of, self.source_kind, _SOURCE_KINDS, f"{label}.source_kind")
        manifest_id = _schema(optional_digest, self.checkpoint_manifest_id, f"{label}.checkpoint_manifest_id")
        if not isinstance(
            self.adopted_artifact_authority, AdoptedArtifactAuthorityV1
        ):
            raise Protocol26SchemaError(
                "CheckpointSelectionEntryV1.adopted_artifact_authority is invalid"
            )
        dependencies = _schema(
            sorted_unique_digests,
            self.dependency_artifact_key_ids,
            f"{label}.dependency_artifact_key_ids",
        )
        objects = _schema(
            sorted_unique_digests,
            self.copied_object_ids,
            f"{label}.copied_object_ids",
        )
        _schema(nonnegative_int, self.copied_byte_count, f"{label}.copied_byte_count")
        if self.rank is not None and not isinstance(self.rank, CheckpointRankV1):
            raise Protocol26SchemaError("CheckpointSelectionEntryV1.rank is invalid")
        _schema(safe_id, self.origin_run_id, f"{label}.origin_run_id")
        _schema(one_of, self.selection_reason, _CONTROLLED_REASONS, f"{label}.selection_reason")
        if self.origin_run_id != self.adopted_artifact_authority.source_run_id:
            raise Protocol26SchemaError(
                "CheckpointSelectionEntryV1 origin disagrees with adopted authority"
            )
        if kind == "workspace_checkpoint":
            if manifest_id is None or self.rank is None:
                raise Protocol26SchemaError(
                    "workspace checkpoint selection requires manifest and rank"
                )
        elif manifest_id is not None:
            raise Protocol26SchemaError(
                "direct parent selection cannot name a checkpoint manifest"
            )
        object.__setattr__(self, "dependency_artifact_key_ids", dependencies)
        object.__setattr__(self, "copied_object_ids", objects)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_event_payload(self, selection_bundle_id: str) -> dict[str, object]:
        _schema(
            digest_value,
            selection_bundle_id,
            "checkpoint_selection_bundle_id",
        )
        if self.source_kind != "workspace_checkpoint" or self.checkpoint_manifest_id is None:
            raise Protocol26SchemaError(
                "only workspace checkpoint selections emit checkpoint events"
            )
        return {
            "checkpoint_selection_bundle_id": selection_bundle_id,
            "checkpoint_manifest_id": self.checkpoint_manifest_id,
            "adopted_artifact_authority": self.adopted_artifact_authority.to_json_dict(),
            "origin_run_id": self.origin_run_id,
            "work_item_id": self.expected_work_item_id,
            "selection_reason": self.selection_reason,
        }

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "expected_work_item_id": self.expected_work_item_id,
            "source_kind": self.source_kind,
            "checkpoint_manifest_id": self.checkpoint_manifest_id,
            "adopted_artifact_authority": self.adopted_artifact_authority.to_json_dict(),
            "dependency_artifact_key_ids": list(self.dependency_artifact_key_ids),
            "copied_object_ids": list(self.copied_object_ids),
            "copied_byte_count": self.copied_byte_count,
            "rank": None if self.rank is None else self.rank.to_json_dict(),
            "origin_run_id": self.origin_run_id,
            "selection_reason": self.selection_reason,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointSelectionEntryV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        rank = raw["rank"]
        return cls(
            schema_version=raw["schema_version"],
            expected_work_item_id=raw["expected_work_item_id"],
            source_kind=raw["source_kind"],
            checkpoint_manifest_id=raw["checkpoint_manifest_id"],
            adopted_artifact_authority=AdoptedArtifactAuthorityV1.from_json_dict(
                raw["adopted_artifact_authority"]
            ),
            dependency_artifact_key_ids=raw["dependency_artifact_key_ids"],
            copied_object_ids=raw["copied_object_ids"],
            copied_byte_count=raw["copied_byte_count"],
            rank=None if rank is None else CheckpointRankV1.from_json_dict(rank),
            origin_run_id=raw["origin_run_id"],
            selection_reason=raw["selection_reason"],
        )


@dataclass(frozen=True, slots=True)
class CheckpointDispositionV1:
    schema_version: int
    checkpoint_manifest_id: str
    expected_work_item_id: str
    disposition: CheckpointDispositionKindV1
    reason: str
    rank: CheckpointRankV1 | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "checkpoint_manifest_id",
        "expected_work_item_id",
        "disposition",
        "reason",
        "rank",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(digest_value, self.checkpoint_manifest_id, f"{label}.checkpoint_manifest_id")
        _schema(digest_value, self.expected_work_item_id, f"{label}.expected_work_item_id")
        _schema(one_of, self.disposition, _DISPOSITIONS, f"{label}.disposition")
        _schema(one_of, self.reason, _CONTROLLED_REASONS, f"{label}.reason")
        if self.rank is not None and not isinstance(self.rank, CheckpointRankV1):
            raise Protocol26SchemaError("CheckpointDispositionV1.rank is invalid")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "checkpoint_manifest_id": self.checkpoint_manifest_id,
            "expected_work_item_id": self.expected_work_item_id,
            "disposition": self.disposition,
            "reason": self.reason,
            "rank": None if self.rank is None else self.rank.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointDispositionV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        rank = raw["rank"]
        return cls(
            schema_version=raw["schema_version"],
            checkpoint_manifest_id=raw["checkpoint_manifest_id"],
            expected_work_item_id=raw["expected_work_item_id"],
            disposition=raw["disposition"],
            reason=raw["reason"],
            rank=None if rank is None else CheckpointRankV1.from_json_dict(rank),
        )


@dataclass(frozen=True, slots=True)
class CheckpointSelectionBundleV1:
    schema_version: int
    source_snapshot_id: str
    partition_manifest_id: str
    target_layer: TargetLayerV1
    target_selection_id: str
    target_graph_id: str
    cache_generation_id: str
    selected: tuple[CheckpointSelectionEntryV1, ...]
    origin_manifest_hashes: tuple[str, ...]
    origin_event_prefix_hashes: tuple[str, ...]
    origin_ledger_prefix_hashes: tuple[str, ...]
    copied_receipt_ids: tuple[str, ...]
    copied_work_item_ids: tuple[str, ...]
    copied_object_ids: tuple[str, ...]
    copied_byte_count: int
    alternatives: tuple[CheckpointDispositionV1, ...]
    rejected: tuple[CheckpointDispositionV1, ...]
    quarantined: tuple[CheckpointDispositionV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "source_snapshot_id",
        "partition_manifest_id",
        "target_layer",
        "target_selection_id",
        "target_graph_id",
        "cache_generation_id",
        "selected",
        "origin_manifest_hashes",
        "origin_event_prefix_hashes",
        "origin_ledger_prefix_hashes",
        "copied_receipt_ids",
        "copied_work_item_ids",
        "copied_object_ids",
        "copied_byte_count",
        "alternatives",
        "rejected",
        "quarantined",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        for field in (
            "source_snapshot_id",
            "partition_manifest_id",
            "target_selection_id",
            "target_graph_id",
            "cache_generation_id",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        _schema(one_of, self.target_layer, _TARGET_LAYERS, f"{label}.target_layer")
        selected = _tuple_of(
            self.selected,
            CheckpointSelectionEntryV1,
            "CheckpointSelectionBundleV1.selected",
        )
        work_ids = tuple(item.expected_work_item_id for item in selected)
        if len(work_ids) != len(set(work_ids)):
            raise Protocol26SchemaError(
                "CheckpointSelectionBundleV1 selected work items must be unique"
            )
        artifact_keys = tuple(
            item.adopted_artifact_authority.artifact_key_id for item in selected
        )
        if len(artifact_keys) != len(set(artifact_keys)):
            raise Protocol26SchemaError(
                "CheckpointSelectionBundleV1 selected artifact keys must be unique"
            )
        for field in (
            "origin_manifest_hashes",
            "origin_event_prefix_hashes",
            "origin_ledger_prefix_hashes",
            "copied_receipt_ids",
            "copied_work_item_ids",
            "copied_object_ids",
        ):
            object.__setattr__(
                self,
                field,
                _schema(sorted_unique_digests, getattr(self, field), f"{label}.{field}"),
            )
        _schema(nonnegative_int, self.copied_byte_count, f"{label}.copied_byte_count")
        for field, expected_disposition in (
            ("alternatives", "not_selected"),
            ("rejected", "rejected"),
            ("quarantined", "quarantined"),
        ):
            values = _tuple_of(
                getattr(self, field),
                CheckpointDispositionV1,
                f"CheckpointSelectionBundleV1.{field}",
                sorted_by_identity=True,
            )
            if any(value.disposition != expected_disposition for value in values):
                raise Protocol26SchemaError(
                    f"CheckpointSelectionBundleV1.{field} has wrong disposition"
                )
            object.__setattr__(self, field, values)
        if tuple(sorted(work_ids)) != self.copied_work_item_ids:
            raise Protocol26SchemaError(
                "CheckpointSelectionBundleV1 copied work item inventory disagrees with selection"
            )
        union_objects = set().union(*(set(item.copied_object_ids) for item in selected))
        if union_objects != set(self.copied_object_ids):
            raise Protocol26SchemaError(
                "CheckpointSelectionBundleV1 copied object inventory disagrees with selection"
            )
        origin_evidence = {
            *self.origin_manifest_hashes,
            *self.origin_event_prefix_hashes,
            *self.origin_ledger_prefix_hashes,
        }
        if not origin_evidence <= set(self.copied_object_ids):
            raise Protocol26SchemaError(
                "CheckpointSelectionBundleV1 origin evidence is not copied"
            )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_snapshot_id": self.source_snapshot_id,
            "partition_manifest_id": self.partition_manifest_id,
            "target_layer": self.target_layer,
            "target_selection_id": self.target_selection_id,
            "target_graph_id": self.target_graph_id,
            "cache_generation_id": self.cache_generation_id,
            "selected": [item.to_json_dict() for item in self.selected],
            "origin_manifest_hashes": list(self.origin_manifest_hashes),
            "origin_event_prefix_hashes": list(self.origin_event_prefix_hashes),
            "origin_ledger_prefix_hashes": list(self.origin_ledger_prefix_hashes),
            "copied_receipt_ids": list(self.copied_receipt_ids),
            "copied_work_item_ids": list(self.copied_work_item_ids),
            "copied_object_ids": list(self.copied_object_ids),
            "copied_byte_count": self.copied_byte_count,
            "alternatives": [item.to_json_dict() for item in self.alternatives],
            "rejected": [item.to_json_dict() for item in self.rejected],
            "quarantined": [item.to_json_dict() for item in self.quarantined],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointSelectionBundleV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)

        def dispositions(field: str) -> tuple[CheckpointDispositionV1, ...]:
            values = raw[field]
            if not isinstance(values, (list, tuple)):
                raise Protocol26SchemaError(
                    f"CheckpointSelectionBundleV1.{field} must be an array"
                )
            return tuple(
                CheckpointDispositionV1.from_json_dict(item) for item in values
            )

        selected = raw["selected"]
        if not isinstance(selected, (list, tuple)):
            raise Protocol26SchemaError(
                "CheckpointSelectionBundleV1.selected must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            source_snapshot_id=raw["source_snapshot_id"],
            partition_manifest_id=raw["partition_manifest_id"],
            target_layer=raw["target_layer"],
            target_selection_id=raw["target_selection_id"],
            target_graph_id=raw["target_graph_id"],
            cache_generation_id=raw["cache_generation_id"],
            selected=tuple(
                CheckpointSelectionEntryV1.from_json_dict(item) for item in selected
            ),
            origin_manifest_hashes=raw["origin_manifest_hashes"],
            origin_event_prefix_hashes=raw["origin_event_prefix_hashes"],
            origin_ledger_prefix_hashes=raw["origin_ledger_prefix_hashes"],
            copied_receipt_ids=raw["copied_receipt_ids"],
            copied_work_item_ids=raw["copied_work_item_ids"],
            copied_object_ids=raw["copied_object_ids"],
            copied_byte_count=raw["copied_byte_count"],
            alternatives=dispositions("alternatives"),
            rejected=dispositions("rejected"),
            quarantined=dispositions("quarantined"),
        )


@dataclass(frozen=True, slots=True)
class RunManifestV5:
    schema_version: int
    engine: Literal["re-v2"]
    engine_protocol_version: Literal["2.6"]
    run_id: str
    created_at: str
    source_snapshot_id: str
    source_snapshot_kind: Literal["workspace-git-composite"]
    partition_manifest_id: str
    target_layer: TargetLayerV1
    layer_execution_contract: CatalogReferenceV1
    checkpoint_selection: CatalogReferenceV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "engine",
        "engine_protocol_version",
        "run_id",
        "created_at",
        "source_snapshot_id",
        "source_snapshot_kind",
        "partition_manifest_id",
        "target_layer",
        "layer_execution_contract",
        "checkpoint_selection",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 5, f"{label}.schema_version")
        _schema(literal, self.engine, "re-v2", f"{label}.engine")
        _schema(literal, self.engine_protocol_version, "2.6", f"{label}.engine_protocol_version")
        _schema(safe_id, self.run_id, f"{label}.run_id")
        _schema(utc_timestamp, self.created_at, f"{label}.created_at")
        _schema(digest_value, self.source_snapshot_id, f"{label}.source_snapshot_id")
        _schema(literal, self.source_snapshot_kind, "workspace-git-composite", f"{label}.source_snapshot_kind")
        _schema(digest_value, self.partition_manifest_id, f"{label}.partition_manifest_id")
        _schema(one_of, self.target_layer, _TARGET_LAYERS, f"{label}.target_layer")
        references = (self.layer_execution_contract, self.checkpoint_selection)
        if any(not isinstance(item, CatalogReferenceV1) for item in references):
            raise Protocol26SchemaError(
                "RunManifestV5 catalog references must be CatalogReferenceV1 values"
            )
        if (
            len({item.object_hash for item in references}) != len(references)
            or len({item.relative_path for item in references}) != len(references)
        ):
            raise Protocol26SchemaError("RunManifestV5 catalog references must be distinct")

    @property
    def run_manifest_id(self) -> str:
        return _identity(self.to_json_dict())

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
            "target_layer": self.target_layer,
            "layer_execution_contract": self.layer_execution_contract.to_json_dict(),
            "checkpoint_selection": self.checkpoint_selection.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "RunManifestV5":
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
            target_layer=raw["target_layer"],
            layer_execution_contract=CatalogReferenceV1.from_json_dict(
                raw["layer_execution_contract"]
            ),
            checkpoint_selection=CatalogReferenceV1.from_json_dict(
                raw["checkpoint_selection"]
            ),
        )


__all__ = (
    "CheckpointArtifactDependencyV1",
    "CheckpointDispositionV1",
    "CheckpointManifestV1",
    "CheckpointRankV1",
    "CheckpointSelectionBundleV1",
    "CheckpointSelectionEntryV1",
    "CheckpointSourceKindV1",
    "LayerExecutionContractV1",
    "LayerManifestV1",
    "Protocol26SchemaError",
    "RunManifestV5",
    "TargetLayerV1",
)

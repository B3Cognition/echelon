"""Pre-activation assembly for self-contained protocol-2.8 exhaustive children."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Mapping
import tempfile

from harness.prosaic_prompt_loader import ProsaicPromptLoader
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.partition import (
    PartitionAuthoritiesV1,
    WorkspacePartitionCatalogV1,
)
from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
from harness.re_v2.protocol_24.model import ParentLineageV1
from harness.re_v2.protocol_28.authority import (
    ValidatedL3ParentV1,
    build_l3_target_projections,
    build_parent_authority_bundle_v3,
)
from harness.re_v2.protocol_28.evidence import (
    EvidenceStagingPolicyV1,
    SnapshotEvidenceCatalogV1,
    stage_snapshot_evidence,
)
from harness.re_v2.protocol_28.executors import (
    build_l4_executor_catalog,
    canonical_exhaustive_response_schema_bytes,
)
from harness.re_v2.protocol_28.inputs import (
    Protocol28CreationInputs,
    protocol_28_required_authority_ids,
)
from harness.re_v2.protocol_28.model import (
    ExhaustiveBudgetPolicyV1,
    ExhaustiveRequestV1,
    ExhaustiveRunManifestV7,
)
from harness.re_v2.protocol_28.orchestration import DeepenOrchestrationRequestV1
from harness.re_v2.protocol_28.planning import (
    ExhaustiveSubjectV1,
    build_exhaustive_plan,
    build_exhaustive_subject_catalog,
)
from harness.re_v2.protocol_28.policies import build_initial_exhaustive_policy
from harness.re_v2.snapshot import (
    CapturedSnapshot,
    load_snapshot_manifest,
    validate_source_snapshot,
)
from harness.re_v2.workspace_snapshot import (
    ReV2WorkspaceSourceError,
    plan_clean_workspace_sources,
)


class Protocol28PreparationError(RuntimeError):
    """Raised before publication when L4 input closure cannot be authenticated."""


_NON_BEHAVIORAL_SUFFIXES = (".gif", ".ico", ".jpeg", ".jpg", ".png")
_ATTEMPT_POLICY_BYTES = canonical_json_bytes(
    {
        "identical_outcome_early_stop": 2,
        "producer_attempt_limit": 3,
        "producer_contract_retry_limit": 0,
        "schema_version": 1,
        "verifier_contract_retry_limit": 1,
    }
)


@dataclass(frozen=True, slots=True)
class Protocol28PreparationOptions:
    run_id: str
    created_at: str
    snapshot: CapturedSnapshot
    workspace_partition: WorkspacePartitionCatalogV1
    inherited_executor_contract_bytes: bytes
    lineage_root_run_id: str
    lineage_root_manifest_hash: str
    authority_objects: Mapping[str, bytes]
    token_limit: int | None = None
    active_ms_limit: int | None = None
    producer_agent_bytes: bytes | None = None
    verifier_agent_bytes: bytes | None = None
    attempt_policy_bytes: bytes = _ATTEMPT_POLICY_BYTES

    def __post_init__(self) -> None:
        if not isinstance(self.authority_objects, Mapping):
            raise Protocol28PreparationError("authority_objects must be a mapping")
        copied: dict[str, bytes] = {}
        for object_id, payload in self.authority_objects.items():
            if not isinstance(payload, bytes) or content_digest(payload) != object_id:
                raise Protocol28PreparationError(
                    f"preparation authority object hash mismatch: {object_id}"
                )
            copied[object_id] = payload
        object.__setattr__(
            self,
            "authority_objects",
            MappingProxyType(dict(sorted(copied.items()))),
        )


def load_protocol_28_role_bytes(workspace_root: Path) -> tuple[bytes, bytes]:
    """Load the two neutral Prosaic role contracts through the shared loader."""
    loader = ProsaicPromptLoader(Path(workspace_root).resolve())
    roles: list[bytes] = []
    for role_id in (
        "echelon.re-exhaustive-analyst",
        "echelon.re-exhaustive-verifier",
    ):
        artifact = loader.load_subagent(role_id)
        if artifact is None:
            raise Protocol28PreparationError(f"required Prosaic role is unavailable: {role_id}")
        roles.append(canonical_prosaic_agent_bytes(artifact))
    return roles[0], roles[1]


def prepare_protocol_28_request(
    workspace_root: Path,
    intent: DeepenOrchestrationRequestV1,
    eligible_l3: ValidatedL3ParentV1,
    options: Protocol28PreparationOptions,
) -> Protocol28CreationInputs:
    """Assemble a complete immutable L4 child input set without publishing it."""
    root = Path(workspace_root).resolve()
    if not isinstance(intent, DeepenOrchestrationRequestV1):
        raise Protocol28PreparationError("L4 preparation requires a durable intent request")
    if not isinstance(eligible_l3, ValidatedL3ParentV1):
        raise Protocol28PreparationError("L4 preparation requires validated L3 authority")
    if not isinstance(options, Protocol28PreparationOptions):
        raise Protocol28PreparationError("L4 preparation options are invalid")
    _validate_clean_exact_sources(root, options.snapshot)
    partition = options.workspace_partition
    if (
        options.snapshot.snapshot_id != intent.source_snapshot_id
        or partition.snapshot_id != intent.source_snapshot_id
        or partition.identity != eligible_l3.workspace_partition_catalog_id
        or eligible_l3.source_snapshot_id != intent.source_snapshot_id
        or eligible_l3.partition_manifest_id != intent.partition_manifest_id
    ):
        raise Protocol28PreparationError(
            "snapshot, partition, intent, and L3 authority do not match"
        )

    producer_agent, verifier_agent = _role_bytes(root, options)
    inherited_hash = content_digest(options.inherited_executor_contract_bytes)
    executors = build_l4_executor_catalog(
        inherited_executor_contract_hash=inherited_hash,
        producer_agent_contract_hash=content_digest(producer_agent),
        verifier_agent_contract_hash=content_digest(verifier_agent),
    )
    policy = build_initial_exhaustive_policy(
        producer_contract_hash=content_digest(producer_agent),
        verifier_contract_hash=content_digest(verifier_agent),
    )
    if (
        policy.identity != intent.exhaustive_policy_catalog_id
        or executors.identity != intent.executor_catalog_id
    ):
        raise Protocol28PreparationError(
            "intent policy or executor authority differs from installed L4 contracts"
        )

    selection = intent.selection
    l3 = build_l3_target_projections(eligible_l3, selection)
    parent = build_parent_authority_bundle_v3(eligible_l3, l3)
    evidence_policy = EvidenceStagingPolicyV1(
        1, policy.raw_shard_byte_limit, _NON_BEHAVIORAL_SUFFIXES
    )
    with tempfile.TemporaryDirectory(prefix="echelon-l4-evidence-") as temporary:
        evidence = stage_snapshot_evidence(
            options.snapshot,
            partition,
            selection,
            evidence_policy,
            ObjectStore(Path(temporary) / "objects"),
        )
    subjects = _build_evidence_subjects(parent, l3, evidence)
    plan = build_exhaustive_plan(parent, l3, evidence, subjects, policy, selection)
    _validate_initial_reservation(plan, producer_agent, verifier_agent, options)

    request = ExhaustiveRequestV1(
        1,
        selection.identity,
        parent.identity,
        l3.identity,
        evidence.identity,
        policy.identity,
        executors.identity,
        parent.source_snapshot_id,
        parent.partition_manifest_id,
    )
    manifest = ExhaustiveRunManifestV7(
        7,
        "re-v2",
        "2.8",
        "exhaustive-depth",
        ("selective-exhaustive-depth",),
        "L4",
        options.run_id,
        options.created_at,
        parent.source_snapshot_id,
        "workspace-git-composite",
        parent.partition_manifest_id,
        selection,
        ParentLineageV1(
            1,
            eligible_l3.run_id,
            eligible_l3.manifest_hash,
            eligible_l3.terminal_event_hash,
            options.lineage_root_run_id,
            options.lineage_root_manifest_hash,
        ),
        parent.workspace_partition_catalog_id,
        parent.inherited_artifact_policy_catalog_id,
        parent.identity,
        l3.identity,
        evidence.identity,
        request,
        plan.identity,
        policy.identity,
        executors.identity,
        content_digest(options.attempt_policy_bytes),
        ExhaustiveBudgetPolicyV1(
            1,
            options.token_limit,
            options.active_ms_limit,
            3,
            0,
            1,
        ),
    )
    candidates = dict(options.authority_objects)
    _add_authority(candidates, canonical_json_bytes(partition.to_json_dict()))
    _add_authority(candidates, canonical_json_bytes(evidence_policy.to_json_dict()))
    for payload in (
        options.inherited_executor_contract_bytes,
        producer_agent,
        verifier_agent,
        canonical_exhaustive_response_schema_bytes("producer"),
        canonical_exhaustive_response_schema_bytes("verifier"),
        options.attempt_policy_bytes,
    ):
        _add_authority(candidates, payload)
    _add_evidence_opaque_authority(candidates, partition, evidence)
    required = protocol_28_required_authority_ids(
        manifest, parent, l3, evidence, subjects, executors
    )
    missing = required - set(candidates)
    if missing:
        raise Protocol28PreparationError(
            "L4 parent authority closure is incomplete: " + ",".join(sorted(missing))
        )
    return Protocol28CreationInputs(
        manifest,
        parent,
        l3,
        evidence,
        subjects,
        policy,
        executors,
        plan,
        {object_id: candidates[object_id] for object_id in sorted(required)},
    )


def _role_bytes(
    workspace_root: Path,
    options: Protocol28PreparationOptions,
) -> tuple[bytes, bytes]:
    if options.producer_agent_bytes is None and options.verifier_agent_bytes is None:
        return load_protocol_28_role_bytes(workspace_root)
    if not isinstance(options.producer_agent_bytes, bytes) or not isinstance(
        options.verifier_agent_bytes, bytes
    ):
        raise Protocol28PreparationError(
            "producer and verifier role bytes must be supplied together"
        )
    return options.producer_agent_bytes, options.verifier_agent_bytes


def _validate_clean_exact_sources(root: Path, snapshot: CapturedSnapshot) -> None:
    try:
        validate_source_snapshot(snapshot)
        manifest = load_snapshot_manifest(snapshot)
        if manifest.components is None:
            raise Protocol28PreparationError("parent snapshot has no workspace components")
        declarations = tuple(
            SimpleNamespace(
                id=item.source_id,
                path=item.workspace_path,
                git_role=item.git_role,
            )
            for item in manifest.components
        )
        plan = plan_clean_workspace_sources(root, declarations)
    except ReV2WorkspaceSourceError as exc:
        raise Protocol28PreparationError(
            "sources must be clean before L4 deepening. Commit, stash including "
            "untracked files, or revert/remove the changes, then retry."
        ) from exc
    expected = {
        item.source_id: (item.workspace_path, item.repository_path, item.commit)
        for item in manifest.components
    }
    actual = {
        item.source_id: (item.workspace_path, item.repository_path, item.commit)
        for item in plan.sources
    }
    if actual != expected:
        raise Protocol28PreparationError(
            "source commits differ from the parent snapshot; restore the exact commits"
        )


def _build_evidence_subjects(parent, l3, evidence):  # type: ignore[no-untyped-def]
    targets = {
        (item.source_id, item.target_kind, item.target_id): item
        for item in l3.projections
    }
    subjects: list[ExhaustiveSubjectV1] = []
    for projection in evidence.projections:
        key = (projection.source_id, projection.target_kind, projection.target_id)
        target = targets[key]
        evidence_ids = tuple(
            sorted(
                {
                    *projection.primary_shard_ids,
                    *projection.primary_empty_receipt_ids,
                    *projection.primary_nontext_disposition_ids,
                }
            )
        )
        if not evidence_ids and not target.finding_ids:
            continue
        subjects.append(
            ExhaustiveSubjectV1(
                1,
                projection.target_kind,
                projection.source_id,
                projection.target_id,
                "authenticated-evidence",
                (
                    "public-surfaces"
                    if projection.target_kind == "domain"
                    else "source-composition",
                ),
                evidence_ids,
                target.finding_ids,
                tuple(
                    sorted(
                        {
                            target.candidate_authority_hash,
                            *target.relevant_l2_root_ids,
                        }
                    )
                ),
            )
        )
    return build_exhaustive_subject_catalog(
        parent.source_snapshot_id,
        parent.partition_manifest_id,
        l3.identity,
        tuple(subjects),
    )


def _validate_initial_reservation(plan, producer, verifier, options):  # type: ignore[no-untyped-def]
    ready = tuple(
        entry
        for target in plan.target_plans
        for entry in target.entries
        if not entry.planned_dependency_root_ids
    )
    if not ready:
        return
    minimum_tokens = min(
        max(
            entry.conservative_tokens,
            len(producer) + len(verifier) + entry.canonical_context_bytes + 2048,
            1,
        )
        * 2
        for entry in ready
    )
    if options.token_limit is not None and options.token_limit < minimum_tokens:
        raise Protocol28PreparationError(
            f"initial L4 token authorization cannot reserve one producer/verifier pair; minimum={minimum_tokens}"
        )
    if options.active_ms_limit is not None and options.active_ms_limit < 600_000:
        raise Protocol28PreparationError(
            "initial L4 active-time authorization cannot reserve one producer/verifier pair; minimum=600000"
        )


def _add_authority(values: dict[str, bytes], payload: bytes) -> None:
    object_id = content_digest(payload)
    existing = values.get(object_id)
    if existing is not None and existing != payload:
        raise Protocol28PreparationError("authority object digest collision")
    values[object_id] = payload


def _add_evidence_opaque_authority(
    values: dict[str, bytes],
    partition: WorkspacePartitionCatalogV1,
    evidence: SnapshotEvidenceCatalogV1,
) -> None:
    records = {
        content_digest(record.to_json_dict()): (source.source_id, record)
        for source in partition.sources
        for record in source.files
    }
    required_records = {
        item.file_record_hash
        for item in (
            *evidence.shards,
            *evidence.empty_receipts,
            *evidence.nontext_dispositions,
        )
    }
    for record_id in required_records:
        source_id, record = records[record_id]
        _add_authority(values, canonical_json_bytes(record.to_json_dict()))
        proof = canonical_json_bytes(
            {
                "file_record": record.to_json_dict(),
                "partition_catalog_id": partition.identity,
                "schema_version": 1,
                "source_id": source_id,
                "source_snapshot_id": partition.snapshot_id,
            }
        )
        _add_authority(values, proof)
    target_ids = {item.target_partition_id for item in evidence.projections}
    for source in partition.sources:
        if source.source_partition_id in target_ids:
            _add_authority(
                values,
                canonical_json_bytes(
                    source.partition_identity_input(
                        PartitionAuthoritiesV1(
                            partition.partitioner,
                            partition.ownership_policy,
                        )
                    ).to_json_dict()
                ),
            )
        for domain in source.domains:
            if domain.domain_partition_id not in target_ids:
                continue
            _add_authority(
                values,
                canonical_json_bytes(
                    {
                        "domain_key": domain.domain_key,
                        "owned_domain_relative_paths": list(
                            domain.owned_domain_relative_paths
                        ),
                        "ownership_policy": partition.ownership_policy.to_json_dict(),
                        "partitioner": partition.partitioner.to_json_dict(),
                        "source_relative_root": domain.source_relative_root,
                        "supporting_source_relative_paths": list(
                            domain.supporting_source_relative_paths
                        ),
                    }
                ),
            )


__all__ = (
    "Protocol28PreparationError",
    "Protocol28PreparationOptions",
    "load_protocol_28_role_bytes",
    "prepare_protocol_28_request",
)

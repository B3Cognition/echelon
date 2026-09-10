"""Pre-activation assembly for self-contained protocol-2.8 exhaustive children."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Mapping
import tempfile

from harness.prosaic_prompt_loader import ProsaicPromptLoader
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_activation import (
    ReviewedDiscoveryBundle, ReviewedSubjectCatalogV1,
    build_reviewed_discovery_catalog, load_reviewed_discovery,
)
import json
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.partition import (
    PartitionAuthoritiesV1,
    WorkspacePartitionCatalogV1,
)
from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
from harness.re_v2.protocol_24.model import ParentLineageV1
from harness.re_v2.protocol_28.authority import (
    ValidatedL3ParentV1,
    ValidatedL3ParentV2,
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
    SafeProtocol28CreationInputs,
    ReviewedProtocol28CreationInputs,
    protocol_28_required_authority_ids,
)
from harness.re_v2.protocol_28.context import (
    Protocol28ContextError,
    Protocol28RunContext,
    build_protocol_28_slice_context,
)
from harness.re_v2.protocol_28.model import (
    ExhaustiveBudgetPolicyV1,
    SafeExhaustiveRequestV1,
    SafeExhaustiveRunManifestV7,
    ReviewedExhaustiveRequestV1, ReviewedExhaustiveRunManifestV7,
)
from harness.re_v2.protocol_28.safe_evidence import (
    SafeLowerAuthorityCatalogV1,
    SafeSnapshotEvidenceCatalogV1,
    build_safe_lower_authority_catalog,
    build_safe_snapshot_evidence_catalog,
)
from harness.re_v2.protocol_28.orchestration import DeepenOrchestrationRequestV1
from harness.re_v2.protocol_28.planning import (
    ExhaustiveSubjectCatalogV1,
    ExhaustiveSubjectV1,
    _supporting_subjects_for_evidence,
    build_exhaustive_plan,
    build_exhaustive_subject_catalog,
    realize_slice,
    validate_exhaustive_plan_coverage,
)
from harness.re_v2.protocol_28.policies import (
    ExhaustivePolicyV2,
    build_initial_exhaustive_policy,
    build_repaired_exhaustive_policy,
)
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


_NON_BEHAVIORAL_SUFFIXES = (".gif", ".ico", ".jpeg", ".jpg", ".mp4", ".png")
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewedProtocol28PreparationOptions(Protocol28PreparationOptions):
    """Explicit opt-in to captured and independently reviewed planning authority."""
    reviewed_discoveries: tuple[ReviewedDiscoveryBundle, ...]


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
    eligible_l3: ValidatedL3ParentV1 | ValidatedL3ParentV2,
    options: Protocol28PreparationOptions,
) -> SafeProtocol28CreationInputs:
    """Assemble a complete immutable L4 child input set without publishing it."""
    root = Path(workspace_root).resolve()
    if not isinstance(intent, DeepenOrchestrationRequestV1):
        raise Protocol28PreparationError("L4 preparation requires a durable intent request")
    if not isinstance(eligible_l3, (ValidatedL3ParentV1, ValidatedL3ParentV2)):
        raise Protocol28PreparationError("L4 preparation requires validated L3 authority")
    if not isinstance(options, Protocol28PreparationOptions):
        raise Protocol28PreparationError("L4 preparation options are invalid")
    _validate_clean_exact_sources(root, options.snapshot)
    normalized_l3 = (
        eligible_l3.parent
        if isinstance(eligible_l3, ValidatedL3ParentV2)
        else eligible_l3
    )
    residual_debt_hash = (
        eligible_l3.residual_debt_acceptance_hash
        if isinstance(eligible_l3, ValidatedL3ParentV2)
        and eligible_l3.input_quality == "partial"
        else None
    )
    if (
        residual_debt_hash is not None
        and residual_debt_hash not in options.authority_objects
    ):
        raise Protocol28PreparationError(
            "L4 parent authority closure is incomplete: " + residual_debt_hash
        )
    partition = options.workspace_partition
    if (
        options.snapshot.snapshot_id != intent.source_snapshot_id
        or partition.snapshot_id != intent.source_snapshot_id
        or partition.identity != normalized_l3.workspace_partition_catalog_id
        or normalized_l3.source_snapshot_id != intent.source_snapshot_id
        or normalized_l3.partition_manifest_id != intent.partition_manifest_id
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
    if policy.identity != intent.exhaustive_policy_catalog_id:
        policy = build_repaired_exhaustive_policy(
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
    if isinstance(options, ReviewedProtocol28PreparationOptions):
        from harness.re_v2.protocol_28.authority import ReviewedParentAuthorityBundleV3
        # Freeze the receipt identity from validated L3 authority, never from the
        # caller's available blobs. Its hash binds finding/source/review lineage.
        parent = ReviewedParentAuthorityBundleV3(**parent.to_json_dict(),
            residual_debt_acceptance_id=residual_debt_hash)
    reviewed = None
    reviewed_catalog = None
    reviewed_objects = {}
    if isinstance(options, ReviewedProtocol28PreparationOptions):
        if not isinstance(policy, ExhaustivePolicyV2) or not options.reviewed_discoveries:
            raise Protocol28PreparationError('reviewed preparation requires repaired policy and authority')
        reviewed = []
        for bundle in options.reviewed_discoveries:
            local_catalog = ReviewedSubjectCatalogV1.from_json_dict(json.loads(bundle.objects[bundle.authority.subject_catalog_id]))
            raw = SnapshotEvidenceCatalogV1.from_json_dict(json.loads(bundle.objects[local_catalog.raw_evidence_catalog_id]))
            verified = load_reviewed_discovery(bundle.authority, bundle.objects, l3, raw)
            if reviewed and raw != reviewed_evidence:
                raise Protocol28PreparationError('reviewed sources bind different raw evidence catalogues')
            reviewed_evidence = raw
            reviewed.append(verified)
            reviewed_objects.update(verified.objects)
        reviewed = tuple(reviewed)
        reviewed_catalog = build_reviewed_discovery_catalog(reviewed)
    shard_byte_limit = policy.raw_shard_byte_limit
    while True:
        evidence_policy = EvidenceStagingPolicyV1(
            1, shard_byte_limit, _NON_BEHAVIORAL_SUFFIXES
        )
        if reviewed is not None:
            evidence = reviewed_evidence
            evidence_policy = EvidenceStagingPolicyV1.from_json_dict(json.loads(reviewed_objects[evidence.policy_id]))
        else:
            with tempfile.TemporaryDirectory(prefix="echelon-l4-evidence-") as temporary:
                evidence = stage_snapshot_evidence(
                    options.snapshot,
                    partition,
                    selection,
                    evidence_policy,
                    ObjectStore(Path(temporary) / "objects"),
                )
        safe_evidence = build_safe_snapshot_evidence_catalog(evidence)
        if reviewed is not None:
            subjects = build_exhaustive_subject_catalog(
                parent.source_snapshot_id, parent.partition_manifest_id, l3.identity,
                tuple(s for bundle in reviewed for s in bundle.subject_catalog.subjects),
            )
        else:
            subjects = _build_evidence_subjects(
                parent,
                l3,
                evidence,
                residual_debt_hash=residual_debt_hash,
                max_subject_bytes=max(policy.max_context_bytes // 32, 1_024),
            )
        plan = build_exhaustive_plan(parent, l3, evidence, subjects, policy, selection, reviewed=reviewed)
        if reviewed is not None and residual_debt_hash is not None:
            # Preserve accepted L3 debt without altering authenticated discovery subjects.
            plan = replace(plan, target_plans=_rebind_composition_dependencies(tuple(
                replace(target, entries=tuple(replace(entry, required_lower_authority_ids=tuple(sorted({
                    *entry.required_lower_authority_ids, residual_debt_hash}))) for entry in target.entries))
                for target in plan.target_plans)))
        safe_lower_authority = build_safe_lower_authority_catalog(
            options.authority_objects,
            _required_lower_authority_ids(plan),
        )
        try:
            plan = _bind_exact_context_sizes(
                plan,
                l3,
                evidence,
                subjects,
                policy,
                options.authority_objects,
                safe_evidence,
                safe_lower_authority,
                reviewed=reviewed,
            )
        except Protocol28PreparationError as exc:
            if (
                reviewed is not None
                or "one evidence shard requires" not in str(exc)
                or shard_byte_limit <= 1_024
            ):
                raise
            shard_byte_limit //= 2
            continue
        break
    _validate_initial_reservation(plan, producer_agent, verifier_agent, options)

    request_type = ReviewedExhaustiveRequestV1 if reviewed is not None else SafeExhaustiveRequestV1
    request = request_type(
        1,
        selection.identity,
        parent.identity,
        l3.identity,
        evidence.identity,
        policy.identity,
        executors.identity,
        parent.source_snapshot_id,
        parent.partition_manifest_id,
        plan.identity,
        safe_evidence.identity,
        safe_lower_authority.identity,
        **({'reviewed_discovery_catalog_id': reviewed_catalog.identity} if reviewed is not None else {}),
    )
    manifest_type = ReviewedExhaustiveRunManifestV7 if reviewed is not None else SafeExhaustiveRunManifestV7
    manifest = manifest_type(
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
            normalized_l3.run_id,
            normalized_l3.manifest_hash,
            normalized_l3.terminal_event_hash,
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
        safe_evidence.identity,
        safe_lower_authority.identity,
        **({'reviewed_discovery_catalog_id': reviewed_catalog.identity} if reviewed is not None else {}),
    )
    candidates = dict(options.authority_objects)
    candidates.update(reviewed_objects)
    _add_authority(candidates, canonical_json_bytes(partition.to_json_dict()))
    _add_authority(candidates, canonical_json_bytes(evidence_policy.to_json_dict()))
    partition_manifest_bytes = _partition_manifest_authority_bytes(options.snapshot)
    if content_digest(partition_manifest_bytes) != parent.partition_manifest_id:
        raise Protocol28PreparationError(
            "snapshot partition authority differs from the L3 parent"
        )
    _add_authority(candidates, partition_manifest_bytes)
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
        manifest, parent, l3, evidence, subjects, executors, reviewed_discovery=reviewed_catalog,
    )
    missing = required - set(candidates)
    if missing:
        raise Protocol28PreparationError(
            "L4 parent authority closure is incomplete: " + ",".join(sorted(missing))
        )
    creation_type = ReviewedProtocol28CreationInputs if reviewed is not None else SafeProtocol28CreationInputs
    created = creation_type(
        manifest,
        parent,
        l3,
        evidence,
        subjects,
        policy,
        executors,
        plan,
        {object_id: candidates[object_id] for object_id in sorted(required)},
        safe_evidence,
        safe_lower_authority,
        **({'reviewed_discovery_catalog': reviewed_catalog} if reviewed is not None else {}),
    )
    _validate_provider_context_bounds(created)
    return created


def _validate_provider_context_bounds(inputs: Protocol28CreationInputs) -> None:
    """Prove the exact published producer payloads fit before child creation."""
    sizing_context = Protocol28RunContext(  # type: ignore[arg-type]
        None,
        inputs,
        None,
        None,
        None,
        None,
        None,
    )
    try:
        for target_plan in inputs.exhaustive_plan.target_plans:
            for entry in target_plan.entries:
                spec = realize_slice(
                    entry,
                    {
                        dependency_id: dependency_id
                        for dependency_id in entry.planned_dependency_root_ids
                    },
                )
                build_protocol_28_slice_context(
                    sizing_context,
                    target_plan,
                    entry,
                    spec,
                    role="producer",
                )
    except Protocol28ContextError as exc:
        raise Protocol28PreparationError(
            f"unsplittable exact provider context: {exc}"
        ) from exc


def _required_lower_authority_ids(plan) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    """Return the exact inherited authority set that any plan slice can expose."""
    return tuple(
        sorted(
            {
                object_id
                for target in plan.target_plans
                for entry in target.entries
                for object_id in entry.required_lower_authority_ids
            }
        )
    )


def _bind_exact_context_sizes(
    plan,  # type: ignore[no-untyped-def]
    l3,  # type: ignore[no-untyped-def]
    evidence,  # type: ignore[no-untyped-def]
    subjects,  # type: ignore[no-untyped-def]
    policy,  # type: ignore[no-untyped-def]
    authority_objects: Mapping[str, bytes],
    safe_evidence: SafeSnapshotEvidenceCatalogV1 | None = None,
    safe_lower_authority: SafeLowerAuthorityCatalogV1 | None = None,
    *, reviewed=None,
):  # type: ignore[no-untyped-def]
    """Bind plan accounting to the byte-identical producer payload."""
    from harness.re_v2.protocol_28.context import _Protocol28SizingInputs, _Protocol28SizingContext
    sizing_inputs = _Protocol28SizingInputs(
        l3_projection_catalog=l3,
        snapshot_evidence_catalog=evidence,
        exhaustive_subject_catalog=subjects,
        exhaustive_policy=policy,
        authority_objects=authority_objects,
        reviewed_discoveries=reviewed,
    )
    sizing_context = _Protocol28SizingContext(sizing_inputs, plan, safe_evidence, safe_lower_authority)
    current = _split_oversized_context_entries(
        plan,
        evidence,
        policy.max_context_bytes,
        sizing_context,
    )
    for _iteration in range(8):
        target_plans = []
        for target_plan in current.target_plans:
            entries = []
            for entry in target_plan.entries:
                measured, size = _measure_context_entry(
                    sizing_context,
                    target_plan,
                    entry,
                )
                if size > policy.max_context_bytes:
                    raise Protocol28PreparationError(
                        "unsplittable exact provider context: "
                        f"source={entry.source_id} target={entry.target_id} "
                        f"category={entry.category_id} ordinal={entry.ordinal} "
                        f"actual={size} maximum={policy.max_context_bytes}"
                    )
                entries.append(measured)
            target_plans.append(replace(target_plan, entries=tuple(entries)))
        updated = replace(
            current,
            target_plans=_rebind_composition_dependencies(tuple(target_plans)),
        )
        if updated == current:
            validate_exhaustive_plan_coverage(updated, subjects, evidence, policy, reviewed=reviewed)
            return updated
        current = updated
    raise Protocol28PreparationError("exact provider context sizing did not converge")


def _measure_context_entry(
    sizing_context: Protocol28RunContext,
    target_plan,  # type: ignore[no-untyped-def]
    entry,  # type: ignore[no-untyped-def]
):  # type: ignore[no-untyped-def]
    """Return the fixed-point entry and exact serialized producer byte count."""
    from harness.re_v2.protocol_28.context import _serialize_protocol_28_slice_context
    current = entry
    for _iteration in range(8):
        # Stable entries use their real target authority so measured bytes,
        # not just their length, match eventual public rendering. Transient
        # split/fixed-point candidates do not yet belong to that target.
        sizing_target = target_plan if current in target_plan.entries else replace(target_plan, entries=(current,))
        spec = realize_slice(
            current,
            {
                dependency_id: dependency_id
                for dependency_id in current.planned_dependency_root_ids
            },
        )
        encoded = _serialize_protocol_28_slice_context(
            sizing_context,
            sizing_target,
            current,
            spec,
            role="producer",
            _enforce_bound=False,
        )
        updated = replace(
            current,
            canonical_context_bytes=len(encoded),
            conservative_tokens=len(encoded),
        )
        if updated == current:
            return updated, len(encoded)
        current = updated
    raise Protocol28PreparationError("exact provider context sizing did not converge")


def _split_oversized_context_entries(
    plan,  # type: ignore[no-untyped-def]
    evidence,  # type: ignore[no-untyped-def]
    maximum: int,
    sizing_context: Protocol28RunContext,
):  # type: ignore[no-untyped-def]
    """Split evidence bins until each byte-identical producer payload fits."""
    reviewed = getattr(sizing_context, '_reviewed_discoveries', None)
    reviewed_owner_ids = ({raw_id: row.subject_id for bundle in reviewed
        for row in bundle.inventory_assessments if row.disposition == 'owned'
        for raw_id in row.raw_evidence_ids} if reviewed is not None else None)
    record_for = {
        **{item.shard_id: item.file_record_hash for item in evidence.shards},
        **{item.receipt_id: item.file_record_hash for item in evidence.empty_receipts},
        **{
            item.disposition_id: item.file_record_hash
            for item in evidence.nontext_dispositions
        },
    }
    target_plans = []
    for target_plan in plan.target_plans:
        expanded = []
        for entry in target_plan.entries:
            measured, size = _measure_context_entry(
                sizing_context,
                target_plan,
                entry,
            )
            if size <= maximum:
                expanded.append(measured)
                continue
            if entry.assigned_finding_ids:
                raise Protocol28PreparationError(
                    "finding closure cannot be split away from its required evidence: "
                    f"source={entry.source_id} target={entry.target_id} "
                    f"actual={size} maximum={maximum}; "
                    "provide a narrower evidence-to-finding mapping or a bounded synthesis stage"
                )
            subjects = (
                sizing_context.inputs.exhaustive_subject_catalog
                if isinstance(sizing_context.inputs.exhaustive_policy, ExhaustivePolicyV2)
                else None
            )
            policy = sizing_context.inputs.exhaustive_policy

            def chunk_fits(candidate, size: int) -> bool:  # type: ignore[no-untyped-def]
                return size <= maximum and (
                    subjects is None or (
                        len(candidate.primary_subject_ids) <= policy.max_primary_subjects
                        and len(candidate.supporting_subject_ids) <= policy.max_supporting_subjects
                        and len(candidate.primary_source_record_ids) <= policy.max_primary_records
                        and len(candidate.supporting_source_record_ids) <= policy.max_supporting_records
                    )
                )

            evidence_ids = (
                tuple(sorted(set(entry.primary_snapshot_evidence_ids + entry.supporting_snapshot_evidence_ids)))
                if subjects is not None else entry.primary_snapshot_evidence_ids
            )
            if len(evidence_ids) < 2:
                raise Protocol28PreparationError(
                    "unsplittable exact provider context: "
                    f"source={entry.source_id} target={entry.target_id} "
                    f"category={entry.category_id} ordinal={entry.ordinal} "
                    f"actual={size} maximum={maximum}"
                )
            first_for_record: dict[str, str] = {}
            for evidence_id in evidence_ids:
                record_id = record_for[evidence_id]
                if record_id in entry.primary_source_record_ids:
                    first_for_record.setdefault(record_id, evidence_id)

            chunks: list[tuple[str, ...]] = []
            current_ids: tuple[str, ...] = ()
            for evidence_id in evidence_ids:
                tentative = (*current_ids, evidence_id)
                candidate = _entry_for_evidence_chunk(
                    entry,
                    tentative,
                    first_for_record,
                    first_chunk=not chunks,
                    ordinal=entry.ordinal + len(chunks),
                    subjects=subjects,
                    record_for=record_for,
                    reviewed_owner_ids=reviewed_owner_ids,
                )
                _candidate, candidate_size = _measure_context_entry(
                    sizing_context,
                    target_plan,
                    candidate,
                )
                if chunk_fits(candidate, candidate_size):
                    current_ids = tentative
                    continue
                if not current_ids:
                    raise Protocol28PreparationError(
                        "unsplittable exact provider context: one evidence shard "
                        f"requires {candidate_size} bytes; maximum={maximum}"
                    )
                chunks.append(current_ids)
                current_ids = (evidence_id,)
                candidate = _entry_for_evidence_chunk(
                    entry,
                    current_ids,
                    first_for_record,
                    first_chunk=False,
                    ordinal=entry.ordinal + len(chunks),
                    subjects=subjects,
                    record_for=record_for,
                    reviewed_owner_ids=reviewed_owner_ids,
                )
                _candidate, candidate_size = _measure_context_entry(
                    sizing_context,
                    target_plan,
                    candidate,
                )
                if not chunk_fits(candidate, candidate_size):
                    raise Protocol28PreparationError(
                        "unsplittable exact provider context: one evidence shard exceeds "
                        f"byte or subject/record bounds; bytes={candidate_size} maximum={maximum}"
                    )
            chunks.append(current_ids)
            for index, chunk in enumerate(chunks):
                candidate = _entry_for_evidence_chunk(
                    entry,
                    chunk,
                    first_for_record,
                    first_chunk=index == 0,
                    ordinal=entry.ordinal + index,
                    subjects=subjects,
                    record_for=record_for,
                    reviewed_owner_ids=reviewed_owner_ids,
                )
                measured, _size = _measure_context_entry(
                    sizing_context,
                    target_plan,
                    candidate,
                )
                expanded.append(measured)

        counters: dict[str, int] = {}
        renumbered = []
        for entry in expanded:
            ordinal = counters.get(entry.category_id, 0)
            counters[entry.category_id] = ordinal + 1
            renumbered.append(replace(entry, ordinal=ordinal))
        target_plans.append(replace(target_plan, entries=tuple(renumbered)))
    return replace(
        plan,
        target_plans=_rebind_composition_dependencies(tuple(target_plans)),
    )


def _rebind_composition_dependencies(target_plans):  # type: ignore[no-untyped-def]
    domain_roots: dict[str, tuple[str, ...]] = {}
    for target_plan in target_plans:
        if target_plan.target_kind == "domain":
            domain_roots.setdefault(target_plan.source_id, ())
            domain_roots[target_plan.source_id] = tuple(
                sorted((*domain_roots[target_plan.source_id], target_plan.identity))
            )
    rebound = []
    for target_plan in target_plans:
        if target_plan.target_kind != "source":
            rebound.append(target_plan)
            continue
        dependencies = domain_roots.get(target_plan.source_id, ())
        entries = tuple(
            replace(
                entry,
                planned_dependency_root_ids=(
                    dependencies
                    if entry.category_id == "source-composition"
                    else entry.planned_dependency_root_ids
                ),
            )
            for entry in target_plan.entries
        )
        rebound.append(replace(target_plan, entries=entries))
    return tuple(rebound)


def _entry_for_evidence_chunk(
    entry,  # type: ignore[no-untyped-def]
    evidence_ids: tuple[str, ...],
    first_for_record: Mapping[str, str],
    *,
    first_chunk: bool,
    ordinal: int,
    subjects: ExhaustiveSubjectCatalogV1 | None = None,
    record_for: Mapping[str, str] | None = None,
    reviewed_owner_ids: Mapping[str, str] | None = None,
):  # type: ignore[no-untyped-def]
    evidence_set = set(evidence_ids)
    records = tuple(
        record_id
        for record_id in entry.primary_source_record_ids
        if first_for_record.get(record_id) in evidence_set
    )
    chunk = replace(
        entry,
        ordinal=ordinal,
        primary_subject_ids=entry.primary_subject_ids if first_chunk else (),
        supporting_subject_ids=(
            entry.supporting_subject_ids
            if first_chunk
            else tuple(
                sorted(
                    {
                        *entry.supporting_subject_ids,
                        *entry.primary_subject_ids,
                    }
                )
            )
        ),
        primary_source_record_ids=records,
        primary_snapshot_evidence_ids=evidence_ids,
        assigned_finding_ids=entry.assigned_finding_ids if first_chunk else (),
        canonical_context_bytes=0,
        conservative_tokens=0,
    )
    if subjects is None:
        return chunk
    if record_for is None:
        raise Protocol28PreparationError("grounded evidence split requires record authority")
    attached = set(entry.primary_subject_ids + entry.supporting_subject_ids)
    available_subjects = tuple(subject for subject in subjects.subjects if subject.identity in attached)
    primary_subjects = tuple(
        subject for subject in available_subjects if subject.identity in chunk.primary_subject_ids
    )
    required_owner_ids = {reviewed_owner_ids[item] for item in evidence_ids
        if reviewed_owner_ids is not None and item in entry.primary_snapshot_evidence_ids}
    if not required_owner_ids.issubset(attached):
        raise Protocol28PreparationError('exact evidence split lost reviewed primary owner')
    required_owners = tuple(subject for subject in available_subjects
        if subject.identity in required_owner_ids and subject not in primary_subjects)
    supporting_subjects = tuple(sorted((*required_owners, *_supporting_subjects_for_evidence(
        available_subjects, (*primary_subjects, *required_owners), evidence_ids,
    )), key=lambda subject: subject.identity))
    return replace(
        chunk,
        supporting_subject_ids=tuple(subject.identity for subject in supporting_subjects),
        primary_snapshot_evidence_ids=tuple(
            item for item in evidence_ids if item in entry.primary_snapshot_evidence_ids
        ),
        supporting_snapshot_evidence_ids=tuple(
            item for item in evidence_ids if item in entry.supporting_snapshot_evidence_ids
        ),
        supporting_source_record_ids=tuple(sorted({record_for[item] for item in evidence_ids} - set(records))),
    )


def _partition_manifest_authority_bytes(snapshot: CapturedSnapshot) -> bytes:
    manifest = load_snapshot_manifest(snapshot)
    if manifest.components is None:
        raise Protocol28PreparationError(
            "L4 snapshot has no composite partition authority"
        )
    return canonical_json_bytes(
        {
            "partition_protocol": "re-v2-partition-v2",
            "source_snapshot_id": manifest.snapshot_id,
            "sources": [
                {
                    "git_role": item.git_role,
                    "id": item.source_id,
                    "path": item.workspace_path,
                }
                for item in manifest.components
            ],
        }
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


def _build_evidence_subjects(
    parent,
    l3,
    evidence,
    *,
    residual_debt_hash: str | None = None,
    max_subject_bytes: int | None = None,
):  # type: ignore[no-untyped-def]
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
        subjects.extend(
            _chunk_evidence_subject(
                target_kind=projection.target_kind,
                source_id=projection.source_id,
                target_id=projection.target_id,
                category_id=(
                    "public-surfaces"
                    if projection.target_kind == "domain"
                    else "source-composition"
                ),
                evidence_ids=evidence_ids,
                finding_ids=target.finding_ids,
                lower_authority_ids=tuple(
                    sorted(
                        {
                            target.candidate_authority_hash,
                            *target.relevant_l2_root_ids,
                            *(() if residual_debt_hash is None else (residual_debt_hash,)),
                        }
                    )
                ),
                max_subject_bytes=max_subject_bytes,
            )
        )
    return build_exhaustive_subject_catalog(
        parent.source_snapshot_id,
        parent.partition_manifest_id,
        l3.identity,
        tuple(subjects),
    )


def _chunk_evidence_subject(
    *,
    target_kind: str,
    source_id: str,
    target_id: str,
    category_id: str,
    evidence_ids: tuple[str, ...],
    finding_ids: tuple[str, ...],
    lower_authority_ids: tuple[str, ...],
    max_subject_bytes: int | None,
) -> tuple[ExhaustiveSubjectV1, ...]:
    """Keep generated subject indexes small enough for exact L4 contexts."""

    def subject(
        subject_id: str,
        evidence: tuple[str, ...],
        findings: tuple[str, ...],
    ) -> ExhaustiveSubjectV1:
        return ExhaustiveSubjectV1(
            1,
            target_kind,  # type: ignore[arg-type]
            source_id,
            target_id,
            subject_id,
            (category_id,),
            evidence,
            findings,
            lower_authority_ids,
        )

    complete = subject("authenticated-evidence", evidence_ids, finding_ids)
    if (
        max_subject_bytes is None
        or len(canonical_json_bytes(complete.to_json_dict())) <= max_subject_bytes
    ):
        return (complete,)

    chunks: list[ExhaustiveSubjectV1] = []
    pending: list[tuple[str, str]] = [
        *(('finding', item) for item in finding_ids),
        *(('evidence', item) for item in evidence_ids),
    ]
    current_evidence: tuple[str, ...] = ()
    current_findings: tuple[str, ...] = ()
    for item_kind, item_id in pending:
        candidate_evidence = (
            tuple(sorted((*current_evidence, item_id)))
            if item_kind == "evidence"
            else current_evidence
        )
        candidate_findings = (
            tuple(sorted((*current_findings, item_id)))
            if item_kind == "finding"
            else current_findings
        )
        candidate = subject(
            f"authenticated-evidence-{len(chunks):06d}",
            candidate_evidence,
            candidate_findings,
        )
        if len(canonical_json_bytes(candidate.to_json_dict())) <= max_subject_bytes:
            current_evidence = candidate_evidence
            current_findings = candidate_findings
            continue
        if not current_evidence and not current_findings:
            raise Protocol28PreparationError(
                "unsplittable L4 subject authority exceeds policy"
            )
        chunks.append(
            subject(
                f"authenticated-evidence-{len(chunks):06d}",
                current_evidence,
                current_findings,
            )
        )
        current_evidence = (item_id,) if item_kind == "evidence" else ()
        current_findings = (item_id,) if item_kind == "finding" else ()
    if current_evidence or current_findings:
        chunks.append(
            subject(
                f"authenticated-evidence-{len(chunks):06d}",
                current_evidence,
                current_findings,
            )
        )
    return tuple(chunks)


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
        (source.source_id, record.source_relative_path): record
        for source in partition.sources
        for record in source.files
    }
    required_records = {
        (item.source_id, item.source_relative_path): item.file_record_hash
        for item in (
            *evidence.shards,
            *evidence.empty_receipts,
            *evidence.nontext_dispositions,
        )
    }
    for (source_id, source_relative_path), record_id in required_records.items():
        record = records[(source_id, source_relative_path)]
        if content_digest(record.to_json_dict()) != record_id:
            raise Protocol28PreparationError(
                "snapshot evidence file record differs from partition authority"
            )
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

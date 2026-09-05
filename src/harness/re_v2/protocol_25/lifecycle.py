"""Pure schema-4 lifecycle identities and immutable guidance authority."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from typing import Literal

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    safe_id,
    sorted_unique_digests,
)
from harness.re_v2.protocol_24.model import SelectionScopeV1

from .guidance import (
    GuidancePolicyV1,
    build_guidance_directive,
    custom_guidance_policy,
    normalize_guidance_answer,
)


RunModeV1 = Literal[
    "new-audit-epoch",
    "audit-successor",
    "closure-successor",
]
_RUN_MODES = frozenset(
    {"new-audit-epoch", "audit-successor", "closure-successor"}
)


@dataclass(frozen=True, slots=True)
class PreparedProtocol25Creation:
    """Immutable schema-4 child authority prepared before workspace mutation."""

    parent: object
    manifest: object
    inputs: object
    graph: object


@dataclass(frozen=True, slots=True)
class ExportedProtocol25Parent:
    """Authenticated schema-4 parent closure retained for one child creation."""

    parent: object
    manifest: object
    inputs: object
    accepted_parent: Mapping[str, object]
    immutable_objects: Mapping[str, bytes]
    recovered: object
    ledger_history: tuple[object, ...]
    source_context: object

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "accepted_parent",
            MappingProxyType(dict(sorted(self.accepted_parent.items()))),
        )
        object.__setattr__(
            self,
            "immutable_objects",
            MappingProxyType(dict(sorted(self.immutable_objects.items()))),
        )


def guidance_id_for(
    *,
    parent_manifest_hash: str,
    parent_terminal_event_hash: str,
    accepted_audit_candidate_hashes: tuple[str, ...],
    unresolved_audit_target_ids: tuple[str, ...],
    audit_epoch_id: str | None,
    closure_root_hash: str | None,
    unresolved_finding_ids: tuple[str, ...],
    answer: str,
) -> str:
    """Hash guidance with the exact blocked authority it is allowed to affect."""
    return content_digest(
        _guidance_payload(
            parent_manifest_hash=parent_manifest_hash,
            parent_terminal_event_hash=parent_terminal_event_hash,
            accepted_audit_candidate_hashes=accepted_audit_candidate_hashes,
            unresolved_audit_target_ids=unresolved_audit_target_ids,
            audit_epoch_id=audit_epoch_id,
            closure_root_hash=closure_root_hash,
            unresolved_finding_ids=unresolved_finding_ids,
            policy=custom_guidance_policy(answer),
        )
    )


def _guidance_payload(
    *,
    parent_manifest_hash: str,
    parent_terminal_event_hash: str,
    accepted_audit_candidate_hashes: tuple[str, ...],
    unresolved_audit_target_ids: tuple[str, ...],
    audit_epoch_id: str | None,
    closure_root_hash: str | None,
    unresolved_finding_ids: tuple[str, ...],
    policy: GuidancePolicyV1,
) -> dict[str, object]:
    """Return the canonical guidance authority before byte publication."""
    return build_guidance_directive(
        policy=policy,
        parent_manifest_hash=parent_manifest_hash,
        parent_terminal_event_hash=parent_terminal_event_hash,
        accepted_audit_candidate_hashes=accepted_audit_candidate_hashes,
        unresolved_audit_target_ids=unresolved_audit_target_ids,
        audit_epoch_id=audit_epoch_id,
        closure_root_hash=closure_root_hash,
        unresolved_finding_ids=unresolved_finding_ids,
    ).to_json_dict()


def semantic_request_id_v2(
    *,
    lineage_root_run_id: str,
    lineage_root_manifest_hash: str,
    direct_parent_run_id: str,
    direct_parent_manifest_hash: str,
    direct_parent_terminal_event_hash: str,
    source_snapshot_id: str,
    partition_manifest_id: str,
    selection: SelectionScopeV1,
    run_mode: RunModeV1,
    artifact_policy_hash: str,
    executor_contract_hash: str,
    audit_policy_hash: str,
    accepted_audit_target_ids: tuple[str, ...],
    frozen_audit_epoch_id: str | None,
    closure_root_hash: str | None,
    guidance_hash: str | None,
) -> str:
    """Identify an exact L3 request independently of mutable authorization."""
    if not isinstance(selection, SelectionScopeV1):
        raise ValueError("semantic request requires SelectionScopeV1")
    if run_mode not in _RUN_MODES:
        raise ValueError("semantic request run mode is unsupported")
    try:
        safe_id(lineage_root_run_id, "lineage root run ID")
        safe_id(direct_parent_run_id, "direct parent run ID")
        for field, value in (
            ("lineage root manifest", lineage_root_manifest_hash),
            ("direct parent manifest", direct_parent_manifest_hash),
            ("direct parent terminal event", direct_parent_terminal_event_hash),
            ("source snapshot", source_snapshot_id),
            ("partition manifest", partition_manifest_id),
            ("artifact policy", artifact_policy_hash),
            ("executor contract", executor_contract_hash),
            ("audit policy", audit_policy_hash),
        ):
            digest_value(value, field)
        targets = sorted_unique_digests(
            accepted_audit_target_ids,
            "accepted audit target IDs",
        )
        for field, value in (
            ("frozen audit epoch", frozen_audit_epoch_id),
            ("closure root", closure_root_hash),
            ("guidance", guidance_hash),
        ):
            if value is not None:
                digest_value(value, field)
    except Protocol22SchemaError as exc:
        raise ValueError(str(exc)) from exc
    if run_mode == "new-audit-epoch":
        if targets or any(
            value is not None
            for value in (frozen_audit_epoch_id, closure_root_hash, guidance_hash)
        ):
            raise ValueError("new audit epoch cannot bind successor-only authority")
    elif run_mode == "audit-successor":
        if (
            guidance_hash is None
            or frozen_audit_epoch_id is not None
            or closure_root_hash is not None
        ):
            raise ValueError("audit successor authority is inconsistent")
    elif guidance_hash is None or frozen_audit_epoch_id is None:
        raise ValueError("closure successor authority is incomplete")
    return content_digest(
        {
            "accepted_audit_target_ids": list(targets),
            "artifact_policy_hash": artifact_policy_hash,
            "audit_policy_hash": audit_policy_hash,
            "closure_root_hash": closure_root_hash,
            "direct_parent_manifest_hash": direct_parent_manifest_hash,
            "direct_parent_run_id": direct_parent_run_id,
            "direct_parent_terminal_event_hash": direct_parent_terminal_event_hash,
            "executor_contract_hash": executor_contract_hash,
            "frozen_audit_epoch_id": frozen_audit_epoch_id,
            "guidance_hash": guidance_hash,
            "lineage_root_manifest_hash": lineage_root_manifest_hash,
            "lineage_root_run_id": lineage_root_run_id,
            "partition_manifest_id": partition_manifest_id,
            "run_mode": run_mode,
            "schema_version": 2,
            "selection": selection.to_json_dict(),
            "source_snapshot_id": source_snapshot_id,
            "target_layer": "L3",
        }
    )


def semantic_request_id_v3(
    *,
    engine_protocol_version: str,
    lineage_root_run_id: str,
    lineage_root_manifest_hash: str,
    direct_parent_run_id: str,
    direct_parent_manifest_hash: str,
    direct_parent_terminal_event_hash: str,
    source_snapshot_id: str,
    partition_manifest_id: str,
    selection: SelectionScopeV1,
    run_mode: RunModeV1,
    artifact_policy_hash: str,
    executor_contract_hash: str,
    audit_policy_hash: str,
    accepted_audit_target_ids: tuple[str, ...],
    frozen_audit_epoch_id: str | None,
    closure_root_hash: str | None,
    guidance_hash: str | None,
) -> str:
    """Identify a versioned L3 request while preserving schema-2 identity."""
    if engine_protocol_version not in {"2.5", "2.5.1"}:
        raise ValueError("semantic request protocol is unsupported")
    legacy_request_id = semantic_request_id_v2(
        lineage_root_run_id=lineage_root_run_id,
        lineage_root_manifest_hash=lineage_root_manifest_hash,
        direct_parent_run_id=direct_parent_run_id,
        direct_parent_manifest_hash=direct_parent_manifest_hash,
        direct_parent_terminal_event_hash=direct_parent_terminal_event_hash,
        source_snapshot_id=source_snapshot_id,
        partition_manifest_id=partition_manifest_id,
        selection=selection,
        run_mode=run_mode,
        artifact_policy_hash=artifact_policy_hash,
        executor_contract_hash=executor_contract_hash,
        audit_policy_hash=audit_policy_hash,
        accepted_audit_target_ids=accepted_audit_target_ids,
        frozen_audit_epoch_id=frozen_audit_epoch_id,
        closure_root_hash=closure_root_hash,
        guidance_hash=guidance_hash,
    )
    return content_digest(
        {
            "engine_protocol_version": engine_protocol_version,
            "legacy_semantic_request_id": legacy_request_id,
            "schema_version": 3,
            "target_layer": "L3",
        }
    )


def find_exact_protocol_25_child(
    workspace_root: Path,
    semantic_request_id: str,
) -> Path | None:
    """Return an exact immutable semantic request regardless of mutable state."""
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    from .model import RunManifestV4

    try:
        digest_value(semantic_request_id, "semantic request ID")
    except Protocol22SchemaError as exc:
        raise ValueError(str(exc)) from exc
    runs = workspace_root.resolve() / "runs"
    if not runs.exists():
        return None
    if runs.is_symlink() or not runs.is_dir():
        raise ValueError("workspace runs path is unsafe")
    for candidate in sorted(runs.iterdir(), key=lambda path: path.name):
        if (
            not candidate.name.startswith("re-")
            or candidate.is_symlink()
            or not candidate.is_dir()
            or not (candidate / "v2" / "run.json").is_file()
        ):
            continue
        manifest = load_run_manifest(candidate)
        candidate_manifest = manifest
        if isinstance(manifest, RunManifestV5) and manifest.target_layer == "L3":
            outer_inputs = load_protocol_26_inputs(
                ReV2Paths.for_run(candidate), manifest
            )
            candidate_manifest = outer_inputs.layer_execution_contract.layer_manifest
        if (
            isinstance(candidate_manifest, RunManifestV4)
            and candidate_manifest.semantic_request_id == semantic_request_id
        ):
            return candidate
    return None


def prepare_new_audit_epoch(
    *,
    parent: object,
    selection: SelectionScopeV1,
    artifact_policy: object,
    executor_contract: object,
    semantic_objects: Mapping[str, bytes],
    created_at: str,
    token_limit: int,
    active_ms_limit: int,
    semantic_token_limit: int,
    semantic_active_ms_limit: int,
    engine_protocol_version: str = "2.5.1",
) -> PreparedProtocol25Creation:
    """Prepare an L3 child from an already authenticated L1/L2 authority."""
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.protocol_22.model import BudgetPolicyV2, CatalogReferenceV1
    from harness.re_v2.protocol_24.adoption import (
        ValidatedParentV1,
        build_parent_authority_bundle,
    )
    from harness.re_v2.protocol_24.model import ParentLineageV1, RunManifestV3
    from harness.re_v2.protocol_26.model import RunManifestV5

    from .adoption import (
        ParentSemanticAuthorityV1,
        Protocol25ParentCandidateV1,
        build_parent_authority_bundle_v2,
        validate_protocol_25_parent,
    )
    from .graph import Protocol25GraphInputsV1, build_protocol_25_graph
    from .inputs import Protocol25InputSet
    from .model import RunManifestV4, SemanticClosurePolicyV1
    from .policies import (
        SemanticArtifactPolicyCatalogV1,
        SemanticExecutorContractCatalogV1,
    )

    if not isinstance(parent, ValidatedParentV1):
        raise ValueError("new audit epoch requires authenticated L1/L2 parent")
    if not isinstance(selection, SelectionScopeV1):
        raise ValueError("new audit epoch requires SelectionScopeV1")
    if not isinstance(artifact_policy, SemanticArtifactPolicyCatalogV1):
        raise ValueError("new audit epoch requires semantic artifact policy")
    if not isinstance(executor_contract, SemanticExecutorContractCatalogV1):
        raise ValueError("new audit epoch requires semantic executor contract")

    lower_bundle, lower_objects = build_parent_authority_bundle(parent)
    parent_layer = (
        parent.manifest.target_layer
        if isinstance(parent.manifest, RunManifestV5)
        else "L2"
        if isinstance(parent.manifest, RunManifestV3)
        else "L1"
    )
    candidate = Protocol25ParentCandidateV1(
        schema_version=1,
        parent_layer=parent_layer,
        parent_state="complete",
        source_snapshot_id=parent.manifest.source_snapshot_id,
        selection_id=selection.identity,
        terminal_event_hash=parent.events[-1].event_hash,
        authentication_state="authenticated",
        workspace_state="clean_exact_commits",
        lineage_state="acyclic",
        lower_authority_bundle=lower_bundle,
        semantic_authority=ParentSemanticAuthorityV1.empty(),
    )
    validated_parent = validate_protocol_25_parent(
        candidate,
        mode="new-audit-epoch",
        expected_source_snapshot_id=parent.manifest.source_snapshot_id,
        expected_selection_id=selection.identity,
    )
    bundle = build_parent_authority_bundle_v2(validated_parent)
    parent_manifest_hash = content_digest(parent.manifest_bytes)
    if (
        isinstance(parent.manifest, RunManifestV5)
        and parent.manifest.target_layer == "L2"
    ):
        from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs

        lineage_manifest = load_protocol_26_inputs(
            parent.paths,
            parent.manifest,
        ).layer_execution_contract.layer_manifest
    else:
        lineage_manifest = parent.manifest
    if isinstance(lineage_manifest, RunManifestV3):
        lineage_root_run_id = lineage_manifest.parent_lineage.lineage_root_run_id
        lineage_root_manifest_hash = (
            lineage_manifest.parent_lineage.lineage_root_manifest_hash
        )
    else:
        lineage_root_run_id = parent.manifest.run_id
        lineage_root_manifest_hash = parent_manifest_hash
    lineage = ParentLineageV1(
        schema_version=1,
        direct_parent_run_id=parent.manifest.run_id,
        direct_parent_manifest_hash=parent_manifest_hash,
        direct_parent_terminal_event_hash=parent.events[-1].event_hash,
        lineage_root_run_id=lineage_root_run_id,
        lineage_root_manifest_hash=lineage_root_manifest_hash,
    )
    request_id_builder = (
        semantic_request_id_v2
        if engine_protocol_version == "2.5"
        else semantic_request_id_v3
    )
    semantic_id = request_id_builder(
        **(
            {"engine_protocol_version": engine_protocol_version}
            if request_id_builder is semantic_request_id_v3
            else {}
        ),
        lineage_root_run_id=lineage.lineage_root_run_id,
        lineage_root_manifest_hash=lineage.lineage_root_manifest_hash,
        direct_parent_run_id=lineage.direct_parent_run_id,
        direct_parent_manifest_hash=lineage.direct_parent_manifest_hash,
        direct_parent_terminal_event_hash=lineage.direct_parent_terminal_event_hash,
        source_snapshot_id=parent.manifest.source_snapshot_id,
        partition_manifest_id=parent.manifest.partition_manifest_id,
        selection=selection,
        run_mode="new-audit-epoch",
        artifact_policy_hash=artifact_policy.identity,
        executor_contract_hash=executor_contract.identity,
        audit_policy_hash=artifact_policy.audit_taxonomy.identity,
        accepted_audit_target_ids=(),
        frozen_audit_epoch_id=None,
        closure_root_hash=None,
        guidance_hash=None,
    )
    manifest = RunManifestV4(
        schema_version=4,
        engine="re-v2",
        engine_protocol_version=engine_protocol_version,
        run_id="re-pending-semantic-audit",
        created_at=created_at,
        source_snapshot_id=parent.manifest.source_snapshot_id,
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=parent.manifest.partition_manifest_id,
        workspace_partition_catalog=CatalogReferenceV1(
            parent.inputs.workspace_partition.identity,
            "workspace-partition.json",
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            artifact_policy.identity,
            "artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            executor_contract.identity,
            "executor-contract.json",
        ),
        audit_policy_catalog=CatalogReferenceV1(
            artifact_policy.audit_taxonomy.identity,
            "audit-policy.json",
        ),
        parent_authority_bundle=CatalogReferenceV1(
            bundle.identity,
            "parent-authority-v2.json",
        ),
        parent_lineage=lineage,
        requested_goals=("semantic-audit-closure",),
        target_layer="L3",
        selection=selection,
        run_mode="new-audit-epoch",
        frozen_audit_epoch=None,
        human_guidance=None,
        semantic_request_id=semantic_id,
        initial_budget_policy=BudgetPolicyV2(
            token_limit=token_limit,
            active_ms_limit=active_ms_limit,
            provider_attempt_limit=2,
            artifact_generation_attempt_limit=2,
            semantic_repair_round_limit=0,
            result_contract_retry_limit=1,
            shared_retry_limit=1,
            artifact_contract_retry_limit=1,
        ),
        semantic_closure_policy=SemanticClosurePolicyV1(
            schema_version=1,
            token_limit=semantic_token_limit,
            active_ms_limit=semantic_active_ms_limit,
            max_rounds_per_target=3,
            consecutive_no_reduction_limit=2,
            provider_attempt_limit=2,
            contract_retry_limit=1,
            unknown_usage_policy="shared-conservative-reservation-v1",
        ),
    )
    immutable_objects = MappingProxyType(
        dict(
            sorted(
                {
                    **dict(parent.inputs.immutable_objects),
                    **dict(lower_objects),
                    **dict(semantic_objects),
                }.items()
            )
        )
    )
    inputs = Protocol25InputSet(
        workspace_partition=parent.inputs.workspace_partition,
        artifact_policy=artifact_policy,
        executor_contract=executor_contract,
        audit_policy=artifact_policy.audit_taxonomy,
        parent_authority_bundle=bundle,
        immutable_objects=immutable_objects,
        frozen_audit_epoch=None,
        human_guidance=None,
    )
    graph_inputs = Protocol25GraphInputsV1(
        workspace_partition=inputs.workspace_partition,
        artifact_policy=inputs.artifact_policy,
        executor_contract=inputs.executor_contract,
        audit_policy=inputs.audit_policy,
        immutable_objects=inputs.immutable_objects,
        prior_semantic_object_hashes=bundle.semantic_authority.object_ids,
    )
    graph = build_protocol_25_graph(manifest, graph_inputs, parent.accepted_parent)
    canonical_json_bytes(manifest.to_json_dict())
    return PreparedProtocol25Creation(validated_parent, manifest, inputs, graph)


def export_protocol_25_parent(
    context: object,
    *,
    mode: RunModeV1 | None = None,
) -> ExportedProtocol25Parent:
    """Authenticate and export a terminal schema-4 blocker as direct-parent authority."""
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.protocol_22.graph import AcceptedArtifactV2
    from harness.re_v2.protocol_24.model import (
        AdoptedArtifactAuthorityV1,
        ParentAuthorityBundleV1,
    )

    from .adoption import (
        ParentSemanticAuthorityV1,
        Protocol25ParentCandidateV1,
        validate_protocol_25_parent,
    )
    from .inputs import _semantic_executor_roles
    from .model import RunManifestV4
    from .recovery import (
        Protocol25RunContext,
        _replay_protocol_25_events,
        recover_protocol_25_run,
    )

    if not isinstance(context, Protocol25RunContext):
        raise ValueError("schema-4 parent export requires Protocol25RunContext")
    recovered = recover_protocol_25_run(context)
    state = recovered.controller_state
    selected_mode = mode
    if selected_mode is None:
        if state.terminal_state == "blocked_incomplete" and state.audit_epoch_id is None:
            selected_mode = "audit-successor"
        elif (
            state.terminal_state in {"blocked_incomplete", "blocked_plateau"}
            and state.audit_epoch_id is not None
        ):
            selected_mode = "closure-successor"
        else:
            raise ValueError(
                f"parent state {state.terminal_state!r} is ineligible for guided resume"
            )
    elif selected_mode != "new-audit-epoch":
        raise ValueError("explicit schema-4 export mode must be new-audit-epoch")
    manifest = context.semantic_graph.manifest
    if not isinstance(manifest, RunManifestV4):
        raise ValueError("schema-4 parent export requires RunManifestV4")
    if not recovered.events or recovered.events[-1].type not in {
        "run_failed",
        "run_completed",
    }:
        raise ValueError("guided resume requires an authenticated terminal event")

    from harness.re_v2.protocol_26.authority import resolve_run_authority
    from harness.re_v2.protocol_26.model import RunManifestV5

    active_manifest = resolve_run_authority(context).active_manifest
    canonical_manifest_bytes = canonical_json_bytes(manifest.to_json_dict())
    if isinstance(active_manifest, RunManifestV5):
        # Protocol 2.6 authenticates the semantic manifest inside the immutable
        # layer execution contract.  The top-level run.json is intentionally the
        # schema-5 wrapper, so comparing its bytes with the embedded schema-4
        # manifest would reject every otherwise valid L3 successor export.
        manifest_bytes = canonical_manifest_bytes
    else:
        manifest_bytes = _stable_regular_bytes(
            context.paths.manifest,
            "parent manifest",
        )
        if manifest_bytes != canonical_manifest_bytes:
            raise ValueError("schema-4 parent manifest changed during export")
    event_bytes = _stable_regular_bytes(context.paths.events, "parent event chain")
    ledger_bytes = _stable_regular_bytes(context.paths.ledger, "parent ledger chain")
    ledger_history, ledger = context.ledger.replay_with_history()
    if ledger != recovered.ledger:
        raise ValueError("schema-4 parent ledger changed during export")

    replay = _replay_protocol_25_events(context, recovered.events)
    accepted_target_ids = tuple(sorted(replay.audit_candidates))
    accepted_candidate_hashes = tuple(sorted(replay.audit_candidates.values()))
    unresolved_target_ids = (
        tuple(
            sorted(
                item.audit_target_id
                for item in state.targets
                if item.audit_state != "accepted"
            )
        )
        if state.audit_epoch_id is None
        else ()
    )
    epochs = tuple(ledger.audit_epochs.values())
    epoch = None if not epochs else epochs[0]
    if len(epochs) > 1 or (epoch is None) != (state.audit_epoch_id is None):
        raise ValueError("schema-4 parent audit epoch authority is inconsistent")
    roots = tuple(ledger.audit_closure_roots.values())
    closure_root = None if not roots else roots[0]
    if len(roots) > 1:
        raise ValueError("schema-4 parent has ambiguous closure roots")
    if selected_mode == "new-audit-epoch" and closure_root is None:
        raise ValueError("next audit epoch parent has no authenticated closure root")
    unresolved_findings = tuple(
        sorted(
            {
                finding_id
                for item in state.targets
                for finding_id in item.unresolved_finding_ids
            }
        )
    )
    overlays = tuple(
        sorted(
            receipt.artifact_hash
            for receipt in ledger.accepted_artifacts.values()
            if receipt.artifact_key.artifact_kind == "semantic-resolution-overlay"
        )
    )
    semantic = ParentSemanticAuthorityV1(
        schema_version=1,
        accepted_audit_target_ids=accepted_target_ids,
        accepted_audit_candidate_hashes=accepted_candidate_hashes,
        unresolved_audit_target_ids=unresolved_target_ids,
        audit_epoch_id=(None if epoch is None else epoch.identity),
        resolution_overlay_hashes=overlays,
        target_assessment_hashes=tuple(
            sorted(ledger.target_closure_assessments)
        ),
        source_assessment_hashes=tuple(
            sorted(ledger.source_composition_assessments)
        ),
        closure_receipt_ids=tuple(sorted(ledger.finding_closures)),
        closure_root_hash=(None if closure_root is None else closure_root.identity),
        unresolved_finding_ids=unresolved_findings,
        deferred_observation_ids=state.deferred_observation_ids,
        l3_source_root_hashes=tuple(
            sorted(item.identity for item in ledger.l3_source_roots.values())
        ),
    )

    lower_acceptances = tuple(
        sorted(
            (
                receipt
                for receipt in ledger.accepted_artifacts.values()
                if receipt.certification_receipt_id in ledger.certifications
            ),
            key=lambda item: item.artifact_key.identity,
        )
    )
    artifacts = []
    for acceptance in lower_acceptances:
        certification = ledger.certifications[acceptance.certification_receipt_id]
        matches = tuple(
            item
            for item in ledger.candidate_assessments.values()
            if item.certification_receipt_id == certification.identity
            and item.outcome == "certified"
        )
        if len(matches) > 1:
            raise ValueError("schema-4 lower artifact has ambiguous candidate authority")
        record = ledger.artifact_acceptance_records.get(acceptance.identity)
        if record is None:
            raise ValueError("schema-4 lower artifact has no ledger authority")
        artifacts.append(
            AdoptedArtifactAuthorityV1(
                schema_version=1,
                artifact_key_id=acceptance.artifact_key.identity,
                artifact_hash=acceptance.artifact_hash,
                dependency_hashes=acceptance.artifact_key.dependency_hashes,
                certification_receipt_id=certification.identity,
                candidate_assessment_id=(matches[0].identity if matches else None),
                artifact_acceptance_receipt_id=acceptance.identity,
                source_run_id=manifest.run_id,
                source_ledger_entry_hash=record.record_hash,
            )
        )
    if not artifacts:
        raise ValueError("schema-4 parent has no accepted lower-layer authority")

    retained = dict(context.semantic_inputs.immutable_objects)
    parent_bundle_bytes = canonical_json_bytes(
        context.semantic_inputs.parent_authority_bundle.to_json_dict()
    )
    retained[content_digest(parent_bundle_bytes)] = parent_bundle_bytes
    semantic_artifact_hashes = {
        *semantic.accepted_audit_candidate_hashes,
        *semantic.resolution_overlay_hashes,
    }
    for object_id in semantic.object_ids:
        retained[object_id] = context.object_store.read_blob(object_id)
    retained_artifact_hashes = {
        *(item.artifact_hash for item in lower_acceptances),
        *semantic_artifact_hashes,
    }
    for acceptance in ledger.accepted_artifacts.values():
        if acceptance.artifact_hash not in retained_artifact_hashes:
            continue
        retained[acceptance.artifact_hash] = context.object_store.read_blob(
            acceptance.artifact_hash
        )
        matches = tuple(
            item
            for item in ledger.candidate_assessments.values()
            if item.certification_receipt_id == acceptance.certification_receipt_id
        )
        for assessment in matches:
            retained[assessment.execution_capture_hash] = context.object_store.read_blob(
                assessment.execution_capture_hash
            )
            if assessment.normalized_authorial_payload_hash is not None:
                payload_hash = assessment.normalized_authorial_payload_hash
                retained[payload_hash] = context.object_store.read_blob(payload_hash)

    manifest_hash = content_digest(manifest_bytes)
    event_hash = content_digest(event_bytes)
    ledger_hash = content_digest(ledger_bytes)
    retained[manifest_hash] = manifest_bytes
    retained[event_hash] = event_bytes
    retained[ledger_hash] = ledger_bytes
    executor_objects = set(_semantic_executor_roles(context.semantic_inputs.executor_contract))
    current_chains = {manifest_hash, event_hash, ledger_hash}
    ancestors = tuple(
        sorted(set(retained) - executor_objects - current_chains - set(semantic.object_ids))
    )
    lower_bundle = ParentAuthorityBundleV1(
        schema_version=1,
        direct_parent_run_id=manifest.run_id,
        source_manifest_hash=manifest_hash,
        source_event_chain_hash=event_hash,
        source_terminal_event_hash=recovered.events[-1].event_hash,
        source_ledger_chain_hash=ledger_hash,
        lineage_root_run_id=manifest.parent_lineage.lineage_root_run_id,
        ancestor_bundle_hashes=ancestors,
        artifacts=tuple(artifacts),
    )
    candidate = Protocol25ParentCandidateV1(
        schema_version=1,
        parent_layer="L3",
        parent_state=state.terminal_state,
        source_snapshot_id=manifest.source_snapshot_id,
        selection_id=manifest.selection.identity,
        terminal_event_hash=recovered.events[-1].event_hash,
        authentication_state="authenticated",
        workspace_state="clean_exact_commits",
        lineage_state="acyclic",
        lower_authority_bundle=lower_bundle,
        semantic_authority=semantic,
    )
    validated = validate_protocol_25_parent(
        candidate,
        mode=selected_mode,
        expected_source_snapshot_id=manifest.source_snapshot_id,
        expected_selection_id=manifest.selection.identity,
    )

    accepted_parent = {}
    for template in context.semantic_graph.prerequisite_graph.templates:
        matching = tuple(
            (receipt, ledger.certification_work_items[receipt.certification_receipt_id])
            for receipt in lower_acceptances
            if receipt.certification_receipt_id in ledger.certification_work_items
            and ledger.certification_work_items[
                receipt.certification_receipt_id
            ].template_id
            == template.template_id
        )
        if len(matching) != 1:
            raise ValueError("schema-4 parent prerequisite closure is incomplete")
        receipt, _work_item = matching[0]
        accepted_parent[template.template_id] = (
            template,
            AcceptedArtifactV2(receipt.artifact_key.identity, receipt.artifact_hash),
        )
    return ExportedProtocol25Parent(
        parent=validated,
        manifest=manifest,
        inputs=context.semantic_inputs,
        accepted_parent=accepted_parent,
        immutable_objects=retained,
        recovered=recovered,
        ledger_history=ledger_history,
        source_context=context,
    )


def _stable_regular_bytes(path: Path, label: str) -> bytes:
    """Read one no-follow regular file and reject concurrent replacement."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            chunks = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    payload = b"".join(chunks)
    if identity(before) != identity(after) or len(payload) != before.st_size:
        raise ValueError(f"{label} changed during export")
    return payload


def prepare_guided_successor(
    *,
    parent: object,
    parent_manifest: object,
    parent_inputs: object,
    accepted_parent: Mapping[str, object],
    parent_objects: Mapping[str, bytes],
    guidance_policy: GuidancePolicyV1,
    created_at: str,
    token_limit: int,
    active_ms_limit: int,
    semantic_token_limit: int,
    semantic_active_ms_limit: int,
    successor_artifact_policy: object | None = None,
    successor_executor_contract: object | None = None,
) -> PreparedProtocol25Creation:
    """Prepare one immutable guided child from authenticated schema-4 authority."""
    return _prepare_protocol_25_l3_child(
        parent=parent,
        parent_manifest=parent_manifest,
        parent_inputs=parent_inputs,
        accepted_parent=accepted_parent,
        parent_objects=parent_objects,
        guidance_policy=guidance_policy,
        created_at=created_at,
        token_limit=token_limit,
        active_ms_limit=active_ms_limit,
        semantic_token_limit=semantic_token_limit,
        semantic_active_ms_limit=semantic_active_ms_limit,
        successor_artifact_policy=successor_artifact_policy,
        successor_executor_contract=successor_executor_contract,
    )


def prepare_next_audit_epoch(
    *,
    parent: object,
    parent_manifest: object,
    parent_inputs: object,
    accepted_parent: Mapping[str, object],
    parent_objects: Mapping[str, bytes],
    created_at: str,
    token_limit: int,
    active_ms_limit: int,
    semantic_token_limit: int,
    semantic_active_ms_limit: int,
    successor_artifact_policy: object | None = None,
    successor_executor_contract: object | None = None,
) -> PreparedProtocol25Creation:
    """Prepare an explicit independent audit epoch over a terminal L3 parent."""
    return _prepare_protocol_25_l3_child(
        parent=parent,
        parent_manifest=parent_manifest,
        parent_inputs=parent_inputs,
        accepted_parent=accepted_parent,
        parent_objects=parent_objects,
        guidance_policy=None,
        created_at=created_at,
        token_limit=token_limit,
        active_ms_limit=active_ms_limit,
        semantic_token_limit=semantic_token_limit,
        semantic_active_ms_limit=semantic_active_ms_limit,
        successor_artifact_policy=successor_artifact_policy,
        successor_executor_contract=successor_executor_contract,
    )


def _prepare_protocol_25_l3_child(
    *,
    parent: object,
    parent_manifest: object,
    parent_inputs: object,
    accepted_parent: Mapping[str, object],
    parent_objects: Mapping[str, bytes],
    guidance_policy: GuidancePolicyV1 | None,
    created_at: str,
    token_limit: int,
    active_ms_limit: int,
    semantic_token_limit: int,
    semantic_active_ms_limit: int,
    successor_artifact_policy: object | None,
    successor_executor_contract: object | None,
) -> PreparedProtocol25Creation:
    """Shared schema-4 child preparation for guided and next-epoch modes."""
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.protocol_22.model import BudgetPolicyV2, CatalogReferenceV1
    from harness.re_v2.protocol_24.model import ParentLineageV1

    from .adoption import (
        ValidatedProtocol25ParentV1,
        build_parent_authority_bundle_v2,
    )
    from .artifacts import AuditEpochV1
    from .graph import Protocol25GraphInputsV1, build_protocol_25_graph
    from .inputs import Protocol25InputSet, ValidatedProtocol25Inputs
    from .model import RunManifestV4, SemanticClosurePolicyV1
    from .policies import (
        SemanticArtifactPolicyCatalogV1,
        SemanticExecutorContractCatalogV1,
    )

    if not isinstance(parent, ValidatedProtocol25ParentV1):
        raise ValueError("guided successor requires authenticated schema-4 parent")
    if parent.mode == "new-audit-epoch":
        if guidance_policy is not None:
            raise ValueError("new audit epoch cannot carry human guidance")
    elif parent.mode in {"audit-successor", "closure-successor"}:
        if guidance_policy is None:
            raise ValueError("guided successor requires human guidance")
    else:
        raise ValueError("schema-4 child parent mode is invalid")
    if not isinstance(parent_manifest, RunManifestV4):
        raise ValueError("guided successor requires RunManifestV4 parent")
    if not isinstance(parent_inputs, ValidatedProtocol25Inputs):
        raise ValueError("guided successor requires authenticated parent inputs")
    artifact_policy = parent_inputs.artifact_policy
    if successor_artifact_policy is not None:
        if not isinstance(
            successor_artifact_policy, SemanticArtifactPolicyCatalogV1
        ):
            raise ValueError("successor artifact policy has an unsupported type")
        _validate_monotonic_successor_policy_upgrade(
            artifact_policy,
            successor_artifact_policy,
        )
        artifact_policy = successor_artifact_policy
    executor_contract = parent_inputs.executor_contract
    if successor_executor_contract is not None:
        if not isinstance(
            successor_executor_contract, SemanticExecutorContractCatalogV1
        ):
            raise ValueError("successor executor contract has an unsupported type")
        _validate_monotonic_successor_executor_upgrade(
            executor_contract,
            successor_executor_contract,
        )
        executor_contract = successor_executor_contract
    candidate = parent.candidate
    lower = candidate.lower_authority_bundle
    parent_manifest_hash = content_digest(
        canonical_json_bytes(parent_manifest.to_json_dict())
    )
    if (
        lower.direct_parent_run_id != parent_manifest.run_id
        or lower.source_manifest_hash != parent_manifest_hash
        or candidate.source_snapshot_id != parent_manifest.source_snapshot_id
        or candidate.selection_id != parent_manifest.selection.identity
    ):
        raise ValueError("guided successor direct-parent authority is inconsistent")

    semantic = candidate.semantic_authority
    guidance_bytes = None
    guidance_hash = None
    if guidance_policy is not None:
        if not isinstance(guidance_policy, GuidancePolicyV1):
            raise ValueError("guided successor requires typed guidance policy")
        if (
            guidance_policy.kind == "banzai"
            and guidance_policy.automation_root_manifest_hash
            != parent_manifest_hash
        ):
            raise ValueError("banzai guidance root must equal the blocked parent")
        guidance_payload = _guidance_payload(
            parent_manifest_hash=parent_manifest_hash,
            parent_terminal_event_hash=lower.source_terminal_event_hash,
            accepted_audit_candidate_hashes=semantic.accepted_audit_candidate_hashes,
            unresolved_audit_target_ids=semantic.unresolved_audit_target_ids,
            audit_epoch_id=semantic.audit_epoch_id,
            closure_root_hash=semantic.closure_root_hash,
            unresolved_finding_ids=semantic.unresolved_finding_ids,
            policy=guidance_policy,
        )
        guidance_bytes = canonical_json_bytes(guidance_payload)
        guidance_hash = content_digest(guidance_bytes)
    bundle = build_parent_authority_bundle_v2(parent)
    lineage = ParentLineageV1(
        schema_version=1,
        direct_parent_run_id=parent_manifest.run_id,
        direct_parent_manifest_hash=parent_manifest_hash,
        direct_parent_terminal_event_hash=lower.source_terminal_event_hash,
        lineage_root_run_id=parent_manifest.parent_lineage.lineage_root_run_id,
        lineage_root_manifest_hash=(
            parent_manifest.parent_lineage.lineage_root_manifest_hash
        ),
    )
    frozen_epoch = None
    if parent.mode == "closure-successor":
        assert semantic.audit_epoch_id is not None
        try:
            epoch_bytes = parent_objects[semantic.audit_epoch_id]
        except KeyError as exc:
            raise ValueError("guided successor frozen epoch object is unavailable") from exc
        from harness.re_v2.protocol_22.schema import load_canonical_object

        frozen_epoch = load_canonical_object(
            epoch_bytes,
            AuditEpochV1.from_json_dict,
        )
        if frozen_epoch.identity != semantic.audit_epoch_id:
            raise ValueError("guided successor frozen epoch authority is inconsistent")

    request_id_builder = (
        semantic_request_id_v2
        if parent_manifest.engine_protocol_version == "2.5"
        else semantic_request_id_v3
    )
    semantic_id = request_id_builder(
        **(
            {"engine_protocol_version": parent_manifest.engine_protocol_version}
            if request_id_builder is semantic_request_id_v3
            else {}
        ),
        lineage_root_run_id=lineage.lineage_root_run_id,
        lineage_root_manifest_hash=lineage.lineage_root_manifest_hash,
        direct_parent_run_id=lineage.direct_parent_run_id,
        direct_parent_manifest_hash=lineage.direct_parent_manifest_hash,
        direct_parent_terminal_event_hash=lineage.direct_parent_terminal_event_hash,
        source_snapshot_id=parent_manifest.source_snapshot_id,
        partition_manifest_id=parent_manifest.partition_manifest_id,
        selection=parent_manifest.selection,
        run_mode=parent.mode,  # type: ignore[arg-type]
        artifact_policy_hash=artifact_policy.identity,
        executor_contract_hash=executor_contract.identity,
        audit_policy_hash=parent_inputs.audit_policy.identity,
        accepted_audit_target_ids=(
            ()
            if parent.mode == "new-audit-epoch"
            else semantic.accepted_audit_target_ids
        ),
        frozen_audit_epoch_id=(
            None if parent.mode == "new-audit-epoch" else semantic.audit_epoch_id
        ),
        closure_root_hash=(
            None if parent.mode == "new-audit-epoch" else semantic.closure_root_hash
        ),
        guidance_hash=guidance_hash,
    )
    manifest = RunManifestV4(
        schema_version=4,
        engine="re-v2",
        engine_protocol_version=parent_manifest.engine_protocol_version,
        run_id="re-pending-semantic-successor",
        created_at=created_at,
        source_snapshot_id=parent_manifest.source_snapshot_id,
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=parent_manifest.partition_manifest_id,
        workspace_partition_catalog=CatalogReferenceV1(
            parent_inputs.workspace_partition.identity,
            "workspace-partition.json",
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            artifact_policy.identity,
            "artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            executor_contract.identity,
            "executor-contract.json",
        ),
        audit_policy_catalog=CatalogReferenceV1(
            parent_inputs.audit_policy.identity,
            "audit-policy.json",
        ),
        parent_authority_bundle=CatalogReferenceV1(
            bundle.identity,
            "parent-authority-v2.json",
        ),
        parent_lineage=lineage,
        requested_goals=("semantic-audit-closure",),
        target_layer="L3",
        selection=parent_manifest.selection,
        run_mode=parent.mode,  # type: ignore[arg-type]
        frozen_audit_epoch=(
            None
            if frozen_epoch is None
            else CatalogReferenceV1(frozen_epoch.identity, "audit-epoch.json")
        ),
        human_guidance=(
            None
            if guidance_hash is None
            else CatalogReferenceV1(guidance_hash, "human-guidance.json")
        ),
        semantic_request_id=semantic_id,
        initial_budget_policy=BudgetPolicyV2(
            token_limit=token_limit,
            active_ms_limit=active_ms_limit,
            provider_attempt_limit=2,
            artifact_generation_attempt_limit=2,
            semantic_repair_round_limit=0,
            result_contract_retry_limit=1,
            shared_retry_limit=1,
            artifact_contract_retry_limit=1,
        ),
        semantic_closure_policy=SemanticClosurePolicyV1(
            schema_version=1,
            token_limit=semantic_token_limit,
            active_ms_limit=semantic_active_ms_limit,
            max_rounds_per_target=3,
            consecutive_no_reduction_limit=2,
            provider_attempt_limit=2,
            contract_retry_limit=1,
            unknown_usage_policy="shared-conservative-reservation-v1",
        ),
    )
    immutable_objects = MappingProxyType(dict(sorted(parent_objects.items())))
    inputs = Protocol25InputSet(
        workspace_partition=parent_inputs.workspace_partition,
        artifact_policy=artifact_policy,
        executor_contract=executor_contract,
        audit_policy=artifact_policy.audit_taxonomy,
        parent_authority_bundle=bundle,
        immutable_objects=immutable_objects,
        frozen_audit_epoch=frozen_epoch,
        human_guidance=guidance_bytes,
    )
    graph_inputs = Protocol25GraphInputsV1(
        workspace_partition=inputs.workspace_partition,
        artifact_policy=inputs.artifact_policy,
        executor_contract=inputs.executor_contract,
        audit_policy=inputs.audit_policy,
        immutable_objects=inputs.immutable_objects,
        prior_semantic_object_hashes=bundle.semantic_authority.object_ids,
    )
    graph = build_protocol_25_graph(manifest, graph_inputs, accepted_parent)
    canonical_json_bytes(manifest.to_json_dict())
    return PreparedProtocol25Creation(parent, manifest, inputs, graph)


def _validate_monotonic_successor_policy_upgrade(
    parent_policy: object,
    successor_policy: object,
) -> None:
    """Allow retained authority across capacity-only semantic policy upgrades."""
    from dataclasses import replace

    from .policies import SemanticArtifactPolicyCatalogV1

    if not isinstance(parent_policy, SemanticArtifactPolicyCatalogV1) or not isinstance(
        successor_policy, SemanticArtifactPolicyCatalogV1
    ):
        raise ValueError("successor artifact policy upgrade has unsupported inputs")
    if (
        parent_policy.schema_version != successor_policy.schema_version
        or parent_policy.inherited_catalog != successor_policy.inherited_catalog
        or parent_policy.audit_taxonomy != successor_policy.audit_taxonomy
    ):
        raise ValueError("successor artifact policy changes semantic authority")
    parent_entries = {item.artifact_kind: item for item in parent_policy.l3_entries}
    successor_entries = {
        item.artifact_kind: item for item in successor_policy.l3_entries
    }
    if parent_entries.keys() != successor_entries.keys():
        raise ValueError("successor artifact policy changes semantic artifact kinds")
    for kind, parent_entry in parent_entries.items():
        successor_entry = successor_entries[kind]
        if (
            successor_entry.max_context_bundle_bytes
            < parent_entry.max_context_bundle_bytes
            or successor_entry.max_conservative_input_tokens
            < parent_entry.max_conservative_input_tokens
        ):
            raise ValueError("successor artifact policy reduces a capacity ceiling")
        normalized = replace(
            successor_entry,
            max_context_bundle_bytes=parent_entry.max_context_bundle_bytes,
            max_conservative_input_tokens=parent_entry.max_conservative_input_tokens,
        )
        if normalized != parent_entry:
            raise ValueError("successor artifact policy changes semantic rules")


def _validate_monotonic_successor_executor_upgrade(
    parent_contract: object,
    successor_contract: object,
) -> None:
    """Allow retained authority across reservation-capacity-only upgrades."""
    from dataclasses import replace

    from .policies import SemanticExecutorContractCatalogV1

    if not isinstance(
        parent_contract, SemanticExecutorContractCatalogV1
    ) or not isinstance(successor_contract, SemanticExecutorContractCatalogV1):
        raise ValueError("successor executor capacity upgrade has unsupported inputs")
    if (
        parent_contract.schema_version != successor_contract.schema_version
        or parent_contract.inherited_catalog != successor_contract.inherited_catalog
    ):
        raise ValueError("successor executor contract changes inherited authority")
    parent_entries = {
        item.producer_family: item for item in parent_contract.semantic_entries
    }
    successor_entries = {
        item.producer_family: item for item in successor_contract.semantic_entries
    }
    if parent_entries.keys() != successor_entries.keys():
        raise ValueError("successor executor contract changes semantic families")
    for family, parent_entry in parent_entries.items():
        successor_entry = successor_entries[family]
        parent_limit = parent_entry.limits.max_billable_tokens_per_dispatch
        successor_limit = successor_entry.limits.max_billable_tokens_per_dispatch
        if successor_limit < parent_limit:
            raise ValueError("successor executor contract reduces a capacity ceiling")
        normalized = replace(
            successor_entry,
            limits=replace(
                successor_entry.limits,
                max_billable_tokens_per_dispatch=parent_limit,
            ),
        )
        if normalized != parent_entry:
            raise ValueError("successor executor contract changes execution authority")


def initialize_protocol_25_child(run_dir: Path, parent: object) -> None:
    """Idempotently import lower-layer authority into a published L3 run."""
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_24.adoption import (
        ValidatedParentV1,
        build_parent_authority_bundle,
        import_parent_acceptance_closure,
    )
    from harness.re_v2.protocol_24.model import AdoptedArtifactAuthorityV1
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    from .events import PROTOCOL_25_EVENTS
    from .inputs import load_protocol_25_inputs
    from .ledger import Protocol25Ledger
    from .model import RunManifestV4

    if not isinstance(parent, ValidatedParentV1):
        raise ValueError("schema-4 initialization requires authenticated parent")
    active_manifest = load_run_manifest(run_dir)
    paths = ReV2Paths.for_run(run_dir)
    if isinstance(active_manifest, RunManifestV5):
        if active_manifest.target_layer != "L3":
            raise ValueError("L3 initialization requires protocol-2.6 target L3")
        protocol_26_inputs = load_protocol_26_inputs(paths, active_manifest)
        manifest = protocol_26_inputs.layer_execution_contract.layer_manifest
        if not isinstance(manifest, RunManifestV4):
            raise ValueError("protocol-2.6 L3 contract has no schema-4 manifest")
        inputs = protocol_26_inputs.layer_inputs
        event_protocol = protocol_26_events_for("L3")
    elif isinstance(active_manifest, RunManifestV4):
        manifest = active_manifest
        inputs = load_protocol_25_inputs(paths, manifest)
        event_protocol = PROTOCOL_25_EVENTS
    else:
        raise ValueError("L3 initialization requires schema 4 or 5")
    if manifest.run_mode != "new-audit-epoch":
        raise ValueError("lower-parent initialization requires new-audit-epoch mode")
    expected_lower, _objects = build_parent_authority_bundle(parent)
    if inputs.parent_authority_bundle.lower_authority_bundle != expected_lower:
        raise ValueError("existing schema-4 child parent authority does not match")
    if not inputs.parent_authority_bundle.semantic_authority.is_empty:
        raise ValueError("new lower-layer audit parent must have empty semantic authority")

    objects = ObjectStore(paths.objects)
    ledger = Protocol25Ledger(paths, objects)
    events = EventStore(paths, protocol=event_protocol)
    import_parent_acceptance_closure(parent, objects, ledger)
    replayed = events.replay()
    if not replayed:
        events.append(
            "run_created",
            {"run_manifest_id": active_manifest.run_manifest_id},
            occurred_at=active_manifest.created_at,
        )
        replayed = events.replay()
    elif (
        replayed[0].type != "run_created"
        or replayed[0].payload.get("run_manifest_id")
        != active_manifest.run_manifest_id
    ):
        raise ValueError("existing schema-4 child has invalid creation authority")

    adopted: dict[str, object] = {}
    for event in replayed:
        if event.type != "artifact_adopted":
            continue
        authority = AdoptedArtifactAuthorityV1.from_json_dict(
            event.payload["adopted_artifact_authority"]
        )
        adopted[authority.artifact_key_id] = event
    replayed_ledger = ledger.replay()
    for authority in inputs.parent_authority_bundle.lower_authority_bundle.artifacts:
        work_item = replayed_ledger.certification_work_items.get(
            authority.certification_receipt_id
        )
        if work_item is None:
            raise ValueError("imported parent work item is missing")
        payload = {
            "adopted_artifact_authority": authority.to_json_dict(),
            "parent_authority_bundle_hash": inputs.parent_authority_bundle.identity,
            "work_item_id": work_item.work_item_id,
        }
        existing = adopted.get(authority.artifact_key_id)
        if existing is not None:
            existing_authority = AdoptedArtifactAuthorityV1.from_json_dict(
                existing.payload["adopted_artifact_authority"]
            )
            if (
                existing_authority != authority
                or existing.payload.get("parent_authority_bundle_hash")
                != inputs.parent_authority_bundle.identity
                or existing.payload.get("work_item_id") != work_item.work_item_id
            ):
                raise ValueError("existing schema-4 adoption conflicts with parent")
            continue
        events.append(
            "artifact_adopted",
            payload,
            occurred_at=active_manifest.created_at,
        )

    final_events = events.replay()
    final_ledger = ledger.replay()
    expected_keys = {
        authority.artifact_key_id
        for authority in inputs.parent_authority_bundle.lower_authority_bundle.artifacts
    }
    adopted_keys = {
        AdoptedArtifactAuthorityV1.from_json_dict(
            event.payload["adopted_artifact_authority"]
        ).artifact_key_id
        for event in final_events
        if event.type == "artifact_adopted"
    }
    if adopted_keys != expected_keys or not expected_keys.issubset(
        final_ledger.accepted_artifacts
    ):
        raise ValueError("schema-4 child adoption initialization is incomplete")


def initialize_protocol_25_successor(
    run_dir: Path,
    exported: ExportedProtocol25Parent,
) -> None:
    """Idempotently import retained lower and semantic authority into a successor."""
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    from .events import PROTOCOL_25_EVENTS
    from .inputs import load_protocol_25_inputs
    from .ledger import Protocol25Ledger
    from .model import RunManifestV4
    from .recovery import _replay_protocol_25_events

    if not isinstance(exported, ExportedProtocol25Parent):
        raise ValueError("schema-4 successor initialization requires exported parent")
    manifest = load_run_manifest(run_dir)
    if not isinstance(manifest, RunManifestV4) or manifest.run_mode not in {
        "new-audit-epoch",
        "audit-successor",
        "closure-successor",
    }:
        raise ValueError("schema-4 successor initialization requires successor manifest")
    inputs = load_protocol_25_inputs(ReV2Paths.for_run(run_dir), manifest)
    if (
        inputs.parent_authority_bundle.lower_authority_bundle
        != exported.parent.candidate.lower_authority_bundle
        or inputs.parent_authority_bundle.semantic_authority
        != exported.parent.candidate.semantic_authority
    ):
        raise ValueError("existing successor parent authority does not match export")

    paths = ReV2Paths.for_run(run_dir)
    objects = ObjectStore(paths.objects)
    ledger = Protocol25Ledger(paths, objects)
    source_ledger = exported.recovered.ledger
    lower_bundle = exported.parent.candidate.lower_authority_bundle
    import_semantic = manifest.run_mode != "new-audit-epoch"
    semantic = exported.parent.candidate.semantic_authority

    # Source-composition assessments authenticate a separately persisted
    # composed view.  That blob is a ledger dependency rather than a catalog
    # object, so copy it explicitly before replaying any retained records.
    for assessment_hash in semantic.source_assessment_hashes if import_semantic else ():
        assessment = source_ledger.source_composition_assessments[assessment_hash]
        payload = exported.source_context.object_store.read_blob(
            assessment.composed_authority_hash
        )
        if objects.put_blob(payload) != assessment.composed_authority_hash:
            raise ValueError("successor composed source authority hash changed")

    ledger_records: list[tuple[str, object]] = []
    for authority in lower_bundle.artifacts:
        acceptance = source_ledger.accepted_artifacts.get(authority.artifact_key_id)
        certification = source_ledger.certifications.get(
            authority.certification_receipt_id
        )
        work_item = source_ledger.certification_work_items.get(
            authority.certification_receipt_id
        )
        if acceptance is None or certification is None or work_item is None:
            raise ValueError("successor lower authority receipt closure is incomplete")
        ledger_records.append(
            (
                "certification",
                {
                    "receipt": certification.to_json_dict(),
                    "work_item": work_item.to_json_dict(),
                },
            )
        )
        if authority.candidate_assessment_id is not None:
            assessment = source_ledger.candidate_assessments.get(
                authority.candidate_assessment_id
            )
            if assessment is None:
                raise ValueError("successor lower candidate authority is missing")
            ledger_records.append(
                ("candidate_assessment", assessment.to_json_dict())
            )
        ledger_records.append(("artifact", acceptance.to_json_dict()))

    retained_semantic_hashes = (
        {
            *semantic.accepted_audit_candidate_hashes,
            *semantic.resolution_overlay_hashes,
        }
        if import_semantic
        else set()
    )
    semantic_acceptances = tuple(
        sorted(
            (
                receipt
                for receipt in source_ledger.accepted_artifacts.values()
                if receipt.artifact_hash in retained_semantic_hashes
                and receipt.certification_receipt_id
                in source_ledger.semantic_certifications
            ),
            key=lambda item: item.artifact_key.identity,
        )
    )
    for acceptance in semantic_acceptances:
        certification = source_ledger.semantic_certifications[
            acceptance.certification_receipt_id
        ]
        ledger_records.append(
            ("semantic_certification", certification.to_json_dict())
        )
        assessments = tuple(
            item
            for item in source_ledger.candidate_assessments.values()
            if item.certification_receipt_id == certification.identity
        )
        if len(assessments) != 1:
            raise ValueError("successor semantic candidate authority is ambiguous")
        ledger_records.append(
            ("candidate_assessment", assessments[0].to_json_dict())
        )
        ledger_records.append(("artifact", acceptance.to_json_dict()))

    if import_semantic and semantic.audit_epoch_id is not None:
        ledger_records.append(
            (
                "audit_epoch",
                source_ledger.audit_epochs[semantic.audit_epoch_id].to_json_dict(),
            )
        )
    for object_id in semantic.target_assessment_hashes if import_semantic else ():
        ledger_records.append(
            (
                "target_closure_assessment",
                source_ledger.target_closure_assessments[object_id].to_json_dict(),
            )
        )
    for object_id in semantic.source_assessment_hashes if import_semantic else ():
        ledger_records.append(
            (
                "source_composition_assessment",
                source_ledger.source_composition_assessments[
                    object_id
                ].to_json_dict(),
            )
        )
    for object_id in semantic.closure_receipt_ids if import_semantic else ():
        ledger_records.append(
            (
                "finding_closure",
                source_ledger.finding_closures[object_id].to_json_dict(),
            )
        )
    if import_semantic and semantic.closure_root_hash is not None:
        ledger_records.append(
            (
                "audit_closure_root",
                source_ledger.audit_closure_roots[
                    semantic.closure_root_hash
                ].to_json_dict(),
            )
        )
    roots_by_identity = {
        item.identity: item for item in source_ledger.l3_source_roots.values()
    }
    for object_id in semantic.l3_source_root_hashes if import_semantic else ():
        ledger_records.append(
            ("l3_source_root", roots_by_identity[object_id].to_json_dict())
        )
    ledger.record_import_batch(ledger_records)

    source_replay = _replay_protocol_25_events(
        exported.source_context,
        exported.recovered.events,
    )
    expected_events: list[tuple[str, dict[str, object]]] = [
        ("run_created", {"run_manifest_id": manifest.run_manifest_id})
    ]
    for authority in lower_bundle.artifacts:
        work_item = source_ledger.certification_work_items[
            authority.certification_receipt_id
        ]
        expected_events.append(
            (
                "artifact_adopted",
                {
                    "adopted_artifact_authority": authority.to_json_dict(),
                    "parent_authority_bundle_hash": inputs.parent_authority_bundle.identity,
                    "work_item_id": work_item.work_item_id,
                },
            )
        )
    for target_id, candidate_hash in (
        sorted(source_replay.audit_candidates.items()) if import_semantic else ()
    ):
        expected_events.append(
            (
                "audit_candidate_accepted",
                {
                    "audit_candidate_authority_id": candidate_hash,
                    "audit_target_id": target_id,
                },
            )
        )
    if import_semantic and semantic.audit_epoch_id is not None:
        epoch = source_ledger.audit_epochs[semantic.audit_epoch_id]
        expected_events.append(
            (
                "audit_epoch_frozen",
                {
                    "audit_epoch_id": epoch.identity,
                    "audit_target_ids": list(epoch.audit_target_ids),
                },
            )
        )
        # Adopt only progress that crossed the parent's durable per-target
        # semantic-progress boundary. Accepted artifacts from an interrupted
        # source cycle remain available as evidence, but do not advance the
        # successor controller or close findings by themselves.
        for target_id, semantic_round in sorted(
            source_replay.rounds_by_target.items()
        ):
            expected_events.append(
                (
                    "semantic_progress_adopted",
                    {
                        "audit_target_id": target_id,
                        "no_reduction_rounds": (
                            source_replay.no_reduction_rounds_by_target.get(
                                target_id,
                                0,
                            )
                        ),
                        "semantic_round": semantic_round,
                        "unresolved_finding_ids": sorted(
                            source_replay.unresolved_by_target[target_id]
                        ),
                    },
                )
            )
            lineage = source_replay.resolution_overlays_by_target_round.get(
                target_id,
                {},
            )
            if set(lineage) != set(range(1, semantic_round + 1)):
                if source_replay.unresolved_by_target[target_id]:
                    raise ValueError(
                        "successor unresolved semantic progress has no complete "
                        "overlay lineage"
                    )
                continue
            expected_events.append(
                (
                    "semantic_progress_lineage_adopted",
                    {
                        "audit_target_id": target_id,
                        "overlay_chain": [
                            {
                                "resolution_overlay_id": lineage[round_index],
                                "semantic_round": round_index,
                            }
                            for round_index in range(1, semantic_round + 1)
                        ],
                    },
                )
            )
    if import_semantic and semantic.closure_root_hash is not None:
        root = source_ledger.audit_closure_roots[semantic.closure_root_hash]
        expected_events.append(
            (
                "audit_closure_root_accepted",
                {
                    "audit_closure_root_id": root.identity,
                    "audit_epoch_id": root.audit_epoch_id,
                    "deferred_observation_ids": [
                        item.observation_id for item in root.deferred_observations
                    ],
                    "unresolved_finding_ids": list(root.unresolved_finding_ids),
                },
            )
        )
        for object_id in semantic.l3_source_root_hashes:
            source_root = roots_by_identity[object_id]
            expected_events.append(
                (
                    "l3_source_root_accepted",
                    {
                        "l3_source_root_id": source_root.identity,
                        "scope_state": source_root.state,
                        "source_id": source_root.source_id,
                    },
                )
            )

    events = EventStore(paths, protocol=PROTOCOL_25_EVENTS)
    existing = events.replay()
    missing_events: list[tuple[str, dict[str, object], str]] = []
    for index, (event_type, payload) in enumerate(expected_events):
        if index < len(existing):
            event = existing[index]
            canonical_payload = PROTOCOL_25_EVENTS.canonical_payload(
                event_type,
                payload,
            )
            if event.type != event_type or event.payload != canonical_payload:
                raise ValueError(
                    "existing successor initialization conflicts with export at "
                    f"event {index + 1}: existing {event.type!r}, "
                    f"expected {event_type!r}"
                )
            continue
        missing_events.append((event_type, payload, manifest.created_at))
    if len(existing) > len(expected_events):
        return
    events.append_batch(missing_events)

    final = ledger.replay()
    if not {
        item.artifact_key_id for item in lower_bundle.artifacts
    }.issubset(final.accepted_artifacts):
        raise ValueError("successor lower authority import is incomplete")
    if not retained_semantic_hashes.issubset(
        {item.artifact_hash for item in final.accepted_artifacts.values()}
    ):
        raise ValueError("successor semantic authority import is incomplete")


__all__ = (
    "export_protocol_25_parent",
    "ExportedProtocol25Parent",
    "find_exact_protocol_25_child",
    "guidance_id_for",
    "initialize_protocol_25_child",
    "initialize_protocol_25_successor",
    "normalize_guidance_answer",
    "prepare_guided_successor",
    "prepare_next_audit_epoch",
    "prepare_new_audit_epoch",
    "PreparedProtocol25Creation",
    "semantic_request_id_v2",
)

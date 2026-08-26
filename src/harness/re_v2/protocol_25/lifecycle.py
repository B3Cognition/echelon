"""Pure schema-4 lifecycle identities and immutable guidance authority."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from typing import Literal
import unicodedata

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    safe_id,
    sorted_unique_digests,
)
from harness.re_v2.protocol_24.model import SelectionScopeV1


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


def normalize_guidance_answer(answer: object) -> str:
    """Return bounded NFC guidance suitable for immutable publication."""
    if not isinstance(answer, str):
        raise ValueError("guidance answer must be text")
    normalized = unicodedata.normalize(
        "NFC",
        answer.replace("\r\n", "\n").replace("\r", "\n"),
    ).strip()
    if not normalized:
        raise ValueError("guidance answer must be nonempty")
    if len(normalized.encode("utf-8", errors="strict")) > 8192:
        raise ValueError("guidance answer must be at most 8192 UTF-8 bytes")
    if any(
        unicodedata.category(character) == "Cc" and character != "\n"
        for character in normalized
    ):
        raise ValueError("guidance answer contains unsupported control characters")
    return normalized


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
            answer=answer,
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
    answer: str,
) -> dict[str, object]:
    """Return the canonical guidance authority before byte publication."""
    try:
        digest_value(parent_manifest_hash, "guidance parent manifest")
        digest_value(parent_terminal_event_hash, "guidance parent terminal event")
        candidates = sorted_unique_digests(
            accepted_audit_candidate_hashes,
            "guidance accepted audit candidates",
        )
        targets = sorted_unique_digests(
            unresolved_audit_target_ids,
            "guidance unresolved audit targets",
        )
        findings = sorted_unique_digests(
            unresolved_finding_ids,
            "guidance unresolved findings",
        )
        if audit_epoch_id is not None:
            digest_value(audit_epoch_id, "guidance audit epoch")
        if closure_root_hash is not None:
            digest_value(closure_root_hash, "guidance closure root")
    except Protocol22SchemaError as exc:
        raise ValueError(str(exc)) from exc
    pre_epoch = audit_epoch_id is None and closure_root_hash is None
    if pre_epoch:
        if not candidates or not targets or findings:
            raise ValueError(
                "pre-epoch guidance requires retained candidates and unresolved targets"
            )
    elif (
        audit_epoch_id is None
        or closure_root_hash is None
        or not findings
        or targets
    ):
        raise ValueError(
            "closure guidance requires epoch, closure root, and unresolved findings"
        )
    return {
        "accepted_audit_candidate_hashes": list(candidates),
        "answer": normalize_guidance_answer(answer),
        "audit_epoch_id": audit_epoch_id,
        "closure_root_hash": closure_root_hash,
        "parent_manifest_hash": parent_manifest_hash,
        "parent_terminal_event_hash": parent_terminal_event_hash,
        "schema_version": 1,
        "unresolved_audit_target_ids": list(targets),
        "unresolved_finding_ids": list(findings),
    }


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
    elif (
        guidance_hash is None
        or frozen_audit_epoch_id is None
        or closure_root_hash is None
    ):
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


def find_exact_protocol_25_child(
    workspace_root: Path,
    semantic_request_id: str,
) -> Path | None:
    """Return an exact immutable semantic request regardless of mutable state."""
    from harness.re_v2.run_store import load_run_manifest

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
        if (
            isinstance(manifest, RunManifestV4)
            and manifest.semantic_request_id == semantic_request_id
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
) -> PreparedProtocol25Creation:
    """Prepare an L3 child from an already authenticated L1/L2 authority."""
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.protocol_22.model import BudgetPolicyV2, CatalogReferenceV1
    from harness.re_v2.protocol_24.adoption import (
        ValidatedParentV1,
        build_parent_authority_bundle,
    )
    from harness.re_v2.protocol_24.model import ParentLineageV1, RunManifestV3

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
    parent_layer = "L2" if isinstance(parent.manifest, RunManifestV3) else "L1"
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
    if isinstance(parent.manifest, RunManifestV3):
        lineage_root_run_id = parent.manifest.parent_lineage.lineage_root_run_id
        lineage_root_manifest_hash = (
            parent.manifest.parent_lineage.lineage_root_manifest_hash
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
    semantic_id = semantic_request_id_v2(
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
        engine_protocol_version="2.5",
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
    )
    graph = build_protocol_25_graph(manifest, graph_inputs, parent.accepted_parent)
    canonical_json_bytes(manifest.to_json_dict())
    return PreparedProtocol25Creation(validated_parent, manifest, inputs, graph)


def prepare_guided_successor(
    *,
    parent: object,
    parent_manifest: object,
    parent_inputs: object,
    accepted_parent: Mapping[str, object],
    parent_objects: Mapping[str, bytes],
    answer: str,
    created_at: str,
    token_limit: int,
    active_ms_limit: int,
    semantic_token_limit: int,
    semantic_active_ms_limit: int,
) -> PreparedProtocol25Creation:
    """Prepare one immutable guided child from authenticated schema-4 authority."""
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

    if not isinstance(parent, ValidatedProtocol25ParentV1):
        raise ValueError("guided successor requires authenticated schema-4 parent")
    if parent.mode not in {"audit-successor", "closure-successor"}:
        raise ValueError("guided successor parent mode is invalid")
    if not isinstance(parent_manifest, RunManifestV4):
        raise ValueError("guided successor requires RunManifestV4 parent")
    if not isinstance(parent_inputs, ValidatedProtocol25Inputs):
        raise ValueError("guided successor requires authenticated parent inputs")
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
    guidance_payload = _guidance_payload(
        parent_manifest_hash=parent_manifest_hash,
        parent_terminal_event_hash=lower.source_terminal_event_hash,
        accepted_audit_candidate_hashes=semantic.accepted_audit_candidate_hashes,
        unresolved_audit_target_ids=semantic.unresolved_audit_target_ids,
        audit_epoch_id=semantic.audit_epoch_id,
        closure_root_hash=semantic.closure_root_hash,
        unresolved_finding_ids=semantic.unresolved_finding_ids,
        answer=answer,
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

    semantic_id = semantic_request_id_v2(
        lineage_root_run_id=lineage.lineage_root_run_id,
        lineage_root_manifest_hash=lineage.lineage_root_manifest_hash,
        direct_parent_run_id=lineage.direct_parent_run_id,
        direct_parent_manifest_hash=lineage.direct_parent_manifest_hash,
        direct_parent_terminal_event_hash=lineage.direct_parent_terminal_event_hash,
        source_snapshot_id=parent_manifest.source_snapshot_id,
        partition_manifest_id=parent_manifest.partition_manifest_id,
        selection=parent_manifest.selection,
        run_mode=parent.mode,  # type: ignore[arg-type]
        artifact_policy_hash=parent_inputs.artifact_policy.identity,
        executor_contract_hash=parent_inputs.executor_contract.identity,
        audit_policy_hash=parent_inputs.audit_policy.identity,
        accepted_audit_target_ids=semantic.accepted_audit_target_ids,
        frozen_audit_epoch_id=semantic.audit_epoch_id,
        closure_root_hash=semantic.closure_root_hash,
        guidance_hash=guidance_hash,
    )
    manifest = RunManifestV4(
        schema_version=4,
        engine="re-v2",
        engine_protocol_version="2.5",
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
            parent_inputs.artifact_policy.identity,
            "artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            parent_inputs.executor_contract.identity,
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
        human_guidance=CatalogReferenceV1(guidance_hash, "human-guidance.json"),
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
        artifact_policy=parent_inputs.artifact_policy,
        executor_contract=parent_inputs.executor_contract,
        audit_policy=parent_inputs.audit_policy,
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
    )
    graph = build_protocol_25_graph(manifest, graph_inputs, accepted_parent)
    canonical_json_bytes(manifest.to_json_dict())
    return PreparedProtocol25Creation(parent, manifest, inputs, graph)


def initialize_protocol_25_child(run_dir: Path, parent: object) -> None:
    """Idempotently import lower-layer authority into a published schema-4 run."""
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_24.adoption import (
        ValidatedParentV1,
        build_parent_authority_bundle,
        import_parent_acceptance_closure,
    )
    from harness.re_v2.protocol_24.model import AdoptedArtifactAuthorityV1
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    from .events import PROTOCOL_25_EVENTS
    from .inputs import load_protocol_25_inputs
    from .ledger import Protocol25Ledger
    from .model import RunManifestV4

    if not isinstance(parent, ValidatedParentV1):
        raise ValueError("schema-4 initialization requires authenticated parent")
    manifest = load_run_manifest(run_dir)
    if not isinstance(manifest, RunManifestV4):
        raise ValueError("schema-4 initialization requires RunManifestV4")
    if manifest.run_mode != "new-audit-epoch":
        raise ValueError("lower-parent initialization requires new-audit-epoch mode")
    paths = ReV2Paths.for_run(run_dir)
    inputs = load_protocol_25_inputs(paths, manifest)
    expected_lower, _objects = build_parent_authority_bundle(parent)
    if inputs.parent_authority_bundle.lower_authority_bundle != expected_lower:
        raise ValueError("existing schema-4 child parent authority does not match")
    if not inputs.parent_authority_bundle.semantic_authority.is_empty:
        raise ValueError("new lower-layer audit parent must have empty semantic authority")

    objects = ObjectStore(paths.objects)
    ledger = Protocol25Ledger(paths, objects)
    events = EventStore(paths, protocol=PROTOCOL_25_EVENTS)
    import_parent_acceptance_closure(parent, objects, ledger)
    replayed = events.replay()
    if not replayed:
        events.append(
            "run_created",
            {"run_manifest_id": manifest.run_manifest_id},
            occurred_at=manifest.created_at,
        )
        replayed = events.replay()
    elif (
        replayed[0].type != "run_created"
        or replayed[0].payload.get("run_manifest_id") != manifest.run_manifest_id
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
            occurred_at=manifest.created_at,
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


__all__ = (
    "find_exact_protocol_25_child",
    "guidance_id_for",
    "initialize_protocol_25_child",
    "normalize_guidance_answer",
    "prepare_guided_successor",
    "prepare_new_audit_epoch",
    "PreparedProtocol25Creation",
    "semantic_request_id_v2",
)

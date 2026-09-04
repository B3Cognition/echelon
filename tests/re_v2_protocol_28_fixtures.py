from __future__ import annotations

from dataclasses import replace

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_24.model import ParentLineageV1, SelectionScopeV1
from harness.re_v2.protocol_28.model import (
    ExhaustiveBudgetPolicyV1,
    ExhaustiveRequestV1,
    ExhaustiveRunManifestV7,
    L4ClosureLineageV1,
    L4ClosureRequestV1,
    L4ClosureRunManifestV7,
)


def digest(seed: str) -> str:
    return content_digest(seed.encode("utf-8"))


def selection_scope_v1() -> SelectionScopeV1:
    return SelectionScopeV1(
        schema_version=1,
        all_sources=False,
        source_ids=("api",),
        domain_keys=(digest("api-domain"),),
    )


def exhaustive_budget_policy_v1(
    *,
    token_limit: int | None = 400_000,
    active_ms_limit: int | None = 600_000,
) -> ExhaustiveBudgetPolicyV1:
    return ExhaustiveBudgetPolicyV1(
        schema_version=1,
        token_limit=token_limit,
        active_ms_limit=active_ms_limit,
        producer_attempt_limit=3,
        producer_contract_retry_limit=0,
        verifier_contract_retry_limit=1,
    )


def exhaustive_request_v1() -> ExhaustiveRequestV1:
    return ExhaustiveRequestV1(
        schema_version=1,
        selection_id=selection_scope_v1().identity,
        parent_authority_bundle_id=digest("parent-authority-bundle"),
        l3_target_projection_catalog_id=digest("l3-target-projections"),
        snapshot_evidence_catalog_id=digest("snapshot-evidence"),
        exhaustive_plan_id=digest("exhaustive-plan"),
        exhaustive_policy_catalog_id=digest("exhaustive-policy"),
        executor_catalog_id=digest("executor-catalog"),
        source_snapshot_id=digest("source-snapshot"),
        partition_manifest_id=digest("partition-manifest"),
    )


def exhaustive_manifest_v7(
    *,
    run_id: str = "re-l4-exhaustive",
    token_limit: int | None = 400_000,
) -> ExhaustiveRunManifestV7:
    request = exhaustive_request_v1()
    return ExhaustiveRunManifestV7(
        schema_version=7,
        engine="re-v2",
        engine_protocol_version="2.8",
        run_mode="exhaustive-depth",
        requested_goals=("selective-exhaustive-depth",),
        target_layer="L4",
        run_id=run_id,
        created_at="2026-08-31T12:00:00Z",
        source_snapshot_id=request.source_snapshot_id,
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=request.partition_manifest_id,
        selection=selection_scope_v1(),
        lineage=ParentLineageV1(
            schema_version=1,
            direct_parent_run_id="re-l3-parent",
            direct_parent_manifest_hash=digest("l3-parent-manifest"),
            direct_parent_terminal_event_hash=digest("l3-parent-terminal"),
            lineage_root_run_id="re-l0-root",
            lineage_root_manifest_hash=digest("l0-root-manifest"),
        ),
        workspace_partition_catalog_id=digest("workspace-partition-catalog"),
        inherited_artifact_policy_catalog_id=digest("artifact-policy-catalog"),
        parent_authority_bundle_id=request.parent_authority_bundle_id,
        l3_target_projection_catalog_id=request.l3_target_projection_catalog_id,
        snapshot_evidence_catalog_id=request.snapshot_evidence_catalog_id,
        exhaustive_request=request,
        exhaustive_plan_id=digest("exhaustive-plan"),
        exhaustive_policy_catalog_id=request.exhaustive_policy_catalog_id,
        executor_catalog_id=request.executor_catalog_id,
        attempt_policy_id=digest("attempt-policy"),
        budget_policy=exhaustive_budget_policy_v1(token_limit=token_limit),
    )


def closure_request_v1() -> L4ClosureRequestV1:
    return L4ClosureRequestV1(
        schema_version=1,
        blocked_l3_manifest_hash=digest("blocked-l3-manifest"),
        blocked_l3_terminal_event_hash=digest("blocked-l3-terminal"),
        frozen_epoch_id=digest("frozen-epoch"),
        unresolved_finding_ids=(digest("finding-1"),),
        l4_run_root_id=digest("l4-run-root"),
        l4_target_root_ids=(digest("l4-target-root"),),
        verification_receipt_ids=(digest("verification-receipt"),),
        closure_policy_id=digest("closure-policy"),
        source_snapshot_id=digest("source-snapshot"),
        partition_manifest_id=digest("partition-manifest"),
        selection_id=selection_scope_v1().identity,
    )


def closure_manifest_v7(
    *, run_id: str = "re-l4-closure"
) -> L4ClosureRunManifestV7:
    request = closure_request_v1()
    return L4ClosureRunManifestV7(
        schema_version=7,
        engine="re-v2",
        engine_protocol_version="2.8",
        run_mode="l4-closure-successor",
        requested_goals=("l4-evidence-closure",),
        target_layer="L4",
        run_id=run_id,
        created_at="2026-08-31T12:30:00Z",
        source_snapshot_id=request.source_snapshot_id,
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=request.partition_manifest_id,
        selection=selection_scope_v1(),
        lineage=L4ClosureLineageV1(
            schema_version=1,
            l3_run_id="re-l3-parent",
            l3_manifest_hash=request.blocked_l3_manifest_hash,
            l3_terminal_event_hash=request.blocked_l3_terminal_event_hash,
            l4_run_id="re-l4-evidence",
            l4_manifest_hash=digest("l4-evidence-manifest"),
            l4_terminal_event_hash=digest("l4-evidence-terminal"),
        ),
        closure_parent_bundle_id=digest("closure-parent-bundle"),
        closure_request=request,
        l4_run_root_id=request.l4_run_root_id,
        closure_policy_id=request.closure_policy_id,
    )


def exhaustive_manifest_with_budget(
    manifest: ExhaustiveRunManifestV7,
    *,
    token_limit: int,
) -> ExhaustiveRunManifestV7:
    return replace(
        manifest,
        budget_policy=exhaustive_budget_policy_v1(token_limit=token_limit),
    )

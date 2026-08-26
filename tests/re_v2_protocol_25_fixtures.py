from __future__ import annotations

from harness.re_v2.protocol_22.model import BudgetPolicyV2, CatalogReferenceV1
from harness.re_v2.protocol_24.model import ParentLineageV1, SelectionScopeV1
from harness.re_v2.protocol_25.model import RunManifestV4, SemanticClosurePolicyV1
from tests.re_v2_protocol_22_fixtures import digest


def catalog_reference(seed: str, relative_path: str) -> CatalogReferenceV1:
    return CatalogReferenceV1(digest(seed), relative_path)


def semantic_policy_v1() -> SemanticClosurePolicyV1:
    return SemanticClosurePolicyV1(
        schema_version=1,
        token_limit=500_000,
        active_ms_limit=1_800_000,
        max_rounds_per_target=3,
        consecutive_no_reduction_limit=2,
        provider_attempt_limit=2,
        contract_retry_limit=1,
        unknown_usage_policy="shared-conservative-reservation-v1",
    )


def manifest_v4(
    *,
    run_id: str = "re-l3-child",
    run_mode: str = "new-audit-epoch",
) -> RunManifestV4:
    successor = run_mode != "new-audit-epoch"
    return RunManifestV4(
        schema_version=4,
        engine="re-v2",
        engine_protocol_version="2.5",
        run_id=run_id,
        created_at="2026-08-26T12:00:00Z",
        source_snapshot_id=digest("workspace-snapshot"),
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=digest("partition-manifest"),
        workspace_partition_catalog=catalog_reference(
            "workspace-partition", "workspace-partition.json"
        ),
        artifact_policy_catalog=catalog_reference(
            "artifact-policy", "artifact-policy.json"
        ),
        executor_contract_catalog=catalog_reference(
            "executor-contract", "executor-contract.json"
        ),
        audit_policy_catalog=catalog_reference("audit-policy", "audit-policy.json"),
        parent_authority_bundle=catalog_reference(
            "parent-authority-v2", "parent-authority-v2.json"
        ),
        parent_lineage=ParentLineageV1(
            schema_version=1,
            direct_parent_run_id="re-parent",
            direct_parent_manifest_hash=digest("parent-manifest"),
            direct_parent_terminal_event_hash=digest("parent-terminal"),
            lineage_root_run_id="re-root",
            lineage_root_manifest_hash=digest("root-manifest"),
        ),
        requested_goals=("semantic-audit-closure",),
        target_layer="L3",
        selection=SelectionScopeV1(
            schema_version=1,
            all_sources=False,
            source_ids=("api",),
            domain_keys=(digest("orders-domain"),),
        ),
        run_mode=run_mode,
        frozen_audit_epoch=(
            catalog_reference("audit-epoch", "audit-epoch.json")
            if run_mode == "closure-successor"
            else None
        ),
        human_guidance=(
            catalog_reference("human-guidance", "human-guidance.json")
            if successor
            else None
        ),
        semantic_request_id=digest("semantic-request-v2"),
        initial_budget_policy=BudgetPolicyV2.for_goal(
            "semantic-audit-closure", 1_000_000, 3_600_000
        ),
        semantic_closure_policy=semantic_policy_v1(),
    )


__all__ = ("catalog_reference", "manifest_v4", "semantic_policy_v1")

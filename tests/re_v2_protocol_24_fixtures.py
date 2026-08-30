from __future__ import annotations

from harness.re_v2.protocol_22.model import BudgetPolicyV2, CatalogReferenceV1
from harness.re_v2.protocol_24.model import (
    ParentLineageV1,
    RunManifestV3,
    SelectionScopeV1,
)
from tests.re_v2_protocol_22_fixtures import digest


def catalog_reference(seed: str, relative_path: str) -> CatalogReferenceV1:
    return CatalogReferenceV1(digest(seed), relative_path)


def selection_scope_v1() -> SelectionScopeV1:
    return SelectionScopeV1(
        schema_version=1,
        all_sources=False,
        source_ids=("api",),
        domain_keys=(digest("orders-domain"),),
    )


def parent_lineage_v1() -> ParentLineageV1:
    return ParentLineageV1(
        schema_version=1,
        direct_parent_run_id="re-parent",
        direct_parent_manifest_hash=digest("parent-manifest"),
        direct_parent_terminal_event_hash=digest("parent-terminal"),
        lineage_root_run_id="re-root",
        lineage_root_manifest_hash=digest("root-manifest"),
    )


def manifest_v3(*, run_id: str = "re-child") -> RunManifestV3:
    return RunManifestV3(
        schema_version=3,
        engine="re-v2",
        engine_protocol_version="2.4",
        run_id=run_id,
        created_at="2026-08-24T12:00:00Z",
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
        parent_authority_bundle=catalog_reference(
            "parent-authority", "parent-authority.json"
        ),
        parent_lineage=parent_lineage_v1(),
        requested_goals=("selective-deepening",),
        target_layer="L2",
        selection=selection_scope_v1(),
        semantic_request_id=digest("semantic-request"),
        initial_budget_policy=BudgetPolicyV2(
            token_limit=1_000_000,
            active_ms_limit=3_600_000,
            provider_attempt_limit=2,
            artifact_generation_attempt_limit=2,
            semantic_repair_round_limit=0,
            result_contract_retry_limit=1,
            shared_retry_limit=1,
            artifact_contract_retry_limit=1,
        ),
    )


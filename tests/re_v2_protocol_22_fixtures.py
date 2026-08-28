from __future__ import annotations

import hashlib

from harness.re_v2.protocol_22.model import (
    ArtifactKeyV2,
    ArtifactScope,
    BudgetPolicyV2,
    CatalogReferenceV1,
    RunManifestV2,
    WorkItemV2,
    WorkTemplateV2,
    instantiate_work_item_v2,
)


def digest(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def budget_policy_v2(*, goal: str = "baseline") -> BudgetPolicyV2:
    return BudgetPolicyV2.for_goal(
        goal,
        token_limit=1_000_000,
        active_ms_limit=3_600_000,
    )


def artifact_scope_v2(*, domain: bool = False, content: bool = True) -> ArtifactScope:
    return ArtifactScope(
        source_id="api",
        domain_key=digest("orders-domain") if domain else None,
        content_id=digest("domain-content" if domain else "source-content") if content else None,
    )


def artifact_key_v2(
    *,
    domain: bool = False,
    artifact_kind: str | None = None,
    layer: str = "L0",
    dependency_hashes: tuple[str, ...] = (),
) -> ArtifactKeyV2:
    return ArtifactKeyV2(
        identity_schema_version=2,
        scope=artifact_scope_v2(domain=domain),
        partition_id=digest("domain-partition" if domain else "source-partition"),
        artifact_kind=artifact_kind or ("domain-inventory" if domain else "source-inventory"),
        layer=layer,
        producer_protocol_version="inventory-v1",
        layer_policy_hash=digest("inventory-policy"),
        dependency_hashes=dependency_hashes,
    )


def work_template_v2(
    *,
    domain: bool = False,
    artifact_kind: str | None = None,
    layer: str = "L0",
    required_template_ids: tuple[str, ...] = (),
) -> WorkTemplateV2:
    kind = artifact_kind or ("domain-inventory" if domain else "source-inventory")
    return WorkTemplateV2(
        identity_schema_version=2,
        goal_id="inventory",
        scope=artifact_scope_v2(domain=domain),
        artifact_kind=kind,
        layer=layer,
        producer_id="inventory",
        producer_family="inventory",
        producer_protocol_version="inventory-v1",
        layer_policy_hash=digest("inventory-policy"),
        required_template_ids=required_template_ids,
        executor_contract_hash=digest("inventory-executor"),
        verifier_id="inventory-verifier",
        verifier_version="v1",
        verifier_implementation_digest=digest("inventory-verifier-implementation"),
        result_contract_id="inventory-result-v1",
        max_provider_attempts=0,
        max_generation_attempts=1,
        max_semantic_rounds=0,
        max_result_contract_retries=0,
        max_shared_retries=0,
        max_artifact_contract_retries=0,
    )


def work_item_v2(
    *,
    domain: bool = False,
    artifact_kind: str | None = None,
    layer: str = "L0",
    dependency_hashes: tuple[str, ...] = (),
) -> WorkItemV2:
    template = work_template_v2(
        domain=domain,
        artifact_kind=artifact_kind,
        layer=layer,
    )
    key = artifact_key_v2(
        domain=domain,
        artifact_kind=template.artifact_kind,
        layer=layer,
        dependency_hashes=dependency_hashes,
    )
    return instantiate_work_item_v2(template, key, dependency_hashes)


def manifest_v2_dict(*, goal: str = "baseline", run_id: str = "re-demo") -> dict[str, object]:
    return {
        "schema_version": 2,
        "engine": "re-v2",
        "engine_protocol_version": "2.2",
        "run_id": run_id,
        "created_at": "2026-08-22T09:00:00Z",
        "source_snapshot_id": digest("workspace-snapshot"),
        "source_snapshot_kind": "workspace-git-composite",
        "partition_manifest_id": digest("partition-manifest"),
        "workspace_partition_catalog": CatalogReferenceV1(
            object_hash=digest("workspace-partition-catalog"),
            relative_path="workspace-partition.json",
        ).to_json_dict(),
        "artifact_policy_catalog": CatalogReferenceV1(
            object_hash=digest("artifact-policy-catalog"),
            relative_path="artifact-policy.json",
        ).to_json_dict(),
        "executor_contract_catalog": CatalogReferenceV1(
            object_hash=digest("executor-contract-catalog"),
            relative_path="executor-contract.json",
        ).to_json_dict(),
        "requested_goals": [goal],
        "initial_budget_policy": budget_policy_v2(goal=goal).to_json_dict(),
        "parent_run_id": None,
    }


def manifest_v2(*, goal: str = "baseline", run_id: str = "re-demo") -> RunManifestV2:
    return RunManifestV2.from_json_dict(manifest_v2_dict(goal=goal, run_id=run_id))

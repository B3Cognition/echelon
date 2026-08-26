from __future__ import annotations

from harness.re_v2.protocol_22.model import (
    ArtifactScope,
    BudgetPolicyV2,
    CatalogReferenceV1,
)
from harness.re_v2.protocol_24.model import ParentLineageV1, SelectionScopeV1
from harness.re_v2.protocol_25.findings import (
    AuditTargetV1,
    AuditedArtifactAuthorityV1,
    DeferredObservationV1,
    EvidenceAnchorAuthorityV1,
    FindingAuthorityVocabularyV1,
    FindingKeyV1,
    SemanticFindingV1,
    normalize_finding_key,
)
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


def audited_artifact_authority_v1(
    seed: str = "baseline",
) -> AuditedArtifactAuthorityV1:
    return AuditedArtifactAuthorityV1(
        schema_version=1,
        artifact_key_id=digest(f"{seed}-key"),
        artifact_hash=digest(seed),
        dependency_hashes=(digest(f"{seed}-dependency"),),
    )


def audit_target_v1(*, target_kind: str = "domain") -> AuditTargetV1:
    domain_key = digest("orders-domain") if target_kind == "domain" else None
    return AuditTargetV1(
        schema_version=1,
        target_kind=target_kind,
        scope=ArtifactScope("api", domain_key, digest("selected-content")),
        audited_artifacts=(audited_artifact_authority_v1(),),
        lower_dependency_hashes=(digest("lower-closure"),),
        context_object_hashes=(digest("audit-context"),),
        evidence_object_hashes=(digest("evidence-pack"),),
        audit_policy_hash=digest("audit-policy"),
        auditor_authority_hash=digest("validator-agent"),
        response_schema_hash=digest("audit-schema"),
    )


def finding_vocabulary_v1() -> FindingAuthorityVocabularyV1:
    target = audit_target_v1()
    return FindingAuthorityVocabularyV1(
        schema_version=1,
        audit_target_id=target.identity,
        rule_ids=("behavior.missing", "behavior.unsupported"),
        subject_refs=("operation:search", "surface:search"),
        claim_anchor_ids=("claim:search-success",),
        evidence_anchors=(
            EvidenceAnchorAuthorityV1(
                schema_version=1,
                anchor_id="evidence:retry-branch",
                aliases=("citation:client-42", "citation:client-43"),
            ),
        ),
    )


def finding_key_v1(
    *,
    subject_kind: str = "operation",
    subject_ref: str = "operation:search",
    evidence_refs: tuple[str, ...] = ("evidence:retry-branch",),
) -> FindingKeyV1:
    return normalize_finding_key(
        vocabulary=finding_vocabulary_v1(),
        audit_target=audit_target_v1(),
        rule_id="behavior.missing",
        finding_class="missing_behavior",
        subject_kind=subject_kind,
        subject_ref=subject_ref,
        claim_anchor_ids=(),
        evidence_refs=evidence_refs,
    )


def semantic_finding_v1(
    *,
    title: str = "Missing retry",
    explanation: str = "No retry exhaustion behavior is described.",
) -> SemanticFindingV1:
    return SemanticFindingV1(
        schema_version=1,
        finding_key=finding_key_v1(),
        title=title,
        explanation=explanation,
        recommendation="Describe the observed retry exhaustion behavior.",
        repair_context="Refine the search operation claim without editing L2.",
    )


def deferred_observation_v1(
    diagnostic: str = "A dynamic branch requires deeper evidence.",
) -> DeferredObservationV1:
    key = finding_key_v1()
    return DeferredObservationV1(
        schema_version=1,
        audit_target_id=key.audit_target_id,
        authority_vocabulary_id=key.authority_vocabulary_id,
        rule_id=key.rule_id,
        finding_class="requires_deeper_evidence",
        subject_kind=key.subject_kind,
        subject_ref=key.subject_ref,
        claim_anchor_ids=key.claim_anchor_ids,
        evidence_anchor_ids=key.evidence_anchor_ids,
        audited_artifact_hashes=key.audited_artifact_hashes,
        diagnostic=diagnostic,
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


__all__ = (
    "audit_target_v1",
    "audited_artifact_authority_v1",
    "catalog_reference",
    "deferred_observation_v1",
    "finding_key_v1",
    "finding_vocabulary_v1",
    "manifest_v4",
    "semantic_finding_v1",
    "semantic_policy_v1",
)

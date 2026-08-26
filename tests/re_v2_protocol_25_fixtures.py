from __future__ import annotations

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.model import (
    ArtifactKeyV2,
    ArtifactScope,
    BudgetPolicyV2,
    CatalogReferenceV1,
)
from harness.re_v2.protocol_24.model import ParentLineageV1, SelectionScopeV1
from harness.re_v2.protocol_24.model import (
    AdoptedArtifactAuthorityV1,
    ParentAuthorityBundleV1,
)
from harness.re_v2.protocol_25.adoption import (
    ParentSemanticAuthorityV1,
    Protocol25ParentCandidateV1,
)
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
from harness.re_v2.protocol_25.artifacts import (
    AuditCandidateV1,
    AuditClosureRootV1,
    AuditEpochV1,
    AuditTargetCandidateAuthorityV1,
    FindingAssessmentV1,
    FindingClosureReceiptV1,
    L3SourceRootV1,
    ResolutionEntryV1,
    SemanticCertificationReceiptV1,
    SemanticResolutionOverlayV1,
    SourceCompositionAssessmentV1,
    TargetClosureAssessmentV1,
    build_finding_closure_receipt,
    build_semantic_resolution_overlay,
    build_source_composition_assessment,
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


def lower_parent_authority_bundle_v1() -> ParentAuthorityBundleV1:
    artifact = AdoptedArtifactAuthorityV1(
        schema_version=1,
        artifact_key_id=digest("lower-key"),
        artifact_hash=digest("lower-artifact"),
        dependency_hashes=(digest("lower-dependency"),),
        certification_receipt_id=digest("lower-certification"),
        candidate_assessment_id=digest("lower-candidate"),
        artifact_acceptance_receipt_id=digest("lower-acceptance"),
        source_run_id="re-parent",
        source_ledger_entry_hash=digest("lower-ledger-entry"),
    )
    return ParentAuthorityBundleV1(
        schema_version=1,
        direct_parent_run_id="re-parent",
        source_manifest_hash=digest("parent-manifest"),
        source_event_chain_hash=digest("parent-events"),
        source_terminal_event_hash=digest("parent-terminal"),
        source_ledger_chain_hash=digest("parent-ledger"),
        lineage_root_run_id="re-root",
        ancestor_bundle_hashes=(digest("ancestor-bundle"),),
        artifacts=(artifact,),
    )


def parent_semantic_authority_v1(
    *,
    epoch: bool = False,
    unresolved_targets: bool = False,
    unresolved_findings: bool = False,
    deferred: bool = False,
) -> ParentSemanticAuthorityV1:
    return ParentSemanticAuthorityV1(
        schema_version=1,
        accepted_audit_target_ids=(digest("accepted-target"),),
        accepted_audit_candidate_hashes=(digest("accepted-candidate"),),
        unresolved_audit_target_ids=(
            (digest("missing-target"),) if unresolved_targets else ()
        ),
        audit_epoch_id=(digest("audit-epoch") if epoch else None),
        resolution_overlay_hashes=((digest("overlay"),) if epoch else ()),
        target_assessment_hashes=(
            (digest("target-assessment"),) if epoch else ()
        ),
        source_assessment_hashes=(
            (digest("source-assessment"),) if epoch else ()
        ),
        closure_receipt_ids=((digest("closure-receipt"),) if epoch else ()),
        closure_root_hash=(digest("closure-root") if epoch else None),
        unresolved_finding_ids=(
            (digest("open-finding"),) if unresolved_findings else ()
        ),
        deferred_observation_ids=(
            (digest("deferred-observation"),) if deferred else ()
        ),
        l3_source_root_hashes=((digest("l3-source-root"),) if epoch else ()),
    )


def protocol_25_parent_candidate_v1(
    parent_state: str,
    *,
    layer: str = "L3",
    semantic_authority: ParentSemanticAuthorityV1 | None = None,
    authentication_state: str = "authenticated",
    workspace_state: str = "clean_exact_commits",
    lineage_state: str = "acyclic",
    terminal: bool = True,
) -> Protocol25ParentCandidateV1:
    return Protocol25ParentCandidateV1(
        schema_version=1,
        parent_layer=layer,
        parent_state=parent_state,
        source_snapshot_id=digest("workspace-snapshot"),
        selection_id=digest("selection"),
        terminal_event_hash=(digest("parent-terminal") if terminal else None),
        authentication_state=authentication_state,
        workspace_state=workspace_state,
        lineage_state=lineage_state,
        lower_authority_bundle=lower_parent_authority_bundle_v1(),
        semantic_authority=(
            semantic_authority
            if semantic_authority is not None
            else (
                ParentSemanticAuthorityV1.empty()
                if layer in {"L1", "L2"}
                else parent_semantic_authority_v1()
            )
        ),
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
    from harness.re_v2.protocol_25.runtime import semantic_response_schema

    domain_key = digest("orders-domain") if target_kind == "domain" else None
    return AuditTargetV1(
        schema_version=1,
        target_kind=target_kind,
        scope=ArtifactScope("api", domain_key, digest("selected-content")),
        audited_artifacts=(audited_artifact_authority_v1(),),
        lower_dependency_hashes=tuple(
            sorted(
                digest(seed)
                for seed in (
                    "baseline",
                    "lower-closure",
                    "audit-context",
                    "evidence-pack",
                )
            )
        ),
        context_object_hashes=(digest("audit-context"),),
        evidence_object_hashes=(digest("evidence-pack"),),
        audit_policy_hash=digest("audit-policy"),
        auditor_authority_hash=digest("validator-agent"),
        response_schema_hash=content_digest(
            semantic_response_schema("semantic-audit-findings")
        ),
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


def l3_artifact_key_v2(
    artifact_kind: str,
    *,
    dependency_hashes: tuple[str, ...],
) -> ArtifactKeyV2:
    return ArtifactKeyV2(
        identity_schema_version=2,
        scope=audit_target_v1().scope,
        partition_id=digest("partition"),
        artifact_kind=artifact_kind,
        layer="L3",
        producer_protocol_version="2.5",
        layer_policy_hash=digest(f"{artifact_kind}-policy"),
        dependency_hashes=tuple(sorted(dependency_hashes)),
    )


def audit_candidate_v1(*, verdict: str = "REPAIR") -> AuditCandidateV1:
    target = audit_target_v1()
    return AuditCandidateV1(
        schema_version=1,
        audit_target=target,
        artifact_key=l3_artifact_key_v2(
            "semantic-audit-findings",
            dependency_hashes=(target.identity,),
        ),
        audit_epoch_id=None,
        verdict=verdict,
        findings=(semantic_finding_v1(),) if verdict == "REPAIR" else (),
    )


def audit_epoch_v1(*, candidate: AuditCandidateV1 | None = None) -> AuditEpochV1:
    selected = candidate or audit_candidate_v1()
    finding_ids = tuple(item.finding_key_id for item in selected.findings)
    return AuditEpochV1(
        schema_version=1,
        selection_id=digest("selection"),
        audit_policy_hash=digest("audit-policy"),
        target_candidate_authorities=(
            AuditTargetCandidateAuthorityV1(
                schema_version=1,
                audit_target_id=selected.audit_target_id,
                candidate_hash=selected.identity,
                certification_receipt_id=digest("audit-certification"),
                acceptance_receipt_id=digest("audit-acceptance"),
                finding_key_ids=finding_ids,
            ),
        ),
        auditor_authority_hash=digest("auditor"),
        executor_authority_hash=digest("executor"),
        verifier_authority_hash=digest("verifier"),
        finding_key_ids=finding_ids,
        audited_l2_root_hashes=(digest("l2-root"),),
    )


def resolution_entry_v1() -> ResolutionEntryV1:
    return ResolutionEntryV1(
        schema_version=1,
        finding_key_ids=(finding_key_v1().identity,),
        disposition="resolved",
        semantic_claims=("Retry exhaustion returns a bounded failure response.",),
        evidence_anchor_ids=("evidence:retry-branch",),
        supersedes_claim_anchor_ids=("claim:search-success",),
        refines_subject_refs=("operation:search",),
        unresolved=False,
    )


def semantic_resolution_overlay_v1(
    *,
    epoch: AuditEpochV1 | None = None,
) -> SemanticResolutionOverlayV1:
    selected_epoch = epoch or audit_epoch_v1()
    target = audit_target_v1()
    return build_semantic_resolution_overlay(
        epoch=selected_epoch,
        schema_version=1,
        artifact_key=l3_artifact_key_v2(
            "semantic-resolution-overlay",
            dependency_hashes=(selected_epoch.identity, target.identity),
        ),
        audit_target_id=target.identity,
        semantic_round=1,
        prior_overlay_hashes=(),
        guidance_hash=None,
        entries=(resolution_entry_v1(),),
    )


def target_closure_assessment_v1(
    *,
    epoch: AuditEpochV1 | None = None,
    overlay: SemanticResolutionOverlayV1 | None = None,
) -> TargetClosureAssessmentV1:
    selected_epoch = epoch or audit_epoch_v1()
    selected_overlay = overlay or semantic_resolution_overlay_v1(epoch=selected_epoch)
    return TargetClosureAssessmentV1(
        schema_version=1,
        audit_epoch_id=selected_epoch.identity,
        audit_target_id=audit_target_v1().identity,
        assessed_finding_ids=selected_epoch.finding_key_ids,
        verdicts=tuple(
            FindingAssessmentV1(1, item, "closed", "resolved_by_overlay")
            for item in selected_epoch.finding_key_ids
        ),
        resolution_overlay_hash=selected_overlay.identity,
        verifier_authority_hash=digest("closure-verifier"),
        context_authority_hash=digest("closure-context"),
        deferred_observations=(),
    )


def source_composition_assessment_v1(
    *,
    epoch: AuditEpochV1 | None = None,
    target: TargetClosureAssessmentV1 | None = None,
) -> SourceCompositionAssessmentV1:
    selected_epoch = epoch or audit_epoch_v1()
    selected_target = target or target_closure_assessment_v1(epoch=selected_epoch)
    return build_source_composition_assessment(
        epoch=selected_epoch,
        schema_version=1,
        source_id="api",
        overlay_hashes=(selected_target.resolution_overlay_hash,),
        target_assessment_hashes=(selected_target.identity,),
        composed_authority_hash=digest("composed-source"),
        implicated_finding_ids=(),
        deferred_observations=(),
        outcome="passed",
    )


def semantic_certification_receipt_v1() -> SemanticCertificationReceiptV1:
    key = l3_artifact_key_v2(
        "semantic-audit-findings",
        dependency_hashes=(audit_target_v1().identity,),
    )
    return SemanticCertificationReceiptV1(
        schema_version=1,
        artifact_key_id=key.identity,
        artifact_hash=digest("audit-artifact"),
        verifier_authority_hash=digest("semantic-verifier"),
        audit_epoch_id=None,
        audit_target_id=audit_target_v1().identity,
        evidence_scope_hash=digest("audit-evidence-scope"),
        verdict="accepted",
        normalized_diagnostics=(),
    )


def finding_closure_receipt_v1() -> FindingClosureReceiptV1:
    epoch = audit_epoch_v1()
    overlay = semantic_resolution_overlay_v1(epoch=epoch)
    target = target_closure_assessment_v1(epoch=epoch, overlay=overlay)
    source = source_composition_assessment_v1(epoch=epoch, target=target)
    return build_finding_closure_receipt(
        epoch=epoch,
        target_assessment=target,
        source_assessment=source,
        schema_version=1,
        finding_key_id=epoch.finding_key_ids[0],
        audit_target_id=audit_target_v1().identity,
        resolution_overlay_hash=overlay.identity,
        closure_verifier_authority_hash=digest("closure-verifier"),
        context_authority_hash=digest("closure-context"),
        semantic_round=1,
        verdict="closed",
        reason_code="resolved_by_overlay",
        diagnostic="The overlay resolves the frozen finding.",
        previous_closure_receipt_id=None,
    )


def audit_closure_root_v1() -> AuditClosureRootV1:
    epoch = audit_epoch_v1()
    receipt = finding_closure_receipt_v1()
    target_id = audit_target_v1().identity
    return AuditClosureRootV1(
        schema_version=1,
        audit_epoch_id=epoch.identity,
        frozen_finding_ids=epoch.finding_key_ids,
        latest_closure_receipts=(receipt,),
        unresolved_finding_ids=(),
        target_rounds=((target_id, 1),),
        plateau_counts=((target_id, 0),),
        deferred_observations=(),
    )


def l3_source_root_v1() -> L3SourceRootV1:
    closure = audit_closure_root_v1()
    return L3SourceRootV1(
        schema_version=1,
        source_id="api",
        selected_domain_keys=(digest("orders-domain"),),
        full_source_coverage=False,
        audit_target_ids=(audit_target_v1().identity,),
        closure_root_hashes=(closure.identity,),
        adopted_l2_root_hash=digest("l2-root"),
        unresolved_finding_ids=(),
        deferred_observation_ids=(),
        state="complete",
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
    "audit_candidate_v1",
    "audit_closure_root_v1",
    "audit_epoch_v1",
    "audit_target_v1",
    "audited_artifact_authority_v1",
    "catalog_reference",
    "deferred_observation_v1",
    "finding_closure_receipt_v1",
    "finding_key_v1",
    "finding_vocabulary_v1",
    "l3_artifact_key_v2",
    "l3_source_root_v1",
    "lower_parent_authority_bundle_v1",
    "manifest_v4",
    "parent_semantic_authority_v1",
    "protocol_25_parent_candidate_v1",
    "resolution_entry_v1",
    "semantic_certification_receipt_v1",
    "semantic_finding_v1",
    "semantic_policy_v1",
    "semantic_resolution_overlay_v1",
    "source_composition_assessment_v1",
    "target_closure_assessment_v1",
)

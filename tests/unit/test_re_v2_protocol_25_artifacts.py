from __future__ import annotations

from dataclasses import replace
import importlib

import pytest

from harness.re_v2.protocol_22.model import ArtifactKeyV2, ArtifactScope
from harness.re_v2.protocol_25.policies import (
    SEMANTIC_PRODUCER_PROTOCOL_BY_ARTIFACT,
)
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_25_fixtures import (
    audit_target_v1,
    deferred_observation_v1,
    finding_key_v1,
    semantic_finding_v1,
)


def _artifacts():  # type: ignore[no-untyped-def]
    try:
        return importlib.import_module("harness.re_v2.protocol_25.artifacts")
    except ModuleNotFoundError:
        pytest.fail("protocol 2.5 L3 artifact authority is not registered")


def _artifact_key(
    artifact_kind: str,
    *,
    scope: ArtifactScope | None = None,
    dependency_hashes: tuple[str, ...],
) -> ArtifactKeyV2:
    return ArtifactKeyV2(
        identity_schema_version=2,
        scope=scope or audit_target_v1().scope,
        partition_id=digest("partition"),
        artifact_kind=artifact_kind,
        layer="L3",
        producer_protocol_version=SEMANTIC_PRODUCER_PROTOCOL_BY_ARTIFACT[
            artifact_kind
        ],
        layer_policy_hash=digest(f"{artifact_kind}-policy"),
        dependency_hashes=tuple(sorted(dependency_hashes)),
    )


def _audit_candidate(*, verdict: str = "REPAIR"):  # type: ignore[no-untyped-def]
    module = _artifacts()
    target = audit_target_v1()
    findings = (semantic_finding_v1(),) if verdict == "REPAIR" else ()
    return module.AuditCandidateV1(
        schema_version=1,
        audit_target=target,
        artifact_key=_artifact_key(
            "semantic-audit-findings",
            dependency_hashes=(target.identity,),
        ),
        audit_epoch_id=None,
        verdict=verdict,
        findings=findings,
    )


def _audit_epoch(*, findings=None):  # type: ignore[no-untyped-def]
    module = _artifacts()
    candidate = _audit_candidate(verdict="PASS" if findings == () else "REPAIR")
    selected_findings = (
        candidate.findings if findings is None else tuple(findings)
    )
    return module.AuditEpochV1(
        schema_version=1,
        selection_id=digest("selection"),
        audit_policy_hash=digest("audit-policy"),
        target_candidate_authorities=(
            module.AuditTargetCandidateAuthorityV1(
                schema_version=1,
                audit_target_id=candidate.audit_target.identity,
                candidate_hash=candidate.identity,
                certification_receipt_id=digest("audit-certification"),
                acceptance_receipt_id=digest("audit-acceptance"),
                finding_key_ids=tuple(
                    finding.finding_key_id for finding in selected_findings
                ),
            ),
        ),
        auditor_authority_hash=digest("auditor"),
        executor_authority_hash=digest("executor"),
        verifier_authority_hash=digest("verifier"),
        finding_key_ids=tuple(
            sorted(finding.finding_key_id for finding in selected_findings)
        ),
        audited_l2_root_hashes=(digest("l2-root"),),
    )


def _resolution_entry(*, finding_ids=None, disposition: str = "resolved"):  # type: ignore[no-untyped-def]
    module = _artifacts()
    ids = (finding_key_v1().identity,) if finding_ids is None else tuple(finding_ids)
    return module.ResolutionEntryV1(
        schema_version=1,
        finding_key_ids=ids,
        disposition=disposition,
        semantic_claims=("Retry exhaustion returns a bounded failure response.",),
        evidence_anchor_ids=("evidence:retry-branch",),
        supersedes_claim_anchor_ids=("claim:search-success",),
        refines_subject_refs=("operation:search",),
        unresolved=disposition != "resolved",
    )


def _overlay(*, epoch=None, entries=None, prior=()):  # type: ignore[no-untyped-def]
    module = _artifacts()
    selected_epoch = epoch or _audit_epoch()
    target = audit_target_v1()
    selected_entries = (_resolution_entry(),) if entries is None else tuple(entries)
    return module.build_semantic_resolution_overlay(
        epoch=selected_epoch,
        schema_version=1,
        artifact_key=_artifact_key(
            "semantic-resolution-overlay",
            dependency_hashes=tuple(
                sorted((selected_epoch.identity, target.identity, *prior))
            ),
        ),
        audit_target_id=target.identity,
        semantic_round=2 if prior else 1,
        prior_overlay_hashes=prior,
        guidance_hash=None,
        entries=selected_entries,
    )


def _target_assessment(*, epoch=None, overlay=None, deferred=()):  # type: ignore[no-untyped-def]
    module = _artifacts()
    selected_epoch = epoch or _audit_epoch()
    selected_overlay = overlay or _overlay(epoch=selected_epoch)
    target = audit_target_v1()
    return module.TargetClosureAssessmentV1(
        schema_version=1,
        audit_epoch_id=selected_epoch.identity,
        audit_target_id=target.identity,
        assessed_finding_ids=selected_epoch.finding_key_ids,
        verdicts=tuple(
            module.FindingAssessmentV1(
                schema_version=1,
                finding_key_id=finding_id,
                verdict="closed",
                reason_code="resolved_by_overlay",
            )
            for finding_id in selected_epoch.finding_key_ids
        ),
        resolution_overlay_hash=selected_overlay.identity,
        verifier_authority_hash=digest("closure-verifier"),
        context_authority_hash=digest("closure-context"),
        deferred_observations=tuple(deferred),
    )


def _source_assessment(*, epoch=None, target_assessment=None, outcome="passed", implicated=(), deferred=()):  # type: ignore[no-untyped-def]
    module = _artifacts()
    selected_epoch = epoch or _audit_epoch()
    selected_target = target_assessment or _target_assessment(epoch=selected_epoch)
    return module.build_source_composition_assessment(
        epoch=selected_epoch,
        schema_version=1,
        source_id="api",
        overlay_hashes=(selected_target.resolution_overlay_hash,),
        target_assessment_hashes=(selected_target.identity,),
        composed_authority_hash=digest("composed-source"),
        implicated_finding_ids=tuple(implicated),
        deferred_observations=tuple(deferred),
        outcome=outcome,
    )


def _closure_receipt(*, previous=None, source_assessment=None):  # type: ignore[no-untyped-def]
    module = _artifacts()
    epoch = _audit_epoch()
    overlay = _overlay(epoch=epoch)
    target = _target_assessment(epoch=epoch, overlay=overlay)
    source = source_assessment or _source_assessment(
        epoch=epoch,
        target_assessment=target,
    )
    return module.build_finding_closure_receipt(
        epoch=epoch,
        target_assessment=target,
        source_assessment=source,
        schema_version=1,
        finding_key_id=epoch.finding_key_ids[0],
        audit_target_id=audit_target_v1().identity,
        resolution_overlay_hash=overlay.identity,
        closure_verifier_authority_hash=digest("closure-verifier"),
        context_authority_hash=digest("closure-context"),
        semantic_round=2 if previous is not None else 1,
        verdict="closed",
        reason_code="resolved_by_overlay",
        diagnostic="The overlay resolves the frozen finding.",
        previous_closure_receipt_id=previous,
    )


def _semantic_certification(*, verdict: str = "accepted"):  # type: ignore[no-untyped-def]
    module = _artifacts()
    key = _artifact_key(
        "semantic-audit-findings",
        dependency_hashes=(audit_target_v1().identity,),
    )
    return module.SemanticCertificationReceiptV1(
        schema_version=1,
        artifact_key_id=key.identity,
        artifact_hash=digest("audit-artifact"),
        verifier_authority_hash=digest("semantic-verifier"),
        audit_epoch_id=None,
        audit_target_id=audit_target_v1().identity,
        evidence_scope_hash=digest("audit-evidence-scope"),
        verdict=verdict,
        normalized_diagnostics=(
            () if verdict == "accepted" else ("Evidence anchor is outside target.",)
        ),
    )
def test_audit_candidate_binds_target_and_requires_null_epoch() -> None:
    candidate = _audit_candidate()

    assert candidate.audit_target_id == audit_target_v1().identity
    with pytest.raises(_artifacts().Protocol25SchemaError, match="null epoch"):
        replace(candidate, audit_epoch_id=digest("premature-epoch"))
    with pytest.raises(_artifacts().Protocol25SchemaError, match="dependency"):
        replace(
            candidate,
            artifact_key=_artifact_key(
                "semantic-audit-findings",
                dependency_hashes=(digest("wrong-target"),),
            ),
        )


@pytest.mark.parametrize(("verdict", "finding_count"), (("PASS", 1), ("REPAIR", 0)))
def test_audit_candidate_verdict_matches_findings(verdict: str, finding_count: int) -> None:
    candidate = _audit_candidate(verdict="REPAIR")
    findings = (semantic_finding_v1(),) if finding_count else ()

    with pytest.raises(_artifacts().Protocol25SchemaError, match="verdict"):
        replace(candidate, verdict=verdict, findings=findings)


def test_epoch_identity_is_independent_of_run_and_time() -> None:
    first = _audit_epoch()
    second = _audit_epoch()

    assert not hasattr(first, "run_id")
    assert not hasattr(first, "created_at")
    assert first.identity == second.identity


def test_zero_finding_epoch_is_valid() -> None:
    assert _audit_epoch(findings=()).finding_key_ids == ()


def test_epoch_finding_set_equals_candidate_authority() -> None:
    epoch = _audit_epoch()

    with pytest.raises(_artifacts().Protocol25SchemaError, match="candidate"):
        replace(epoch, finding_key_ids=())


def test_pre_epoch_semantic_certification_has_null_epoch() -> None:
    receipt = _semantic_certification()

    assert receipt.audit_epoch_id is None
    with pytest.raises(_artifacts().Protocol25SchemaError, match="verdict"):
        replace(receipt, verdict="rejected")


def test_protocol_package_exports_l3_authorities() -> None:
    protocol = importlib.import_module("harness.re_v2.protocol_25")
    module = _artifacts()

    for name in (
        "AuditCandidateV1",
        "AuditEpochV1",
        "SemanticResolutionOverlayV1",
        "SemanticCertificationReceiptV1",
        "TargetClosureAssessmentV1",
        "SourceCompositionAssessmentV1",
        "FindingClosureReceiptV1",
        "AuditClosureRootV1",
        "L3SourceRootV1",
    ):
        assert getattr(protocol, name) is getattr(module, name)


def test_resolution_rejects_non_epoch_finding() -> None:
    epoch = _audit_epoch()

    with pytest.raises(_artifacts().Protocol25SchemaError, match="outside audit epoch"):
        _overlay(
            epoch=epoch,
            entries=(_resolution_entry(finding_ids=(digest("not-in-epoch"),)),),
        )


def test_resolution_requires_exact_prior_overlay_chain() -> None:
    module = _artifacts()
    epoch = _audit_epoch()

    with pytest.raises(module.Protocol25SchemaError, match="dependency"):
        module.build_semantic_resolution_overlay(
            epoch=epoch,
            schema_version=1,
            artifact_key=_artifact_key(
                "semantic-resolution-overlay",
                dependency_hashes=(epoch.identity, audit_target_v1().identity),
            ),
            audit_target_id=audit_target_v1().identity,
            semantic_round=2,
            prior_overlay_hashes=(digest("round-1-overlay"),),
            guidance_hash=None,
            entries=(_resolution_entry(),),
        )


def test_resolution_requires_supersession_for_resolved_claim() -> None:
    with pytest.raises(_artifacts().Protocol25SchemaError, match="supersession"):
        replace(
            _resolution_entry(),
            supersedes_claim_anchor_ids=(),
            refines_subject_refs=(),
        )


def test_qualified_resolution_can_close_a_finding() -> None:
    qualified = replace(
        _resolution_entry(),
        disposition="qualified",
        unresolved=False,
    )

    assert qualified.disposition == "qualified"


def test_target_assessment_covers_each_finding_exactly_once() -> None:
    assessment = _target_assessment()

    with pytest.raises(_artifacts().Protocol25SchemaError, match="exactly"):
        replace(assessment, verdicts=assessment.verdicts + assessment.verdicts)


def test_source_assessment_rejects_new_finding() -> None:
    with pytest.raises(_artifacts().Protocol25SchemaError, match="outside audit epoch"):
        _source_assessment(implicated=(digest("new-finding"),), outcome="failed")


def test_closure_receipt_requires_passing_source_guard() -> None:
    epoch = _audit_epoch()
    target = _target_assessment(epoch=epoch)
    failed = _source_assessment(
        epoch=epoch,
        target_assessment=target,
        outcome="failed",
        implicated=epoch.finding_key_ids,
    )

    with pytest.raises(_artifacts().Protocol25SchemaError, match="source composition"):
        _closure_receipt(source_assessment=failed)


def test_later_closure_receipt_requires_previous_dependency() -> None:
    first = _closure_receipt()
    second = _closure_receipt(previous=first.identity)

    assert second.previous_closure_receipt_id == first.identity
    with pytest.raises(_artifacts().Protocol25SchemaError, match="previous"):
        replace(second, semantic_round=2, previous_closure_receipt_id=None)


def test_closure_root_unresolved_set_equals_latest_receipts() -> None:
    module = _artifacts()
    epoch = _audit_epoch()
    receipt = replace(_closure_receipt(), verdict="open", reason_code="still_open")

    root = module.AuditClosureRootV1(
        schema_version=1,
        audit_epoch_id=epoch.identity,
        frozen_finding_ids=epoch.finding_key_ids,
        latest_closure_receipts=(receipt,),
        unresolved_finding_ids=epoch.finding_key_ids,
        target_rounds=((audit_target_v1().identity, 1),),
        plateau_counts=((audit_target_v1().identity, 0),),
        deferred_observations=(),
    )
    assert root.unresolved_finding_ids == epoch.finding_key_ids

    with pytest.raises(module.Protocol25SchemaError, match="unresolved"):
        replace(root, unresolved_finding_ids=())

    with pytest.raises(module.Protocol25SchemaError, match="sorted and unique"):
        replace(
            root,
            target_rounds=(
                (audit_target_v1().identity, 0),
                (audit_target_v1().identity, 1),
            ),
        )


def test_source_root_complete_requires_no_open_or_deferred_authority() -> None:
    module = _artifacts()
    complete = module.L3SourceRootV1(
        schema_version=1,
        source_id="api",
        selected_domain_keys=(digest("orders-domain"),),
        full_source_coverage=False,
        audit_target_ids=(audit_target_v1().identity,),
        closure_root_hashes=(digest("closure-root"),),
        adopted_l2_root_hash=digest("l2-root"),
        unresolved_finding_ids=(),
        deferred_observation_ids=(),
        state="complete",
    )
    assert complete.state == "complete"

    with pytest.raises(module.Protocol25SchemaError, match="complete"):
        replace(complete, unresolved_finding_ids=(finding_key_v1().identity,))
    with pytest.raises(module.Protocol25SchemaError, match="complete"):
        replace(
            complete,
            deferred_observation_ids=(deferred_observation_v1().observation_id,),
        )


def test_all_l3_authorities_round_trip_exactly() -> None:
    module = _artifacts()
    epoch = _audit_epoch()
    overlay = _overlay(epoch=epoch)
    target = _target_assessment(epoch=epoch, overlay=overlay)
    source = _source_assessment(epoch=epoch, target_assessment=target)
    receipt = _closure_receipt()
    root = module.AuditClosureRootV1(
        schema_version=1,
        audit_epoch_id=epoch.identity,
        frozen_finding_ids=epoch.finding_key_ids,
        latest_closure_receipts=(receipt,),
        unresolved_finding_ids=(),
        target_rounds=((audit_target_v1().identity, 1),),
        plateau_counts=((audit_target_v1().identity, 0),),
        deferred_observations=(),
    )
    source_root = module.L3SourceRootV1(
        schema_version=1,
        source_id="api",
        selected_domain_keys=(digest("orders-domain"),),
        full_source_coverage=False,
        audit_target_ids=(audit_target_v1().identity,),
        closure_root_hashes=(root.identity,),
        adopted_l2_root_hash=digest("l2-root"),
        unresolved_finding_ids=(),
        deferred_observation_ids=(),
        state="complete",
    )

    for value in (
        _audit_candidate(),
        epoch,
        _resolution_entry(),
        overlay,
        target.verdicts[0],
        target,
        source,
        _semantic_certification(),
        receipt,
        root,
        source_root,
    ):
        assert type(value).from_json_dict(value.to_json_dict()) == value

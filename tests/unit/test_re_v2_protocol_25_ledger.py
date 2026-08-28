from __future__ import annotations

from dataclasses import dataclass, replace
import importlib
import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_22.baseline import (
    ArtifactAcceptanceReceiptV2,
    CandidateAssessmentReceiptV1,
)
from harness.re_v2.protocol_25.artifacts import (
    AuditClosureRootV1,
    AuditEpochV1,
    AuditTargetCandidateAuthorityV1,
    FindingClosureReceiptV1,
    L3SourceRootV1,
    SemanticCertificationReceiptV1,
    SourceCompositionAssessmentV1,
    TargetClosureAssessmentV1,
    build_finding_closure_receipt,
)
from harness.re_v2.protocol_25.ledger import Protocol25Ledger
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_25_fixtures import (
    audit_candidate_v1,
    deferred_observation_v1,
    semantic_resolution_overlay_v1,
    source_composition_assessment_v1,
    target_closure_assessment_v1,
)
from tests.unit.test_re_v2_protocol_22_ledger import _deterministic_authority


def _ledger(tmp_path: Path) -> tuple[Protocol25Ledger, ObjectStore]:
    objects = ObjectStore(tmp_path / "objects")
    return Protocol25Ledger(tmp_path / "ledger.jsonl", objects), objects


def _put(objects: ObjectStore, authority) -> str:  # type: ignore[no-untyped-def]
    return objects.put_blob(canonical_json_bytes(authority.to_json_dict()))


def _record_semantic_artifact(
    ledger: Protocol25Ledger,
    objects: ObjectStore,
    authority,
    *,
    audit_target_id: str,
    audit_epoch_id: str | None,
):  # type: ignore[no-untyped-def]
    artifact_hash = _put(objects, authority)
    certification = SemanticCertificationReceiptV1(
        schema_version=1,
        artifact_key_id=authority.artifact_key.identity,
        artifact_hash=artifact_hash,
        verifier_authority_hash=digest("semantic-verifier"),
        audit_epoch_id=audit_epoch_id,
        audit_target_id=audit_target_id,
        evidence_scope_hash=digest("semantic-evidence-scope"),
        verdict="accepted",
        normalized_diagnostics=(),
    )
    ledger.record_semantic_certification(certification)
    capture = objects.put_blob(f"capture:{artifact_hash}".encode())
    candidate = CandidateAssessmentReceiptV1(
        schema_version=1,
        candidate_id=digest(f"provider-candidate:{artifact_hash}"),
        work_item_id=digest(f"semantic-work:{artifact_hash}"),
        execution_capture_hash=capture,
        normalized_authorial_payload_hash=artifact_hash,
        artifact_hash=artifact_hash,
        certification_receipt_id=certification.identity,
        outcome="certified",
        normalized_diagnostics=(),
    )
    ledger.record_candidate_assessment(candidate)
    acceptance = ArtifactAcceptanceReceiptV2(
        schema_version=2,
        artifact_key=authority.artifact_key,
        artifact_hash=artifact_hash,
        certification_receipt_id=certification.identity,
    )
    ledger.record_artifact_acceptance(acceptance)
    return certification, candidate, acceptance


@dataclass(frozen=True)
class _EpochFixture:
    epoch: AuditEpochV1
    candidate: object
    certification: SemanticCertificationReceiptV1
    acceptance: ArtifactAcceptanceReceiptV2


def _record_epoch(
    ledger: Protocol25Ledger,
    objects: ObjectStore,
) -> _EpochFixture:
    candidate = audit_candidate_v1()
    certification, _assessment, acceptance = _record_semantic_artifact(
        ledger,
        objects,
        candidate,
        audit_target_id=candidate.audit_target_id,
        audit_epoch_id=None,
    )
    epoch = AuditEpochV1(
        schema_version=1,
        selection_id=digest("selection"),
        audit_policy_hash=candidate.audit_target.audit_policy_hash,
        target_candidate_authorities=(
            AuditTargetCandidateAuthorityV1(
                schema_version=1,
                audit_target_id=candidate.audit_target_id,
                candidate_hash=candidate.identity,
                certification_receipt_id=certification.identity,
                acceptance_receipt_id=acceptance.identity,
                finding_key_ids=tuple(
                    item.finding_key_id for item in candidate.findings
                ),
            ),
        ),
        auditor_authority_hash=candidate.audit_target.auditor_authority_hash,
        executor_authority_hash=digest("semantic-executor"),
        verifier_authority_hash=certification.verifier_authority_hash,
        finding_key_ids=tuple(item.finding_key_id for item in candidate.findings),
        audited_l2_root_hashes=(objects.put_blob(b"accepted L2 root\n"),),
    )
    _put(objects, epoch)
    ledger.record_audit_epoch(epoch)
    return _EpochFixture(epoch, candidate, certification, acceptance)


@dataclass(frozen=True)
class _ClosureFixture:
    epoch: AuditEpochV1
    overlay: object
    target: TargetClosureAssessmentV1
    source: SourceCompositionAssessmentV1
    receipt: FindingClosureReceiptV1


def _record_closure_prerequisites(
    ledger: Protocol25Ledger,
    objects: ObjectStore,
    *,
    record_target: bool = True,
    record_source: bool = True,
) -> _ClosureFixture:
    epoch_fixture = _record_epoch(ledger, objects)
    epoch = epoch_fixture.epoch
    candidate = epoch_fixture.candidate
    overlay = semantic_resolution_overlay_v1(epoch=epoch)
    _record_semantic_artifact(
        ledger,
        objects,
        overlay,
        audit_target_id=candidate.audit_target_id,
        audit_epoch_id=epoch.identity,
    )
    target = target_closure_assessment_v1(epoch=epoch, overlay=overlay)
    _put(objects, target)
    if record_target:
        ledger.record_target_closure_assessment(target)
    source = source_composition_assessment_v1(epoch=epoch, target=target)
    composed = objects.put_blob(b"composed semantic source authority\n")
    source = replace(source, composed_authority_hash=composed)
    _put(objects, source)
    if record_source:
        ledger.record_source_composition_assessment(source)
    receipt = build_finding_closure_receipt(
        epoch=epoch,
        target_assessment=target,
        source_assessment=source,
        schema_version=1,
        finding_key_id=epoch.finding_key_ids[0],
        audit_target_id=candidate.audit_target_id,
        resolution_overlay_hash=overlay.identity,
        closure_verifier_authority_hash=digest("closure-verifier"),
        context_authority_hash=digest("closure-context"),
        semantic_round=1,
        verdict="closed",
        reason_code="resolved_by_overlay",
        diagnostic="The frozen finding is closed.",
        previous_closure_receipt_id=None,
    )
    _put(objects, receipt)
    return _ClosureFixture(epoch, overlay, target, source, receipt)


def test_semantic_ledger_replays_shared_and_l3_receipts(tmp_path: Path) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, acceptance = _deterministic_authority(objects)
    ledger.record_certification(certification, item)
    ledger.record_artifact_acceptance(acceptance)
    closure = _record_closure_prerequisites(ledger, objects)
    ledger.record_finding_closure(closure.receipt)
    target_id = closure.epoch.audit_target_ids[0]
    root = AuditClosureRootV1(
        1,
        closure.epoch.identity,
        closure.epoch.finding_key_ids,
        (closure.receipt,),
        (),
        ((target_id, 1),),
        ((target_id, 0),),
        (),
    )
    _put(objects, root)
    ledger.record_audit_closure_root(root)
    source_root = L3SourceRootV1(
        1,
        "api",
        (digest("orders-domain"),),
        False,
        closure.epoch.audit_target_ids,
        (root.identity,),
        objects.put_blob(b"accepted L2 source root\n"),
        (),
        (),
        "complete",
    )
    _put(objects, source_root)
    ledger.record_l3_source_root(source_root)

    replayed = ledger.replay()

    assert replayed.accepted_artifacts[item.output_key.identity] == acceptance
    assert replayed.semantic_certifications
    assert replayed.audit_epochs == {closure.epoch.identity: closure.epoch}
    assert replayed.finding_closures[closure.receipt.identity] == closure.receipt
    assert replayed.audit_closure_roots[root.identity] == root
    assert replayed.l3_source_roots["api"] == source_root
    semantic_candidate = next(
        item
        for item in replayed.candidate_assessments.values()
        if item.certification_receipt_id in replayed.semantic_certifications
    )
    assert replayed.work_failure(semantic_candidate.work_item_id) is None


def test_semantic_certification_requires_object_and_unique_artifact_key(
    tmp_path: Path,
) -> None:
    ledger, objects = _ledger(tmp_path)
    candidate = audit_candidate_v1()
    missing = SemanticCertificationReceiptV1(
        1,
        candidate.artifact_key.identity,
        candidate.identity,
        digest("verifier"),
        None,
        candidate.audit_target_id,
        digest("scope"),
        "accepted",
        (),
    )
    with pytest.raises(ReV2LedgerError, match="object"):
        ledger.record_semantic_certification(missing)

    first, _assessment, _acceptance = _record_semantic_artifact(
        ledger,
        objects,
        candidate,
        audit_target_id=candidate.audit_target_id,
        audit_epoch_id=None,
    )
    assert ledger.record_semantic_certification(first).seq == 1
    alternate_hash = objects.put_blob(b"different semantic artifact\n")
    conflicting = replace(first, artifact_hash=alternate_hash)
    with pytest.raises(ReV2LedgerError, match="conflicting semantic certification"):
        ledger.record_semantic_certification(conflicting)


def test_target_assessment_rejects_wrong_epoch_target_and_deferred_identity(
    tmp_path: Path,
) -> None:
    ledger, objects = _ledger(tmp_path)
    closure = _record_closure_prerequisites(
        ledger, objects, record_target=False, record_source=False
    )
    wrong_epoch = replace(closure.target, audit_epoch_id=digest("other-epoch"))
    _put(objects, wrong_epoch)
    with pytest.raises(ReV2LedgerError, match="epoch"):
        ledger.record_target_closure_assessment(wrong_epoch)

    wrong_target = replace(closure.target, audit_target_id=digest("other-target"))
    _put(objects, wrong_target)
    with pytest.raises(ReV2LedgerError, match="target"):
        ledger.record_target_closure_assessment(wrong_target)

    observation = replace(
        deferred_observation_v1(),
        audit_target_id=digest("other-target"),
    )
    deferred = replace(closure.target, deferred_observations=(observation,))
    _put(objects, deferred)
    with pytest.raises(ReV2LedgerError, match="deferred observation"):
        ledger.record_target_closure_assessment(deferred)


def test_finding_close_requires_assessments_and_passing_source(tmp_path: Path) -> None:
    ledger, objects = _ledger(tmp_path)
    closure = _record_closure_prerequisites(
        ledger, objects, record_target=False, record_source=False
    )

    with pytest.raises(ReV2LedgerError, match="preceding target assessment"):
        ledger.record_finding_closure(closure.receipt)

    ledger.record_target_closure_assessment(closure.target)
    failed_source = replace(
        closure.source,
        outcome="failed",
        implicated_finding_ids=(closure.epoch.finding_key_ids[0],),
    )
    _put(objects, failed_source)
    ledger.record_source_composition_assessment(failed_source)
    receipt = replace(
        closure.receipt,
        source_composition_assessment_hash=failed_source.identity,
    )
    _put(objects, receipt)
    with pytest.raises(ReV2LedgerError, match="passing source"):
        ledger.record_finding_closure(receipt)


def test_non_epoch_finding_and_out_of_order_receipt_fail_closed(tmp_path: Path) -> None:
    ledger, objects = _ledger(tmp_path)
    closure = _record_closure_prerequisites(ledger, objects)
    outside = replace(closure.receipt, finding_key_id=digest("outside-finding"))
    _put(objects, outside)
    with pytest.raises(ReV2LedgerError, match="outside.*epoch"):
        ledger.record_finding_closure(outside)

    ledger.record_finding_closure(closure.receipt)
    skipped = replace(
        closure.receipt,
        semantic_round=3,
        previous_closure_receipt_id=closure.receipt.identity,
    )
    _put(objects, skipped)
    with pytest.raises(ReV2LedgerError, match="consecutive|preceding receipt"):
        ledger.record_finding_closure(skipped)

    missing_previous = replace(
        closure.receipt,
        semantic_round=2,
        previous_closure_receipt_id=digest("missing-receipt"),
    )
    _put(objects, missing_previous)
    with pytest.raises(ReV2LedgerError, match="preceding receipt"):
        ledger.record_finding_closure(missing_previous)


def test_closure_root_rejects_unresolved_mismatch(tmp_path: Path) -> None:
    ledger, objects = _ledger(tmp_path)
    closure = _record_closure_prerequisites(ledger, objects)
    ledger.record_finding_closure(closure.receipt)
    target_id = closure.epoch.audit_target_ids[0]
    root = AuditClosureRootV1(
        1,
        closure.epoch.identity,
        closure.epoch.finding_key_ids,
        (closure.receipt,),
        (),
        ((target_id, 1),),
        ((target_id, 0),),
        (),
    )
    raw = root.to_json_dict()
    raw["unresolved_finding_ids"] = [closure.epoch.finding_key_ids[0]]

    with pytest.raises(ReV2LedgerError, match="unresolved"):
        ledger._append("audit_closure_root", raw)


def test_semantic_ledger_detects_truncation_and_hash_chain_corruption(
    tmp_path: Path,
) -> None:
    ledger, objects = _ledger(tmp_path)
    closure = _record_closure_prerequisites(ledger, objects)
    original = ledger.path.read_bytes()
    ledger.path.write_bytes(original[:-1])
    with pytest.raises(ReV2LedgerError, match="partial final"):
        ledger.replay()

    ledger.path.write_bytes(original)
    records = [json.loads(line) for line in original.splitlines()]
    records[1]["previous_record_hash"] = digest("wrong-previous")
    identity = dict(records[1])
    del identity["record_hash"]
    records[1]["record_hash"] = content_digest(identity)
    ledger.path.write_bytes(b"".join(canonical_json_bytes(item) for item in records))
    with pytest.raises(ReV2LedgerError, match="wrong previous"):
        ledger.replay()

    assert closure.epoch.identity


def test_protocol_package_exports_semantic_ledger_contract() -> None:
    protocol = importlib.import_module("harness.re_v2.protocol_25")

    assert protocol.Protocol25Ledger is Protocol25Ledger

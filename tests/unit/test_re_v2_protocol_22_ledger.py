from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_22.artifacts import (
    ContextBundleV1,
    DeterministicAssessmentInputV2,
)
from harness.re_v2.protocol_22.baseline import (
    ArtifactAcceptanceReceiptV2,
    CandidateAssessmentReceiptV1,
    CertificationReceiptV2,
    DeterministicCertificationAssessmentV2,
    certify_deterministic_artifact,
    parse_authorial_candidate,
)
from harness.re_v2.protocol_22.executors import VerifierAuthorityV1
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    ExecutorFailureStateV2,
    PlanningAuthorityV2,
    WorkFailureStateV2,
    build_protocol_22_graph,
    plan_next_v22,
)
from harness.re_v2.protocol_22.ledger import (
    ExecutorFailureReceiptV1,
    Protocol22Ledger,
    WorkItemFailureReceiptV1,
)
from harness.re_v2.protocol_22.model import WorkItemV2
from harness.re_v2.protocol_22.schema import load_canonical_object
from tests.re_v2_protocol_22_fixtures import digest, work_item_v2
from tests.unit.test_re_v2_protocol_22_certification import (
    _domain_certification_fixture,
    _valid_domain_candidate,
)
from tests.unit.test_re_v2_protocol_22_context import _domain_fixture
from tests.unit.test_re_v2_protocol_22_graph import (
    _Budget,
    _fixture as _graph_fixture,
)


def _ledger(tmp_path: Path) -> tuple[Protocol22Ledger, ObjectStore]:
    objects = ObjectStore(tmp_path / "objects")
    return Protocol22Ledger(tmp_path / "ledger.jsonl", objects), objects


def _verifier(item: WorkItemV2) -> VerifierAuthorityV1:
    return VerifierAuthorityV1(
        verifier_id=item.verifier_id,
        verifier_version=item.verifier_version,
        implementation_digest=item.verifier_implementation_digest,
    )


def _deterministic_authority(
    objects: ObjectStore,
    *,
    payload: bytes = b"canonical inventory\n",
    item: WorkItemV2 | None = None,
    accepted: bool = True,
) -> tuple[WorkItemV2, CertificationReceiptV2, ArtifactAcceptanceReceiptV2]:
    selected = item or work_item_v2()
    artifact_hash = objects.put_blob(payload)
    assessment = DeterministicAssessmentInputV2(
        canonical_schema_valid=accepted,
        dependency_closure_valid=True,
        policy_conformance_valid=True,
        depth_debt=None,
        normalized_diagnostics=() if accepted else ("canonical_schema_invalid",),
    )
    certification = certify_deterministic_artifact(
        selected,
        artifact_hash,
        assessment,
        _verifier(selected),
    )
    acceptance = ArtifactAcceptanceReceiptV2(
        schema_version=2,
        artifact_key=selected.output_key,
        artifact_hash=artifact_hash,
        certification_receipt_id=certification.identity,
    )
    return selected, certification, acceptance


def _provider_authority(
    objects: ObjectStore,
    *,
    candidate: str = "candidate-a",
    capture: str = "capture-a",
):  # type: ignore[no-untyped-def]
    fixture = _domain_fixture()
    context = load_canonical_object(
        fixture.context_bytes,
        ContextBundleV1.from_json_dict,
    )
    raw = _valid_domain_candidate(context)
    result, item, _context, _reader = _domain_certification_fixture(
        raw,
        candidate=candidate,
        capture=capture,
    )
    assert objects.put_blob(result.artifact_bytes) == (
        result.certification.certification_key.artifact_hash
    )
    normalized = parse_authorial_candidate(
        canonical_json_bytes(raw),
        "domain-baseline",
        context.target_artifact_policy,
    )
    assert objects.put_blob(canonical_json_bytes(normalized.to_json_dict())) == (
        result.candidate_assessment.normalized_authorial_payload_hash
    )
    assert objects.put_blob(capture.encode()) == (
        result.candidate_assessment.execution_capture_hash
    )
    acceptance = ArtifactAcceptanceReceiptV2(
        schema_version=2,
        artifact_key=item.output_key,
        artifact_hash=result.certification.certification_key.artifact_hash,
        certification_receipt_id=result.certification.identity,
    )
    return item, result.certification, result.candidate_assessment, acceptance


def _work_failure(**changes: object) -> WorkItemFailureReceiptV1:
    values: dict[str, object] = {
        "schema_version": 1,
        "work_item_id": digest("failed-work"),
        "dispatch_id": "dispatch-1",
        "candidate_id": None,
        "candidate_assessment_id": None,
        "execution_capture_hash": digest("capture-1"),
        "dispatch_abandonment_event_hash": None,
        "failure_class": "result_contract",
        "reason_code": "result_unrecoverable",
        "normalized_diagnostics": ("terminal_result_missing",),
    }
    values.update(changes)
    return WorkItemFailureReceiptV1(**values)  # type: ignore[arg-type]


def _executor_failure(**changes: object) -> ExecutorFailureReceiptV1:
    values: dict[str, object] = {
        "schema_version": 1,
        "executor_contract_hash": digest("executor"),
        "trigger_work_item_id": digest("trigger"),
        "dispatch_id": None,
        "candidate_id": None,
        "execution_capture_hash": None,
        "reason_code": "reservation_mismatch",
        "normalized_diagnostics": ("reservation_did_not_recompute",),
    }
    values.update(changes)
    return ExecutorFailureReceiptV1(**values)  # type: ignore[arg-type]


def test_artifact_acceptance_is_candidate_and_timestamp_independent() -> None:
    acceptance = ArtifactAcceptanceReceiptV2(
        schema_version=2,
        artifact_key=work_item_v2().output_key,
        artifact_hash=digest("a"),
        certification_receipt_id=digest("c"),
    )

    assert set(acceptance.to_json_dict()) == {
        "schema_version",
        "artifact_key",
        "artifact_hash",
        "certification_receipt_id",
    }


def test_deterministic_receipts_replay_as_planning_authority(tmp_path: Path) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, acceptance = _deterministic_authority(objects)

    first = ledger.record_certification(certification, item)
    second = ledger.record_artifact_acceptance(acceptance)
    view = ledger.replay()

    assert (first.seq, second.seq, second.previous_record_hash) == (
        1,
        2,
        first.record_hash,
    )
    authority: PlanningAuthorityV2 = view
    assert authority is view
    assert view.artifact_for_key(item.output_key.identity) == AcceptedArtifactV2(
        item.output_key.identity,
        acceptance.artifact_hash,
    )
    assert view.certifications[certification.identity] == certification
    assert view.accepted_artifacts[item.output_key.identity] == acceptance
    assert [json.loads(line)["schema_version"] for line in ledger.path.read_bytes().splitlines()] == [1, 1]


def test_certification_key_is_unique_and_duplicate_bytes_are_idempotent(
    tmp_path: Path,
) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, _acceptance = _deterministic_authority(objects)
    first = ledger.record_certification(certification, item)

    assert ledger.record_certification(certification, item) == first
    rejected_assessment = replace(
        certification.assessment,
        canonical_schema_valid=False,
        normalized_diagnostics=("canonical_schema_invalid",),
    )
    assert isinstance(rejected_assessment, DeterministicCertificationAssessmentV2)
    conflicting = replace(
        certification,
        verdict="rejected",
        assessment=rejected_assessment,
    )
    with pytest.raises(ReV2LedgerError, match="conflicting certification receipt"):
        ledger.record_certification(conflicting, item)
    assert len(ledger.path.read_bytes().splitlines()) == 1


def test_certification_must_match_work_item_and_verified_object(tmp_path: Path) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, _acceptance = _deterministic_authority(objects)

    wrong_item = replace(item, verifier_version="v2")
    with pytest.raises(ReV2LedgerError, match="verifier|work item"):
        ledger.record_certification(certification, wrong_item)

    object_path = objects._path(certification.certification_key.artifact_hash)
    object_path.chmod(0o600)
    object_path.write_bytes(b"corrupt")
    with pytest.raises(ReV2LedgerError, match="hash mismatch"):
        ledger.record_certification(certification, item)


def test_artifact_requires_preceding_accepted_certification(tmp_path: Path) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, acceptance = _deterministic_authority(objects)

    with pytest.raises(ReV2LedgerError, match="preceding certification"):
        ledger.record_artifact_acceptance(acceptance)

    rejected_item, rejected, rejected_acceptance = _deterministic_authority(
        objects,
        payload=b"rejected inventory\n",
        accepted=False,
    )
    ledger.record_certification(rejected, rejected_item)
    with pytest.raises(ReV2LedgerError, match="accepted certification"):
        ledger.record_artifact_acceptance(rejected_acceptance)
    assert item.work_item_id == rejected_item.work_item_id
    assert certification.identity != rejected.identity


def test_two_candidates_can_share_one_certification_and_acceptance(
    tmp_path: Path,
) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, first_assessment, acceptance = _provider_authority(
        objects,
        candidate="candidate-one",
        capture="capture-one",
    )
    second_item, second_certification, second_assessment, _ = _provider_authority(
        objects,
        candidate="candidate-two",
        capture="capture-two",
    )
    assert second_item == item
    assert second_certification == certification

    certification_record = ledger.record_certification(certification, item)
    assert ledger.record_certification(second_certification, second_item) == (
        certification_record
    )
    ledger.record_candidate_assessment(first_assessment)
    ledger.record_candidate_assessment(second_assessment)
    ledger.record_artifact_acceptance(acceptance)
    view = ledger.replay()

    assert len(view.certifications) == 1
    assert set(view.candidate_assessments) == {
        first_assessment.identity,
        second_assessment.identity,
    }
    assert len(view.accepted_artifacts) == 1


def test_provider_acceptance_requires_matching_certified_assessment(
    tmp_path: Path,
) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, assessment, acceptance = _provider_authority(objects)
    ledger.record_certification(certification, item)

    with pytest.raises(ReV2LedgerError, match="certified candidate assessment"):
        ledger.record_artifact_acceptance(acceptance)

    ledger.record_candidate_assessment(assessment)
    ledger.record_artifact_acceptance(acceptance)


def test_certified_candidate_cannot_be_reclassified_as_work_failure(
    tmp_path: Path,
) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, assessment, _acceptance = _provider_authority(objects)
    ledger.record_certification(certification, item)
    ledger.record_candidate_assessment(assessment)
    failure = _work_failure(
        work_item_id=item.work_item_id,
        candidate_id=assessment.candidate_id,
        candidate_assessment_id=assessment.identity,
        execution_capture_hash=assessment.execution_capture_hash,
        failure_class="artifact_contract",
        reason_code="authorial_schema_invalid",
        normalized_diagnostics=("authorial_schema_invalid",),
    )

    with pytest.raises(ReV2LedgerError, match="certified candidate"):
        ledger.record_work_item_failure(failure)


def test_candidate_assessment_requires_preceding_matching_compact_certification(
    tmp_path: Path,
) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, assessment, _acceptance = _provider_authority(objects)

    with pytest.raises(ReV2LedgerError, match="preceding certification"):
        ledger.record_candidate_assessment(assessment)

    ledger.record_certification(certification, item)
    rejected = replace(
        assessment,
        outcome="rejected_after_artifact",
        normalized_diagnostics=("minimum_utility_not_met",),
    )
    with pytest.raises(ReV2LedgerError, match="outcome.*certification"):
        ledger.record_candidate_assessment(rejected)

    deterministic_item, deterministic, _ = _deterministic_authority(
        objects,
        payload=b"other deterministic artifact",
    )
    ledger.record_certification(deterministic, deterministic_item)
    deterministic_candidate = replace(
        assessment,
        work_item_id=deterministic_item.work_item_id,
        artifact_hash=deterministic.certification_key.artifact_hash,
        certification_receipt_id=deterministic.identity,
    )
    with pytest.raises(ReV2LedgerError, match="compact certification"):
        ledger.record_candidate_assessment(deterministic_candidate)


def test_rejected_before_artifact_candidate_is_visible_without_certification(
    tmp_path: Path,
) -> None:
    ledger, objects = _ledger(tmp_path)
    capture = objects.put_blob(b"capture: malformed candidate")
    receipt = CandidateAssessmentReceiptV1(
        schema_version=1,
        candidate_id=digest("malformed candidate"),
        work_item_id=digest("work"),
        execution_capture_hash=capture,
        normalized_authorial_payload_hash=None,
        artifact_hash=None,
        certification_receipt_id=None,
        outcome="rejected_before_artifact",
        normalized_diagnostics=("authorial_schema_invalid",),
    )

    record = ledger.record_candidate_assessment(receipt)
    view = ledger.replay()

    assert view.candidate_assessments[receipt.identity] == receipt
    assert view.candidate_assessment_records[receipt.identity] == record


@pytest.mark.parametrize(
    ("failure_class", "reason_code"),
    (
        ("result_contract", "authorial_schema_invalid"),
        ("artifact_contract", "result_unrecoverable"),
        ("minimum_utility", "evidence_contract_invalid"),
        ("execution_indeterminate", "result_unrecoverable"),
    ),
)
def test_work_failure_rejects_invalid_class_reason_pair(
    failure_class: str,
    reason_code: str,
) -> None:
    with pytest.raises(ValueError, match="failure_class|reason_code"):
        _work_failure(failure_class=failure_class, reason_code=reason_code)


def test_work_failure_capture_and_abandonment_authority_are_exclusive() -> None:
    with pytest.raises(ValueError, match="capture.*abandonment|mutually exclusive"):
        _work_failure(dispatch_abandonment_event_hash=digest("abandoned"))

    abandoned = _work_failure(
        failure_class="execution_indeterminate",
        reason_code="execution_outcome_indeterminate",
        execution_capture_hash=None,
        dispatch_abandonment_event_hash=digest("abandoned"),
    )
    assert abandoned.execution_capture_hash is None
    assert abandoned.dispatch_abandonment_event_hash == digest("abandoned")


def test_work_failure_candidate_fields_are_paired_and_match_assessment(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="candidate.*paired"):
        _work_failure(candidate_id=digest("candidate"))

    ledger, objects = _ledger(tmp_path)
    capture = objects.put_blob(b"capture: invalid candidate")
    assessment = CandidateAssessmentReceiptV1(
        schema_version=1,
        candidate_id=digest("invalid candidate"),
        work_item_id=digest("failed work"),
        execution_capture_hash=capture,
        normalized_authorial_payload_hash=None,
        artifact_hash=None,
        certification_receipt_id=None,
        outcome="rejected_before_artifact",
        normalized_diagnostics=("authorial_schema_invalid",),
    )
    ledger.record_candidate_assessment(assessment)
    failure = _work_failure(
        work_item_id=assessment.work_item_id,
        candidate_id=assessment.candidate_id,
        candidate_assessment_id=assessment.identity,
        execution_capture_hash=capture,
        failure_class="artifact_contract",
        reason_code="authorial_schema_invalid",
        normalized_diagnostics=("authorial_schema_invalid",),
    )

    record = ledger.record_work_item_failure(failure)
    view = ledger.replay()

    assert view.work_item_failures[failure.work_item_id] == failure
    assert view.work_item_failure_records[failure.work_item_id] == record
    assert view.work_failure(failure.work_item_id) == WorkFailureStateV2(
        failure.work_item_id,
        failure.reason_code,
        failure.identity,
    )

    omitted_root = tmp_path / "omitted"
    omitted_root.mkdir()
    other_ledger, other_objects = _ledger(omitted_root)
    omitted_capture = other_objects.put_blob(b"capture: omitted provenance")
    omitted_assessment = replace(
        assessment,
        execution_capture_hash=omitted_capture,
    )
    other_ledger.record_candidate_assessment(omitted_assessment)
    with pytest.raises(ReV2LedgerError, match="candidate fields.*persisted"):
        other_ledger.record_work_item_failure(
            _work_failure(
                work_item_id=omitted_assessment.work_item_id,
                execution_capture_hash=omitted_capture,
                failure_class="artifact_contract",
                reason_code="authorial_schema_invalid",
                normalized_diagnostics=("authorial_schema_invalid",),
            )
        )


def test_failure_receipt_diagnostics_are_nonempty_sorted_unique_and_bounded() -> None:
    for diagnostics in ((), ("z", "a"), ("same", "same"), ("x" * 1025,)):
        with pytest.raises(ValueError, match="diagnostic"):
            _work_failure(normalized_diagnostics=diagnostics)


@pytest.mark.parametrize(
    "reason",
    ("reservation_mismatch", "limit_unenforceable"),
)
def test_predispatch_executor_failure_requires_null_dispatch_fields(reason: str) -> None:
    receipt = _executor_failure(reason_code=reason)
    assert (receipt.dispatch_id, receipt.candidate_id, receipt.execution_capture_hash) == (
        None,
        None,
        None,
    )
    with pytest.raises(ValueError, match="pre-dispatch"):
        _executor_failure(reason_code=reason, dispatch_id="dispatch-1")


@pytest.mark.parametrize(
    "reason",
    (
        "usage_exceeded_reservation",
        "deterministic_execution_failed",
        "deterministic_artifact_invalid",
    ),
)
def test_postdispatch_executor_failure_requires_dispatch_and_capture(
    reason: str,
) -> None:
    with pytest.raises(ValueError, match="post-dispatch"):
        _executor_failure(reason_code=reason)

    receipt = _executor_failure(
        reason_code=reason,
        dispatch_id="dispatch-1",
        execution_capture_hash=digest("capture"),
    )
    assert receipt.dispatch_id == "dispatch-1"


@pytest.mark.parametrize(
    "reason",
    ("deterministic_execution_failed", "deterministic_artifact_invalid"),
)
def test_deterministic_executor_failure_forbids_provider_candidate(
    reason: str,
) -> None:
    with pytest.raises(ValueError, match="deterministic.*candidate"):
        _executor_failure(
            reason_code=reason,
            dispatch_id="dispatch-1",
            execution_capture_hash=digest("capture"),
            candidate_id=digest("provider candidate"),
        )


def test_executor_failure_is_unique_per_contract_and_visible_when_orphaned(
    tmp_path: Path,
) -> None:
    ledger, _objects = _ledger(tmp_path)
    receipt = _executor_failure()
    record = ledger.record_executor_failure(receipt)

    assert ledger.record_executor_failure(receipt) == record
    with pytest.raises(ReV2LedgerError, match="conflicting executor-failure receipt"):
        ledger.record_executor_failure(
            _executor_failure(
                reason_code="limit_unenforceable",
                normalized_diagnostics=("limit_cannot_be_enforced",),
            )
        )
    view = ledger.replay()
    assert view.executor_failures[receipt.executor_contract_hash] == receipt
    assert view.executor_failure(receipt.executor_contract_hash) == (
        ExecutorFailureStateV2(
            receipt.executor_contract_hash,
            receipt.reason_code,
            receipt.identity,
        )
    )


def test_executor_trigger_is_derived_as_failed_without_synthetic_receipt(
    tmp_path: Path,
) -> None:
    ledger, _objects = _ledger(tmp_path)
    receipt = _executor_failure()
    ledger.record_executor_failure(receipt)
    view = ledger.replay()

    assert view.work_failure(receipt.trigger_work_item_id) == WorkFailureStateV2(
        receipt.trigger_work_item_id,
        "failed_executor_contract",
        receipt.identity,
    )
    assert receipt.trigger_work_item_id not in view.work_item_failures
    assert view.work_failure(digest("same-contract sibling")) is None


def test_executor_failure_does_not_invalidate_previously_accepted_trigger(
    tmp_path: Path,
) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, acceptance = _deterministic_authority(objects)
    ledger.record_certification(certification, item)
    ledger.record_artifact_acceptance(acceptance)
    failure = _executor_failure(
        executor_contract_hash=item.executor_contract_hash,
        trigger_work_item_id=item.work_item_id,
    )

    ledger.record_executor_failure(failure)
    view = ledger.replay()

    assert view.artifact_for_key(item.output_key.identity) is not None
    assert view.work_failure(item.work_item_id) is None
    assert view.executor_failure(item.executor_contract_hash) is not None


def test_ledger_view_drives_executor_and_downstream_failure_derivation(
    tmp_path: Path,
) -> None:
    manifest, inputs = _graph_fixture(
        {"api": ("orders", "users")},
        goal="inventory",
    )
    graph = build_protocol_22_graph(manifest, inputs)
    empty_ledger, _objects = _ledger(tmp_path)
    initial = plan_next_v22(graph, empty_ledger.replay(), _Budget())
    inventories = tuple(
        item for item in initial.ready if item.producer_family == "inventory"
    )
    trigger = inventories[0]
    failure = _executor_failure(
        executor_contract_hash=trigger.executor_contract_hash,
        trigger_work_item_id=trigger.work_item_id,
    )
    empty_ledger.record_executor_failure(failure)

    decision = plan_next_v22(graph, empty_ledger.replay(), _Budget())

    assert decision.explanations[trigger.template_id].reason_code == (
        "failed_executor_contract"
    )
    for sibling in inventories[1:]:
        assert decision.explanations[sibling.template_id].reason_code == (
            "blocked_by_executor_failure"
        )
    assert any(
        explanation.reason_code == "blocked_by_failed_dependency"
        for explanation in decision.explanations.values()
    )
    assert any(item.producer_family == "partition" for item in decision.ready)


def test_replay_reverifies_every_referenced_artifact_object(tmp_path: Path) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, acceptance = _deterministic_authority(objects)
    ledger.record_certification(certification, item)
    ledger.record_artifact_acceptance(acceptance)

    path = objects._path(acceptance.artifact_hash)
    path.chmod(0o600)
    path.write_bytes(b"corrupt")

    with pytest.raises(ReV2LedgerError, match="hash mismatch"):
        ledger.replay()


def test_protocol_22_replay_rejects_legacy_artifact_payload(tmp_path: Path) -> None:
    ledger, objects = _ledger(tmp_path)
    item, certification, acceptance = _deterministic_authority(objects)
    ledger.record_certification(certification, item)
    record = ledger.record_artifact_acceptance(acceptance).to_json_dict()
    record["payload"] = {
        **record["payload"],
        "candidate_id": digest("smuggled candidate"),
    }
    identity = dict(record)
    del identity["record_hash"]
    record["record_hash"] = content_digest(identity)
    ledger.path.write_bytes(
        canonical_json_bytes(json.loads(ledger.path.read_bytes().splitlines()[0]))
        + canonical_json_bytes(record)
    )

    with pytest.raises(ReV2LedgerError, match="unknown fields|invalid artifact"):
        ledger.replay()

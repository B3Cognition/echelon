from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_28.artifacts import ExhaustiveVerificationV1
from harness.re_v2.protocol_28.execution import (
    L4CandidateReceiptV1,
    L4CertificationReceiptV1,
    L4ExecutionEnvelopeV1,
    L4VerificationReceiptV1,
    Protocol28ExecutionError,
    certify_and_accept,
    persist_provider_result,
)
from harness.re_v2.protocol_28.ledger import Protocol28Ledger
from harness.re_v2.protocol_28.graph import AcceptedExhaustiveSliceV1
from harness.re_v2.protocol_28.planning import realize_slice
from harness.re_v2.protocol_28.policies import build_initial_exhaustive_policy
from tests.re_v2_protocol_28_fixtures import digest
from tests.unit.test_re_v2_protocol_28_artifacts import _candidate_fixture


def _envelope(entry, spec, *, role: str, candidate_id: str | None = None, same_context: bool = False):  # type: ignore[no-untyped-def]
    return L4ExecutionEnvelopeV1(
        1,
        f"dispatch-{role}",
        role,
        spec.identity,
        entry.identity,
        1,
        entry.producer_contract_hash if role == "producer" else entry.verifier_contract_hash,
        digest("shared-context" if same_context else f"{role}-context"),
        digest(f"{role}-request"),
        candidate_id,
    )


def _pass_verification(entry, spec, candidate):  # type: ignore[no-untyped-def]
    return ExhaustiveVerificationV1(
        1,
        spec.identity,
        candidate.identity,
        entry.verifier_contract_hash,
        "PASS",
        (),
        candidate.covered_primary_evidence_ids,
        candidate.addressed_finding_ids,
    )


def _captures(
    tmp_path: Path,
    *,
    same_context: bool = False,
    bind_results: bool = True,
    producer_result_kind: str = "provider_result",
    noncanonical_provider_json: bool = False,
):  # type: ignore[no-untyped-def]
    entry, _old_spec, evidence, candidate = _candidate_fixture()
    spec = realize_slice(entry, {})
    store = ObjectStore(tmp_path / "objects")
    ledger = Protocol28Ledger(tmp_path / "ledger.jsonl", store)
    producer_envelope = _envelope(entry, spec, role="producer", same_context=same_context)
    producer = persist_provider_result(
        store,
        producer_envelope,
        (
            (
                json.dumps(candidate.to_json_dict(), indent=2).encode("utf-8")
                if noncanonical_provider_json
                else canonical_json_bytes(candidate.to_json_dict())
            )
            if bind_results
            else b"producer-result"
        ),
        provider_name="codex",
        model_revision="gpt-test",
        started_at="2026-08-31T12:00:00Z",
        ended_at="2026-08-31T12:00:01Z",
        duration_ms=1000,
        result_kind=producer_result_kind,
        ledger=ledger,
    )
    verifier_envelope = _envelope(
        entry,
        spec,
        role="verifier",
        candidate_id=candidate.identity,
        same_context=same_context,
    )
    verifier = persist_provider_result(
        store,
        verifier_envelope,
        (
            (
                json.dumps(
                    _pass_verification(entry, spec, candidate).to_json_dict(),
                    indent=2,
                ).encode("utf-8")
                if noncanonical_provider_json
                else canonical_json_bytes(
                    _pass_verification(entry, spec, candidate).to_json_dict()
                )
            )
            if bind_results
            else b"verifier-result"
        ),
        provider_name="codex",
        model_revision="gpt-test",
        started_at="2026-08-31T12:00:02Z",
        ended_at="2026-08-31T12:00:03Z",
        duration_ms=1000,
        ledger=ledger,
    )
    return entry, spec, evidence, candidate, store, ledger, producer, verifier


@pytest.mark.unit
def test_candidate_record_requires_preceding_producer_capture(tmp_path: Path) -> None:
    entry, spec, _evidence, candidate = _candidate_fixture()
    store = ObjectStore(tmp_path / "objects")
    ledger = Protocol28Ledger(tmp_path / "ledger.jsonl", store)
    candidate_bytes = canonical_json_bytes(candidate.to_json_dict())
    candidate_hash = store.put_blob(candidate_bytes)
    receipt = L4CandidateReceiptV1(
        1, spec.identity, entry.identity, candidate_hash, digest("missing-capture")
    )

    with pytest.raises(ReV2LedgerError, match="producer capture"):
        ledger.record_candidate(receipt)


@pytest.mark.unit
def test_candidate_record_authenticates_parsed_producer_result(tmp_path: Path) -> None:
    entry, spec, _evidence, candidate, store, ledger, producer, _verifier = _captures(
        tmp_path, bind_results=False
    )
    store.put_blob(canonical_json_bytes(candidate.to_json_dict()))

    with pytest.raises(ReV2LedgerError, match="producer result.*candidate"):
        ledger.record_candidate(
            L4CandidateReceiptV1(
                1,
                spec.identity,
                entry.identity,
                candidate.identity,
                producer.capture.identity,
            )
        )


@pytest.mark.unit
def test_provider_failure_capture_cannot_authorize_candidate(tmp_path: Path) -> None:
    entry, spec, _evidence, candidate, store, ledger, producer, _verifier = _captures(
        tmp_path, producer_result_kind="provider_failure"
    )
    store.put_blob(canonical_json_bytes(candidate.to_json_dict()))

    with pytest.raises(ReV2LedgerError, match="successful producer result"):
        ledger.record_candidate(
            L4CandidateReceiptV1(
                1,
                spec.identity,
                entry.identity,
                candidate.identity,
                producer.capture.identity,
            )
        )


@pytest.mark.unit
def test_verification_record_requires_candidate_and_verifier_capture(tmp_path: Path) -> None:
    entry, spec, _evidence, candidate, store, ledger, producer, _verifier = _captures(tmp_path)
    verification = _pass_verification(entry, spec, candidate)
    verification_hash = store.put_blob(canonical_json_bytes(verification.to_json_dict()))
    receipt = L4VerificationReceiptV1(
        1,
        spec.identity,
        entry.identity,
        candidate.identity,
        verification_hash,
        digest("missing-verifier-capture"),
        "PASS",
    )

    with pytest.raises(ReV2LedgerError, match="candidate.*preceding"):
        ledger.record_verification(receipt)

    store.put_blob(canonical_json_bytes(candidate.to_json_dict()))
    ledger.record_candidate(
        L4CandidateReceiptV1(
            1, spec.identity, entry.identity, candidate.identity, producer.capture.identity
        )
    )
    with pytest.raises(ReV2LedgerError, match="verifier capture"):
        ledger.record_verification(receipt)


@pytest.mark.unit
def test_acceptance_requires_fresh_verifier_context(tmp_path: Path) -> None:
    entry, spec, evidence, candidate, store, ledger, producer, verifier = _captures(
        tmp_path, same_context=True
    )

    with pytest.raises(Protocol28ExecutionError, match="fresh independent context"):
        certify_and_accept(
            store,
            ledger,
            spec,
            entry,
            evidence,
            build_initial_exhaustive_policy(),
            candidate,
            _pass_verification(entry, spec, candidate),
            producer,
            verifier,
        )


@pytest.mark.unit
def test_ledger_certification_rechecks_fresh_verifier_context(tmp_path: Path) -> None:
    entry, spec, _evidence, candidate, store, ledger, producer, verifier = _captures(
        tmp_path, same_context=True
    )
    verification = _pass_verification(entry, spec, candidate)
    candidate_hash = store.put_blob(canonical_json_bytes(candidate.to_json_dict()))
    verification_hash = store.put_blob(canonical_json_bytes(verification.to_json_dict()))
    ledger.record_candidate(
        L4CandidateReceiptV1(
            1, spec.identity, entry.identity, candidate_hash, producer.capture.identity
        )
    )
    ledger.record_verification(
        L4VerificationReceiptV1(
            1,
            spec.identity,
            entry.identity,
            candidate_hash,
            verification_hash,
            verifier.capture.identity,
            "PASS",
        )
    )
    certification = L4CertificationReceiptV1(
        1,
        spec.identity,
        entry.identity,
        spec.output_artifact_key_id,
        candidate_hash,
        producer.capture.identity,
        verification_hash,
        verifier.capture.identity,
        True,
        True,
        "accepted",
    )
    store.put_blob(canonical_json_bytes(certification.to_json_dict()))

    with pytest.raises(ReV2LedgerError, match="fresh independent context"):
        ledger.record_certification(certification)


@pytest.mark.unit
def test_acceptance_rejects_candidate_not_parsed_from_producer_capture(tmp_path: Path) -> None:
    entry, spec, evidence, candidate, store, ledger, producer, verifier = _captures(
        tmp_path, bind_results=False
    )

    with pytest.raises(Protocol28ExecutionError, match="producer capture.*candidate"):
        certify_and_accept(
            store,
            ledger,
            spec,
            entry,
            evidence,
            build_initial_exhaustive_policy(),
            candidate,
            _pass_verification(entry, spec, candidate),
            producer,
            verifier,
        )


@pytest.mark.unit
def test_repair_verdict_cannot_create_acceptance(tmp_path: Path) -> None:
    entry, spec, evidence, candidate, store, ledger, producer, verifier = _captures(tmp_path)
    repair = ExhaustiveVerificationV1(
        1,
        spec.identity,
        candidate.identity,
        entry.verifier_contract_hash,
        "REPAIR",
        (),
        candidate.covered_primary_evidence_ids,
        candidate.addressed_finding_ids,
    )

    with pytest.raises(Protocol28ExecutionError, match="PASS"):
        certify_and_accept(
            store,
            ledger,
            spec,
            entry,
            evidence,
            build_initial_exhaustive_policy(),
            candidate,
            repair,
            producer,
            verifier,
        )


@pytest.mark.unit
def test_controller_pass_creates_replayable_accepted_slice(tmp_path: Path) -> None:
    entry, spec, evidence, candidate, store, ledger, producer, verifier = _captures(tmp_path)

    accepted = certify_and_accept(
        store,
        ledger,
        spec,
        entry,
        evidence,
        build_initial_exhaustive_policy(),
        candidate,
        _pass_verification(entry, spec, candidate),
        producer,
        verifier,
    )
    view = ledger.replay()

    assert view.accepted_slices[spec.output_artifact_key_id] == accepted
    assert view.certifications[accepted.certification_receipt_hash].verdict == "accepted"
    assert store.read_blob(accepted.candidate_hash) == canonical_json_bytes(candidate.to_json_dict())


@pytest.mark.unit
@pytest.mark.parametrize(
    "crash_stage",
    (
        "before_candidate_and_verification_objects",
        "candidate_and_verification_objects_durable",
        "candidate_and_verification_recorded",
        "before_certification",
        "certification_durable",
        "certification_recorded",
        "before_acceptance",
        "acceptance_durable",
        "acceptance_recorded",
        "before_accepted_slice",
        "accepted_slice_durable",
        "accepted_slice_recorded",
    ),
)
def test_every_acceptance_crash_seam_recovers_idempotently(
    tmp_path: Path, crash_stage: str
) -> None:
    entry, spec, evidence, candidate, store, ledger, producer, verifier = _captures(tmp_path)
    verification = _pass_verification(entry, spec, candidate)

    def crash(stage: str) -> None:
        if stage == crash_stage:
            raise RuntimeError(f"crash at {stage}")

    with pytest.raises(RuntimeError, match="crash at"):
        certify_and_accept(
            store,
            ledger,
            spec,
            entry,
            evidence,
            build_initial_exhaustive_policy(),
            candidate,
            verification,
            producer,
            verifier,
            fault=crash,
        )

    recovered = certify_and_accept(
        store,
        ledger,
        spec,
        entry,
        evidence,
        build_initial_exhaustive_policy(),
        candidate,
        verification,
        producer,
        verifier,
    )
    assert ledger.replay().accepted_slices[spec.output_artifact_key_id] == recovered


@pytest.mark.unit
def test_accepted_slice_cannot_invent_addressed_findings(tmp_path: Path) -> None:
    entry, spec, evidence, candidate, store, ledger, producer, verifier = _captures(tmp_path)
    verification = _pass_verification(entry, spec, candidate)

    def stop_after_acceptance(stage: str) -> None:
        if stage == "acceptance_recorded":
            raise RuntimeError("stop before accepted slice")

    with pytest.raises(RuntimeError, match="stop before accepted slice"):
        certify_and_accept(
            store,
            ledger,
            spec,
            entry,
            evidence,
            build_initial_exhaustive_policy(),
            candidate,
            verification,
            producer,
            verifier,
            fault=stop_after_acceptance,
        )
    view = ledger.replay()
    certification = next(iter(view.certifications.values()))
    acceptance = view.acceptances[spec.output_artifact_key_id]
    forged = AcceptedExhaustiveSliceV1(
        1,
        entry.identity,
        spec.identity,
        spec.output_artifact_key_id,
        candidate.identity,
        producer.capture.identity,
        verification.identity,
        verifier.capture.identity,
        certification.identity,
        acceptance.identity,
        (digest("invented-finding"),),
        "PASS",
    )
    store.put_blob(canonical_json_bytes(forged.to_json_dict()))

    with pytest.raises(ReV2LedgerError, match="addressed findings"):
        ledger.record_accepted_slice(forged)


@pytest.mark.unit
def test_identical_replay_is_idempotent_but_conflicting_dispatch_is_rejected(tmp_path: Path) -> None:
    entry, spec, _evidence, candidate, store, ledger, producer, _verifier = _captures(tmp_path)
    first = ledger.record_execution_capture(producer.envelope, producer.capture)
    assert ledger.record_execution_capture(producer.envelope, producer.capture) == first

    conflicting = persist_provider_result(
        store,
        _envelope(entry, spec, role="producer"),
        b"conflicting-result",
        provider_name="codex",
        model_revision="gpt-test",
        started_at="2026-08-31T12:00:00Z",
        ended_at="2026-08-31T12:00:01Z",
        duration_ms=1000,
    )
    with pytest.raises(ReV2LedgerError, match="conflicting execution capture"):
        ledger.record_execution_capture(conflicting.envelope, conflicting.capture)


@pytest.mark.unit
def test_replay_authenticates_every_referenced_object(tmp_path: Path) -> None:
    entry, spec, evidence, candidate, store, ledger, producer, verifier = _captures(tmp_path)
    accepted = certify_and_accept(
        store,
        ledger,
        spec,
        entry,
        evidence,
        build_initial_exhaustive_policy(),
        candidate,
        _pass_verification(entry, spec, candidate),
        producer,
        verifier,
    )
    suffix = accepted.candidate_hash.removeprefix("sha256:")
    (store.root / "sha256" / suffix[:2] / suffix[2:]).unlink()

    with pytest.raises(ReV2LedgerError, match="object"):
        Protocol28Ledger(tmp_path / "ledger.jsonl", ObjectStore(store.root)).replay()

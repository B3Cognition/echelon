from __future__ import annotations

from harness.fulfillment_reconciliation import (
    FulfillmentCandidate,
    FulfillmentReconciliationContext,
    reconcile_verified_fulfillment,
)
from harness.verified_fulfillment_ledger import (
    VerifiedFulfillmentLedger,
    VerifiedLedgerRow,
)
from harness.verification_evidence import VerificationStage, write_verification_receipt


def _ledger() -> VerifiedFulfillmentLedger:
    return VerifiedFulfillmentLedger(
        rows=(
            VerifiedLedgerRow(
                requirement_id="NFR-001",
                status="UNVERIFIED",
                evidence_refs=(),
                verified_commit="",
                verified_at="",
                spec_input_hash="spec-a",
                implementation_input_hash="impl-a",
                artifact_hashes={},
                verifier_version="verify-v1",
                verify_scope="full",
                source_report_path="report.md",
            ),
        )
    )


def _receipt(tmp_path):
    return write_verification_receipt(
        evidence_dir=tmp_path / "evidence",
        spec_id="003-demo",
        strategy_id="default",
        build_id="build-1",
        candidate_commit="a" * 40,
        fingerprint_before="product-a",
        fingerprint_after="product-a",
        verifier_source="harness",
        stages=(
            VerificationStage(
                name="verify",
                command=("true",),
                exit_code=0,
                duration_ms=1,
                stdout=b"ok",
                stderr=b"",
            ),
        ),
        attempt_sequence=1,
        sensitive_environment={},
        started_at="2026-09-07T10:00:00+00:00",
    )


def test_reconciliation_replaces_unverified_row_with_compatible_receipt(tmp_path):
    receipt = _receipt(tmp_path)
    result = reconcile_verified_fulfillment(
        _ledger(),
        candidates=(
            FulfillmentCandidate(
                requirement_id="NFR-001",
                status="IMPLEMENTED",
                evidence_refs=("tests/e2e/game.spec.ts",),
                verified_at="2026-09-07T10:00:00+00:00",
                receipt=receipt,
                spec_input_hash="spec-a",
                requirement_set_fingerprint="requirements-a",
                contract_hash="contract-a",
            ),
        ),
        context=FulfillmentReconciliationContext(
            product_fingerprint="product-a",
            spec_input_hash="spec-a",
            requirement_set_fingerprint="requirements-a",
            contract_hash="contract-a",
        ),
    )

    assert result.status == "reconciled"
    assert result.ledger.rows[0].status == "IMPLEMENTED"
    assert result.ledger.rows[0].receipt_refs[0]["receipt_sha256"] == receipt.receipt_sha256


def test_reconciliation_requires_reverify_for_changed_product_content(tmp_path):
    receipt = _receipt(tmp_path)
    result = reconcile_verified_fulfillment(
        _ledger(),
        candidates=(
            FulfillmentCandidate(
                requirement_id="NFR-001",
                status="IMPLEMENTED",
                evidence_refs=("tests/e2e/game.spec.ts",),
                verified_at="2026-09-07T10:00:00+00:00",
                receipt=receipt,
                spec_input_hash="spec-a",
                requirement_set_fingerprint="requirements-a",
                contract_hash="contract-a",
            ),
        ),
        context=FulfillmentReconciliationContext(
            product_fingerprint="product-changed",
            spec_input_hash="spec-a",
            requirement_set_fingerprint="requirements-a",
            contract_hash="contract-a",
        ),
    )

    assert result.status == "reverify_required"
    assert result.ledger.rows[0].status == "UNVERIFIED"


def test_reconciliation_aggregates_matching_successes_deterministically(tmp_path):
    first = _receipt(tmp_path)
    second = write_verification_receipt(
        evidence_dir=tmp_path / "evidence-second",
        spec_id="003-demo",
        strategy_id="default",
        build_id="build-2",
        candidate_commit="b" * 40,
        fingerprint_before="product-a",
        fingerprint_after="product-a",
        verifier_source="harness",
        stages=(
            VerificationStage("verify", ("true",), 0, 1, b"ok", b""),
        ),
        attempt_sequence=2,
        sensitive_environment={},
        started_at="2026-09-07T11:00:00+00:00",
    )
    candidates = tuple(
        FulfillmentCandidate(
            requirement_id="NFR-001",
            status="IMPLEMENTED",
            evidence_refs=("tests/e2e/game.spec.ts",),
            verified_at=verified_at,
            receipt=receipt,
            spec_input_hash="spec-a",
            requirement_set_fingerprint="requirements-a",
            contract_hash="contract-a",
        )
        for receipt, verified_at in (
            (second, "2026-09-07T11:00:00+00:00"),
            (first, "2026-09-07T10:00:00+00:00"),
        )
    )

    result = reconcile_verified_fulfillment(
        _ledger(),
        candidates=candidates,
        context=FulfillmentReconciliationContext(
            product_fingerprint="product-a",
            spec_input_hash="spec-a",
            requirement_set_fingerprint="requirements-a",
            contract_hash="contract-a",
        ),
    )

    row = result.ledger.rows[0]
    assert result.status == "reconciled"
    assert row.verified_commit == first.candidate_commit
    assert [ref["receipt_sha256"] for ref in row.receipt_refs] == [
        first.receipt_sha256,
        second.receipt_sha256,
    ]

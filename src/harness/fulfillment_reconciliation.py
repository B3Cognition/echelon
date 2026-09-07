"""Deterministic reconciliation of requirement fulfillment evidence."""

from __future__ import annotations

from dataclasses import dataclass, replace

from harness.verified_fulfillment_ledger import (
    UNRESOLVED_STATUSES,
    VerifiedFulfillmentLedger,
    VerifiedLedgerRow,
)
from harness.verification_evidence import (
    VerificationEvidenceRef,
    validate_equivalent_product_receipt,
)


@dataclass(frozen=True)
class FulfillmentCandidate:
    requirement_id: str
    status: str
    evidence_refs: tuple[str, ...]
    verified_at: str
    receipt: VerificationEvidenceRef
    spec_input_hash: str
    requirement_set_fingerprint: str
    contract_hash: str


@dataclass(frozen=True)
class FulfillmentReconciliationContext:
    product_fingerprint: str
    spec_input_hash: str
    requirement_set_fingerprint: str
    contract_hash: str


@dataclass(frozen=True)
class FulfillmentReconciliationResult:
    status: str
    ledger: VerifiedFulfillmentLedger
    rejected_reasons: tuple[str, ...]


def reconcile_verified_fulfillment(
    ledger: VerifiedFulfillmentLedger,
    *,
    candidates: tuple[FulfillmentCandidate, ...],
    context: FulfillmentReconciliationContext,
) -> FulfillmentReconciliationResult:
    """Upgrade only unresolved rows with receipt-validated compatible evidence."""
    by_requirement: dict[str, list[FulfillmentCandidate]] = {}
    rejected: list[str] = []
    for candidate in candidates:
        reason = _candidate_rejection_reason(candidate, context)
        if reason:
            rejected.append(f"{candidate.requirement_id}:{reason}")
            continue
        by_requirement.setdefault(candidate.requirement_id, []).append(candidate)

    rows: list[VerifiedLedgerRow] = []
    changed = False
    for row in ledger.rows:
        eligible = sorted(
            by_requirement.get(row.requirement_id, []),
            key=lambda value: (value.verified_at, value.receipt.receipt_sha256),
        )
        if row.status not in UNRESOLVED_STATUSES or not eligible:
            rows.append(row)
            continue
        selected = eligible[0]
        rows.append(
            replace(
                row,
                status=selected.status,
                evidence_refs=selected.evidence_refs,
                verified_commit=selected.receipt.candidate_commit,
                verified_at=selected.verified_at,
                receipt_refs=tuple(item.receipt.as_mapping() for item in eligible),
                candidate_content_fingerprint=context.product_fingerprint,
                contract_hash=context.contract_hash,
                requirement_set_fingerprint=context.requirement_set_fingerprint,
                selected_evidence=selected.evidence_refs,
            )
        )
        changed = True

    status = "reconciled" if changed else ("reverify_required" if rejected else "no_candidates")
    return FulfillmentReconciliationResult(
        status=status,
        ledger=VerifiedFulfillmentLedger(rows=tuple(rows)),
        rejected_reasons=tuple(sorted(rejected)),
    )


def _candidate_rejection_reason(
    candidate: FulfillmentCandidate,
    context: FulfillmentReconciliationContext,
) -> str:
    if candidate.status in UNRESOLVED_STATUSES:
        return "incomplete_requirement_evidence"
    if not candidate.evidence_refs:
        return "missing_requirement_evidence"
    if candidate.spec_input_hash != context.spec_input_hash:
        return "spec_input_mismatch"
    if candidate.requirement_set_fingerprint != context.requirement_set_fingerprint:
        return "requirement_set_mismatch"
    if candidate.contract_hash != context.contract_hash:
        return "contract_mismatch"
    validation = validate_equivalent_product_receipt(
        candidate.receipt,
        candidate_fingerprint=context.product_fingerprint,
    )
    if not validation.valid:
        return f"receipt_invalid:{validation.reason}"
    return ""

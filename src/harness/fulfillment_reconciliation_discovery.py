"""Discover receipt-backed reconciliation candidates from immutable delivery state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.canonical_requirements import (
    CanonicalRequirement,
    canonical_requirement_fingerprint,
    extract_canonical_requirements,
)
from harness.fulfillment_reconciliation import (
    FulfillmentCandidate,
    FulfillmentReconciliationContext,
    FulfillmentReconciliationResult,
    reconcile_verified_fulfillment,
)
from harness.fulfillment_runner import _spec_input_hash, fulfillment_contract_hash
from harness.product_inventory import product_evidence_fingerprint
from harness.verification_evidence import VerificationEvidenceRef
from harness.verified_fulfillment_ledger import VerifiedFulfillmentLedger


def reconcile_from_delivery_state(
    *, root: Path, spec_dir: Path, target: Path, ledger: VerifiedFulfillmentLedger
) -> FulfillmentReconciliationResult:
    """Reconcile only state files that carry a complete immutable snapshot.

    Older state is deliberately visible only as a rejected candidate: it must
    never be promoted from a report or a mutable checkout.
    """
    requirements = extract_canonical_requirements(spec_dir)
    context = FulfillmentReconciliationContext(
        product_fingerprint=product_evidence_fingerprint(target),
        spec_input_hash=_spec_input_hash(spec_dir) or "",
        requirement_set_fingerprint=canonical_requirement_fingerprint(requirements),
        contract_hash=fulfillment_contract_hash(),
    )
    candidates: list[FulfillmentCandidate] = []
    for state_path in sorted((root / "runs").glob("**/state/*.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(state, dict) or str(state.get("spec_id") or "") != spec_dir.name:
            continue
        snapshot = _snapshot(state.get("verified_requirement_snapshot"))
        if snapshot is None or canonical_requirement_fingerprint(snapshot) != str(
            state.get("verified_requirement_set_fingerprint") or ""
        ):
            continue
        raw_receipt = state.get("verified_evidence")
        if not isinstance(raw_receipt, dict):
            continue
        try:
            receipt = VerificationEvidenceRef.from_mapping(raw_receipt)
        except (TypeError, ValueError):
            continue
        for raw_row in state.get("verified_fulfillment_rows", []):
            if not isinstance(raw_row, dict):
                continue
            requirement_id = str(raw_row.get("requirement_id") or "")
            status = str(raw_row.get("status") or "").upper()
            evidence = tuple(str(item) for item in raw_row.get("evidence_refs", []) if str(item))
            if not requirement_id:
                continue
            candidates.append(FulfillmentCandidate(
                requirement_id=requirement_id, status=status, evidence_refs=evidence,
                verified_at=str(raw_row.get("verified_at") or ""), receipt=receipt,
                spec_input_hash=str(state.get("verified_spec_input_hash") or ""),
                requirement_set_fingerprint=str(state.get("verified_requirement_set_fingerprint") or ""),
                contract_hash=str(state.get("verified_contract_hash") or ""),
            ))
    return reconcile_verified_fulfillment(ledger, candidates=tuple(candidates), context=context)


def _snapshot(raw: Any) -> list[CanonicalRequirement] | None:
    if not isinstance(raw, list):
        return None
    result: list[CanonicalRequirement] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        try:
            result.append(CanonicalRequirement(
                id=str(item["id"]), source_kind=str(item["source_kind"]),
                source_file=str(item["source_file"]), source_line=int(item["source_line"]),
                source_text=str(item["source_text"]),
            ))
        except (KeyError, TypeError, ValueError):
            return None
    return result

"""Requirement-level verified fulfillment ledger helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Mapping

from kernel.fulfillment import read_fulfillment_metadata


UNRESOLVED_STATUSES = frozenset({"MISSING", "PARTIAL", "DEVIATED", "UNVERIFIED"})


@dataclass(frozen=True)
class VerifiedLedgerRow:
    requirement_id: str
    status: str
    evidence_refs: tuple[str, ...]
    verified_commit: str
    verified_at: str
    spec_input_hash: str
    implementation_input_hash: str
    artifact_hashes: Mapping[str, str]
    verifier_version: str
    verify_scope: str
    source_report_path: str


@dataclass(frozen=True)
class VerifiedFulfillmentLedger:
    rows: tuple[VerifiedLedgerRow, ...]


@dataclass(frozen=True)
class VerifiedLedgerReusePlan:
    reused_requirement_ids: tuple[str, ...]
    rechecked_requirement_ids: tuple[str, ...]
    invalidated_requirement_ids: tuple[str, ...]
    unresolved_requirement_ids: tuple[str, ...]


def verified_fulfillment_ledger_path(spec_dir: Path) -> Path:
    return spec_dir / "verified-fulfillment-ledger.json"


def write_verified_ledger(path: Path, ledger: VerifiedFulfillmentLedger) -> None:
    payload = {
        "schema_version": 1,
        "rows": [
            {
                "requirement_id": row.requirement_id,
                "status": row.status,
                "evidence_refs": list(row.evidence_refs),
                "verified_commit": row.verified_commit,
                "verified_at": row.verified_at,
                "spec_input_hash": row.spec_input_hash,
                "implementation_input_hash": row.implementation_input_hash,
                "artifact_hashes": dict(row.artifact_hashes),
                "verifier_version": row.verifier_version,
                "verify_scope": row.verify_scope,
                "source_report_path": row.source_report_path,
            }
            for row in ledger.rows
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_verified_ledger(
    *,
    report_path: Path,
    spec_input_hash: str,
    implementation_input_hash: str,
    artifact_hashes: Mapping[str, str],
    verifier_version: str,
) -> VerifiedFulfillmentLedger:
    """Build a row-level ledger from a fulfillment report."""
    metadata = read_fulfillment_metadata(report_path)
    verified_commit = _string(metadata.get("verified_commit"))
    verified_at = _string(metadata.get("verified_at"))
    verify_scope = _string(metadata.get("verify_scope")) or "full"
    rows: list[VerifiedLedgerRow] = []
    for row in _fulfillment_rows(report_path.read_text(encoding="utf-8", errors="replace")):
        evidence_refs = _evidence_refs(row.evidence)
        rows.append(
            VerifiedLedgerRow(
                requirement_id=row.requirement_id,
                status=row.status,
                evidence_refs=evidence_refs,
                verified_commit=verified_commit,
                verified_at=verified_at,
                spec_input_hash=spec_input_hash,
                implementation_input_hash=implementation_input_hash,
                artifact_hashes={
                    ref: artifact_hashes[ref]
                    for ref in evidence_refs
                    if ref in artifact_hashes
                },
                verifier_version=verifier_version,
                verify_scope=verify_scope,
                source_report_path=str(report_path),
            )
        )
    return VerifiedFulfillmentLedger(rows=tuple(rows))


def plan_verified_ledger_reuse(
    ledger: VerifiedFulfillmentLedger,
    *,
    current_spec_input_hash: str,
    current_implementation_input_hash: str,
    current_artifact_hashes: Mapping[str, str],
    current_verifier_version: str,
) -> VerifiedLedgerReusePlan:
    """Return which ledger rows can be reused and which need judgment."""
    reused: list[str] = []
    invalidated: list[str] = []
    unresolved: list[str] = []

    for row in ledger.rows:
        if row.status in UNRESOLVED_STATUSES:
            unresolved.append(row.requirement_id)
            continue
        if _row_invalidated(
            row,
            current_spec_input_hash=current_spec_input_hash,
            current_implementation_input_hash=current_implementation_input_hash,
            current_artifact_hashes=current_artifact_hashes,
            current_verifier_version=current_verifier_version,
        ):
            invalidated.append(row.requirement_id)
        else:
            reused.append(row.requirement_id)

    rechecked = tuple(dict.fromkeys([*invalidated, *unresolved]))
    return VerifiedLedgerReusePlan(
        reused_requirement_ids=tuple(reused),
        rechecked_requirement_ids=rechecked,
        invalidated_requirement_ids=tuple(invalidated),
        unresolved_requirement_ids=tuple(unresolved),
    )


def _row_invalidated(
    row: VerifiedLedgerRow,
    *,
    current_spec_input_hash: str,
    current_implementation_input_hash: str,
    current_artifact_hashes: Mapping[str, str],
    current_verifier_version: str,
) -> bool:
    if row.spec_input_hash != current_spec_input_hash:
        return True
    if row.verifier_version != current_verifier_version:
        return True
    if not row.evidence_refs:
        return row.implementation_input_hash != current_implementation_input_hash
    for ref in row.evidence_refs:
        if row.artifact_hashes.get(ref) != current_artifact_hashes.get(ref):
            return True
    return False


@dataclass(frozen=True)
class _ReportRow:
    requirement_id: str
    status: str
    evidence: str


_REQ_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9_.:]+)+$")
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n?", re.DOTALL)


def _fulfillment_rows(markdown: str) -> tuple[_ReportRow, ...]:
    rows: list[_ReportRow] = []
    for line in _strip_frontmatter(markdown).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3 or cells[0] == "ID" or not _REQ_ID_RE.match(cells[0]):
            continue
        rows.append(
            _ReportRow(
                requirement_id=cells[0],
                status=cells[1].upper(),
                evidence=cells[2],
            )
        )
    return tuple(rows)


def _evidence_refs(evidence: str) -> tuple[str, ...]:
    refs: list[str] = []
    for item in re.split(r"[,; ]+", evidence):
        normalized = _normalize_evidence_ref(item)
        if normalized and "/" in normalized and normalized not in refs:
            refs.append(normalized)
    return tuple(refs)


def _normalize_evidence_ref(value: str) -> str:
    normalized = value.strip().strip("`[]()")
    if ":" in normalized:
        path, suffix = normalized.rsplit(":", 1)
        if suffix.isdigit():
            normalized = path
    return normalized.replace("\\", "/").lstrip("./")


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""

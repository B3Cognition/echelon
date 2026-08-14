"""Minimal content-bound authorization seam for accepted Phase 1 quality debt."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Mapping

from harness.proportional_quality import (
    QualityCandidateManifest,
    QualityCandidateIntegrityError,
    validate_repair_state,
)


SCHEMA_VERSION = 1


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise QualityCandidateIntegrityError(
            f"quality-debt input could not be read: {path.name}"
        ) from exc


def _project_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "quality-debt path escapes the project root"
        ) from exc


def _write_atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    content = (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    )
    descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("short quality-debt write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
    except OSError as exc:
        raise QualityCandidateIntegrityError(
            "quality-debt artifact persistence failed"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_quality_debt_authorization(
    *,
    project_root: Path,
    spec_dir: Path,
    candidate: QualityCandidateManifest,
    candidate_manifest: Path,
    repair_state: Mapping[str, object],
    decision_id: str,
    resolved_by: str,
) -> dict[str, object]:
    """Write ``quality-debt.json`` and return its schema-v1 authorization.

    This deliberately narrow Task 5 seam constructs debt only from an eligible,
    still-failing restored candidate.  Task 6 adds exhaustive currentness checks
    at every downstream prerequisite boundary.
    """
    if not isinstance(candidate, QualityCandidateManifest):
        raise QualityCandidateIntegrityError("quality-debt candidate is invalid")
    if candidate.schema_version != SCHEMA_VERSION or candidate.eligibility_reasons:
        raise QualityCandidateIntegrityError(
            "quality-debt candidate is not eligible"
        )
    if type(decision_id) is not str or not decision_id.strip():
        raise QualityCandidateIntegrityError("quality-debt decision ID is invalid")
    if resolved_by not in {"user", "COMMANDER"}:
        raise QualityCandidateIntegrityError("quality-debt resolver is invalid")

    validated_repair = validate_repair_state(repair_state)
    root = Path(project_root).resolve()
    resolved_spec_dir = Path(spec_dir).resolve()
    manifest_path = Path(candidate_manifest).resolve()
    evidence_path = Path(candidate.understanding_evidence).resolve()
    source_path = resolved_spec_dir / "spec.md"
    source_digest = _sha256(source_path)
    artifact_digests = dict(candidate.owned_artifact_digests)
    if artifact_digests.get("spec.md") != source_digest:
        raise QualityCandidateIntegrityError(
            "restored candidate does not match the current specification"
        )
    evidence_digest = _sha256(evidence_path)
    if evidence_digest != candidate.understanding_evidence_digest:
        raise QualityCandidateIntegrityError(
            "quality-debt Understanding evidence digest mismatch"
        )
    if manifest_path.name != f"{candidate.candidate_id}.json":
        raise QualityCandidateIntegrityError(
            "quality-debt candidate manifest identity mismatch"
        )
    manifest_digest = _sha256(manifest_path)

    failed_gates = [
        {
            "name": name,
            "score": score,
            "threshold": threshold,
            "margin": float(Decimal(str(score)) - Decimal(str(threshold))),
        }
        for name, score, threshold, passed in candidate.normalized_gates
        if not passed
    ]
    if not failed_gates:
        raise QualityCandidateIntegrityError(
            "passing candidates cannot create quality debt"
        )

    accepted_at = datetime.now(timezone.utc).isoformat()
    source_ref = _project_relative(source_path, root)
    evidence_ref = _project_relative(evidence_path, root)
    manifest_ref = _project_relative(manifest_path, root)
    debt_path = resolved_spec_dir / "quality-debt.json"
    debt_ref = _project_relative(debt_path, root)
    debt: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": "accepted_with_debt",
        "source_path": source_ref,
        "source_sha256": source_digest,
        "understanding_evidence": evidence_ref,
        "understanding_evidence_sha256": evidence_digest,
        "candidate_manifest": manifest_ref,
        "candidate_manifest_sha256": manifest_digest,
        "selected_candidate_id": candidate.candidate_id,
        "failed_gates": failed_gates,
        "qualitative_debt": [dict(item) for item in candidate.sage_finding_routes],
        "repair_accounting": validated_repair,
        "selection_rationale": {
            "failed_gate_count": candidate.failed_gate_count,
            "worst_gate_margin": candidate.worst_gate_margin,
            "overall_score": candidate.overall_score,
            "formal_statement_count": candidate.formal_statement_count,
            "assessment_index": candidate.assessment_index,
        },
        "decision_id": decision_id,
        "resolved_by": resolved_by,
        "accepted_at": accepted_at,
    }
    _write_atomic_json(debt_path, debt)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "accepted_with_debt",
        "source_path": source_ref,
        "source_sha256": source_digest,
        "understanding_evidence": evidence_ref,
        "understanding_evidence_sha256": evidence_digest,
        "candidate_manifest": manifest_ref,
        "candidate_manifest_sha256": manifest_digest,
        "debt_artifact": debt_ref,
        "debt_artifact_sha256": _sha256(debt_path),
        "selected_candidate_id": candidate.candidate_id,
        "failed_gates": failed_gates,
        "qualitative_debt": [dict(item) for item in candidate.sage_finding_routes],
        "decision_id": decision_id,
        "resolved_by": resolved_by,
        "accepted_at": accepted_at,
    }

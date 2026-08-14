"""Content-bound authorization for accepted Phase 1 specification debt."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Mapping

from harness.blocked_decision import (
    BlockedDecisionError,
    is_valid_decision_id,
    validate_blocked_decision_v2,
)
from echelon.strict_json import loads_strict_json
from harness.proportional_quality import (
    QualityCandidateManifest,
    QualityCandidateIntegrityError,
    load_authoritative_sage_issues,
    load_quality_candidate_manifest,
    validate_repair_state,
)
from harness.understanding_gate import has_current_understanding_evidence


SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_AUTHORIZATION_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "source_path",
        "source_sha256",
        "understanding_evidence",
        "understanding_evidence_sha256",
        "candidate_manifest",
        "candidate_manifest_sha256",
        "debt_artifact",
        "debt_artifact_sha256",
        "selected_candidate_id",
        "failed_gates",
        "qualitative_debt",
        "decision_id",
        "resolved_by",
        "accepted_at",
    }
)
_DEBT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "source_path",
        "source_sha256",
        "understanding_evidence",
        "understanding_evidence_sha256",
        "candidate_manifest",
        "candidate_manifest_sha256",
        "selected_candidate_id",
        "failed_gates",
        "qualitative_debt",
        "repair_accounting",
        "selection_rationale",
        "decision_id",
        "resolved_by",
        "accepted_at",
    }
)
_CANDIDATE_ARTIFACTS = frozenset(
    {
        "spec.md",
        "requirements-overview.md",
        "quality-gates.md",
        "issues.md",
    }
)
_REQUIRED_CANDIDATE_ARTIFACTS = frozenset(
    {"spec.md", "quality-gates.md", "issues.md"}
)
_DEBT_REASON_CODES = frozenset(
    {
        "proportional_quality_budget_exhausted",
        "proportional_quality_extension_exhausted",
    }
)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise OSError("not a regular file")
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


def _resolve_project_reference(root: Path, value: object) -> Path:
    if type(value) is not str or not value or Path(value).is_absolute():
        raise QualityCandidateIntegrityError(
            "quality-debt project reference is invalid"
        )
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "quality-debt path escapes the project root"
        ) from exc
    return path


def _resolve_state_reference(root: Path, value: object) -> Path:
    if type(value) is not str or not value:
        raise QualityCandidateIntegrityError(
            "quality-debt state reference is invalid"
        )
    path = Path(value).expanduser()
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "quality-debt state reference escapes the project"
        ) from exc
    return path


def _utc_timestamp(value: object) -> datetime:
    if type(value) is not str or not value:
        raise QualityCandidateIntegrityError(
            "quality-debt timestamp is invalid"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "quality-debt timestamp is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise QualityCandidateIntegrityError(
            "quality-debt timestamp is not UTC"
        )
    return parsed


def _validate_debt_decision(
    value: object,
    *,
    decision_id: str,
    resolved_by: str,
    resolved: bool,
) -> dict[str, object]:
    try:
        decision = validate_blocked_decision_v2(value)
    except (BlockedDecisionError, TypeError, ValueError) as exc:
        raise QualityCandidateIntegrityError(
            "quality-debt decision is invalid"
        ) from exc
    option_ids = {
        option.get("id")
        for option in decision["options"]
        if isinstance(option, Mapping)
    }
    if (
        decision["id"] != decision_id
        or decision["source_kind"] != "controller_safeguard"
        or decision["source_phase"] != "phase1-why2"
        or decision["reason_code"] not in _DEBT_REASON_CODES
        or decision["classification"] != "material"
        or decision["resolution_handler"] != "proportional_quality_debt"
        or "continue_with_debt" not in option_ids
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt decision linkage is invalid"
        )
    if resolved:
        if (
            decision["status"] != "resolved"
            or decision["selected_option_id"] != "continue_with_debt"
            or decision["resolved_by"] != resolved_by
        ):
            raise QualityCandidateIntegrityError(
                "quality-debt decision resolution changed"
            )
    elif (
        decision["status"] not in {"awaiting_human", "resolving"}
        or decision["selected_option_id"] is not None
        or decision["resolved_by"] is not None
        or resolved_by == "user"
        and decision["status"] != "awaiting_human"
        or resolved_by == "COMMANDER"
        and decision["status"] != "resolving"
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt decision is not sealed for resolution"
        )
    return decision


def _verify_restored_candidate(
    *,
    root: Path,
    spec_dir: Path,
    candidate: QualityCandidateManifest,
    candidate_manifest: Path,
) -> tuple[str, str, Mapping[str, object]]:
    artifact_root = Path(candidate.run_artifact_root).resolve()
    evidence_path = Path(candidate.understanding_evidence).resolve()
    manifest_path = Path(candidate_manifest).resolve()
    try:
        spec_dir.relative_to(root)
        artifact_root.relative_to(root)
        evidence_path.relative_to(artifact_root)
        manifest_path.relative_to(artifact_root)
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "quality-debt candidate path escapes its authority root"
        ) from exc
    expected_manifest = (
        artifact_root
        / "quality-candidates"
        / f"{candidate.candidate_id}.json"
    ).resolve()
    if manifest_path != expected_manifest:
        raise QualityCandidateIntegrityError(
            "quality-debt candidate manifest identity mismatch"
        )
    loaded = load_quality_candidate_manifest(manifest_path)
    if loaded != candidate:
        raise QualityCandidateIntegrityError(
            "quality-debt candidate conflicts with its manifest"
        )

    artifact_digests = dict(candidate.owned_artifact_digests)
    if (
        len(artifact_digests) != len(candidate.owned_artifact_digests)
        or not _REQUIRED_CANDIDATE_ARTIFACTS <= set(artifact_digests)
        or not set(artifact_digests) <= _CANDIDATE_ARTIFACTS
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt candidate artifact contract is invalid"
        )
    for name, expected_digest in artifact_digests.items():
        if not _SHA256_RE.fullmatch(expected_digest) or _sha256(
            spec_dir / name
        ) != expected_digest:
            raise QualityCandidateIntegrityError(
                f"quality-debt candidate artifact digest mismatch: {name}"
            )

    authoritative_issues = load_authoritative_sage_issues(
        spec_dir / "issues.md"
    )
    if any(
        issue.get("severity") == "CRITICAL"
        or issue.get("type") == "contradiction"
        for issue in authoritative_issues
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt candidate contains a hard SAGE blocker"
        )
    issues_by_id = {
        issue["issue_id"]: issue for issue in authoritative_issues
    }
    if set(issues_by_id) != {
        str(route.get("issue_id") or "")
        for route in candidate.sage_finding_routes
    }:
        raise QualityCandidateIntegrityError(
            "quality-debt SAGE findings changed"
        )
    for route in candidate.sage_finding_routes:
        issue = issues_by_id.get(str(route.get("issue_id") or ""))
        if (
            issue is None
            or route.get("route") != "spec_repair"
            or any(
                route.get(key) != issue.get(key)
                for key in ("severity", "type", "title")
            )
        ):
            raise QualityCandidateIntegrityError(
                "quality-debt SAGE finding route is invalid"
            )

    evidence_digest = _sha256(evidence_path)
    if evidence_digest != candidate.understanding_evidence_digest:
        raise QualityCandidateIntegrityError(
            "quality-debt Understanding evidence digest mismatch"
        )
    try:
        report = loads_strict_json(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise QualityCandidateIntegrityError(
            "quality-debt Understanding evidence is malformed"
        ) from exc
    report_spec = report.get("spec") if isinstance(report, Mapping) else None
    if (
        not isinstance(report, Mapping)
        or report.get("schema_version") != SCHEMA_VERSION
        or report.get("status") != "completed"
        or report.get("phase") != "phase1-why2"
        or report.get("pass") is not False
        or report.get("requirement_count") != candidate.formal_statement_count
        or not isinstance(report_spec, Mapping)
        or report_spec.get("sha256") != artifact_digests["spec.md"]
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt Understanding evidence conflicts with the candidate"
        )
    scores = report.get("scores")
    thresholds = report.get("thresholds")
    gates = report.get("gates")
    if not all(isinstance(value, Mapping) for value in (scores, thresholds, gates)):
        raise QualityCandidateIntegrityError(
            "quality-debt Understanding gate evidence is malformed"
        )
    for name, score, threshold, passed in candidate.normalized_gates:
        gate = gates.get(name)
        if (
            scores.get(name) != score
            or thresholds.get(name) != threshold
            or not isinstance(gate, Mapping)
            or gate.get("score") != score
            or gate.get("threshold") != threshold
            or gate.get("pass") is not passed
        ):
            raise QualityCandidateIntegrityError(
                "quality-debt gates conflict with Understanding evidence"
            )
    return _sha256(manifest_path), evidence_digest, report


def _failed_gates(
    candidate: QualityCandidateManifest,
) -> list[dict[str, object]]:
    failed = [
        {
            "name": name,
            "score": score,
            "threshold": threshold,
            "margin": float(Decimal(str(score)) - Decimal(str(threshold))),
        }
        for name, score, threshold, passed in candidate.normalized_gates
        if not passed
    ]
    if not failed:
        raise QualityCandidateIntegrityError(
            "passing candidates cannot create quality debt"
        )
    return failed


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
        _fsync_directory(path.parent)
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


@dataclass(frozen=True)
class PreparedQualityDebtAuthorization:
    authorization: dict[str, object]
    debt: dict[str, object]
    debt_path: str

    def effect_payload(self) -> dict[str, object]:
        return {
            "operation": "debt_write",
            "debt_path": self.debt_path,
            "debt": dict(self.debt),
            "authorization": dict(self.authorization),
        }


def build_quality_debt_authorization(
    *,
    project_root: Path,
    spec_dir: Path,
    candidate: QualityCandidateManifest,
    candidate_manifest: Path,
    repair_state: Mapping[str, object],
    decision: Mapping[str, object],
    decision_id: str,
    resolved_by: str,
) -> PreparedQualityDebtAuthorization:
    """Prepare schema-v1 debt and authorization without external effects."""
    if not isinstance(candidate, QualityCandidateManifest):
        raise QualityCandidateIntegrityError("quality-debt candidate is invalid")
    if candidate.schema_version != SCHEMA_VERSION or candidate.eligibility_reasons:
        raise QualityCandidateIntegrityError(
            "quality-debt candidate is not eligible"
        )
    if not is_valid_decision_id(decision_id):
        raise QualityCandidateIntegrityError("quality-debt decision ID is invalid")
    if resolved_by not in {"user", "COMMANDER"}:
        raise QualityCandidateIntegrityError("quality-debt resolver is invalid")
    _validate_debt_decision(
        decision,
        decision_id=decision_id,
        resolved_by=resolved_by,
        resolved=False,
    )

    validated_repair = validate_repair_state(repair_state)
    if candidate.candidate_id not in validated_repair["candidate_ids"]:
        raise QualityCandidateIntegrityError(
            "quality-debt candidate is not in the repair history"
        )
    root = Path(project_root).resolve()
    resolved_spec_dir = Path(spec_dir).resolve()
    manifest_path = Path(candidate_manifest).resolve()
    evidence_path = Path(candidate.understanding_evidence).resolve()
    source_path = resolved_spec_dir / "spec.md"
    manifest_digest, evidence_digest, _report = _verify_restored_candidate(
        root=root,
        spec_dir=resolved_spec_dir,
        candidate=candidate,
        candidate_manifest=manifest_path,
    )
    source_digest = _sha256(source_path)
    failed_gates = _failed_gates(candidate)

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
    debt_content = (json.dumps(debt, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    authorization = {
        "schema_version": SCHEMA_VERSION,
        "status": "accepted_with_debt",
        "source_path": source_ref,
        "source_sha256": source_digest,
        "understanding_evidence": evidence_ref,
        "understanding_evidence_sha256": evidence_digest,
        "candidate_manifest": manifest_ref,
        "candidate_manifest_sha256": manifest_digest,
        "debt_artifact": debt_ref,
        "debt_artifact_sha256": hashlib.sha256(debt_content).hexdigest(),
        "selected_candidate_id": candidate.candidate_id,
        "failed_gates": failed_gates,
        "qualitative_debt": [dict(item) for item in candidate.sage_finding_routes],
        "decision_id": decision_id,
        "resolved_by": resolved_by,
        "accepted_at": accepted_at,
    }
    return PreparedQualityDebtAuthorization(
        authorization=authorization,
        debt=debt,
        debt_path=debt_ref,
    )


def _validate_failed_gates(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise QualityCandidateIntegrityError(
            "quality-debt failed gates are invalid"
        )
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, Mapping) or set(row) != {
            "name",
            "score",
            "threshold",
            "margin",
        }:
            raise QualityCandidateIntegrityError(
                "quality-debt failed gates are invalid"
            )
        name = row.get("name")
        score = row.get("score")
        threshold = row.get("threshold")
        margin = row.get("margin")
        if (
            type(name) is not str
            or not name
            or name in seen
            or type(score) not in {int, float}
            or type(threshold) not in {int, float}
            or type(margin) not in {int, float}
            or not all(
                math.isfinite(float(item))
                for item in (score, threshold, margin)
            )
            or float(margin)
            != float(Decimal(str(score)) - Decimal(str(threshold)))
            or float(margin) >= 0
        ):
            raise QualityCandidateIntegrityError(
                "quality-debt failed gate margin is invalid"
            )
        seen.add(name)
        normalized.append(dict(row))
    return normalized


def _validate_last_resolution_link(
    state: Mapping[str, object],
    decision_id: str,
) -> None:
    completion = state.get("last_human_input_completion")
    if (
        not isinstance(completion, Mapping)
        or set(completion)
        != {
            "schema_version",
            "completion_id",
            "intent_sha256",
            "receipts_sha256",
            "decision_id",
        }
        or completion.get("schema_version") != SCHEMA_VERSION
        or type(completion.get("completion_id")) is not str
        or re.fullmatch(r"[0-9a-f]{32}", str(completion["completion_id"])) is None
        or _SHA256_RE.fullmatch(str(completion.get("intent_sha256") or ""))
        is None
        or _SHA256_RE.fullmatch(str(completion.get("receipts_sha256") or ""))
        is None
        or completion.get("decision_id") != decision_id
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt completion linkage is invalid"
        )


def _current_quality_debt_authorization(
    state: Mapping[str, object],
    *,
    project_root: Path,
) -> dict[str, object]:
    root = Path(project_root).resolve()
    stored = state.get("spec_quality_debt_authorization")
    if not isinstance(stored, Mapping) or set(stored) != _AUTHORIZATION_KEYS:
        raise QualityCandidateIntegrityError(
            "quality-debt authorization schema is invalid"
        )
    authorization = dict(stored)
    if (
        authorization.get("schema_version") != SCHEMA_VERSION
        or authorization.get("status") != "accepted_with_debt"
        or authorization.get("resolved_by") not in {"user", "COMMANDER"}
        or not is_valid_decision_id(authorization.get("decision_id"))
        or type(authorization.get("selected_candidate_id")) is not str
        or not authorization["selected_candidate_id"]
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt authorization identity is invalid"
        )
    accepted_at = _utc_timestamp(authorization.get("accepted_at"))
    for key in (
        "source_sha256",
        "understanding_evidence_sha256",
        "candidate_manifest_sha256",
        "debt_artifact_sha256",
    ):
        if _SHA256_RE.fullmatch(str(authorization.get(key) or "")) is None:
            raise QualityCandidateIntegrityError(
                "quality-debt authorization digest is invalid"
            )
    source_path = _resolve_project_reference(root, authorization["source_path"])
    evidence_path = _resolve_project_reference(
        root,
        authorization["understanding_evidence"],
    )
    manifest_path = _resolve_project_reference(
        root,
        authorization["candidate_manifest"],
    )
    debt_path = _resolve_project_reference(root, authorization["debt_artifact"])
    spec_dir_ref = state.get("spec_dir")
    if type(spec_dir_ref) is not str:
        raise QualityCandidateIntegrityError(
            "quality-debt specification authority is invalid"
        )
    spec_dir = Path(spec_dir_ref)
    spec_dir = (
        spec_dir.resolve()
        if spec_dir.is_absolute()
        else (root / spec_dir).resolve()
    )
    try:
        spec_dir.relative_to(root)
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "quality-debt specification root escapes the project"
        ) from exc
    if source_path != spec_dir / "spec.md" or debt_path != spec_dir / "quality-debt.json":
        raise QualityCandidateIntegrityError(
            "quality-debt artifact is not beside the active specification"
        )
    if (
        _sha256(source_path) != authorization["source_sha256"]
        or _sha256(evidence_path)
        != authorization["understanding_evidence_sha256"]
        or _sha256(manifest_path) != authorization["candidate_manifest_sha256"]
        or _sha256(debt_path) != authorization["debt_artifact_sha256"]
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt authorization content changed"
        )

    try:
        debt = loads_strict_json(debt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise QualityCandidateIntegrityError(
            "quality-debt artifact is malformed"
        ) from exc
    if not isinstance(debt, Mapping) or set(debt) != _DEBT_KEYS:
        raise QualityCandidateIntegrityError(
            "quality-debt artifact schema changed"
        )
    shared = {
        "schema_version",
        "status",
        "source_path",
        "source_sha256",
        "understanding_evidence",
        "understanding_evidence_sha256",
        "candidate_manifest",
        "candidate_manifest_sha256",
        "selected_candidate_id",
        "failed_gates",
        "qualitative_debt",
        "decision_id",
        "resolved_by",
        "accepted_at",
    }
    if any(debt.get(key) != authorization.get(key) for key in shared):
        raise QualityCandidateIntegrityError(
            "quality-debt artifact conflicts with its authorization"
        )
    failed_gates = _validate_failed_gates(authorization["failed_gates"])
    qualitative = authorization.get("qualitative_debt")
    if not isinstance(qualitative, list) or any(
        not isinstance(item, Mapping) for item in qualitative
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt qualitative evidence is invalid"
        )

    candidate = load_quality_candidate_manifest(manifest_path)
    if (
        candidate.candidate_id != authorization["selected_candidate_id"]
        or candidate.eligibility_reasons
        or _failed_gates(candidate) != failed_gates
        or [dict(item) for item in candidate.sage_finding_routes]
        != [dict(item) for item in qualitative]
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt candidate evidence changed"
        )
    manifest_digest, evidence_digest, _report = _verify_restored_candidate(
        root=root,
        spec_dir=spec_dir,
        candidate=candidate,
        candidate_manifest=manifest_path,
    )
    if (
        manifest_digest != authorization["candidate_manifest_sha256"]
        or evidence_digest != authorization["understanding_evidence_sha256"]
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt candidate input digest changed"
        )

    repair = validate_repair_state(state.get("phase1_quality_repair"))
    if debt.get("repair_accounting") != repair:
        raise QualityCandidateIntegrityError(
            "quality-debt repair accounting changed"
        )
    expected_selection = {
        "failed_gate_count": candidate.failed_gate_count,
        "worst_gate_margin": candidate.worst_gate_margin,
        "overall_score": candidate.overall_score,
        "formal_statement_count": candidate.formal_statement_count,
        "assessment_index": candidate.assessment_index,
    }
    if debt.get("selection_rationale") != expected_selection:
        raise QualityCandidateIntegrityError(
            "quality-debt selection rationale changed"
        )

    evidence = state.get("understanding_evidence")
    if (
        not isinstance(evidence, Mapping)
        or evidence.get("phase") != "phase1-why2"
        or evidence.get("status") != "completed"
        or evidence.get("pass") is not False
        or evidence.get("digest") != authorization["understanding_evidence_sha256"]
        or _resolve_state_reference(root, evidence.get("path")) != evidence_path
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt Understanding state linkage changed"
        )
    completed = state.get("completed_phases")
    if not isinstance(completed, list) or "phase1-why2" not in completed:
        raise QualityCandidateIntegrityError(
            "quality-debt WHY2 completion is missing"
        )
    if not has_current_understanding_evidence(
        state,
        project_root=root,
        phase="phase1-why2",
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt Understanding evidence is not current"
        )
    candidate_evidence = state.get("proportional_quality_candidate_evidence")
    if (
        not isinstance(candidate_evidence, Mapping)
        or candidate_evidence.get("selected_candidate_id")
        != candidate.candidate_id
        or candidate_evidence.get("candidate_manifest_sha256")
        != authorization["candidate_manifest_sha256"]
        or candidate_evidence.get("selected_spec_sha256")
        != authorization["source_sha256"]
        or candidate_evidence.get("eligibility_reasons") != []
        or _resolve_state_reference(
            root,
            candidate_evidence.get("candidate_manifest"),
        ) != manifest_path
        or candidate_evidence.get("failed_gates")
        != [
            {
                "name": name,
                "score": score,
                "threshold": threshold,
                "pass": passed,
            }
            for name, score, threshold, passed in candidate.normalized_gates
            if not passed
        ]
        or candidate_evidence.get("sage_finding_routes")
        != [dict(item) for item in candidate.sage_finding_routes]
    ):
        raise QualityCandidateIntegrityError(
            "quality-debt candidate state linkage changed"
        )

    decision = _validate_debt_decision(
        state.get("blocked_decision"),
        decision_id=str(authorization["decision_id"]),
        resolved_by=str(authorization["resolved_by"]),
        resolved=True,
    )
    resolved_at = _utc_timestamp(decision.get("resolved_at"))
    if accepted_at > resolved_at:
        raise QualityCandidateIntegrityError(
            "quality-debt authorization postdates its resolution"
        )
    _validate_last_resolution_link(
        state,
        str(authorization["decision_id"]),
    )
    return authorization


def has_current_quality_debt_authorization(
    state: Mapping[str, object],
    *,
    project_root: Path,
) -> bool:
    """Return whether every recorded debt authority input is still current."""
    try:
        _current_quality_debt_authorization(
            state,
            project_root=project_root,
        )
    except (
        BlockedDecisionError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        QualityCandidateIntegrityError,
    ):
        return False
    return True


def apply_or_verify_quality_debt_effect(
    project_root: Path,
    payload: Mapping[str, object],
    *,
    expected_receipt: object | None = None,
) -> dict[str, object]:
    """Idempotently apply one sealed debt write/removal operation."""
    root = Path(project_root).resolve()
    if not isinstance(payload, Mapping):
        raise QualityCandidateIntegrityError("quality-debt effect is invalid")
    operation = payload.get("operation")
    debt_ref = payload.get("debt_path")
    if type(debt_ref) is not str or not debt_ref:
        raise QualityCandidateIntegrityError("quality-debt effect path is invalid")
    debt_path = _resolve_project_reference(root, debt_ref)
    if operation == "debt_write":
        if set(payload) != {"operation", "debt_path", "debt", "authorization"}:
            raise QualityCandidateIntegrityError(
                "quality-debt write effect is invalid"
            )
        debt = payload.get("debt")
        authorization = payload.get("authorization")
        if (
            not isinstance(debt, Mapping)
            or set(debt) != _DEBT_KEYS
            or not isinstance(authorization, Mapping)
            or set(authorization) != _AUTHORIZATION_KEYS
            or authorization.get("debt_artifact") != debt_ref
        ):
            raise QualityCandidateIntegrityError(
                "quality-debt write effect is invalid"
            )
        shared = _AUTHORIZATION_KEYS - {
            "debt_artifact",
            "debt_artifact_sha256",
        }
        if any(debt.get(key) != authorization.get(key) for key in shared):
            raise QualityCandidateIntegrityError(
                "quality-debt write evidence changed"
            )
        content = (
            json.dumps(dict(debt), indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        if authorization.get("debt_artifact_sha256") != digest:
            raise QualityCandidateIntegrityError(
                "quality-debt authorization digest changed"
            )
        if debt_path.exists():
            try:
                metadata = debt_path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(
                    metadata.st_mode
                ):
                    raise OSError("not a regular file")
                if debt_path.read_bytes() != content:
                    raise QualityCandidateIntegrityError(
                        "quality-debt artifact conflicts with sealed authorization"
                    )
            except OSError as exc:
                raise QualityCandidateIntegrityError(
                    "quality-debt artifact could not be verified"
                ) from exc
        else:
            _write_atomic_json(debt_path, debt)
        receipt = {
            "schema_version": 1,
            "operation": operation,
            "debt_path": debt_ref,
            "debt_artifact_sha256": digest,
        }
    elif operation == "debt_remove":
        if set(payload) != {"operation", "debt_path"}:
            raise QualityCandidateIntegrityError("quality-debt removal effect is invalid")
        try:
            debt_path.unlink(missing_ok=True)
            _fsync_directory(debt_path.parent)
        except OSError as exc:
            raise QualityCandidateIntegrityError("quality-debt artifact removal failed") from exc
        receipt = {
            "schema_version": 1,
            "operation": operation,
            "debt_path": debt_ref,
            "removed": True,
        }
    else:
        raise QualityCandidateIntegrityError("quality-debt effect operation is invalid")
    if expected_receipt is not None and expected_receipt != receipt:
        raise QualityCandidateIntegrityError("quality-debt effect receipt mismatch")
    return receipt

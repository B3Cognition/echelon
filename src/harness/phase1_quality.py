"""Content-bound certification for Phase 1 specification quality."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from echelon.spec_authoring import PROPORTIONAL_MODE, normalize_spec_authoring_mode

from harness.phase1_quality_debt import has_current_quality_debt_authorization
from harness.proportional_quality import (
    AuthoritativeSageEvidenceSnapshot,
    QualityCandidateIntegrityError,
    load_authoritative_sage_evidence_snapshot,
    require_current_authoritative_sage_evidence_snapshot,
)
from harness.understanding_gate import has_current_understanding_evidence


SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class AuthoritativeQualityAssessment:
    numeric_pass: bool
    provider_verdict: str
    sage_verdict: str
    authoritative_issues: tuple[Mapping[str, object], ...]
    exact_routes: tuple[Mapping[str, object], ...]
    ordinary_pass: bool
    proportional_failure: bool
    hard_blockers: tuple[str, ...]
    sage_evidence: AuthoritativeSageEvidenceSnapshot | None = None


def build_phase1_quality_certificate(
    state: Mapping[str, object],
    *,
    project_root: Path,
    authoritative_sage_assessment: AuthoritativeQualityAssessment | None = None,
) -> dict[str, object] | None:
    """Build a schema-v2 certificate from an authoritative ordinary PASS."""
    assessment = authoritative_sage_assessment
    if (
        not isinstance(assessment, AuthoritativeQualityAssessment)
        or assessment.numeric_pass is not True
        or assessment.provider_verdict != "PASS"
        or assessment.sage_verdict != "PASS"
        or assessment.authoritative_issues
        or assessment.exact_routes
        or assessment.ordinary_pass is not True
        or assessment.proportional_failure is not False
        or assessment.hard_blockers
    ):
        return None
    base = _passing_certificate_base(state, project_root=project_root)
    if base is None:
        return None
    sage_snapshot = assessment.sage_evidence
    if not isinstance(sage_snapshot, AuthoritativeSageEvidenceSnapshot):
        return None
    issues_path = _authoritative_issues_path(state, project_root)
    if issues_path is None:
        return None
    try:
        require_current_authoritative_sage_evidence_snapshot(
            sage_snapshot,
            issues_path,
            project_root=project_root,
        )
    except QualityCandidateIntegrityError:
        return None
    if (
        sage_snapshot.project_relative_path
        != _relative_or_absolute(issues_path, project_root)
        or sage_snapshot.verdict != "PASS"
        or sage_snapshot.issues
        or sage_snapshot.verdict != assessment.sage_verdict
        or sage_snapshot.issues != assessment.authoritative_issues
    ):
        return None
    return {
        "schema_version": SCHEMA_VERSION,
        **base,
        "sage_evidence": sage_snapshot.project_relative_path,
        "sage_evidence_sha256": sage_snapshot.sha256,
        "sage_verdict": "PASS",
    }


def _passing_certificate_base(
    state: Mapping[str, object],
    *,
    project_root: Path,
) -> dict[str, object] | None:
    if not has_current_understanding_evidence(
        state,
        project_root=project_root,
        phase="phase1-why2",
    ):
        return None

    evidence = state.get("understanding_evidence")
    if not isinstance(evidence, Mapping) or evidence.get("pass") is not True:
        return None
    report_ref = evidence.get("path")
    report_digest = evidence.get("digest")
    if (
        not isinstance(report_ref, str)
        or not report_ref.strip()
        or not isinstance(report_digest, str)
        or not _SHA256_RE.fullmatch(report_digest)
    ):
        return None
    report_path = _resolve(project_root, report_ref)
    try:
        if _sha256(report_path) != report_digest:
            return None
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if report.get("pass") is not True:
        return None

    spec_path = _spec_path(state, project_root)
    if spec_path is None or not spec_path.is_file():
        return None
    source_digest = _sha256(spec_path)
    report_spec = report.get("spec")
    if (
        not isinstance(report_spec, Mapping)
        or report_spec.get("sha256") != source_digest
    ):
        return None

    return {
        "status": "passed",
        "source_path": _relative_or_absolute(spec_path, project_root),
        "source_sha256": source_digest,
        "understanding_evidence": _relative_or_absolute(
            report_path,
            project_root,
        ),
        "understanding_evidence_sha256": report_digest,
        "sage_phase": "phase1-why2",
    }


def build_legacy_phase1_quality_certificate(
    state: Mapping[str, object],
    *,
    project_root: Path,
) -> dict[str, object] | None:
    base = _passing_certificate_base(state, project_root=project_root)
    if base is None:
        return None
    return {"schema_version": LEGACY_SCHEMA_VERSION, **base}


def has_current_phase1_quality_certificate(
    state: Mapping[str, object],
    *,
    project_root: Path,
) -> bool:
    """Return whether the stored certificate matches current source evidence."""
    completed = state.get("completed_phases")
    if not isinstance(completed, list) or "phase1-why2" not in completed:
        return False
    stored = state.get("spec_quality_certificate")
    if not isinstance(stored, Mapping):
        return False
    schema_version = stored.get("schema_version")
    if schema_version == LEGACY_SCHEMA_VERSION:
        if normalize_spec_authoring_mode(state.get("spec_authoring_mode")) == PROPORTIONAL_MODE:
            return False
        current = build_legacy_phase1_quality_certificate(
            state,
            project_root=project_root,
        )
    elif schema_version == SCHEMA_VERSION:
        sage_snapshot = _current_v2_sage_evidence(
            state,
            stored,
            project_root=project_root,
        )
        if sage_snapshot is None:
            return False
        current = build_phase1_quality_certificate(
            state,
            project_root=project_root,
            authoritative_sage_assessment=AuthoritativeQualityAssessment(
                numeric_pass=True,
                provider_verdict="PASS",
                sage_verdict="PASS",
                authoritative_issues=(),
                exact_routes=(),
                ordinary_pass=True,
                proportional_failure=False,
                hard_blockers=(),
                sage_evidence=sage_snapshot,
            ),
        )
    else:
        return False
    if current is None:
        return False
    return dict(stored) == current


def _current_v2_sage_evidence(
    state: Mapping[str, object],
    stored: Mapping[str, object],
    *,
    project_root: Path,
) -> AuthoritativeSageEvidenceSnapshot | None:
    issues_path = _authoritative_issues_path(state, project_root)
    if issues_path is None:
        return None
    expected_ref = _relative_or_absolute(issues_path, project_root)
    stored_ref = stored.get("sage_evidence")
    stored_digest = stored.get("sage_evidence_sha256")
    if (
        type(stored_ref) is not str
        or stored_ref != expected_ref
        or Path(stored_ref).is_absolute()
        or any(part == ".." for part in Path(stored_ref).parts)
        or type(stored_digest) is not str
        or _SHA256_RE.fullmatch(stored_digest) is None
        or stored.get("sage_verdict") != "PASS"
    ):
        return None
    try:
        snapshot = load_authoritative_sage_evidence_snapshot(
            issues_path,
            project_root=project_root,
        )
    except QualityCandidateIntegrityError:
        return None
    if (
        snapshot.project_relative_path != expected_ref
        or snapshot.verdict != "PASS"
        or snapshot.issues
        or snapshot.sha256 != stored_digest
    ):
        return None
    return snapshot


def has_current_phase1_quality_prerequisite(
    state: Mapping[str, object],
    *,
    project_root: Path,
) -> bool:
    """Accept an unchanged PASS certificate or explicit current debt authority."""
    return has_current_phase1_quality_certificate(
        state,
        project_root=project_root,
    ) or has_current_quality_debt_authorization(
        state,
        project_root=project_root,
    )


def _spec_path(
    state: Mapping[str, object],
    project_root: Path,
) -> Path | None:
    spec_dir_ref = str(state.get("spec_dir") or "").strip()
    if not spec_dir_ref:
        return None
    return _resolve(project_root, spec_dir_ref) / "spec.md"


def _authoritative_issues_path(
    state: Mapping[str, object],
    project_root: Path,
) -> Path | None:
    spec_path = _spec_path(state, project_root)
    if spec_path is None:
        return None
    root = Path(project_root).resolve()
    issues_path = spec_path.parent.resolve() / "issues.md"
    try:
        issues_path.relative_to(root)
    except ValueError:
        return None
    return issues_path


def _resolve(project_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root / path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_or_absolute(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())

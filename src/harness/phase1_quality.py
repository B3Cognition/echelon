"""Content-bound certification for Phase 1 specification quality."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

from harness.understanding_gate import has_current_understanding_evidence


SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


def build_phase1_quality_certificate(
    state: Mapping[str, object],
    *,
    project_root: Path,
) -> dict[str, object] | None:
    """Build a certificate only from current passing WHY2 evidence."""
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
        "schema_version": SCHEMA_VERSION,
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
    current = build_phase1_quality_certificate(
        state,
        project_root=project_root,
    )
    if current is None:
        return False
    return dict(stored) == current


def _spec_path(
    state: Mapping[str, object],
    project_root: Path,
) -> Path | None:
    spec_dir_ref = str(state.get("spec_dir") or "").strip()
    if not spec_dir_ref:
        return None
    return _resolve(project_root, spec_dir_ref) / "spec.md"


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

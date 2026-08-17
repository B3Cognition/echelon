"""Controller-owned accounting for proportional Phase 1 quality repair."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
from types import MappingProxyType
from typing import Mapping, MutableMapping, Sequence

from echelon.git_helpers import GitHelperError, run_git, run_git_hardened
from echelon.strict_json import loads_strict_json
from echelon.spec_authoring import (
    PERFECTIONIST_MODE,
    PROPORTIONAL_MODE,
    normalize_spec_authoring_mode,
)
from kernel.quality_gates import evaluate_quality_thresholds
from harness.phase_checkpoints import (
    PhaseCheckpoint,
    PhaseCheckpointError,
    create_or_recover_completion_checkpoint,
    create_phase_checkpoint,
    restore_checkpoint_artifacts,
    verify_checkpoint_artifact_digests,
)


SCHEMA_VERSION = 1
AUTOMATIC_REPAIR_LIMIT = 3
EXTENSION_REPAIR_LIMIT = 1

_REPAIR_STATE_KEYS = frozenset(
    {
        "schema_version",
        "authoring_mode",
        "automatic_limit",
        "automatic_consumed",
        "extension_limit",
        "extension_authorized",
        "extension_consumed",
        "migration_basis",
        "baseline_candidate_id",
        "candidate_ids",
    }
)
_PRE_CANDIDATE_REPAIR_STATE_KEYS = _REPAIR_STATE_KEYS - {
    "baseline_candidate_id",
    "candidate_ids",
}
_MIGRATION_BASES = frozenset(
    {"fresh", "why2_history", "iteration_fallback"}
)


@dataclass(frozen=True)
class RepairOutcome:
    """Detached repair state and its accounting result for one WHAT attempt."""

    repair_state: dict[str, object]
    outcome: str


class QualityCandidateIntegrityError(RuntimeError):
    """Raised when candidate evidence or restoration cannot be trusted."""


@dataclass(frozen=True)
class AuthoritativeSageEvidenceSnapshot:
    """One parsed SAGE artifact and the digest of those exact pinned bytes."""

    project_relative_path: str
    content: bytes = field(repr=False)
    sha256: str
    verdict: str
    issues: tuple[Mapping[str, object], ...]
    file_identity: tuple[object, ...]


@dataclass(frozen=True)
class QualityCandidateManifest:
    schema_version: int
    candidate_id: str
    checkpoint_commit: str
    owned_artifact_digests: tuple[tuple[str, str], ...]
    run_artifact_root: str
    understanding_evidence: str
    understanding_evidence_digest: str
    normalized_gates: tuple[tuple[str, float, float, bool], ...]
    sage_finding_routes: tuple[Mapping[str, object], ...]
    failed_gate_count: int
    worst_gate_margin: float
    overall_score: float
    formal_statement_count: int
    byte_count: int
    repair_number: int
    assessment_index: int
    eligibility_reasons: tuple[str, ...]


@dataclass(frozen=True)
class QualityCandidateSnapshot:
    """One parsed candidate and the digest of those exact pinned bytes."""

    manifest: QualityCandidateManifest
    sha256: str


@dataclass(frozen=True)
class CandidateCheckpointEntry:
    path: str
    mode: str
    blob_oid: str
    sha256: str
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class PreflightedCandidateRestore:
    snapshot: QualityCandidateSnapshot
    entries: tuple[CandidateCheckpointEntry, ...]


_CANDIDATE_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "checkpoint_commit",
        "owned_artifact_digests",
        "run_artifact_root",
        "understanding_evidence",
        "understanding_evidence_digest",
        "normalized_gates",
        "sage_finding_routes",
        "failed_gate_count",
        "worst_gate_margin",
        "overall_score",
        "formal_statement_count",
        "byte_count",
        "repair_number",
        "assessment_index",
        "eligibility_reasons",
    }
)


_SAGE_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
_SAGE_ISSUE_TYPES = frozenset(
    {
        "ambiguity",
        "incompleteness",
        "inconsistency",
        "untestability",
        "missing-requirement",
        "contradiction",
    }
)
_SAGE_REQUIRED_ISSUE_FIELDS = (
    "Description",
    "Affected artifact",
    "Affected section",
    "Evidence",
    "Recommendation",
    "Responsible agent",
    "Action Required",
)


def load_authoritative_sage_assessment(
    path: Path,
) -> tuple[str, tuple[dict[str, str], ...]]:
    """Parse the required current WHY2 issues artifact or fail closed."""
    issue_path = Path(path)
    authority_root = (
        issue_path.parent.resolve()
        if issue_path.is_absolute()
        else Path.cwd().resolve()
    )
    snapshot = load_authoritative_sage_evidence_snapshot(
        issue_path,
        project_root=authority_root,
    )
    return snapshot.verdict, tuple(dict(issue) for issue in snapshot.issues)


def load_authoritative_sage_evidence_snapshot(
    path: Path,
    *,
    project_root: Path,
) -> AuthoritativeSageEvidenceSnapshot:
    """Read, digest, and parse one no-follow regular SAGE evidence snapshot."""
    issue_path, relative_path = _safe_authoritative_sage_path(
        path,
        project_root=project_root,
    )
    parent_descriptor: int | None = None
    try:
        parent_descriptor = _open_pinned_candidate_directory(issue_path.parent)
        pinned = _candidate_entry_snapshot(parent_descriptor, issue_path.name)
        if pinned is None:
            raise OSError("authoritative SAGE issues are missing")
        digest, content, identity, _mode = pinned
        verdict, issues = _parse_authoritative_sage_assessment_bytes(content)
    except QualityCandidateIntegrityError:
        raise
    except (OSError, ValueError) as exc:
        raise QualityCandidateIntegrityError(
            "authoritative SAGE issues are missing or malformed"
        ) from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    return AuthoritativeSageEvidenceSnapshot(
        project_relative_path=relative_path,
        content=content,
        sha256=digest,
        verdict=verdict,
        issues=tuple(MappingProxyType(dict(issue)) for issue in issues),
        file_identity=identity,
    )


def require_current_authoritative_sage_evidence_snapshot(
    snapshot: AuthoritativeSageEvidenceSnapshot,
    path: Path,
    *,
    project_root: Path,
) -> None:
    """Fail when a pinned SAGE entry no longer names the captured file."""
    if not isinstance(snapshot, AuthoritativeSageEvidenceSnapshot):
        raise QualityCandidateIntegrityError(
            "authoritative SAGE evidence snapshot is invalid"
        )
    parsed_verdict, parsed_issues = _parse_authoritative_sage_assessment_bytes(
        snapshot.content
    )
    if (
        hashlib.sha256(snapshot.content).hexdigest() != snapshot.sha256
        or parsed_verdict != snapshot.verdict
        or tuple(parsed_issues) != snapshot.issues
    ):
        raise QualityCandidateIntegrityError(
            "authoritative SAGE evidence snapshot is contradictory"
        )
    issue_path, relative_path = _safe_authoritative_sage_path(
        path,
        project_root=project_root,
    )
    if relative_path != snapshot.project_relative_path:
        raise QualityCandidateIntegrityError(
            "authoritative SAGE evidence path changed"
        )
    parent_descriptor: int | None = None
    try:
        parent_descriptor = _open_pinned_candidate_directory(issue_path.parent)
        metadata = os.stat(
            issue_path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or _candidate_file_identity(metadata) != snapshot.file_identity
        ):
            raise OSError("authoritative SAGE evidence changed")
    except OSError as exc:
        raise QualityCandidateIntegrityError(
            "authoritative SAGE evidence changed after assessment"
        ) from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _safe_authoritative_sage_path(
    path: Path,
    *,
    project_root: Path,
) -> tuple[Path, str]:
    root = Path(project_root).resolve()
    requested = Path(path)
    if not requested.is_absolute():
        requested = root / requested
    try:
        parent = requested.parent.resolve(strict=True)
        issue_path = parent / requested.name
        relative = issue_path.relative_to(root)
    except (OSError, ValueError) as exc:
        raise QualityCandidateIntegrityError(
            "authoritative SAGE evidence path is unsafe"
        ) from exc
    relative_path = relative.as_posix()
    if (
        not relative_path
        or relative.is_absolute()
        or any(part == ".." for part in relative.parts)
    ):
        raise QualityCandidateIntegrityError(
            "authoritative SAGE evidence path is unsafe"
        )
    return issue_path, relative_path


def _parse_authoritative_sage_assessment_bytes(
    content: bytes,
) -> tuple[str, tuple[dict[str, str], ...]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise QualityCandidateIntegrityError(
            "authoritative SAGE issues are missing or malformed"
        ) from exc
    if not text.strip():
        raise QualityCandidateIntegrityError(
            "authoritative SAGE issues are missing or malformed"
        )
    counts: dict[str, int] = {}
    for severity in _SAGE_SEVERITIES:
        matches = re.findall(
            rf"(?m)^-?\s*\*\*{severity}:\*\*\s*(\d+)\s*$",
            text,
        )
        if len(matches) != 1:
            raise QualityCandidateIntegrityError(
                "authoritative SAGE issue summary is malformed"
            )
        counts[severity] = int(matches[0])
    verdicts = re.findall(
        r"(?m)^-?\s*\*\*Verdict:\*\*\s*(PASS|FAIL)\s*$",
        text,
    )
    if len(verdicts) != 1:
        raise QualityCandidateIntegrityError(
            "authoritative SAGE issue verdict is malformed"
        )
    headings = list(
        re.finditer(
            r"(?m)^###\s+(ISS-[A-Za-z0-9-]+):\s*([^\n]+)\s*$",
            text,
        )
    )
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, heading in enumerate(headings):
        issue_id = heading.group(1)
        if issue_id in seen:
            raise QualityCandidateIntegrityError(
                "authoritative SAGE issue IDs are duplicated"
            )
        seen.add(issue_id)
        end = (
            headings[index + 1].start()
            if index + 1 < len(headings)
            else len(text)
        )
        body = text[heading.end():end]
        severity_matches = re.findall(
            r"(?m)^-?\s*\*\*Severity:\*\*\s*(CRITICAL|HIGH|MEDIUM|LOW)\s*$",
            body,
        )
        type_matches = re.findall(
            r"(?m)^-?\s*\*\*Type:\*\*\s*([a-z-]+)\s*$",
            body,
        )
        required_fields = {
            label: re.findall(
                rf"(?m)^-?\s*\*\*{re.escape(label)}:\*\*\s*(\S[^\n]*)$",
                body,
            )
            for label in _SAGE_REQUIRED_ISSUE_FIELDS
        }
        if (
            len(severity_matches) != 1
            or len(type_matches) != 1
            or type_matches[0] not in _SAGE_ISSUE_TYPES
            or any(len(matches) != 1 for matches in required_fields.values())
        ):
            raise QualityCandidateIntegrityError(
                "authoritative SAGE issue entry is malformed"
            )
        issues.append(
            {
                "issue_id": issue_id,
                "title": heading.group(2).strip(),
                "severity": severity_matches[0],
                "type": type_matches[0],
            }
        )
    observed = {
        severity: sum(1 for issue in issues if issue["severity"] == severity)
        for severity in _SAGE_SEVERITIES
    }
    if observed != counts or sum(counts.values()) != len(issues):
        raise QualityCandidateIntegrityError(
            "authoritative SAGE issue counts are contradictory"
        )
    return verdicts[0], tuple(issues)


def load_authoritative_sage_issues(
    path: Path,
) -> tuple[dict[str, str], ...]:
    """Compatibility view over the authoritative verdict and issue snapshot."""
    _verdict, issues = load_authoritative_sage_assessment(path)
    return issues


def load_quality_candidate_snapshot(
    path: Path,
    *,
    expected_sha256: str | None = None,
    expected_candidate_id: str | None = None,
) -> QualityCandidateSnapshot:
    """Load one exact persisted candidate manifest for controller use."""
    parent_descriptor: int | None = None
    try:
        manifest_path = Path(path)
        parent_descriptor = _open_pinned_candidate_directory(
            manifest_path.parent
        )
        snapshot = _candidate_entry_snapshot(
            parent_descriptor,
            manifest_path.name,
        )
        if snapshot is None:
            raise OSError("candidate manifest is missing")
        digest, content, _token, _mode = snapshot
        if expected_sha256 is not None and (
            not _is_sha256(expected_sha256)
            or digest != expected_sha256
        ):
            raise QualityCandidateIntegrityError(
                "candidate manifest digest mismatch"
            )
        payload = loads_strict_json(content.decode("utf-8"))
    except QualityCandidateIntegrityError:
        raise
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise QualityCandidateIntegrityError(
            "candidate manifest is missing or malformed"
        ) from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    if type(payload) is not dict or set(payload) != _CANDIDATE_MANIFEST_KEYS:
        raise QualityCandidateIntegrityError("candidate manifest is malformed")
    owned = payload["owned_artifact_digests"]
    raw_gates = payload["normalized_gates"]
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != SCHEMA_VERSION
        or not _is_candidate_id(payload["candidate_id"])
        or type(payload["checkpoint_commit"]) is not str
        or not re.fullmatch(r"[0-9a-f]{40,64}", payload["checkpoint_commit"])
        or type(owned) is not dict
        or not owned
        or any(
            type(name) is not str or not _is_sha256(digest)
            for name, digest in owned.items()
        )
        or type(payload["run_artifact_root"]) is not str
        or not payload["run_artifact_root"].strip()
        or type(payload["understanding_evidence"]) is not str
        or not payload["understanding_evidence"].strip()
        or not _is_sha256(payload["understanding_evidence_digest"])
        or type(raw_gates) is not list
    ):
        raise QualityCandidateIntegrityError("candidate manifest is malformed")
    gates: dict[str, dict[str, object]] = {}
    for row in raw_gates:
        if type(row) is not dict or set(row) != {
            "name", "score", "threshold", "pass"
        }:
            raise QualityCandidateIntegrityError("candidate manifest is malformed")
        name = row["name"]
        if type(name) is not str or name in gates:
            raise QualityCandidateIntegrityError("candidate manifest is malformed")
        gates[name] = {
            "score": row["score"],
            "threshold": row["threshold"],
            "pass": row["pass"],
        }
    normalized_gates = _normalize_candidate_gates(gates)
    routes = _normalize_finding_routes(payload["sage_finding_routes"])
    reasons = _normalize_eligibility_reasons(payload["eligibility_reasons"])
    for key in (
        "failed_gate_count",
        "formal_statement_count",
        "byte_count",
        "repair_number",
        "assessment_index",
    ):
        if type(payload[key]) is not int or payload[key] < 0:
            raise QualityCandidateIntegrityError("candidate manifest is malformed")
    for key in ("worst_gate_margin", "overall_score"):
        if type(payload[key]) not in {int, float} or not math.isfinite(
            float(payload[key])
        ):
            raise QualityCandidateIntegrityError("candidate manifest is malformed")
    expected_assessment = int(payload["candidate_id"].rsplit("-", 1)[1])
    scores = {
        name: score
        for name, score, _threshold, _passed in normalized_gates
    }
    if (
        payload["assessment_index"] != expected_assessment
        or payload["failed_gate_count"]
        != sum(1 for *_prefix, passed in normalized_gates if not passed)
        or float(payload["worst_gate_margin"])
        != min(
            score - threshold
            for _name, score, threshold, _passed in normalized_gates
        )
        or float(payload["overall_score"]) != scores["overall"]
    ):
        raise QualityCandidateIntegrityError(
            "candidate manifest ranking evidence is contradictory"
        )
    candidate = QualityCandidateManifest(
        schema_version=SCHEMA_VERSION,
        candidate_id=payload["candidate_id"],
        checkpoint_commit=payload["checkpoint_commit"],
        owned_artifact_digests=tuple(sorted(owned.items())),
        run_artifact_root=payload["run_artifact_root"],
        understanding_evidence=payload["understanding_evidence"],
        understanding_evidence_digest=payload["understanding_evidence_digest"],
        normalized_gates=normalized_gates,
        sage_finding_routes=routes,
        failed_gate_count=payload["failed_gate_count"],
        worst_gate_margin=float(payload["worst_gate_margin"]),
        overall_score=float(payload["overall_score"]),
        formal_statement_count=payload["formal_statement_count"],
        byte_count=payload["byte_count"],
        repair_number=payload["repair_number"],
        assessment_index=payload["assessment_index"],
        eligibility_reasons=reasons,
    )
    if expected_candidate_id is not None and (
        not _is_candidate_id(expected_candidate_id)
        or candidate.candidate_id != expected_candidate_id
    ):
        raise QualityCandidateIntegrityError(
            "candidate manifest identity mismatch"
        )
    return QualityCandidateSnapshot(manifest=candidate, sha256=digest)


def load_quality_candidate_manifest(
    path: Path,
    *,
    expected_sha256: str | None = None,
    expected_candidate_id: str | None = None,
) -> QualityCandidateManifest:
    """Compatibility view over the exact persisted manifest snapshot."""
    return load_quality_candidate_snapshot(
        path,
        expected_sha256=expected_sha256,
        expected_candidate_id=expected_candidate_id,
    ).manifest


def quality_candidate_effect_payload(
    candidate: QualityCandidateManifest,
) -> dict[str, object]:
    """Return the canonical serializable draft used by the completion outbox."""
    if (
        not isinstance(candidate, QualityCandidateManifest)
        or candidate.checkpoint_commit != "0" * 40
    ):
        raise QualityCandidateIntegrityError("candidate effect draft is invalid")
    return _candidate_manifest_payload(candidate)


def quality_candidate_from_effect_payload(
    payload: object,
) -> QualityCandidateManifest:
    """Validate and reconstruct a completion-bound candidate draft."""
    if (
        type(payload) is not dict
        or payload.get("checkpoint_commit") != "0" * 40
    ):
        raise QualityCandidateIntegrityError("candidate effect payload is invalid")
    # Reuse the persisted manifest validator without weakening its on-disk
    # checkpoint rule: validate fields directly through the same normalizers.
    if set(payload) != _CANDIDATE_MANIFEST_KEYS:
        raise QualityCandidateIntegrityError("candidate effect payload is invalid")
    owned = payload.get("owned_artifact_digests")
    raw_gates = payload.get("normalized_gates")
    if (
        payload.get("schema_version") != 1
        or not _is_candidate_id(payload.get("candidate_id"))
        or type(owned) is not dict
        or not owned
        or any(
            type(name) is not str or not _is_sha256(digest)
            for name, digest in owned.items()
        )
        or type(raw_gates) is not list
        or not isinstance(payload.get("sage_finding_routes"), list)
        or not isinstance(payload.get("eligibility_reasons"), list)
    ):
        raise QualityCandidateIntegrityError("candidate effect payload is invalid")
    gates: dict[str, dict[str, object]] = {}
    for row in raw_gates:
        if type(row) is not dict or set(row) != {
            "name",
            "score",
            "threshold",
            "pass",
        }:
            raise QualityCandidateIntegrityError("candidate effect payload is invalid")
        name = row.get("name")
        if type(name) is not str or name in gates:
            raise QualityCandidateIntegrityError("candidate effect payload is invalid")
        gates[name] = {
            "score": row.get("score"),
            "threshold": row.get("threshold"),
            "pass": row.get("pass"),
        }
    normalized = _normalize_candidate_gates(gates)
    integer_fields = (
        "failed_gate_count",
        "formal_statement_count",
        "byte_count",
        "repair_number",
        "assessment_index",
    )
    if any(
        type(payload.get(key)) is not int or int(payload[key]) < 0
        for key in integer_fields
    ):
        raise QualityCandidateIntegrityError("candidate effect payload is invalid")
    for key in ("worst_gate_margin", "overall_score"):
        value = payload.get(key)
        if type(value) not in {int, float} or not math.isfinite(float(value)):
            raise QualityCandidateIntegrityError("candidate effect payload is invalid")
    if (
        type(payload.get("run_artifact_root")) is not str
        or not str(payload["run_artifact_root"]).strip()
        or type(payload.get("understanding_evidence")) is not str
        or not str(payload["understanding_evidence"]).strip()
        or not _is_sha256(payload.get("understanding_evidence_digest"))
    ):
        raise QualityCandidateIntegrityError("candidate effect payload is invalid")
    candidate = QualityCandidateManifest(
        schema_version=1,
        candidate_id=str(payload["candidate_id"]),
        checkpoint_commit="0" * 40,
        owned_artifact_digests=tuple(sorted(owned.items())),
        run_artifact_root=str(payload.get("run_artifact_root") or ""),
        understanding_evidence=str(payload.get("understanding_evidence") or ""),
        understanding_evidence_digest=str(
            payload.get("understanding_evidence_digest") or ""
        ),
        normalized_gates=normalized,
        sage_finding_routes=_normalize_finding_routes(
            payload["sage_finding_routes"]
        ),
        failed_gate_count=int(payload["failed_gate_count"]),
        worst_gate_margin=float(payload.get("worst_gate_margin")),
        overall_score=float(payload.get("overall_score")),
        formal_statement_count=int(payload["formal_statement_count"]),
        byte_count=int(payload["byte_count"]),
        repair_number=int(payload["repair_number"]),
        assessment_index=int(payload["assessment_index"]),
        eligibility_reasons=_normalize_eligibility_reasons(
            payload["eligibility_reasons"]
        ),
    )
    scores = {
        name: score for name, score, _threshold, _passed in normalized
    }
    if (
        candidate.assessment_index
        != int(candidate.candidate_id.rsplit("-", 1)[1])
        or candidate.failed_gate_count
        != sum(1 for *_prefix, passed in normalized if not passed)
        or candidate.worst_gate_margin
        != min(
            score - threshold
            for _name, score, threshold, _passed in normalized
        )
        or candidate.overall_score != scores["overall"]
        or quality_candidate_effect_payload(candidate) != payload
    ):
        raise QualityCandidateIntegrityError("candidate effect payload is contradictory")
    return candidate


def initialize_repair_state(
    state: Mapping[str, object],
) -> dict[str, object] | None:
    """Return the proportional repair record for a new or continued run.

    Legacy runs without the record are migrated from immutable controller WHY2
    history.  Only when that history is unavailable may the global workflow
    iteration seed the dedicated counter.
    """
    if not isinstance(state, Mapping):
        raise ValueError("repair state source must be a mapping")
    mode = normalize_spec_authoring_mode(state.get("spec_authoring_mode"))
    has_existing = "phase1_quality_repair" in state
    existing = state.get("phase1_quality_repair")
    if mode == PERFECTIONIST_MODE:
        if has_existing:
            raise ValueError("perfectionist runs cannot contain repair state")
        return None
    if has_existing:
        return validate_repair_state(existing)

    history_count = _certified_why2_assessment_count(state)
    if history_count is None:
        consumed = min(_legacy_iteration(state), AUTOMATIC_REPAIR_LIMIT)
        migration_basis = "iteration_fallback"
    else:
        consumed = min(max(history_count - 1, 0), AUTOMATIC_REPAIR_LIMIT)
        migration_basis = "why2_history"
    if not _is_legacy_state(state):
        consumed = 0
        migration_basis = "fresh"
    return {
        "schema_version": SCHEMA_VERSION,
        "authoring_mode": PROPORTIONAL_MODE,
        "automatic_limit": AUTOMATIC_REPAIR_LIMIT,
        "automatic_consumed": consumed,
        "extension_limit": EXTENSION_REPAIR_LIMIT,
        "extension_authorized": 0,
        "extension_consumed": 0,
        "migration_basis": migration_basis,
        "baseline_candidate_id": None,
        "candidate_ids": [],
    }


def validate_repair_state(value: object) -> dict[str, object]:
    """Return one detached exact-schema repair record or fail closed."""
    if type(value) is not dict or frozenset(value) not in {
        _REPAIR_STATE_KEYS,
        _PRE_CANDIDATE_REPAIR_STATE_KEYS,
    }:
        raise ValueError("proportional repair state has invalid fields")
    state = deepcopy(value)
    if frozenset(state) == _PRE_CANDIDATE_REPAIR_STATE_KEYS:
        state["baseline_candidate_id"] = None
        state["candidate_ids"] = []
    if (
        type(state["schema_version"]) is not int
        or state["schema_version"] != SCHEMA_VERSION
    ):
        raise ValueError("proportional repair state schema version is invalid")
    if state["authoring_mode"] != PROPORTIONAL_MODE:
        raise ValueError("proportional repair state authoring mode is invalid")
    if (
        type(state["automatic_limit"]) is not int
        or state["automatic_limit"] != AUTOMATIC_REPAIR_LIMIT
    ):
        raise ValueError("proportional automatic repair limit is invalid")
    if (
        type(state["extension_limit"]) is not int
        or state["extension_limit"] != EXTENSION_REPAIR_LIMIT
    ):
        raise ValueError("proportional extension repair limit is invalid")
    for key, limit in (
        ("automatic_consumed", AUTOMATIC_REPAIR_LIMIT),
        ("extension_authorized", EXTENSION_REPAIR_LIMIT),
        ("extension_consumed", EXTENSION_REPAIR_LIMIT),
    ):
        counter = state[key]
        if type(counter) is not int or not 0 <= counter <= limit:
            raise ValueError(f"proportional repair state {key} is invalid")
    if state["extension_consumed"] > state["extension_authorized"]:
        raise ValueError("proportional extension consumption is unauthorized")
    if state["migration_basis"] not in _MIGRATION_BASES:
        raise ValueError("proportional repair migration basis is invalid")
    candidate_ids = state["candidate_ids"]
    baseline_candidate_id = state["baseline_candidate_id"]
    if (
        type(candidate_ids) is not list
        or any(not _is_candidate_id(item) for item in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
        or candidate_ids
        != [f"quality-candidate-{index}" for index in range(len(candidate_ids))]
    ):
        raise ValueError("proportional candidate IDs are invalid")
    if baseline_candidate_id is not None and not _is_candidate_id(
        baseline_candidate_id
    ):
        raise ValueError("proportional baseline candidate ID is invalid")
    if (
        baseline_candidate_id is None
        and candidate_ids
        or baseline_candidate_id is not None
        and (not candidate_ids or candidate_ids[0] != baseline_candidate_id)
    ):
        raise ValueError("proportional baseline candidate membership is invalid")
    return state


def prepare_quality_candidate(
    *,
    project_root: Path,
    spec_dir: Path,
    run_artifact_root: Path,
    run_id: str,
    spec_id: str,
    candidate_id: str,
    understanding_evidence: Path,
    normalized_gates: Mapping[str, Mapping[str, object]],
    sage_finding_routes: Sequence[Mapping[str, object]],
    formal_statement_count: int,
    repair_number: int,
    assessment_index: int,
    eligibility_reasons: Sequence[str],
    repair_state: MutableMapping[str, object],
    authoritative_sage_evidence: AuthoritativeSageEvidenceSnapshot | None = None,
) -> QualityCandidateManifest:
    """Validate and describe one WHY2 candidate without external effects."""
    if not _is_candidate_id(candidate_id):
        raise QualityCandidateIntegrityError("candidate ID is invalid")
    validated_state = validate_repair_state(dict(repair_state))
    expected_index = len(validated_state["candidate_ids"])
    if candidate_id != f"quality-candidate-{expected_index}":
        raise QualityCandidateIntegrityError("candidate sequence is invalid")
    for label, value in (
        ("formal statement count", formal_statement_count),
        ("repair number", repair_number),
        ("assessment index", assessment_index),
    ):
        if type(value) is not int or value < 0:
            raise QualityCandidateIntegrityError(f"candidate {label} is invalid")
    if assessment_index != expected_index:
        raise QualityCandidateIntegrityError("candidate assessment index is invalid")

    root = Path(project_root).resolve()
    resolved_spec = Path(spec_dir).resolve()
    artifact_root = Path(run_artifact_root).resolve()
    try:
        resolved_spec.relative_to(root)
        artifact_root.relative_to(root)
    except ValueError as exc:
        raise QualityCandidateIntegrityError("candidate paths escape project root") from exc
    evidence_path = Path(understanding_evidence).resolve()
    try:
        evidence_path.relative_to(artifact_root)
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "Understanding evidence escapes the run artifact root"
        ) from exc

    artifact_names = (
        "spec.md",
        "requirements-overview.md",
        "quality-gates.md",
        "issues.md",
    )
    digests: list[tuple[str, str]] = []
    contents: dict[str, bytes] = {}
    sage_snapshot = authoritative_sage_evidence
    for name in artifact_names:
        path = resolved_spec / name
        if name == "issues.md" and sage_snapshot is not None:
            require_current_authoritative_sage_evidence_snapshot(
                sage_snapshot,
                path,
                project_root=root,
            )
            content = sage_snapshot.content
            try:
                text = content.decode("utf-8")
                if not text.strip():
                    raise ValueError("empty Markdown")
            except (UnicodeDecodeError, ValueError) as exc:
                raise QualityCandidateIntegrityError(
                    "candidate artifact is malformed: issues.md"
                ) from exc
            contents[name] = content
            digests.append((name, sage_snapshot.sha256))
            continue
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            if name == "requirements-overview.md":
                continue
            raise QualityCandidateIntegrityError(
                f"candidate artifact is missing: {name}"
            ) from None
        except OSError as exc:
            raise QualityCandidateIntegrityError(
                f"candidate artifact could not be inspected: {name}"
            ) from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise QualityCandidateIntegrityError(
                f"candidate artifact must be a regular file: {name}"
            )
        try:
            content = path.read_bytes()
            text = content.decode("utf-8")
            if not text.strip():
                raise ValueError("empty Markdown")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise QualityCandidateIntegrityError(
                f"candidate artifact is malformed: {name}"
            ) from exc
        contents[name] = content
        digests.append((name, hashlib.sha256(content).hexdigest()))

    evidence_digest, evidence_payload = _verified_understanding_evidence(
        evidence_path
    )
    evidence_spec = evidence_payload["spec"]
    if evidence_spec.get("sha256") != dict(digests)["spec.md"]:
        raise QualityCandidateIntegrityError(
            "Understanding evidence describes a different spec"
        )
    if formal_statement_count != evidence_payload.get("requirement_count"):
        raise QualityCandidateIntegrityError(
            "candidate formal statement count conflicts with Understanding evidence"
        )
    authoritative_gates = _authoritative_gates(evidence_payload)
    normalized = _normalize_candidate_gates(normalized_gates)
    if normalized != authoritative_gates:
        raise QualityCandidateIntegrityError(
            "candidate gate data conflicts with immutable Understanding evidence"
        )
    routes = _normalize_finding_routes(sage_finding_routes)
    reasons = _normalize_eligibility_reasons(eligibility_reasons)
    failed = sum(1 for _name, _score, _threshold, passed in normalized if not passed)
    margins = tuple(
        score - threshold
        for _name, score, threshold, _passed in normalized
    )
    scores = {name: score for name, score, _threshold, _passed in normalized}
    manifest = QualityCandidateManifest(
        schema_version=SCHEMA_VERSION,
        candidate_id=candidate_id,
        # A draft is ranked before the state transaction authorizes its Git
        # effect.  Materialization replaces this sentinel with the bound commit.
        checkpoint_commit="0" * 40,
        owned_artifact_digests=tuple(digests),
        run_artifact_root=str(artifact_root),
        understanding_evidence=str(evidence_path),
        understanding_evidence_digest=evidence_digest,
        normalized_gates=normalized,
        sage_finding_routes=routes,
        failed_gate_count=failed,
        worst_gate_margin=min(margins),
        overall_score=scores["overall"],
        formal_statement_count=formal_statement_count,
        byte_count=len(contents["spec.md"]),
        repair_number=repair_number,
        assessment_index=assessment_index,
        eligibility_reasons=reasons,
    )
    updated_ids = [*validated_state["candidate_ids"], candidate_id]
    validated_state["candidate_ids"] = updated_ids
    if validated_state["baseline_candidate_id"] is None:
        validated_state["baseline_candidate_id"] = candidate_id
    validated_state = validate_repair_state(validated_state)
    repair_state.clear()
    repair_state.update(validated_state)
    return manifest


def materialize_quality_candidate(
    *,
    project_root: Path,
    spec_dir: Path,
    candidate: QualityCandidateManifest,
    run_id: str,
    spec_id: str,
    completion_id: str,
    next_phase: str,
    checkpoint_prestate: Mapping[str, object],
    require_current_artifacts: bool = True,
    expected_receipt: object | None = None,
) -> tuple[QualityCandidateManifest, dict[str, object]]:
    """Apply or verify an authorized candidate checkpoint and manifest."""
    root = Path(project_root).resolve()
    resolved_spec = Path(spec_dir).resolve()
    artifact_root = Path(candidate.run_artifact_root).resolve()
    evidence_path = Path(candidate.understanding_evidence).resolve()
    try:
        resolved_spec.relative_to(root)
        artifact_root.relative_to(root)
        evidence_path.relative_to(artifact_root)
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "candidate materialization path escapes its authority"
        ) from exc
    if candidate.checkpoint_commit != "0" * 40:
        raise QualityCandidateIntegrityError("candidate draft is invalid")
    expected = (
        expected_receipt
        if isinstance(expected_receipt, Mapping)
        else None
    )
    checkpoint_expected = (
        expected.get("checkpoint") if expected is not None else None
    )
    evidence_digest, evidence_payload = _verified_understanding_evidence(
        evidence_path
    )
    if (
        evidence_digest != candidate.understanding_evidence_digest
        or evidence_payload["spec"].get("sha256")
        != dict(candidate.owned_artifact_digests).get("spec.md")
        or _authoritative_gates(evidence_payload) != candidate.normalized_gates
        or evidence_payload.get("requirement_count")
        != candidate.formal_statement_count
    ):
        raise QualityCandidateIntegrityError(
            "candidate evidence changed before materialization"
        )
    manifest_path = (
        artifact_root / "quality-candidates" / f"{candidate.candidate_id}.json"
    )
    existing_manifest: QualityCandidateManifest | None = None
    if manifest_path.exists():
        existing_manifest = load_quality_candidate_manifest(manifest_path)
        if replace(existing_manifest, checkpoint_commit="0" * 40) != candidate:
            raise QualityCandidateIntegrityError("candidate manifest identity drift")
    if existing_manifest is None or require_current_artifacts:
        for name, digest in candidate.owned_artifact_digests:
            try:
                actual = hashlib.sha256(
                    (resolved_spec / name).read_bytes()
                ).hexdigest()
            except OSError as exc:
                raise QualityCandidateIntegrityError(
                    "candidate artifacts changed before materialization"
                ) from exc
            if actual != digest:
                raise QualityCandidateIntegrityError(
                    "candidate artifacts changed before materialization"
                )
    try:
        checkpoint_receipt = create_or_recover_completion_checkpoint(
            project_root=root,
            spec_dir=resolved_spec,
            phase=f"phase1-{candidate.candidate_id}",
            next_phase=next_phase,
            run_id=run_id,
            spec_id=spec_id,
            completion_id=completion_id,
            checkpoint_prestate=checkpoint_prestate,
            force_commit=True,
            expected_receipt=checkpoint_expected,
        )
    except (PhaseCheckpointError, OSError, ValueError) as exc:
        raise QualityCandidateIntegrityError("candidate checkpoint failed") from exc
    commit = checkpoint_receipt.get("commit")
    if type(commit) is not str:
        raise QualityCandidateIntegrityError("candidate checkpoint failed")
    materialized = replace(candidate, checkpoint_commit=commit)
    try:
        verify_checkpoint_artifact_digests(
            project_root=root,
            spec_dir=resolved_spec,
            checkpoint_commit=commit,
            artifact_digests=dict(candidate.owned_artifact_digests),
        )
    except PhaseCheckpointError as exc:
        raise QualityCandidateIntegrityError(
            f"candidate checkpoint artifact digest mismatch: {exc}"
        ) from exc
    try:
        _persist_candidate_manifest(artifact_root, materialized, recover=True)
    except (OSError, ValueError) as exc:
        raise QualityCandidateIntegrityError(
            "candidate manifest materialization failed"
        ) from exc
    receipt = {
        "schema_version": 1,
        "candidate_id": candidate.candidate_id,
        "checkpoint": checkpoint_receipt,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    if expected is not None and dict(expected) != receipt:
        raise QualityCandidateIntegrityError("candidate receipt mismatch")
    return materialized, receipt


def capture_quality_candidate(
    *,
    project_root: Path,
    spec_dir: Path,
    run_artifact_root: Path,
    run_id: str,
    spec_id: str,
    candidate_id: str,
    understanding_evidence: Path,
    normalized_gates: Mapping[str, Mapping[str, object]],
    sage_finding_routes: Sequence[Mapping[str, object]],
    formal_statement_count: int,
    repair_number: int,
    assessment_index: int,
    eligibility_reasons: Sequence[str],
    repair_state: MutableMapping[str, object],
) -> QualityCandidateManifest:
    """Compatibility seam: synchronously capture outside controller routing."""
    original_repair = deepcopy(dict(repair_state))
    draft = prepare_quality_candidate(
        project_root=project_root,
        spec_dir=spec_dir,
        run_artifact_root=run_artifact_root,
        run_id=run_id,
        spec_id=spec_id,
        candidate_id=candidate_id,
        understanding_evidence=understanding_evidence,
        normalized_gates=normalized_gates,
        sage_finding_routes=sage_finding_routes,
        formal_statement_count=formal_statement_count,
        repair_number=repair_number,
        assessment_index=assessment_index,
        eligibility_reasons=eligibility_reasons,
        repair_state=repair_state,
    )
    try:
        head = run_git(
            project_root,
            "rev-parse",
            "HEAD^{commit}",
        ).stdout.strip()
    except GitHelperError as exc:
        repair_state.clear()
        repair_state.update(original_repair)
        raise QualityCandidateIntegrityError("candidate checkpoint failed") from exc
    try:
        materialized, _receipt = materialize_quality_candidate(
            project_root=project_root,
            spec_dir=spec_dir,
            candidate=draft,
            run_id=run_id,
            spec_id=spec_id,
            completion_id=hashlib.sha256(
                f"legacy-candidate:{run_id}:{draft.candidate_id}".encode()
            ).hexdigest()[:32],
            next_phase="phase1-what",
            checkpoint_prestate={"kind": "git_head", "head": head},
        )
    except BaseException:
        repair_state.clear()
        repair_state.update(original_repair)
        raise
    return materialized


def rank_quality_candidates(
    candidates: Sequence[QualityCandidateManifest],
) -> tuple[QualityCandidateManifest, ...]:
    """Return eligible candidates ordered by the sealed policy tuple."""
    eligible = [
        candidate
        for candidate in candidates
        if isinstance(candidate, QualityCandidateManifest)
        and not candidate.eligibility_reasons
    ]
    return tuple(
        sorted(
            eligible,
            key=lambda candidate: (
                candidate.failed_gate_count,
                -candidate.worst_gate_margin,
                -candidate.overall_score,
                candidate.formal_statement_count,
                candidate.assessment_index,
            ),
        )
    )


def _restore_candidate_artifact_digests(
    candidate: QualityCandidateManifest,
) -> dict[str, str]:
    if (
        not isinstance(candidate, QualityCandidateManifest)
        or candidate.schema_version != SCHEMA_VERSION
        or not _is_candidate_id(candidate.candidate_id)
    ):
        raise QualityCandidateIntegrityError("candidate manifest is invalid")
    artifact_digests = dict(candidate.owned_artifact_digests)
    if len(artifact_digests) != len(candidate.owned_artifact_digests):
        raise QualityCandidateIntegrityError("candidate artifact paths are duplicated")
    allowed = {
        "spec.md",
        "requirements-overview.md",
        "quality-gates.md",
        "issues.md",
    }
    required = {"spec.md", "quality-gates.md", "issues.md"}
    if not required <= set(artifact_digests) or not set(artifact_digests) <= allowed:
        raise QualityCandidateIntegrityError("candidate artifact paths are unsafe")
    return artifact_digests


def _validate_restore_candidate(
    project_root: Path,
    candidate: QualityCandidateManifest,
    *,
    run_id: str,
    spec_id: str,
) -> dict[str, str]:
    artifact_digests = _restore_candidate_artifact_digests(candidate)
    root = Path(project_root).resolve()
    artifact_root = Path(candidate.run_artifact_root).resolve()
    evidence_path = Path(candidate.understanding_evidence).resolve()
    try:
        artifact_root.relative_to(root)
        evidence_path.relative_to(artifact_root)
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "Understanding evidence escapes the recorded run artifact root"
        ) from exc
    actual_evidence_digest, evidence_payload = _verified_understanding_evidence(
        evidence_path
    )
    if actual_evidence_digest != candidate.understanding_evidence_digest:
        raise QualityCandidateIntegrityError("Understanding evidence digest mismatch")
    evidence_spec = evidence_payload["spec"]
    if evidence_spec.get("sha256") != artifact_digests["spec.md"]:
        raise QualityCandidateIntegrityError(
            "Understanding evidence describes a different spec"
        )
    authoritative_gates = _authoritative_gates(evidence_payload)
    margins = tuple(
        score - threshold
        for _name, score, threshold, _passed in authoritative_gates
    )
    authoritative_scores = {
        name: score
        for name, score, _threshold, _passed in authoritative_gates
    }
    if (
        candidate.normalized_gates != authoritative_gates
        or candidate.failed_gate_count
        != sum(1 for *_prefix, passed in authoritative_gates if not passed)
        or candidate.worst_gate_margin != min(margins)
        or candidate.overall_score != authoritative_scores["overall"]
        or candidate.formal_statement_count
        != evidence_payload.get("requirement_count")
    ):
        raise QualityCandidateIntegrityError(
            "candidate ranking data conflicts with immutable gate evidence"
        )
    _verify_candidate_checkpoint_identity(
        project_root=Path(project_root),
        candidate=candidate,
        run_id=run_id,
        spec_id=spec_id,
    )
    return artifact_digests


def restore_quality_candidate(
    project_root: Path,
    spec_dir: Path,
    candidate: QualityCandidateManifest,
    *,
    run_id: str,
    spec_id: str,
) -> PhaseCheckpoint:
    """Restore one verified candidate without rewinding repository state."""
    artifact_digests = _validate_restore_candidate(
        project_root,
        candidate,
        run_id=run_id,
        spec_id=spec_id,
    )
    try:
        previous = {
            name: (Path(spec_dir) / name).read_bytes()
            for name in artifact_digests
        }
    except OSError as exc:
        raise QualityCandidateIntegrityError(
            "current candidate artifacts could not be read"
        ) from exc
    try:
        restore_checkpoint_artifacts(
            project_root=project_root,
            spec_dir=spec_dir,
            checkpoint_commit=candidate.checkpoint_commit,
            artifact_digests=artifact_digests,
        )
        return create_phase_checkpoint(
            project_root=project_root,
            spec_dir=spec_dir,
            phase="phase1-quality-candidate-restored",
            next_phase="phase1-lexicon",
            run_id=run_id,
            spec_id=spec_id,
            checkpoint_owned_paths=tuple(
                Path(spec_dir) / name for name in artifact_digests
            ),
            force_commit=True,
        )
    except (PhaseCheckpointError, OSError, ValueError) as exc:
        try:
            _replace_candidate_files(Path(spec_dir), previous)
        except OSError as rollback_exc:
            raise QualityCandidateIntegrityError(
                "candidate restoration and rollback integrity failure"
            ) from rollback_exc
        raise QualityCandidateIntegrityError(
            f"candidate restoration integrity failure: {exc}"
        ) from exc


def candidate_artifact_preimage_digests(
    spec_dir: Path,
    candidate: QualityCandidateManifest,
) -> dict[str, str]:
    """Seal the exact regular-file preimages for a later durable restore."""
    if not isinstance(candidate, QualityCandidateManifest):
        raise QualityCandidateIntegrityError("candidate manifest is invalid")
    artifact_digests = dict(candidate.owned_artifact_digests)
    if len(artifact_digests) != len(candidate.owned_artifact_digests):
        raise QualityCandidateIntegrityError("candidate artifact paths are duplicated")
    preimages: dict[str, str] = {}
    for name in sorted(artifact_digests):
        path = Path(spec_dir) / name
        try:
            metadata_before = path.lstat()
            if stat.S_ISLNK(metadata_before.st_mode) or not stat.S_ISREG(
                metadata_before.st_mode
            ):
                raise OSError("candidate preimage is not a regular file")
            content = path.read_bytes()
            metadata_after = path.lstat()
        except OSError as exc:
            raise QualityCandidateIntegrityError(
                f"candidate artifact preimage is unavailable: {name}"
            ) from exc
        if (
            metadata_before.st_dev,
            metadata_before.st_ino,
            metadata_before.st_size,
            metadata_before.st_mtime_ns,
        ) != (
            metadata_after.st_dev,
            metadata_after.st_ino,
            metadata_after.st_size,
            metadata_after.st_mtime_ns,
        ):
            raise QualityCandidateIntegrityError(
                f"candidate artifact preimage changed while reading: {name}"
            )
        preimages[name] = hashlib.sha256(content).hexdigest()
    return preimages


def _validated_restore_preimages(
    value: object,
    *,
    artifact_digests: Mapping[str, str],
) -> dict[str, str]:
    if (
        type(value) is not dict
        or set(value) != set(artifact_digests)
        or any(
            type(name) is not str or not _is_sha256(digest)
            for name, digest in value.items()
        )
    ):
        raise QualityCandidateIntegrityError(
            "candidate artifact preimages are malformed"
        )
    return dict(value)


def load_candidate_checkpoint_entries(
    project_root: Path,
    spec_dir: Path,
    candidate: QualityCandidateManifest,
) -> tuple[CandidateCheckpointEntry, ...]:
    """Load exact manifest-owned blobs from an immutable candidate commit."""
    artifact_digests = _restore_candidate_artifact_digests(candidate)
    root = Path(project_root).resolve()
    resolved_spec = Path(spec_dir).resolve()
    try:
        spec_relative = resolved_spec.relative_to(root)
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "candidate spec directory escapes project root"
        ) from exc
    entries: list[CandidateCheckpointEntry] = []
    try:
        checkpoint = candidate.checkpoint_commit
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", checkpoint) is None:
            raise QualityCandidateIntegrityError(
                "candidate checkpoint commit is invalid"
            )
        resolved = run_git_hardened(
            root,
            "rev-parse",
            "--verify",
            f"{checkpoint}^{{commit}}",
        )
        if resolved.returncode != 0 or resolved.stdout.strip() != checkpoint:
            raise QualityCandidateIntegrityError(
                "candidate checkpoint commit is invalid"
            )
        for name, expected_digest in candidate.owned_artifact_digests:
            relative = (spec_relative / name).as_posix()
            tree = run_git_hardened(
                root,
                "ls-tree",
                "-z",
                "--full-tree",
                checkpoint,
                "--",
                relative,
                check=False,
                text=False,
            )
            rows = tuple(row for row in tree.stdout.split(b"\0") if row)
            if (
                tree.returncode != 0
                or len(rows) != 1
                or b"\t" not in rows[0]
            ):
                raise QualityCandidateIntegrityError(
                    f"candidate owned artifact is missing: {name}"
                )
            header, raw_path = rows[0].split(b"\t", 1)
            fields = header.split()
            if (
                len(fields) != 3
                or fields[0] not in {b"100644", b"100755"}
                or fields[1] != b"blob"
                or re.fullmatch(rb"[0-9a-f]{40}|[0-9a-f]{64}", fields[2])
                is None
                or raw_path != relative.encode("utf-8")
            ):
                raise QualityCandidateIntegrityError(
                    f"candidate owned artifact is not a regular blob: {name}"
                )
            blob_oid = fields[2].decode("ascii")
            blob = run_git_hardened(
                root,
                "cat-file",
                "blob",
                blob_oid,
                check=False,
                text=False,
            )
            if blob.returncode != 0:
                raise QualityCandidateIntegrityError(
                    f"candidate owned artifact is missing: {name}"
                )
            content = bytes(blob.stdout)
            digest = hashlib.sha256(content).hexdigest()
            if digest != expected_digest:
                raise QualityCandidateIntegrityError(
                    f"candidate artifact digest mismatch: {name}"
                )
            entries.append(
                CandidateCheckpointEntry(
                    path=name,
                    mode=fields[0].decode("ascii"),
                    blob_oid=blob_oid,
                    sha256=digest,
                    content=content,
                )
            )
    except (OSError, GitHelperError, UnicodeError) as exc:
        raise QualityCandidateIntegrityError(
            "candidate checkpoint artifacts could not be read"
        ) from exc
    if len(entries) != len(candidate.owned_artifact_digests):
        raise QualityCandidateIntegrityError(
            "candidate checkpoint artifact count mismatch"
        )
    return tuple(entries)


def preflight_quality_candidate_restore(
    *,
    project_root: Path,
    spec_dir: Path,
    manifest_path: Path,
    expected_candidate_id: str,
    expected_manifest_sha256: str,
) -> PreflightedCandidateRestore:
    """Authenticate selected manifest bytes and pin all checkpoint blobs."""
    snapshot = load_quality_candidate_snapshot(
        manifest_path,
        expected_sha256=expected_manifest_sha256,
        expected_candidate_id=expected_candidate_id,
    )
    return PreflightedCandidateRestore(
        snapshot=snapshot,
        entries=load_candidate_checkpoint_entries(
            project_root,
            spec_dir,
            snapshot.manifest,
        ),
    )


def _preflighted_checkpoint_contents(
    restore: PreflightedCandidateRestore,
    candidate: QualityCandidateManifest,
) -> tuple[dict[str, str], dict[str, bytes]]:
    if (
        not isinstance(restore, PreflightedCandidateRestore)
        or not isinstance(restore.snapshot, QualityCandidateSnapshot)
        or restore.snapshot.manifest != candidate
        or not _is_sha256(restore.snapshot.sha256)
    ):
        raise QualityCandidateIntegrityError(
            "candidate restore preflight changed"
        )
    artifact_digests = _restore_candidate_artifact_digests(candidate)
    expected_paths = tuple(
        path for path, _digest in candidate.owned_artifact_digests
    )
    if (
        type(restore.entries) is not tuple
        or any(
            not isinstance(entry, CandidateCheckpointEntry)
            for entry in restore.entries
        )
        or tuple(entry.path for entry in restore.entries) != expected_paths
    ):
        raise QualityCandidateIntegrityError(
            "candidate checkpoint artifact count mismatch"
        )
    contents: dict[str, bytes] = {}
    for entry in restore.entries:
        if (
            entry.mode not in {"100644", "100755"}
            or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", entry.blob_oid)
            is None
            or type(entry.content) is not bytes
            or hashlib.sha256(entry.content).hexdigest() != entry.sha256
            or artifact_digests.get(entry.path) != entry.sha256
        ):
            raise QualityCandidateIntegrityError(
                f"candidate checkpoint entry changed: {entry.path}"
            )
        contents[entry.path] = entry.content
    return artifact_digests, contents


_RESTORE_EXCHANGE_DIRECTORY = "quality-restore-exchanges"
_RESTORE_EXCHANGE_TEMP_PREFIX = ".echelon-quality-restore-"
_LEGACY_RESTORE_GUIDANCE = (
    "legacy candidate restore recovery required: pending pre-Git-first restore "
    "authority requires operator intervention"
)
_LEGACY_RESTORE_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "artifact_preimage_digests",
        "artifact_postimage_digests",
        "checkpoint",
    }
)
_GIT_FIRST_RESTORE_RECEIPT_KEYS = _LEGACY_RESTORE_RECEIPT_KEYS | {
    "restore_protocol",
    "plan_sha256",
    "target_commit",
}
_COMMITTED_CHECKPOINT_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "completion_id",
        "run_id",
        "spec_id",
        "phase",
        "next_phase",
        "outcome",
        "commit",
    }
)


def _validate_committed_checkpoint_receipt_shape(value: object) -> dict[str, object]:
    if type(value) is not dict or frozenset(value) != _COMMITTED_CHECKPOINT_RECEIPT_KEYS:
        raise QualityCandidateIntegrityError(
            "candidate restoration checkpoint receipt shape mismatch"
        )
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or type(value.get("completion_id")) is not str
        or re.fullmatch(r"[0-9a-f]{32}", str(value.get("completion_id"))) is None
        or any(
            type(value.get(key)) is not str or not value.get(key)
            for key in ("run_id", "spec_id", "phase", "next_phase")
        )
        or value.get("outcome") != "committed"
        or type(value.get("commit")) is not str
        or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(value.get("commit")))
        is None
    ):
        raise QualityCandidateIntegrityError(
            "candidate restoration checkpoint receipt shape mismatch"
        )
    return dict(value)


def _validate_restore_receipt_digest_map(value: object) -> dict[str, str]:
    allowed = {
        "spec.md",
        "requirements-overview.md",
        "quality-gates.md",
        "issues.md",
    }
    required = {"spec.md", "quality-gates.md", "issues.md"}
    if (
        type(value) is not dict
        or not required <= set(value)
        or not set(value) <= allowed
        or any(type(name) is not str or not _is_sha256(digest) for name, digest in value.items())
    ):
        raise QualityCandidateIntegrityError(
            "candidate restoration receipt digest map mismatch"
        )
    return dict(value)


def classify_quality_candidate_restore_receipt(
    value: object | None,
) -> tuple[str, dict[str, object] | None]:
    """Discriminate the exact schema-v1 legacy/Git-first receipt union."""

    if value is None:
        return "none", None
    if type(value) is not dict:
        raise QualityCandidateIntegrityError(
            "candidate restoration receipt shape mismatch"
        )
    keys = frozenset(value)
    if keys == _LEGACY_RESTORE_RECEIPT_KEYS:
        kind = "legacy"
    elif keys == _GIT_FIRST_RESTORE_RECEIPT_KEYS:
        kind = "git_first"
    else:
        raise QualityCandidateIntegrityError(
            "candidate restoration receipt shape mismatch"
        )
    preimages = _validate_restore_receipt_digest_map(
        value.get("artifact_preimage_digests")
    )
    postimages = _validate_restore_receipt_digest_map(
        value.get("artifact_postimage_digests")
    )
    checkpoint = _validate_committed_checkpoint_receipt_shape(
        value.get("checkpoint")
    )
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or not _is_candidate_id(value.get("candidate_id"))
        or set(preimages) != set(postimages)
    ):
        raise QualityCandidateIntegrityError(
            "candidate restoration receipt shape mismatch"
        )
    if kind == "git_first" and (
        value.get("restore_protocol") != "git_first_v1"
        or not _is_sha256(value.get("plan_sha256"))
        or type(value.get("target_commit")) is not str
        or re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}",
            str(value.get("target_commit")),
        )
        is None
        or value.get("target_commit") != checkpoint["commit"]
    ):
        raise QualityCandidateIntegrityError(
            "candidate restoration receipt protocol mismatch"
        )
    return kind, dict(value)


def _open_pinned_candidate_directory(path: Path) -> int:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise OSError("candidate restore parent is not a directory")
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or (opened.st_dev, opened.st_ino)
        != (metadata.st_dev, metadata.st_ino)
    ):
        os.close(descriptor)
        raise OSError("candidate restore parent changed while opening")
    return descriptor


def _candidate_entry_snapshot(
    directory_fd: int,
    name: str,
    *,
    missing_ok: bool = False,
) -> tuple[str, bytes, tuple[object, ...], int] | None:
    """Read one regular entry through its pinned no-follow descriptor."""
    try:
        metadata = os.stat(
            name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise OSError("candidate restore entry is not a regular file")
    descriptor = os.open(
        name,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        token = _candidate_file_identity(opened)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino, opened.st_size)
            != (metadata.st_dev, metadata.st_ino, metadata.st_size)
        ):
            raise OSError("candidate restore entry changed while opening")
        remaining = opened.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(1_048_576, remaining))
            if not chunk:
                raise OSError("short candidate restore read")
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        after_token = _candidate_file_identity(after)
        current = os.stat(
            name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        current_token = _candidate_file_identity(current)
        if after_token != token or current_token != token:
            raise OSError("candidate restore entry changed while reading")
        return (
            hashlib.sha256(content).hexdigest(),
            content,
            token,
            stat.S_IMODE(opened.st_mode),
        )
    finally:
        os.close(descriptor)


def _candidate_file_identity(metadata: os.stat_result) -> tuple[object, ...]:
    return (
        stat.S_IFMT(metadata.st_mode),
        metadata.st_mode,
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        getattr(metadata, "st_flags", None),
        getattr(metadata, "st_gen", None),
    )


def _legacy_restore_authority_present(
    *,
    spec_dir: Path,
    candidate: QualityCandidateManifest,
    completion_id: str,
    expected_receipt: object | None,
) -> bool:
    """Classify only exact schema-v1 file-first authority as legacy."""

    receipt_kind, _receipt = classify_quality_candidate_restore_receipt(
        expected_receipt
    )
    if receipt_kind != "none":
        return receipt_kind == "legacy"
    artifact_root = Path(candidate.run_artifact_root).resolve()
    journal_dir = artifact_root / _RESTORE_EXCHANGE_DIRECTORY
    journal = journal_dir / f"{completion_id}.json"
    try:
        journal_directory_metadata = journal_dir.lstat()
    except FileNotFoundError:
        journal_directory_metadata = None
    except OSError as exc:
        raise QualityCandidateIntegrityError(
            "legacy candidate restore recovery required: journal directory is unreadable"
        ) from exc
    if journal_directory_metadata is not None:
        try:
            unsafe_journal_directory = (
                not stat.S_ISDIR(journal_directory_metadata.st_mode)
                or stat.S_ISLNK(journal_directory_metadata.st_mode)
                or journal_dir.resolve(strict=True) != journal_dir
            )
        except OSError as exc:
            raise QualityCandidateIntegrityError(
                "legacy candidate restore recovery required: journal directory is unsafe"
            ) from exc
        if unsafe_journal_directory:
            raise QualityCandidateIntegrityError(
                "legacy candidate restore recovery required: journal directory is unsafe"
            )
    try:
        journal_metadata = journal.lstat()
    except FileNotFoundError:
        journal_metadata = None
    except OSError as exc:
        raise QualityCandidateIntegrityError(
            "legacy candidate restore recovery required: journal is unreadable"
        ) from exc
    if journal_metadata is not None:
        if not stat.S_ISREG(journal_metadata.st_mode):
            raise QualityCandidateIntegrityError(
                "legacy candidate restore recovery required: journal is unsafe"
            )
        return True
    resolved_spec = Path(os.path.abspath(spec_dir))
    try:
        spec_metadata = resolved_spec.lstat()
        if (
            not stat.S_ISDIR(spec_metadata.st_mode)
            or stat.S_ISLNK(spec_metadata.st_mode)
            or resolved_spec.resolve(strict=True) != resolved_spec
        ):
            raise OSError("legacy restore spec directory is unsafe")
        names = os.listdir(resolved_spec)
    except OSError as exc:
        raise QualityCandidateIntegrityError(
            "legacy candidate restore recovery required: spec is unreadable"
        ) from exc
    if any(name.startswith(_RESTORE_EXCHANGE_TEMP_PREFIX) for name in names):
        return True
    return False


def materialize_quality_candidate_restore(
    *,
    project_root: Path,
    spec_dir: Path,
    candidate: QualityCandidateManifest,
    run_id: str,
    spec_id: str,
    completion_id: str,
    next_phase: str,
    checkpoint_prestate: Mapping[str, object],
    artifact_preimage_digests: Mapping[str, str],
    preflighted_restore: PreflightedCandidateRestore | None = None,
    restore_plan: "GitFirstRestorePlan | None" = None,
    expected_receipt: object | None = None,
) -> dict[str, object]:
    """Apply current Git-first authority; legacy recovery is fail-closed."""

    receipt_kind, expected = classify_quality_candidate_restore_receipt(
        expected_receipt
    )
    if receipt_kind == "legacy" or _legacy_restore_authority_present(
        spec_dir=spec_dir,
        candidate=candidate,
        completion_id=completion_id,
        expected_receipt=None,
    ):
        raise QualityCandidateIntegrityError(_LEGACY_RESTORE_GUIDANCE)
    if restore_plan is None:
        raise QualityCandidateIntegrityError(
            "git-first candidate restore plan is missing"
        )
    if preflighted_restore is None:
        raise QualityCandidateIntegrityError(
            "git-first candidate restore preflight is missing"
        )
    artifact_digests, _contents = _preflighted_checkpoint_contents(
        preflighted_restore,
        candidate,
    )
    preimages = _validated_restore_preimages(
        artifact_preimage_digests,
        artifact_digests=artifact_digests,
    )
    if (
        type(checkpoint_prestate) is not dict
        or checkpoint_prestate != {
            "kind": "git_head",
            "head": restore_plan.base_commit,
        }
    ):
        raise QualityCandidateIntegrityError(
            "git-first candidate restore prestate changed"
        )
    plan_by_name = {
        Path(entry.path).name: entry for entry in restore_plan.entries
    }
    selected_by_name = {
        entry.path: entry for entry in preflighted_restore.entries
    }
    if set(plan_by_name) != set(artifact_digests) or set(selected_by_name) != set(
        artifact_digests
    ):
        raise QualityCandidateIntegrityError(
            "git-first candidate restore plan changed"
        )
    for name in sorted(artifact_digests):
        planned = plan_by_name[name]
        selected = selected_by_name[name]
        if (
            planned.base_sha256 != preimages[name]
            or planned.target_mode != selected.mode
            or planned.target_blob_oid != selected.blob_oid
            or planned.target_sha256 != selected.sha256
            or planned.target_sha256 != artifact_digests[name]
        ):
            raise QualityCandidateIntegrityError(
                "git-first candidate restore plan changed"
            )
    git_expected: dict[str, object] | None = None
    if expected is not None:
        git_expected = {
            "schema_version": 1,
            "completion_id": completion_id,
            "restore_protocol": expected.get("restore_protocol"),
            "plan_sha256": expected.get("plan_sha256"),
            "target_commit": expected.get("target_commit"),
            "checkpoint": expected.get("checkpoint"),
        }
    try:
        from harness.git_first_restore import (
            GitFirstRestoreError,
            apply_or_recover_git_first_restore,
        )

        restored = apply_or_recover_git_first_restore(
            project_root=project_root,
            spec_dir=spec_dir,
            journal_root=Path(candidate.run_artifact_root),
            plan=restore_plan,
            run_id=run_id,
            spec_id=spec_id,
            next_phase=next_phase,
            expected_receipt=git_expected,
        )
    except GitFirstRestoreError as exc:
        raise QualityCandidateIntegrityError(
            f"candidate restoration integrity failure: {exc}"
        ) from exc
    receipt = {
        "schema_version": 1,
        "candidate_id": candidate.candidate_id,
        "artifact_preimage_digests": dict(sorted(preimages.items())),
        "artifact_postimage_digests": dict(sorted(artifact_digests.items())),
        "restore_protocol": restored.restore_protocol,
        "plan_sha256": restored.plan_sha256,
        "target_commit": restored.target_commit,
        "checkpoint": dict(restored.checkpoint),
    }
    if expected is not None and dict(expected) != receipt:
        raise QualityCandidateIntegrityError(
            "candidate restoration receipt mismatch"
        )
    return receipt


def _normalize_candidate_gates(
    gates: Mapping[str, Mapping[str, object]],
) -> tuple[tuple[str, float, float, bool], ...]:
    if not isinstance(gates, Mapping) or "overall" not in gates or not gates:
        raise QualityCandidateIntegrityError("candidate gates are malformed")
    normalized: list[tuple[str, float, float, bool]] = []
    for name in sorted(gates):
        gate = gates[name]
        if (
            type(name) is not str
            or not name
            or type(gate) is not dict
            or set(gate) != {"score", "threshold", "pass"}
        ):
            raise QualityCandidateIntegrityError("candidate gates are malformed")
        score = gate.get("score")
        threshold = gate.get("threshold")
        passed = gate.get("pass")
        if (
            type(score) not in {int, float}
            or type(threshold) not in {int, float}
            or type(passed) is not bool
            or not math.isfinite(float(score))
            or not math.isfinite(float(threshold))
        ):
            raise QualityCandidateIntegrityError("candidate gates are malformed")
        normalized.append((name, float(score), float(threshold), passed))
    return tuple(normalized)


def _authoritative_gates(
    evidence: Mapping[str, object],
) -> tuple[tuple[str, float, float, bool], ...]:
    raw_scores = evidence.get("scores")
    raw_thresholds = evidence.get("thresholds")
    raw_gates = evidence.get("gates")
    if (
        type(raw_scores) is not dict
        or type(raw_thresholds) is not dict
        or type(raw_gates) is not dict
        or not raw_scores
        or set(raw_scores) != set(raw_thresholds)
        or set(raw_scores) != set(raw_gates)
        or "overall" not in raw_scores
    ):
        raise QualityCandidateIntegrityError(
            "Understanding gate evidence is malformed"
        )
    scores: dict[str, float] = {}
    thresholds: dict[str, float] = {}
    for name in raw_scores:
        score = raw_scores[name]
        threshold = raw_thresholds[name]
        if (
            type(name) is not str
            or not name
            or type(score) not in {int, float}
            or type(threshold) not in {int, float}
            or not math.isfinite(float(score))
            or not math.isfinite(float(threshold))
        ):
            raise QualityCandidateIntegrityError(
                "Understanding gate evidence is malformed"
            )
        scores[name] = float(score)
        thresholds[name] = float(threshold)
    decision = evaluate_quality_thresholds(scores, thresholds)
    normalized: list[tuple[str, float, float, bool]] = []
    for name in sorted(scores):
        gate = raw_gates[name]
        if not isinstance(gate, Mapping):
            raise QualityCandidateIntegrityError(
                "Understanding gate evidence is malformed"
            )
        expected_keys = {"score", "threshold", "pass"}
        if name == "overall":
            expected_keys |= {"numeric_pass", "pass_basis"}
        if (
            set(gate) != expected_keys
            or type(gate.get("pass")) is not bool
            or gate.get("score") != scores[name]
            or gate.get("threshold") != thresholds[name]
            or gate.get("pass") is not decision.effective_passes[name]
        ):
            raise QualityCandidateIntegrityError(
                "Understanding gate evidence is internally contradictory"
            )
        if name == "overall" and (
            gate.get("numeric_pass") is not decision.numeric_passes[name]
            or gate.get("pass_basis") != decision.overall_pass_basis
        ):
            raise QualityCandidateIntegrityError(
                "Understanding overall gate evidence is internally contradictory"
            )
        normalized.append(
            (name, scores[name], thresholds[name], decision.effective_passes[name])
        )
    if evidence.get("pass") is not decision.passed:
        raise QualityCandidateIntegrityError(
            "Understanding aggregate gate verdict is internally contradictory"
        )
    return tuple(normalized)


def _verify_candidate_checkpoint_identity(
    *,
    project_root: Path,
    candidate: QualityCandidateManifest,
    run_id: str,
    spec_id: str,
) -> None:
    try:
        checkpoint = candidate.checkpoint_commit
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", checkpoint) is None:
            raise QualityCandidateIntegrityError(
                "candidate checkpoint identity mismatch"
            )
        resolved = run_git_hardened(
            project_root,
            "rev-parse",
            "--verify",
            f"{checkpoint}^{{commit}}",
            check=False,
        )
        result = run_git_hardened(
            project_root,
            "cat-file",
            "commit",
            checkpoint,
            check=False,
            text=False,
        )
    except GitHelperError as exc:
        raise QualityCandidateIntegrityError(
            "candidate checkpoint identity could not be verified"
        ) from exc
    expected = (
        f"Echelon-Checkpoint: phase1-{candidate.candidate_id}",
        f"Echelon-Phase: phase1-{candidate.candidate_id}",
        f"Echelon-Spec: {spec_id}",
        f"Echelon-Run: {run_id}",
    )
    try:
        _headers, message = result.stdout.split(b"\n\n", 1)
        lines = message.decode("utf-8", errors="strict").splitlines()
    except (UnicodeError, ValueError) as exc:
        raise QualityCandidateIntegrityError(
            "candidate checkpoint identity could not be verified"
        ) from exc
    if (
        resolved.returncode != 0
        or resolved.stdout.strip() != checkpoint
        or result.returncode != 0
        or any(lines.count(item) != 1 for item in expected)
    ):
        raise QualityCandidateIntegrityError("candidate checkpoint identity mismatch")


def _normalize_finding_routes(
    routes: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    if isinstance(routes, (str, bytes)) or not isinstance(routes, Sequence):
        raise QualityCandidateIntegrityError("SAGE finding routes are malformed")
    normalized: list[Mapping[str, object]] = []
    for route in routes:
        if not isinstance(route, Mapping):
            raise QualityCandidateIntegrityError("SAGE finding routes are malformed")
        try:
            cloned = json.loads(json.dumps(dict(route), sort_keys=True))
        except (TypeError, ValueError) as exc:
            raise QualityCandidateIntegrityError(
                "SAGE finding routes are malformed"
            ) from exc
        normalized.append(cloned)
    return tuple(normalized)


def _normalize_eligibility_reasons(reasons: Sequence[str]) -> tuple[str, ...]:
    if isinstance(reasons, (str, bytes)) or not isinstance(reasons, Sequence):
        raise QualityCandidateIntegrityError(
            "candidate eligibility reasons are malformed"
        )
    values = tuple(reasons)
    if any(type(reason) is not str or not reason.strip() for reason in values):
        raise QualityCandidateIntegrityError(
            "candidate eligibility reasons are malformed"
        )
    if len(set(values)) != len(values):
        raise QualityCandidateIntegrityError(
            "candidate eligibility reasons are duplicated"
        )
    return values


def _verified_understanding_evidence(path: Path) -> tuple[str, Mapping[str, object]]:
    try:
        content = path.read_bytes()
        payload = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise QualityCandidateIntegrityError(
            "Understanding evidence is missing or malformed"
        ) from exc
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != 1
        or payload.get("status") != "completed"
        or payload.get("phase") != "phase1-why2"
        or type(payload.get("iteration")) is not int
        or not isinstance(payload.get("spec"), Mapping)
        or type(payload["spec"].get("path")) is not str
        or not payload["spec"].get("path").strip()
        or not _is_sha256(payload["spec"].get("sha256"))
        or not isinstance(payload.get("thresholds"), Mapping)
        or not isinstance(payload.get("scores"), Mapping)
        or not isinstance(payload.get("gates"), Mapping)
        or type(payload.get("pass")) is not bool
        or type(payload.get("requirement_count")) is not int
        or payload.get("requirement_count") < 0
    ):
        raise QualityCandidateIntegrityError("Understanding evidence is malformed")
    return hashlib.sha256(content).hexdigest(), payload


def _candidate_manifest_payload(
    manifest: QualityCandidateManifest,
) -> dict[str, object]:
    return {
        "schema_version": manifest.schema_version,
        "candidate_id": manifest.candidate_id,
        "checkpoint_commit": manifest.checkpoint_commit,
        "owned_artifact_digests": dict(manifest.owned_artifact_digests),
        "run_artifact_root": manifest.run_artifact_root,
        "understanding_evidence": manifest.understanding_evidence,
        "understanding_evidence_digest": manifest.understanding_evidence_digest,
        "normalized_gates": [
            {"name": name, "score": score, "threshold": threshold, "pass": passed}
            for name, score, threshold, passed in manifest.normalized_gates
        ],
        "sage_finding_routes": list(manifest.sage_finding_routes),
        "failed_gate_count": manifest.failed_gate_count,
        "worst_gate_margin": manifest.worst_gate_margin,
        "overall_score": manifest.overall_score,
        "formal_statement_count": manifest.formal_statement_count,
        "byte_count": manifest.byte_count,
        "repair_number": manifest.repair_number,
        "assessment_index": manifest.assessment_index,
        "eligibility_reasons": list(manifest.eligibility_reasons),
    }


def _persist_candidate_manifest(
    root: Path,
    manifest: QualityCandidateManifest,
    *,
    recover: bool = False,
) -> None:
    directory = root / "quality-candidates"
    path = directory / f"{manifest.candidate_id}.json"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        payload = _candidate_manifest_payload(manifest)
        content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        if path.exists():
            if recover and path.read_bytes() == content:
                return
            raise QualityCandidateIntegrityError("candidate manifest already exists")
        temporary = directory / (
            f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            offset = 0
            while offset < len(content):
                written = os.write(descriptor, content[offset:])
                if written <= 0:
                    raise OSError("short candidate manifest write")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        directory_descriptor = os.open(
            directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except QualityCandidateIntegrityError:
        raise
    except OSError as exc:
        raise QualityCandidateIntegrityError("candidate manifest persistence failed") from exc
    finally:
        if "temporary" in locals():
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _replace_candidate_files(spec_dir: Path, contents: Mapping[str, bytes]) -> None:
    temporary_paths: list[tuple[Path, Path]] = []
    try:
        for name, content in contents.items():
            destination = spec_dir / name
            temporary = destination.with_name(
                f".{destination.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
            )
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            try:
                offset = 0
                while offset < len(content):
                    written = os.write(descriptor, content[offset:])
                    if written <= 0:
                        raise OSError("short candidate rollback write")
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            temporary_paths.append((temporary, destination))
        for temporary, destination in temporary_paths:
            os.replace(temporary, destination)
    finally:
        for temporary, _destination in temporary_paths:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def record_what_outcome(
    repair_state: object,
    *,
    baseline_sha256: object,
    current_sha256: object,
    valid_completion: object,
    extension_active: object,
) -> RepairOutcome:
    """Account for a completed WHAT attempt without touching global iteration."""
    state = validate_repair_state(repair_state)
    if type(valid_completion) is not bool or type(extension_active) is not bool:
        raise ValueError("WHAT outcome flags must be Boolean")
    if not valid_completion:
        return RepairOutcome(state, "not_consumed")
    if not _is_sha256(baseline_sha256) or not _is_sha256(current_sha256):
        raise ValueError("WHAT outcome digests must be SHA-256 strings")

    changed = baseline_sha256 != current_sha256
    if extension_active:
        if (
            state["extension_authorized"] != EXTENSION_REPAIR_LIMIT
            or state["extension_consumed"] == EXTENSION_REPAIR_LIMIT
        ):
            return RepairOutcome(state, "not_consumed")
        state["extension_consumed"] = EXTENSION_REPAIR_LIMIT
        return RepairOutcome(
            state,
            "consumed" if changed else "no_artifact_progress",
        )

    if not changed:
        return RepairOutcome(state, "no_artifact_progress")
    if state["automatic_consumed"] == AUTOMATIC_REPAIR_LIMIT:
        return RepairOutcome(state, "not_consumed")
    state["automatic_consumed"] = int(state["automatic_consumed"]) + 1
    return RepairOutcome(state, "consumed")


def _is_legacy_state(state: Mapping[str, object]) -> bool:
    if "spec_authoring_mode" not in state or state.get(
        "spec_authoring_mode"
    ) in {None, ""}:
        return True
    return any(
        key in state
        for key in (
            "iteration",
            "quality_scores",
            "completed_phases",
            "last_dispatch",
        )
    )


def _certified_why2_assessment_count(state: Mapping[str, object]) -> int | None:
    scores = state.get("quality_scores")
    if not isinstance(scores, list):
        return None
    assessment_ids: set[str] = set()
    for score in scores:
        if not isinstance(score, Mapping) or score.get(
            "source"
        ) != "harness:understanding":
            continue
        assessment_id = _certified_why2_assessment_id(score)
        if assessment_id is None:
            return None
        assessment_ids.add(assessment_id)
    if not assessment_ids:
        return None
    iterations = sorted(
        int(assessment_id.rsplit("-", 1)[1])
        for assessment_id in assessment_ids
    )
    if iterations != list(range(len(iterations))):
        return None
    return len(iterations)


def _certified_why2_assessment_id(score: Mapping[str, object]) -> str | None:
    """Return one WHY2 identity only when its immutable report verifies."""
    pass_id = score.get("pass_id")
    passed = score.get("pass")
    evidence = score.get("evidence")
    evidence_digest = score.get("evidence_digest")
    if (
        type(pass_id) is not str
        or type(passed) is not bool
        or type(evidence) is not str
        or not evidence.strip()
        or not _is_sha256(evidence_digest)
    ):
        return None
    try:
        report_path = Path(evidence).expanduser()
        content = report_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != evidence_digest:
            return None
        report = json.loads(content)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(report, Mapping):
        return None
    iteration = report.get("iteration")
    report_spec = report.get("spec")
    if (
        type(report.get("schema_version")) is not int
        or report.get("schema_version") != 1
        or report.get("status") != "completed"
        or report.get("phase") != "phase1-why2"
        or type(iteration) is not int
        or iteration < 0
        or pass_id != f"WHY2-iter-{iteration}"
        or report.get("pass") is not passed
        or not isinstance(report_spec, Mapping)
        or type(report_spec.get("path")) is not str
        or not report_spec.get("path").strip()
        or not _is_sha256(report_spec.get("sha256"))
    ):
        return None
    return pass_id


def _legacy_iteration(state: Mapping[str, object]) -> int:
    iteration = state.get("iteration", 0)
    if type(iteration) is not int or iteration < 0:
        raise ValueError("legacy workflow iteration is invalid")
    return iteration


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_candidate_id(value: object) -> bool:
    return (
        type(value) is str
        and re.fullmatch(r"quality-candidate-[0-9]+", value) is not None
    )

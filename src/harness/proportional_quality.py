"""Controller-owned accounting for proportional Phase 1 quality repair."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Mapping, MutableMapping, Sequence

from echelon.git_helpers import GitHelperError, run_git
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


def load_authoritative_sage_issues(
    path: Path,
) -> tuple[dict[str, str], ...]:
    """Parse the required current WHY2 issues artifact or fail closed."""
    issue_path = Path(path)
    try:
        metadata = issue_path.lstat()
        content = issue_path.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise QualityCandidateIntegrityError(
            "authoritative SAGE issues are missing or malformed"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or not text.strip():
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
    return tuple(issues)


def load_quality_candidate_manifest(
    path: Path,
    *,
    expected_sha256: str | None = None,
    expected_candidate_id: str | None = None,
) -> QualityCandidateManifest:
    """Load one exact persisted candidate manifest for controller use."""
    try:
        manifest_path = Path(path)
        metadata_before = manifest_path.lstat()
        if stat.S_ISLNK(metadata_before.st_mode) or not stat.S_ISREG(
            metadata_before.st_mode
        ):
            raise OSError("candidate manifest is not a regular file")
        content = manifest_path.read_bytes()
        metadata_after = manifest_path.lstat()
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
            raise OSError("candidate manifest changed while reading")
        if expected_sha256 is not None and (
            not _is_sha256(expected_sha256)
            or hashlib.sha256(content).hexdigest() != expected_sha256
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
    return candidate


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
    for name in artifact_names:
        path = resolved_spec / name
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


def _validate_restore_candidate(
    project_root: Path,
    candidate: QualityCandidateManifest,
    *,
    run_id: str,
    spec_id: str,
) -> dict[str, str]:
    if (
        not isinstance(candidate, QualityCandidateManifest)
        or candidate.schema_version != SCHEMA_VERSION
        or not _is_candidate_id(candidate.candidate_id)
    ):
        raise QualityCandidateIntegrityError("candidate manifest is invalid")
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


def _candidate_checkpoint_contents(
    *,
    project_root: Path,
    spec_dir: Path,
    checkpoint_commit: str,
    artifact_digests: Mapping[str, str],
) -> dict[str, bytes]:
    root = Path(project_root).resolve()
    resolved_spec = Path(spec_dir).resolve()
    try:
        spec_relative = resolved_spec.relative_to(root)
    except ValueError as exc:
        raise QualityCandidateIntegrityError(
            "candidate spec directory escapes project root"
        ) from exc
    contents: dict[str, bytes] = {}
    try:
        for name in sorted(artifact_digests):
            relative = (spec_relative / name).as_posix()
            result = run_git(
                root,
                "show",
                f"{checkpoint_commit}:{relative}",
                check=False,
            )
            if result.returncode != 0:
                raise QualityCandidateIntegrityError(
                    f"candidate owned artifact is missing: {name}"
                )
            content = result.stdout.encode("utf-8")
            if hashlib.sha256(content).hexdigest() != artifact_digests[name]:
                raise QualityCandidateIntegrityError(
                    f"candidate artifact digest mismatch: {name}"
                )
            contents[name] = content
    except GitHelperError as exc:
        raise QualityCandidateIntegrityError(
            "candidate checkpoint artifacts could not be read"
        ) from exc
    return contents


def _replace_candidate_artifact_pinned(
    path: Path,
    content: bytes,
    *,
    expected_preimage_sha256: str,
) -> None:
    # The debt exchange is the established controller-owned final-component
    # compare-and-exchange primitive.  Import lazily because that module also
    # consumes candidate validation from this module.
    from harness.phase1_quality_debt import _pinned_replace_file

    _pinned_replace_file(
        path,
        content,
        expected_preimage_sha256=expected_preimage_sha256,
    )


def _fsync_candidate_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
    expected_receipt: object | None = None,
) -> dict[str, object]:
    """Apply or recover a state-authorized best-candidate restoration."""
    artifact_digests = _validate_restore_candidate(
        project_root,
        candidate=candidate,
        run_id=run_id,
        spec_id=spec_id,
    )
    preimages = _validated_restore_preimages(
        artifact_preimage_digests,
        artifact_digests=artifact_digests,
    )
    contents = _candidate_checkpoint_contents(
        project_root=project_root,
        spec_dir=spec_dir,
        checkpoint_commit=candidate.checkpoint_commit,
        artifact_digests=artifact_digests,
    )
    expected = (
        expected_receipt
        if isinstance(expected_receipt, Mapping)
        else None
    )
    checkpoint_expected = (
        expected.get("checkpoint") if expected is not None else None
    )
    try:
        resolved_spec = Path(spec_dir).resolve()
        for name in sorted(artifact_digests):
            path = resolved_spec / name
            try:
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
                    metadata.st_mode
                ):
                    raise OSError("candidate artifact is not a regular file")
                observed = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise QualityCandidateIntegrityError(
                    f"candidate restoration preimage is unavailable: {name}"
                ) from exc
            postimage = artifact_digests[name]
            if observed == postimage:
                continue
            if observed != preimages[name]:
                raise QualityCandidateIntegrityError(
                    f"candidate restoration preimage changed: {name}"
                )
            _replace_candidate_artifact_pinned(
                path,
                contents[name],
                expected_preimage_sha256=preimages[name],
            )
        _fsync_candidate_directory(resolved_spec)
        for name, postimage in artifact_digests.items():
            path = resolved_spec / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != postimage:
                raise QualityCandidateIntegrityError(
                    f"restored candidate digest mismatch: {name}"
                )
        checkpoint_receipt = create_or_recover_completion_checkpoint(
            project_root=project_root,
            spec_dir=spec_dir,
            phase="phase1-quality-candidate-restored",
            next_phase=next_phase,
            run_id=run_id,
            spec_id=spec_id,
            completion_id=completion_id,
            checkpoint_prestate=checkpoint_prestate,
            force_commit=True,
            expected_receipt=checkpoint_expected,
        )
    except QualityCandidateIntegrityError:
        raise
    except (PhaseCheckpointError, OSError, ValueError) as exc:
        raise QualityCandidateIntegrityError(
            f"candidate restoration integrity failure: {exc}"
        ) from exc
    receipt = {
        "schema_version": 1,
        "candidate_id": candidate.candidate_id,
        "artifact_preimage_digests": dict(sorted(preimages.items())),
        "artifact_postimage_digests": dict(sorted(artifact_digests.items())),
        "checkpoint": checkpoint_receipt,
    }
    if expected is not None and dict(expected) != receipt:
        raise QualityCandidateIntegrityError("candidate restoration receipt mismatch")
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
        result = run_git(
            project_root,
            "show",
            "-s",
            "--format=%B",
            candidate.checkpoint_commit,
            check=False,
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
    lines = result.stdout.splitlines()
    if result.returncode != 0 or any(lines.count(item) != 1 for item in expected):
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

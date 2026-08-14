"""Controller-owned accounting for proportional Phase 1 quality repair."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
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


def load_quality_candidate_manifest(path: Path) -> QualityCandidateManifest:
    """Load one exact persisted candidate manifest for controller use."""
    try:
        payload = loads_strict_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise QualityCandidateIntegrityError(
            "candidate manifest is missing or malformed"
        ) from exc
    expected = {
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
    if type(payload) is not dict or set(payload) != expected:
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
    return QualityCandidateManifest(
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
        consumed = min(history_count, AUTOMATIC_REPAIR_LIMIT)
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
    """Checkpoint and atomically persist one completed WHY2 candidate."""
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
    checkpoint_phase = f"phase1-{candidate_id}"
    try:
        checkpoint = create_phase_checkpoint(
            project_root=root,
            spec_dir=resolved_spec,
            phase=checkpoint_phase,
            next_phase="phase1-what",
            run_id=run_id,
            spec_id=spec_id,
            checkpoint_owned_paths=tuple(resolved_spec / name for name, _ in digests),
            force_commit=True,
        )
    except (PhaseCheckpointError, OSError, ValueError) as exc:
        raise QualityCandidateIntegrityError("candidate checkpoint failed") from exc

    try:
        verify_checkpoint_artifact_digests(
            project_root=root,
            spec_dir=resolved_spec,
            checkpoint_commit=checkpoint.commit,
            artifact_digests=dict(digests),
        )
    except PhaseCheckpointError as exc:
        raise QualityCandidateIntegrityError(
            f"candidate checkpoint artifact digest mismatch: {exc}"
        ) from exc

    failed = sum(1 for _name, _score, _threshold, passed in normalized if not passed)
    margins = tuple(
        score - threshold
        for _name, score, threshold, _passed in normalized
    )
    scores = {name: score for name, score, _threshold, _passed in normalized}
    manifest = QualityCandidateManifest(
        schema_version=SCHEMA_VERSION,
        candidate_id=candidate_id,
        checkpoint_commit=checkpoint.commit,
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
    _persist_candidate_manifest(artifact_root, manifest)
    repair_state.clear()
    repair_state.update(validated_state)
    return manifest


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


def restore_quality_candidate(
    project_root: Path,
    spec_dir: Path,
    candidate: QualityCandidateManifest,
    *,
    run_id: str,
    spec_id: str,
) -> PhaseCheckpoint:
    """Restore one verified candidate without rewinding repository state."""
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


def _persist_candidate_manifest(root: Path, manifest: QualityCandidateManifest) -> None:
    directory = root / "quality-candidates"
    path = directory / f"{manifest.candidate_id}.json"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise QualityCandidateIntegrityError("candidate manifest already exists")
        payload = {
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
        content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
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
    return len(assessment_ids) if assessment_ids else None


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

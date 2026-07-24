"""Controller-owned Understanding analysis and immutable evidence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from harness.quality_scores import QUALITY_GATE_SCORE_KEYS, resolve_quality_gate_thresholds
from understanding.service import DEFAULT_QUALITY_GATES, analyze_spec_bundle


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class UnderstandingGateResult:
    completed: bool
    passed: bool
    phase: str
    iteration: int
    report_path: Path | None
    report_digest: str | None
    report: dict[str, object]
    operational_error: str | None = None

    def state_updates(self, quality_scores: object) -> dict[str, object]:
        """Build controller-owned state without duplicating certified scores."""
        existing = list(quality_scores) if isinstance(quality_scores, list) else []
        evidence = {
            "phase": self.phase,
            "iteration": self.iteration,
            "status": "completed" if self.completed else "error",
            "path": str(self.report_path) if self.report_path is not None else None,
            "digest": self.report_digest,
            "pass": self.passed if self.completed else None,
            "failing_gates": _failing_gates(self.report),
            "error": self.operational_error,
        }
        updates: dict[str, object] = {"understanding_evidence": evidence}
        if not self.completed:
            return updates

        score = _score_from_report(
            self.report,
            phase=self.phase,
            iteration=self.iteration,
            report_path=self.report_path,
            report_digest=self.report_digest,
        )
        duplicate = any(
            isinstance(item, dict)
            and item.get("source") == "harness:understanding"
            and item.get("evidence_digest") == self.report_digest
            and item.get("pass_id") == score["pass_id"]
            for item in existing
        )
        if not duplicate:
            existing.append(score)
        updates["quality_scores"] = existing
        return updates


def run_understanding_gate(
    *,
    project_root: Path,
    squad_dir: Path,
    phase: str,
    iteration: int,
    spec_dir: str,
    config: Mapping[str, object],
) -> UnderstandingGateResult:
    """Analyze one spec and persist immutable controller evidence."""
    thresholds = _resolve_thresholds(project_root, config)
    diagram_enabled = _diagram_enabled(config)
    spec_root = Path(spec_dir).expanduser()
    if not spec_root.is_absolute():
        spec_root = project_root / spec_root
    spec_path = spec_root / "spec.md"
    evidence_dir = squad_dir / "evidence" / "understanding"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    base_path = evidence_dir / f"{phase}-iter-{iteration}.json"

    if not spec_path.is_file():
        display_path = _project_relative(spec_path, project_root)
        error = f"spec.md not found: {display_path}"
        report = _error_report(
            phase=phase,
            iteration=iteration,
            spec_path=display_path,
            thresholds=thresholds,
            error=error,
        )
        try:
            report_path = _write_immutable_report(base_path, report)
            report_digest = _file_digest(report_path)
        except OSError as exc:
            return UnderstandingGateResult(
                completed=False,
                passed=False,
                phase=phase,
                iteration=iteration,
                report_path=None,
                report_digest=None,
                report=report,
                operational_error=f"Understanding evidence write failed: {exc}",
            )
        return UnderstandingGateResult(
            completed=False,
            passed=False,
            phase=phase,
            iteration=iteration,
            report_path=report_path,
            report_digest=report_digest,
            report=report,
            operational_error=error,
        )

    spec_digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    evidence_identity = _evidence_identity(
        spec_digest=spec_digest,
        thresholds=thresholds,
        diagram_enabled=diagram_enabled,
    )
    digest_path = base_path.with_name(
        f"{base_path.stem}-{evidence_identity[:12]}{base_path.suffix}"
    )
    reusable = None
    for candidate in (base_path, digest_path):
        reusable = _load_reusable_report(
            candidate,
            phase=phase,
            iteration=iteration,
            spec_digest=spec_digest,
            thresholds=thresholds,
        )
        if reusable is not None:
            break
    if reusable is not None:
        report_path, report = reusable
        return UnderstandingGateResult(
            completed=True,
            passed=bool(report.get("pass")),
            phase=phase,
            iteration=iteration,
            report_path=report_path,
            report_digest=_file_digest(report_path),
            report=report,
        )

    try:
        bundle = analyze_spec_bundle(
            spec_path,
            thresholds=thresholds,
            enhanced=True,
            use_nlp=True,
            diagrams_enabled=diagram_enabled,
            diagram_output_dir=(
                evidence_dir
                / f"{phase}-iter-{iteration}-{evidence_identity[:12]}-diagrams"
            ),
        )
        payload = bundle.to_dict()
        report: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "status": "completed",
            "phase": phase,
            "iteration": iteration,
            "spec": {
                "path": _project_relative(spec_path, project_root),
                "sha256": spec_digest,
            },
            "thresholds": thresholds,
            "scores": payload["scores"],
            "gates": payload["gates"],
            "pass": payload["pass"],
            "requirement_count": payload["requirement_count"],
            "per_requirement": payload["per_requirement"],
            "entity_analysis": payload["entity_analysis"],
            "behavioral_analysis": payload["behavioral_analysis"],
            "diagrams": payload["diagrams"],
            "findings": payload["findings"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        error = f"Understanding analysis failed: {exc}"
        report = _error_report(
            phase=phase,
            iteration=iteration,
            spec_path=_project_relative(spec_path, project_root),
            thresholds=thresholds,
            error=error,
            spec_digest=spec_digest,
        )
        error_target = base_path if not base_path.exists() else digest_path
        try:
            report_path = _write_immutable_report(error_target, report)
            report_digest = _file_digest(report_path)
        except OSError as write_exc:
            return UnderstandingGateResult(
                completed=False,
                passed=False,
                phase=phase,
                iteration=iteration,
                report_path=None,
                report_digest=None,
                report=report,
                operational_error=f"Understanding evidence write failed: {write_exc}",
            )
        return UnderstandingGateResult(
            completed=False,
            passed=False,
            phase=phase,
            iteration=iteration,
            report_path=report_path,
            report_digest=report_digest,
            report=report,
            operational_error=error,
        )

    target = base_path if not base_path.exists() else digest_path
    try:
        report_path = _write_immutable_report(target, report)
        report_digest = _file_digest(report_path)
    except OSError as exc:
        return UnderstandingGateResult(
            completed=False,
            passed=False,
            phase=phase,
            iteration=iteration,
            report_path=None,
            report_digest=None,
            report=report,
            operational_error=f"Understanding evidence write failed: {exc}",
        )
    return UnderstandingGateResult(
        completed=True,
        passed=bool(report["pass"]),
        phase=phase,
        iteration=iteration,
        report_path=report_path,
        report_digest=report_digest,
        report=report,
    )


def has_current_understanding_evidence(
    state: Mapping[str, object],
    *,
    project_root: Path,
    phase: str,
) -> bool:
    """Return whether state points to certified evidence for the current spec."""
    evidence = state.get("understanding_evidence")
    if not isinstance(evidence, Mapping):
        return False
    if evidence.get("status") != "completed" or evidence.get("phase") != phase:
        return False
    report_ref = evidence.get("path")
    expected_digest = evidence.get("digest")
    if not isinstance(report_ref, str) or not isinstance(expected_digest, str):
        return False
    report_path = Path(report_ref).expanduser()
    if not report_path.is_absolute():
        report_path = project_root / report_path
    try:
        if _file_digest(report_path) != expected_digest:
            return False
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    spec_dir = Path(str(state.get("spec_dir") or "")).expanduser()
    if not spec_dir.is_absolute():
        spec_dir = project_root / spec_dir
    spec_path = spec_dir / "spec.md"
    report_spec = report.get("spec")
    report_matches = (
        report.get("schema_version") == SCHEMA_VERSION
        and report.get("status") == "completed"
        and report.get("phase") == phase
        and isinstance(report_spec, Mapping)
        and spec_path.is_file()
        and report_spec.get("sha256")
        == hashlib.sha256(spec_path.read_bytes()).hexdigest()
    )
    if not report_matches:
        return False
    quality_scores = state.get("quality_scores")
    if not isinstance(quality_scores, list):
        return False
    return any(
        isinstance(score, Mapping)
        and score.get("source") == "harness:understanding"
        and score.get("evidence_digest") == expected_digest
        and str(score.get("pass_id") or "").startswith(
            "WHY3-" if phase == "phase3-consensus" else "WHY2-"
        )
        for score in quality_scores
    )


def _resolve_thresholds(
    project_root: Path,
    config: Mapping[str, object],
) -> dict[str, float]:
    resolved = resolve_quality_gate_thresholds(
        project_root,
        defaults=DEFAULT_QUALITY_GATES,
    )
    configured = config.get("quality_gates")
    if isinstance(configured, Mapping):
        for key in QUALITY_GATE_SCORE_KEYS:
            value = configured.get(key)
            if isinstance(value, (int, float)):
                resolved[key] = float(value)
    return {key: float(resolved.get(key, DEFAULT_QUALITY_GATES[key])) for key in QUALITY_GATE_SCORE_KEYS}


def _diagram_enabled(config: Mapping[str, object]) -> bool:
    understanding = config.get("understanding")
    if not isinstance(understanding, Mapping):
        return False
    diagram = understanding.get("diagram")
    return isinstance(diagram, Mapping) and diagram.get("enabled") is True


def _evidence_identity(
    *,
    spec_digest: str,
    thresholds: Mapping[str, float],
    diagram_enabled: bool,
) -> str:
    payload = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "spec_sha256": spec_digest,
            "thresholds": dict(thresholds),
            "diagram_enabled": diagram_enabled,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _project_relative(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _load_reusable_report(
    path: Path,
    *,
    phase: str,
    iteration: int,
    spec_digest: str,
    thresholds: Mapping[str, float],
) -> tuple[Path, dict[str, object]] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    spec = payload.get("spec")
    if (
        payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("status") == "completed"
        and payload.get("phase") == phase
        and payload.get("iteration") == iteration
        and isinstance(spec, dict)
        and spec.get("sha256") == spec_digest
        and payload.get("thresholds") == dict(thresholds)
    ):
        return path, payload
    return None


def _write_immutable_report(path: Path, payload: Mapping[str, object]) -> Path:
    """Create a complete JSON file without replacing existing evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf-8"))
            existing_comparable = dict(existing)
            payload_comparable = dict(payload)
            existing_comparable.pop("generated_at", None)
            payload_comparable.pop("generated_at", None)
            if existing_comparable != payload_comparable:
                raise OSError(f"immutable evidence already exists with different content: {path}")
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _error_report(
    *,
    phase: str,
    iteration: int,
    spec_path: str,
    thresholds: Mapping[str, float],
    error: str,
    spec_digest: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "error",
        "phase": phase,
        "iteration": iteration,
        "spec": {"path": spec_path, "sha256": spec_digest},
        "thresholds": dict(thresholds),
        "scores": {},
        "gates": {},
        "pass": False,
        "requirement_count": 0,
        "per_requirement": [],
        "entity_analysis": {},
        "behavioral_analysis": {},
        "diagrams": {"enabled": False, "status": "skipped", "outputs": []},
        "findings": [],
        "error": error,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _score_from_report(
    report: Mapping[str, object],
    *,
    phase: str,
    iteration: int,
    report_path: Path | None,
    report_digest: str | None,
) -> dict[str, object]:
    raw_scores = report.get("scores")
    scores = raw_scores if isinstance(raw_scores, Mapping) else {}
    prefix = "WHY3" if phase == "phase3-consensus" else "WHY2"
    score: dict[str, object] = {
        "pass": bool(report.get("pass")),
        "pass_id": f"{prefix}-iter-{iteration}",
        "source": "harness:understanding",
        "evidence": str(report_path) if report_path is not None else None,
        "evidence_digest": report_digest,
    }
    for key in QUALITY_GATE_SCORE_KEYS:
        score[key] = float(scores.get(key, 0.0))
    return score


def _failing_gates(report: Mapping[str, object]) -> list[str]:
    raw_gates = report.get("gates")
    if not isinstance(raw_gates, Mapping):
        return []
    return [
        str(name)
        for name, gate in raw_gates.items()
        if isinstance(gate, Mapping) and gate.get("pass") is False
    ]

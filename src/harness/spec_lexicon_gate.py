"""Provider-free validation boundary for the derived spec Lexicon artifact."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from harness.lexicon_gate_io import write_json_atomic
from lexicon.glossary import load_glossary_terms, parse_glossary_terms


@dataclass(frozen=True)
class SpecLexiconGateResult:
    """Complete deterministic outcome for one spec Lexicon node execution."""

    evaluation: str
    passed: bool | None
    attempts: int
    findings: int | None = None
    report_path: Path | None = None
    detail: str = ""

    def state_updates(self) -> dict[str, object]:
        updates: dict[str, object] = {
            "lexicon_evaluation": self.evaluation,
            "lexicon_attempts": self.attempts,
        }
        if self.passed is not None:
            updates["lexicon_pass"] = self.passed
        if self.findings is not None:
            updates["lexicon_findings"] = self.findings
        if self.report_path is not None:
            updates["lexicon_report"] = str(self.report_path)
        return updates


def lexicon_gate_exhausted(*, gate, artifact, state, updates, default_max_iterations):
    """Native spec/tasks exhaustion policy, shared with retained gate proofs."""
    if not isinstance(gate, dict) or not gate.get("enabled", False):
        return False
    artifacts = gate.get("artifacts", {})
    artifact_gate = artifacts.get(artifact, {}) if isinstance(artifacts, dict) else {}
    if not isinstance(artifact_gate, dict) or not artifact_gate.get("enabled", False):
        return False
    try:
        repair_cap = int(gate.get("max_repair_attempts", 3))
    except (TypeError, ValueError):
        repair_cap = 3
    prefix = "lexicon" if artifact == "spec" else "tasks_lexicon"
    attempts = updates.get(prefix + "_attempts", state.get(prefix + "_attempts"))
    exhausted = (isinstance(attempts, int) and repair_cap > 0 and attempts >= repair_cap)
    exhausted = exhausted or int(state.get("iteration") or 0) >= int(state.get("max_iterations") or default_max_iterations)
    return bool(exhausted and updates.get(prefix + "_pass") is not True
        and (artifact == "spec" or str(gate.get("on_exhausted", "block")).lower() != "warn"))


def has_current_spec_lexicon_evidence(
    state: dict[str, object],
    *,
    project_root: Path,
    config: dict[str, object],
) -> bool:
    """Return whether state points to a current passing spec Lexicon report."""
    gate = config.get("lexicon_gate")
    gate = gate if isinstance(gate, dict) else {}
    artifacts = gate.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    spec_gate = artifacts.get("spec")
    spec_gate = spec_gate if isinstance(spec_gate, dict) else {}
    if not gate.get("enabled", False) or spec_gate.get("enabled", True) is False:
        return True
    if state.get("lexicon_evaluation") != "passed" or state.get("lexicon_pass") is not True:
        return False

    spec_dir_text = str(state.get("spec_dir") or "").strip()
    report_text = str(state.get("lexicon_report") or "").strip()
    if not spec_dir_text or not report_text:
        return False
    spec_dir = Path(spec_dir_text)
    if not spec_dir.is_absolute():
        spec_dir = project_root / spec_dir
    report_path = Path(report_text)
    if not report_path.is_absolute():
        report_path = project_root / report_path
    derived_path = spec_dir / str(
        spec_gate.get("path") or "requirements.lexicon.md"
    ).strip()
    source_path = spec_dir / str(spec_gate.get("source_ref") or "spec.md").strip()
    glossary_path = spec_dir / str(
        spec_gate.get("glossary_file")
        or gate.get("glossary_file")
        or "glossary.md"
    ).strip()
    if not report_path.is_file() or not derived_path.is_file() or not source_path.is_file():
        return False
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("ok") is not True:
            return False
        if report.get("artifact_type") != str(spec_gate.get("type") or "spec").upper():
            return False
        if Path(str(report.get("artifact_path") or "")).resolve() != derived_path.resolve():
            return False
        if Path(str(report.get("source_path") or "")).resolve() != source_path.resolve():
            return False
        if Path(str(report.get("glossary_path") or "")).resolve() != glossary_path.resolve():
            return False
        if report.get("artifact_sha256") != _sha256_file(derived_path):
            return False
        if report.get("source_sha256") != _sha256_file(source_path):
            return False
        if report.get("glossary_sha256") != _optional_sha256_file(glossary_path):
            return False
        evidence_time = report_path.stat().st_mtime_ns
        return evidence_time >= max(
            derived_path.stat().st_mtime_ns,
            source_path.stat().st_mtime_ns,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def run_spec_lexicon_gate(
    *,
    project_root: Path,
    spec_dir_ref: str,
    config: dict[str, object],
    previous_attempts: object,
) -> SpecLexiconGateResult:
    """Validate the configured derived spec artifact without invoking a provider."""
    gate = config.get("lexicon_gate")
    gate = gate if isinstance(gate, dict) else {}
    artifacts = gate.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    spec_gate = artifacts.get("spec")
    spec_gate = spec_gate if isinstance(spec_gate, dict) else {}

    if not gate.get("enabled", False) or spec_gate.get("enabled", True) is False:
        return _pending("spec Lexicon gate disabled")

    spec_dir_text = str(spec_dir_ref or "").strip()
    if not spec_dir_text:
        return _pending("spec_dir is missing")
    spec_dir = Path(spec_dir_text)
    if not spec_dir.is_absolute():
        spec_dir = project_root / spec_dir

    artifact_type = str(spec_gate.get("type") or "spec").upper()
    derived_path = spec_dir / str(
        spec_gate.get("path") or "requirements.lexicon.md"
    ).strip()
    source_path = spec_dir / str(spec_gate.get("source_ref") or "spec.md").strip()
    glossary_path = spec_dir / str(
        spec_gate.get("glossary_file")
        or gate.get("glossary_file")
        or "glossary.md"
    ).strip()

    if not derived_path.is_file():
        return _pending(f"derived artifact is missing: {derived_path}")
    if not source_path.is_file():
        return _pending(f"source artifact is missing: {source_path}")

    try:
        report = _validate_spec_lexicon_artifacts(
            derived_path=derived_path,
            source_path=source_path,
            glossary_path=glossary_path,
            artifact_type=artifact_type,
        )
        report_path = spec_dir / str(
            spec_gate.get("report") or "spec-lexicon-report.json"
        ).strip()
        write_json_atomic(report_path, report)
    except Exception as exc:
        return _pending(f"spec Lexicon validation could not execute: {exc}")

    return _report_result(report, report_path, previous_attempts)


def evaluate_captured_spec_lexicon(
    *,
    derived_text: str | None,
    source_text: str | None,
    glossary_text: str | None,
    derived_path: Path,
    source_path: Path,
    glossary_path: Path,
    report_path: Path,
    artifact_type: str,
    previous_attempts: object,
) -> tuple[SpecLexiconGateResult, dict[str, object] | None]:
    """Evaluate exact captured inputs without reading or publishing files.

    Paths are report labels only. The managed completion owner must authenticate
    the capture and publish the returned report before treating it as evidence.
    A result alone grants neither certification nor permission to advance.
    """
    if derived_text is None:
        return _pending(f"derived artifact is missing: {derived_path}"), None
    if source_text is None:
        return _pending(f"source artifact is missing: {source_path}"), None
    try:
        report = validate_spec_lexicon_texts(
            derived_text=derived_text,
            source_text=source_text,
            source_name=source_path.name,
            glossary_text=glossary_text,
            artifact_type=artifact_type,
        )
        report.update(artifact_path=str(derived_path), source_path=str(source_path),
            glossary_path=str(glossary_path))
        return _report_result(report, report_path, previous_attempts), report
    except Exception as exc:
        return _pending(f"spec Lexicon validation could not execute: {exc}"), None


def _report_result(report, report_path, previous_attempts):
    """One native attempt policy for file-backed and captured validation."""
    if report["ok"]:
        attempts = 0
        evaluation = "passed"
    else:
        try:
            attempts = max(0, int(previous_attempts)) + 1
        except (TypeError, ValueError):
            attempts = 1
        evaluation = "failed"
    return SpecLexiconGateResult(
        evaluation=evaluation,
        passed=bool(report["ok"]),
        attempts=attempts,
        findings=len(report["findings"]),
        report_path=report_path,
        detail=f"{len(report['findings'])} finding(s)",
    )


def _pending(detail: str) -> SpecLexiconGateResult:
    return SpecLexiconGateResult(
        evaluation="pending",
        passed=None,
        attempts=0,
        detail=detail,
    )


def _validate_spec_lexicon_artifacts(
    *,
    derived_path: Path,
    source_path: Path,
    glossary_path: Path,
    artifact_type: str,
) -> dict[str, object]:
    derived_text = derived_path.read_text(encoding="utf-8")
    source_text = source_path.read_text(encoding="utf-8")
    glossary_text = (
        glossary_path.read_text(encoding="utf-8")
        if glossary_path.is_file()
        else None
    )
    report = validate_spec_lexicon_texts(
        derived_text=derived_text,
        source_text=source_text,
        source_name=source_path.name,
        glossary_text=glossary_text,
        artifact_type=artifact_type,
    )
    return {
        "schema_version": report["schema_version"],
        "artifact_type": report["artifact_type"],
        "artifact_path": str(derived_path),
        "source_path": str(source_path),
        "glossary_path": str(glossary_path),
        "artifact_sha256": _sha256_file(derived_path),
        "source_sha256": _sha256_file(source_path),
        "glossary_sha256": _optional_sha256_file(glossary_path),
        "ok": report["ok"],
        "findings": report["findings"],
    }


def validate_spec_lexicon_texts(
    *,
    derived_text: str,
    source_text: str,
    source_name: str,
    glossary_text: str | None,
    artifact_type: str,
) -> dict[str, object]:
    """Validate one exact captured Lexicon/source/glossary text snapshot."""
    from lexicon.source_contract import (
        source_approved_terms_text,
        source_contract_findings_text,
    )
    from lexicon.validity import validate as validate_lexicon

    validation = validate_lexicon(
        derived_text,
        glossary=(
            (parse_glossary_terms(glossary_text) if glossary_text is not None else set())
            | source_approved_terms_text(source_text)
        ),
        artifact_type=artifact_type,
    )
    raw_findings = [
        *validation.findings,
        *source_contract_findings_text(
            derived_text,
            source_text=source_text,
            source_name=source_name,
        ),
    ]
    findings = [
        {
            "code": str(item.code),
            "message": str(item.message),
            "line": int(item.line),
            "span": str(item.span),
        }
        for item in raw_findings
    ]
    return {
        "schema_version": 1,
        "artifact_type": artifact_type,
        "artifact_sha256": hashlib.sha256(derived_text.encode("utf-8")).hexdigest(),
        "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "glossary_sha256": (
            hashlib.sha256(glossary_text.encode("utf-8")).hexdigest()
            if glossary_text is not None
            else None
        ),
        "ok": not findings,
        "findings": findings,
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _optional_sha256_file(path: Path) -> str | None:
    return _sha256_file(path) if path.is_file() else None


def _load_glossary_terms(glossary_path: Path) -> set[str]:
    return load_glossary_terms(glossary_path)

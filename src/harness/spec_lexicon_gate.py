"""Provider-free validation boundary for the derived spec Lexicon artifact."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


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
    if (
        str(gate.get("on_exhausted") or "block").lower() == "warn"
        and state.get("lexicon_warning_waiver") is True
    ):
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
        return SpecLexiconGateResult(
            evaluation="passed",
            passed=True,
            attempts=0,
            findings=0,
            detail="spec Lexicon gate disabled",
        )

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
        _write_json_atomic(report_path, report)
    except Exception as exc:
        return _pending(f"spec Lexicon validation could not execute: {exc}")

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
    from lexicon.glossary import load_glossary_terms
    from lexicon.source_contract import source_contract_findings
    from lexicon.validity import validate as validate_lexicon

    derived_text = derived_path.read_text(encoding="utf-8")
    validation = validate_lexicon(
        derived_text,
        glossary=load_glossary_terms(glossary_path),
        artifact_type=artifact_type,
    )
    raw_findings = [
        *validation.findings,
        *source_contract_findings(derived_text, source_path),
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
        "artifact_path": str(derived_path),
        "source_path": str(source_path),
        "glossary_path": str(glossary_path),
        "artifact_sha256": _sha256_file(derived_path),
        "source_sha256": _sha256_file(source_path),
        "glossary_sha256": _optional_sha256_file(glossary_path),
        "ok": not findings,
        "findings": findings,
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _optional_sha256_file(path: Path) -> str | None:
    return _sha256_file(path) if path.is_file() else None


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise

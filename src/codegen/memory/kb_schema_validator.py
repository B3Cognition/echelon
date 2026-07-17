"""Deterministic validators for durable knowledge-base memory records."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_EXPECTED_SCHEMA_VERSIONS: dict[str, int] = {
    "calibration-profile.yaml": 1,
    "estimates-log.yaml": 1,
    "patterns.yaml": 1,
    "pitfalls.yaml": 1,
    "agent-scores.yaml": 1,
    "internalization-log.yaml": 2,
    "evolution-signals.yaml": 2,
    "sage-decisions.yaml": 2,
}

_APPEND_ONLY_FILES = {
    "estimates-log.yaml",
    "internalization-log.yaml",
    "evolution-signals.yaml",
    "sage-decisions.yaml",
}
_ENTRY_LIST_KEYS = {
    "estimates-log.yaml": "entries",
    "patterns.yaml": "entries",
    "pitfalls.yaml": "entries",
    "internalization-log.yaml": "entries",
    "evolution-signals.yaml": "signals",
    "sage-decisions.yaml": "entries",
}
_PROVENANCE_KEYS = ("run_id", "source", "created_at")
_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{12}$")


@dataclass(frozen=True)
class KnowledgeBaseValidationIssue:
    """One deterministic knowledge-base validation failure."""

    path: str
    message: str


@dataclass(frozen=True)
class KnowledgeBaseValidationResult:
    """Aggregate validation result."""

    ok: bool
    issues: list[KnowledgeBaseValidationIssue] = field(default_factory=list)


def validate_kb_file(path: Path) -> KnowledgeBaseValidationResult:
    """Load and validate a knowledge-base YAML file."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        return _result([_issue("$", f"PyYAML unavailable: {exc}")])

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _result([_issue("$", f"cannot parse YAML: {exc}")])
    return validate_kb_document(path.name, data)


def validate_kb_document(
    filename: str,
    data: Any,
) -> KnowledgeBaseValidationResult:
    """Validate a parsed durable knowledge-base document."""
    issues: list[KnowledgeBaseValidationIssue] = []
    if not isinstance(data, dict):
        return _result([_issue("$", "document must be a mapping")])

    expected = _EXPECTED_SCHEMA_VERSIONS.get(filename)
    if expected is None:
        issues.append(_issue("$", f"unsupported knowledge-base file: {filename}"))
    elif data.get("schema_version") != expected:
        issues.append(
            _issue(
                "schema_version",
                f"expected {expected}, got {data.get('schema_version')!r}",
            )
        )

    if filename in _APPEND_ONLY_FILES and data.get("append_only") is not True:
        issues.append(_issue("append_only", "expected true for append-only file"))

    list_key = _ENTRY_LIST_KEYS.get(filename)
    if list_key is not None:
        entries = data.get(list_key)
        if not isinstance(entries, list):
            issues.append(_issue(list_key, "expected list"))
        else:
            for index, entry in enumerate(entries):
                _validate_entry(filename, list_key, index, entry, issues)

    return _result(issues)


def validate_pending_operation(data: Any) -> KnowledgeBaseValidationResult:
    """Validate a queued knowledge-base write operation."""
    issues: list[KnowledgeBaseValidationIssue] = []
    if not isinstance(data, dict):
        return _result([_issue("$", "pending operation must be a mapping")])

    for key in (
        "schema_version",
        "operation_id",
        "created_at",
        "source",
        "target_file",
        "operation",
        "payload",
        "checksum",
    ):
        if key not in data:
            issues.append(_issue(key, "required"))

    if data.get("schema_version") != 1:
        issues.append(_issue("schema_version", "expected 1"))
    _validate_iso_datetime(data.get("created_at"), "created_at", issues)

    source = data.get("source")
    if not isinstance(source, dict):
        issues.append(_issue("source", "expected mapping"))
    else:
        if not source.get("run_id"):
            issues.append(_issue("source.run_id", "required"))
        if not source.get("agent"):
            issues.append(_issue("source.agent", "required"))

    if data.get("operation") != "append_entry":
        issues.append(_issue("operation", "expected append_entry"))
    if not isinstance(data.get("payload"), dict):
        issues.append(_issue("payload", "expected mapping"))
    checksum = data.get("checksum")
    if not isinstance(checksum, str) or not checksum.startswith("sha256:"):
        issues.append(_issue("checksum", "expected sha256:<hex>"))

    return _result(issues)


def _validate_entry(
    filename: str,
    list_key: str,
    index: int,
    entry: Any,
    issues: list[KnowledgeBaseValidationIssue],
) -> None:
    base = f"{list_key}[{index}]"
    if not isinstance(entry, dict):
        issues.append(_issue(base, "expected mapping"))
        return

    if filename in {
        "estimates-log.yaml",
        "patterns.yaml",
        "pitfalls.yaml",
        "internalization-log.yaml",
        "evolution-signals.yaml",
    }:
        for key in _PROVENANCE_KEYS:
            if not entry.get(key):
                issues.append(_issue(f"{base}.{key}", "required"))
        _validate_iso_datetime(entry.get("created_at"), f"{base}.created_at", issues)

    if filename in {"patterns.yaml", "pitfalls.yaml"}:
        _validate_required_strings(base, entry, ("id",), issues)
        _validate_learning_scope(base, entry, issues)
        _validate_confidence(entry.get("confidence"), f"{base}.confidence", issues)

    if filename == "internalization-log.yaml":
        _validate_internalization_entry(base, entry, issues)

    if filename == "sage-decisions.yaml":
        _validate_sage_decision_entry(base, entry, issues)


def _validate_required_strings(
    base: str,
    entry: dict[str, Any],
    keys: tuple[str, ...],
    issues: list[KnowledgeBaseValidationIssue],
) -> None:
    for key in keys:
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            issues.append(_issue(f"{base}.{key}", "required non-empty string"))


def _validate_sage_decision_entry(
    base: str,
    entry: dict[str, Any],
    issues: list[KnowledgeBaseValidationIssue],
) -> None:
    _validate_required_strings(
        base,
        entry,
        ("run_id", "artifact", "challenge_type", "challenge_summary", "outcome", "resolution"),
        issues,
    )
    if entry.get("challenge_type") not in {
        "logical_inconsistency",
        "missing_evidence",
        "assumption_violation",
        "quality_threshold",
        "specification_gap",
    }:
        issues.append(_issue(f"{base}.challenge_type", "invalid challenge type"))
    if entry.get("outcome") not in {"blocked", "passed_with_warnings", "passed"}:
        issues.append(_issue(f"{base}.outcome", "invalid outcome"))
    if not isinstance(entry.get("was_correct"), bool):
        issues.append(_issue(f"{base}.was_correct", "expected boolean"))


def _validate_learning_scope(
    base: str,
    entry: dict[str, Any],
    issues: list[KnowledgeBaseValidationIssue],
) -> None:
    scope = entry.get("scope", "local_only")
    if scope not in {"local_only", "global"}:
        issues.append(_issue(f"{base}.scope", "expected local_only or global"))
        return
    fingerprint = entry.get("project_fingerprint")
    if scope == "local_only":
        if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.match(fingerprint):
            issues.append(
                _issue(
                    f"{base}.project_fingerprint",
                    "required 12-character hex fingerprint for local_only learning",
                )
            )
    elif fingerprint is not None and (
        not isinstance(fingerprint, str) or not _FINGERPRINT_RE.match(fingerprint)
    ):
        issues.append(_issue(f"{base}.project_fingerprint", "expected 12-character hex fingerprint or null"))


def _validate_internalization_entry(
    base: str,
    entry: dict[str, Any],
    issues: list[KnowledgeBaseValidationIssue],
) -> None:
    required = {
        "id",
        "agent",
        "agent_tier",
        "prompt_version",
        "int_gate_verdict",
        "chk_doubt_count",
        "computation_health",
    }
    for key in sorted(required):
        if key not in entry:
            issues.append(_issue(f"{base}.{key}", "required"))

    if entry.get("source") != "AUDITOR":
        issues.append(_issue(f"{base}.source", "expected AUDITOR"))
    if entry.get("agent_tier") not in {"deep", "moderate", "minimal", "exempt"}:
        issues.append(_issue(f"{base}.agent_tier", "invalid agent tier"))
    if entry.get("int_gate_verdict") not in {"PASS", "FAIL", "EXEMPT", "INSUFFICIENT_DATA"}:
        issues.append(_issue(f"{base}.int_gate_verdict", "invalid gate verdict"))

    doubt_count = entry.get("chk_doubt_count")
    if not isinstance(doubt_count, int) or doubt_count < 0:
        issues.append(_issue(f"{base}.chk_doubt_count", "expected integer >= 0"))

    health = entry.get("computation_health")
    if not isinstance(health, dict):
        issues.append(_issue(f"{base}.computation_health", "expected mapping"))
    else:
        for key in ("inputs_available", "inputs_missing", "formulas_valid", "formulas_failed"):
            value = health.get(key)
            if not isinstance(value, int) or value < 0:
                issues.append(_issue(f"{base}.computation_health.{key}", "expected integer >= 0"))


def _validate_confidence(
    value: Any,
    path: str,
    issues: list[KnowledgeBaseValidationIssue],
) -> None:
    if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        issues.append(_issue(path, "expected number between 0 and 1"))


def _validate_iso_datetime(
    value: Any,
    path: str,
    issues: list[KnowledgeBaseValidationIssue],
) -> None:
    if not isinstance(value, str) or not _ISO_DATETIME_RE.match(value):
        issues.append(_issue(path, "expected ISO-8601 date-time"))


def _issue(path: str, message: str) -> KnowledgeBaseValidationIssue:
    return KnowledgeBaseValidationIssue(path=path, message=message)


def _result(issues: list[KnowledgeBaseValidationIssue]) -> KnowledgeBaseValidationResult:
    return KnowledgeBaseValidationResult(ok=not issues, issues=issues)

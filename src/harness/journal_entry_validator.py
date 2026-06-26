"""Python validator for Echelon reasoning-journal entries."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


MAX_ENTRY_BYTES = 1_048_576


@dataclass(frozen=True)
class JournalEntryValidationVerdict:
    valid: bool
    entry_type: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def default_journal_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "extension/workflow/journal-entry-types.yaml"


def validate_journal_entry(
    entry: dict[str, Any],
    *,
    schema_path: Path | None = None,
) -> JournalEntryValidationVerdict:
    """Validate one journal entry against workflow/journal-entry-types.yaml.

    Mirrors the shell validator contract: unknown types are allowed with a
    warning, while registered types missing required data fields are invalid.
    """
    entry_size = len(str(entry).encode("utf-8"))
    if entry_size > MAX_ENTRY_BYTES:
        return JournalEntryValidationVerdict(
            valid=False,
            entry_type=str(entry.get("type") or "unknown"),
            errors=["Entry exceeds 1MB size limit"],
        )

    entry_type = entry.get("type")
    if not isinstance(entry_type, str) or not entry_type.strip():
        return JournalEntryValidationVerdict(
            valid=False,
            entry_type="unknown",
            errors=["Missing required field: type"],
        )
    entry_type = entry_type.strip()

    registry = _load_type_registry(schema_path or default_journal_schema_path())
    type_def = registry.get(entry_type)
    if not isinstance(type_def, dict):
        return JournalEntryValidationVerdict(
            valid=True,
            entry_type=entry_type,
            warnings=[f"Type not registered in schema: {entry_type}"],
        )

    data = entry.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return JournalEntryValidationVerdict(
            valid=False,
            entry_type=entry_type,
            errors=["Entry data must be an object"],
        )

    required = _string_list(type_def.get("required_data_fields", []))
    optional = _string_list(type_def.get("optional_data_fields", []))
    missing = [field for field in required if field not in data]
    declared = set(required) | set(optional)
    extra = [field for field in data if field not in declared]

    warnings: list[str] = []
    if extra:
        warnings.append("Extra fields not in schema: " + ", ".join(sorted(extra)))
    if str(data.get("source") or "").startswith("tool:") and not data.get("tool_output_ref"):
        warnings.append("source starts with tool: but tool_output_ref is absent or empty")

    if missing:
        return JournalEntryValidationVerdict(
            valid=False,
            entry_type=entry_type,
            warnings=warnings,
            errors=["Missing required fields: " + ", ".join(missing)],
        )

    return JournalEntryValidationVerdict(
        valid=True,
        entry_type=entry_type,
        warnings=warnings,
    )


def prepare_journal_entries_for_append(
    entries: list[Any],
    *,
    phase_id: str,
    next_id: int,
    timestamp: str,
    schema_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Assign journal metadata and add schema_warning siblings when needed."""
    prepared: list[dict[str, Any]] = []
    current_id = next_id
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue

        entry = dict(raw_entry)
        if entry.get("id") is None:
            entry["id"] = current_id
        if entry.get("timestamp") is None:
            entry["timestamp"] = timestamp
        if entry.get("phase") is None:
            entry["phase"] = phase_id
        prepared.append(entry)
        current_id += 1

        verdict = validate_journal_entry(entry, schema_path=schema_path)
        if not verdict.valid:
            warning = _schema_warning_entry(
                entry=entry,
                verdict=verdict,
                warning_id=current_id,
                timestamp=timestamp,
            )
            prepared.append(warning)
            current_id += 1

    return prepared


def _schema_warning_entry(
    *,
    entry: dict[str, Any],
    verdict: JournalEntryValidationVerdict,
    warning_id: int,
    timestamp: str,
) -> dict[str, Any]:
    details = verdict.errors[0] if verdict.errors else "validation failed"
    return {
        "id": warning_id,
        "type": "schema_warning",
        "phase": entry.get("phase") or "unknown",
        "agent": "speckit-echelon-commander",
        "timestamp": timestamp,
        "data": {
            "violating_entry_id": entry.get("id", "unknown"),
            "violation_type": _violation_type(details),
            "details": details,
        },
    }


def _violation_type(details: str) -> str:
    lowered = details.lower()
    if "size limit" in lowered:
        return "size_limit_exceeded"
    if "malformed" in lowered or "parse" in lowered or "type" in lowered:
        return "malformed_json"
    return "missing_required_field"


def _load_type_registry(schema_path: Path) -> dict[str, Any]:
    if not schema_path.exists():
        default_path = default_journal_schema_path()
        if schema_path != default_path:
            schema_path = default_path
    try:
        raw = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    types = raw.get("types")
    return types if isinstance(types, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]

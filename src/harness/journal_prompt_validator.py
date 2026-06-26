"""Static validation for journal-entry examples embedded in prompt files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable

import yaml

from harness.journal_entry_validator import default_journal_schema_path


@dataclass(frozen=True)
class JournalPromptFinding:
    path: Path
    line: int
    entry_type: str
    reason: str
    details: str


_JOURNAL_ENTRIES_RE = re.compile(r"^(?P<indent>\s*)journal_entries:\s*(?P<value>.*)$")
_ENTRY_TYPE_RE = re.compile(r"^(?P<indent>\s*)-\s+type:\s*(?P<value>.+?)\s*(?:#.*)?$")
_DATA_RE = re.compile(r"^(?P<indent>\s*)data:\s*(?:#.*)?$")
_FIELD_RE = re.compile(r"^(?P<indent>\s*)(?P<field>[A-Za-z_][A-Za-z0-9_-]*):")


def validate_prompt_journal_examples(
    paths: Iterable[Path],
    *,
    schema_path: Path | None = None,
) -> list[JournalPromptFinding]:
    """Validate concrete `echelon_result.journal_entries` prompt examples.

    This intentionally validates examples, not arbitrary prose mentions. It
    scans YAML-shaped journal entry blocks and enforces that concrete registered
    types include a `data` mapping with the registry's required top-level data
    fields. Concrete unregistered types are findings because prompt examples
    should not teach agents to emit undeclared durable journal records.
    """
    registry = _load_type_registry(schema_path or default_journal_schema_path())
    findings: list[JournalPromptFinding] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        findings.extend(_validate_file(path, lines, registry))
    return findings


def _validate_file(
    path: Path,
    lines: list[str],
    registry: dict[str, Any],
) -> list[JournalPromptFinding]:
    findings: list[JournalPromptFinding] = []
    idx = 0
    while idx < len(lines):
        match = _JOURNAL_ENTRIES_RE.match(lines[idx])
        if not match:
            idx += 1
            continue

        value = match.group("value").strip()
        if value == "[]":
            idx += 1
            continue

        journal_indent = len(match.group("indent"))
        block_start = idx + 1
        block_end = _find_mapping_block_end(lines, block_start, journal_indent)
        findings.extend(
            _validate_journal_block(
                path=path,
                lines=lines,
                start=block_start,
                end=block_end,
                registry=registry,
            )
        )
        idx = max(block_end, idx + 1)
    return findings


def _find_mapping_block_end(lines: list[str], start: int, parent_indent: int) -> int:
    idx = start
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if not stripped:
            idx += 1
            continue
        if stripped.startswith("#"):
            idx += 1
            continue
        if stripped.startswith("```"):
            return idx
        indent = len(line) - len(line.lstrip())
        if indent <= parent_indent:
            return idx
        idx += 1
    return idx


def _validate_journal_block(
    *,
    path: Path,
    lines: list[str],
    start: int,
    end: int,
    registry: dict[str, Any],
) -> list[JournalPromptFinding]:
    findings: list[JournalPromptFinding] = []
    entry_indexes = [
        idx for idx in range(start, end) if _ENTRY_TYPE_RE.match(lines[idx])
    ]
    for pos, idx in enumerate(entry_indexes):
        entry_match = _ENTRY_TYPE_RE.match(lines[idx])
        if entry_match is None:
            continue
        raw_type = entry_match.group("value").strip()
        entry_type = _normalize_type_value(raw_type)
        if _is_placeholder_type(entry_type):
            continue

        entry_end = entry_indexes[pos + 1] if pos + 1 < len(entry_indexes) else end
        type_def = registry.get(entry_type)
        if not isinstance(type_def, dict):
            findings.append(
                JournalPromptFinding(
                    path=path,
                    line=idx + 1,
                    entry_type=entry_type,
                    reason="unregistered_type",
                    details="Journal entry type is not declared in workflow/journal-entry-types.yaml",
                )
            )
            continue

        required = _string_list(type_def.get("required_data_fields", []))
        if not required:
            continue
        data_line = _find_data_line(lines, idx + 1, entry_end)
        if data_line is None:
            findings.append(
                JournalPromptFinding(
                    path=path,
                    line=idx + 1,
                    entry_type=entry_type,
                    reason="missing_data",
                    details=f"Registered type requires data fields: {', '.join(required)}",
                )
            )
            continue

        fields = _data_fields(lines, data_line, entry_end)
        missing = [field for field in required if field not in fields]
        if missing:
            findings.append(
                JournalPromptFinding(
                    path=path,
                    line=idx + 1,
                    entry_type=entry_type,
                    reason="missing_required_data_fields",
                    details=", ".join(missing),
                )
            )
    return findings


def _find_data_line(lines: list[str], start: int, end: int) -> int | None:
    for idx in range(start, end):
        if _DATA_RE.match(lines[idx]):
            return idx
    return None


def _data_fields(lines: list[str], data_line: int, end: int) -> set[str]:
    data_indent = len(lines[data_line]) - len(lines[data_line].lstrip())
    fields: set[str] = set()
    for idx in range(data_line + 1, end):
        line = lines[idx]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= data_indent:
            break
        match = _FIELD_RE.match(line)
        if match and len(match.group("indent")) == data_indent + 2:
            fields.add(match.group("field"))
    return fields


def _normalize_type_value(raw_type: str) -> str:
    value = raw_type.strip().strip("'\"")
    if value.startswith('"') or value.startswith("'"):
        value = value[1:]
    if value.endswith('"') or value.endswith("'"):
        value = value[:-1]
    return value.strip()


def _is_placeholder_type(entry_type: str) -> bool:
    return any(marker in entry_type for marker in ("<", ">", "{", "}", "|", "$"))


def _load_type_registry(schema_path: Path) -> dict[str, Any]:
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

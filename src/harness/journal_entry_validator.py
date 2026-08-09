"""Python validator for Echelon reasoning-journal entries."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from harness.reasoning_journal_store import (
    JournalStoreError,
    canonicalize_store_path,
    durably_replace_file,
    read_reasoning_journal,
    reasoning_journal_lock,
)


MAX_ENTRY_BYTES = 1_048_576
MAX_CLI_BATCH_BYTES = 4_194_304
MAX_JOURNAL_INDEX_BYTES = 1_048_576
_RJ_ID_PATTERN = re.compile(r"\ARJ-([0-9]+)\Z")
_SHA256_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")
_INDEXED_BATCH_STAMP_KEYS = frozenset(
    {
        "batch_id_sha256",
        "entry_index",
        "entry_count",
        "content_sha256",
    }
)
_COMPLETION_RESERVED_FIELDS = frozenset(
    {
        "id",
        "timestamp",
        "phase",
        "completion_id",
        "entry_index",
        "content_sha256",
        "controller_completion",
        "journal_batch",
    }
)


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
    invalid_registered_policy: Literal["warn", "quarantine"] = "warn",
) -> list[dict[str, Any]]:
    """Assign journal metadata and add schema_warning entries when needed."""
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

        verdict = validate_journal_entry(entry, schema_path=schema_path)
        if not verdict.valid:
            warning_id = (
                current_id + 1
                if invalid_registered_policy == "warn"
                else current_id
            )
            warning = _schema_warning_entry(
                entry=entry,
                verdict=verdict,
                warning_id=warning_id,
                timestamp=timestamp,
            )
            if invalid_registered_policy == "quarantine":
                prepared.append(warning)
                current_id += 1
                continue

            prepared.append(entry)
            prepared.append(warning)
            current_id += 2
            continue

        prepared.append(entry)
        current_id += 1

    return prepared


def prepare_completion_journal_contents(
    entries: list[Any],
    *,
    phase_id: str,
    schema_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Build completion-owned content with all generated metadata removed."""
    prepared: list[dict[str, Any]] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        entry = {
            key: value
            for key, value in raw_entry.items()
            if key not in _COMPLETION_RESERVED_FIELDS
        }
        entry["phase"] = phase_id
        verdict = validate_journal_entry(entry, schema_path=schema_path)
        if verdict.valid:
            prepared.append(entry)
            continue
        details = (
            verdict.errors[0]
            if verdict.errors
            else "validation failed"
        )
        prepared.append(
            {
                "type": "schema_warning",
                "phase": phase_id,
                "agent": "echelon-commander",
                "data": {
                    "violating_entry_id": "controller_completion_entry",
                    "violating_entry_type": verdict.entry_type,
                    "violation_type": _violation_type(details),
                    "details": details,
                },
            }
        )
    return prepared


def _canonical_json_bytes(
    value: object,
    *,
    newline: bool = True,
) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if newline:
            encoded += "\n"
        return encoded.encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ValueError("journal_invalid") from None


def append_reasoning_journal_entries(
    squad_dir: Path,
    entries: list[Any],
    *,
    phase_id: str,
    schema_path: Path | None = None,
    invalid_registered_policy: Literal["warn", "quarantine"] = "quarantine",
    journal_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Validate and atomically append one ordinary journal batch."""
    if not isinstance(squad_dir, Path):
        raise ValueError("journal_invalid")
    journal = (
        journal_path
        if journal_path is not None
        else squad_dir / "reasoning-journal.jsonl"
    )
    if not isinstance(journal, Path) or journal.parent != squad_dir:
        raise ValueError("journal_invalid")
    try:
        with reasoning_journal_lock(squad_dir):
            original, existing = read_reasoning_journal(journal)
            numeric_ids = [
                row["id"]
                for row in existing
                if type(row.get("id")) is int
            ]
            timestamp = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            sanitized = [
                (
                    {
                        key: value
                        for key, value in entry.items()
                        if key != "journal_batch"
                    }
                    if type(entry) is dict
                    else entry
                )
                for entry in entries
            ]
            prepared = prepare_journal_entries_for_append(
                sanitized,
                phase_id=phase_id,
                next_id=max([0, *numeric_ids]) + 1,
                timestamp=timestamp,
                schema_path=schema_path,
                invalid_registered_policy=invalid_registered_policy,
            )
            if not prepared:
                return []
            separator = (
                b"\n"
                if original and not original.endswith(b"\n")
                else b""
            )
            serialized = b"".join(
                _canonical_json_bytes(entry) for entry in prepared
            )
            durably_replace_file(
                journal,
                original + separator + serialized,
            )
            return prepared
    except JournalStoreError:
        raise ValueError("journal_invalid") from None


def _read_optional_json_object(path: Path) -> dict[str, Any]:
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return {}
    except OSError:
        raise ValueError("journal_invalid") from None
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_size > MAX_JOURNAL_INDEX_BYTES
    ):
        raise ValueError("journal_invalid")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        raise ValueError("journal_invalid") from None
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (before.st_dev, before.st_ino)
        ):
            raise ValueError("journal_invalid")
        chunks: list[bytes] = []
        remaining = MAX_JOURNAL_INDEX_BYTES + 1
        while remaining:
            chunk = os.read(
                descriptor,
                min(1_048_576, remaining),
            )
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > MAX_JOURNAL_INDEX_BYTES:
            raise ValueError("journal_invalid")
        after = os.fstat(descriptor)
        if (
            after.st_size != len(content)
            or (after.st_dev, after.st_ino)
            != (opened.st_dev, opened.st_ino)
        ):
            raise ValueError("journal_invalid")
    except OSError:
        raise ValueError("journal_invalid") from None
    finally:
        os.close(descriptor)
    try:
        value = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        raise ValueError("journal_invalid") from None
    if type(value) is not dict:
        raise ValueError("journal_invalid")
    return value


def _indexed_paths(
    squad_dir: Path,
    journal_path: Path | None,
    index_path: Path | None,
) -> tuple[Path, Path]:
    if not isinstance(squad_dir, Path):
        raise ValueError("journal_invalid")
    journal = journal_path or squad_dir / "reasoning-journal.jsonl"
    index = index_path or squad_dir / "reasoning-journal-index.json"
    if (
        not isinstance(journal, Path)
        or not isinstance(index, Path)
        or journal.parent != squad_dir
        or index.parent != squad_dir
    ):
        raise ValueError("journal_invalid")
    return journal, index


def _batch_id_sha256(batch_id: str) -> str:
    if type(batch_id) is not str or not batch_id:
        raise ValueError("journal_invalid")
    encoded = batch_id.encode("utf-8")
    if len(encoded) > 4_096:
        raise ValueError("journal_invalid")
    return hashlib.sha256(encoded).hexdigest()


def _indexed_batch_contents(
    entries: list[Any],
    *,
    phase_id: str,
) -> list[dict[str, Any]]:
    if any(type(entry) is not dict for entry in entries):
        raise ValueError("journal_invalid")
    contents: list[dict[str, Any]] = []
    for entry in entries:
        row = {
            key: value
            for key, value in entry.items()
            if key not in {"id", "timestamp", "journal_batch"}
        }
        if row.get("phase") is None:
            row["phase"] = phase_id
        _canonical_json_bytes(row, newline=False)
        contents.append(row)
    return contents


def _rj_numbers(
    rows: list[dict[str, object]],
    index_value: dict[str, Any],
) -> list[int]:
    numbers: list[int] = []
    for row in rows:
        identifier = row.get("id")
        if type(identifier) is str:
            match = _RJ_ID_PATTERN.fullmatch(identifier)
            if match is not None:
                numbers.append(int(match.group(1)))
    last_identifier = index_value.get("last_entry_id")
    if type(last_identifier) is str:
        match = _RJ_ID_PATTERN.fullmatch(last_identifier)
        if match is not None:
            numbers.append(int(match.group(1)))
    return numbers


def _valid_indexed_timestamp(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _match_indexed_batch(
    rows: list[dict[str, object]],
    *,
    batch_id_sha256: str,
    expected_contents: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    candidates: list[dict[str, Any]] = []
    positions: list[int] = []
    for position, row in enumerate(rows):
        stamp = row.get("journal_batch")
        if (
            type(stamp) is dict
            and stamp.get("batch_id_sha256") == batch_id_sha256
        ):
            candidates.append(row)
            positions.append(position)
    if not candidates:
        return None
    first_stamp = candidates[0].get("journal_batch")
    if type(first_stamp) is not dict:
        raise ValueError("journal_invalid")
    entry_count = first_stamp.get("entry_count")
    if (
        type(entry_count) is not int
        or entry_count <= 0
        or entry_count != len(candidates)
        or (
            expected_contents is not None
            and entry_count != len(expected_contents)
        )
    ):
        raise ValueError("journal_invalid")
    if positions != list(
        range(positions[0], positions[0] + entry_count)
    ):
        raise ValueError("journal_invalid")

    identifiers: list[str] = []
    timestamps: list[str] = []
    matched: list[dict[str, Any]] = []
    for expected_index, row in enumerate(candidates):
        stamp = row.get("journal_batch")
        if (
            type(stamp) is not dict
            or frozenset(stamp) != _INDEXED_BATCH_STAMP_KEYS
            or stamp.get("batch_id_sha256") != batch_id_sha256
            or stamp.get("entry_count") != entry_count
            or stamp.get("entry_index") != expected_index
        ):
            raise ValueError("journal_invalid")
        digest = stamp.get("content_sha256")
        if (
            type(digest) is not str
            or _SHA256_PATTERN.fullmatch(digest) is None
        ):
            raise ValueError("journal_invalid")
        content = dict(row)
        identifier = content.pop("id", None)
        timestamp = content.pop("timestamp", None)
        content.pop("journal_batch", None)
        actual_digest = hashlib.sha256(
            _canonical_json_bytes(content, newline=False)
        ).hexdigest()
        if digest != actual_digest:
            raise ValueError("journal_invalid")
        if (
            expected_contents is not None
            and content != expected_contents[expected_index]
        ):
            raise ValueError("journal_invalid")
        if type(identifier) is not str:
            raise ValueError("journal_invalid")
        match = _RJ_ID_PATTERN.fullmatch(identifier)
        if match is None or not _valid_indexed_timestamp(timestamp):
            raise ValueError("journal_invalid")
        identifiers.append(identifier)
        timestamps.append(str(timestamp))
        matched.append(row)
    numbers = [
        int(_RJ_ID_PATTERN.fullmatch(identifier).group(1))
        for identifier in identifiers
    ]
    if (
        numbers
        != list(range(numbers[0], numbers[0] + len(numbers)))
        or len(set(timestamps)) != 1
    ):
        raise ValueError("journal_invalid")
    for identifier in identifiers:
        if sum(
            type(row.get("id")) is str
            and row.get("id") == identifier
            for row in rows
        ) != 1:
            raise ValueError("journal_invalid")
    return matched


def _repair_journal_index(
    index: Path,
    index_value: dict[str, Any],
    rows: list[dict[str, object]],
) -> None:
    numbers = _rj_numbers(rows, index_value)
    if not numbers:
        return
    last_identifier = f"RJ-{max(numbers):03d}"
    if index_value.get("last_entry_id") == last_identifier:
        return
    repaired = dict(index_value)
    repaired["last_entry_id"] = last_identifier
    durably_replace_file(index, _canonical_json_bytes(repaired))


def append_indexed_reasoning_journal_entries(
    squad_dir: Path,
    entries: list[Any],
    *,
    phase_id: str,
    journal_path: Path | None = None,
    index_path: Path | None = None,
    batch_id: str | None = None,
) -> list[dict[str, Any]]:
    """Append or adopt an RJ-ID batch and durably repair its index."""
    journal, index = _indexed_paths(
        squad_dir,
        journal_path,
        index_path,
    )
    batch_digest = (
        _batch_id_sha256(batch_id)
        if batch_id is not None
        else None
    )
    batch_contents = (
        _indexed_batch_contents(entries, phase_id=phase_id)
        if batch_digest is not None
        else None
    )
    if not entries:
        return []
    try:
        with reasoning_journal_lock(squad_dir):
            original, existing = read_reasoning_journal(journal)
            index_value = _read_optional_json_object(index)
            if batch_digest is not None:
                adopted = _match_indexed_batch(
                    existing,
                    batch_id_sha256=batch_digest,
                    expected_contents=batch_contents,
                )
                if adopted is not None:
                    _repair_journal_index(
                        index,
                        index_value,
                        existing,
                    )
                    return adopted
            used_numbers = _rj_numbers(existing, index_value)
            next_number = max(used_numbers, default=0) + 1
            timestamp = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            prepared: list[dict[str, Any]] = []
            for offset, entry in enumerate(entries):
                row = (
                    dict(batch_contents[offset])
                    if batch_contents is not None
                    else dict(entry)
                )
                row["id"] = f"RJ-{next_number + offset:03d}"
                if batch_digest is not None:
                    row["timestamp"] = timestamp
                    content_digest = hashlib.sha256(
                        _canonical_json_bytes(
                            batch_contents[offset],
                            newline=False,
                        )
                    ).hexdigest()
                    row["journal_batch"] = {
                        "batch_id_sha256": batch_digest,
                        "entry_index": offset,
                        "entry_count": len(entries),
                        "content_sha256": content_digest,
                    }
                else:
                    if row.get("timestamp") is None:
                        row["timestamp"] = timestamp
                    if row.get("phase") is None:
                        row["phase"] = phase_id
                prepared.append(row)
            separator = (
                b"\n"
                if original and not original.endswith(b"\n")
                else b""
            )
            durably_replace_file(
                journal,
                original
                + separator
                + b"".join(
                    _canonical_json_bytes(row) for row in prepared
                ),
            )
            updated_index = dict(index_value)
            updated_index["last_entry_id"] = prepared[-1]["id"]
            durably_replace_file(
                index,
                _canonical_json_bytes(updated_index),
            )
            return prepared
    except (JournalStoreError, ValueError):
        raise ValueError("journal_invalid") from None


def recover_indexed_reasoning_journal_batch(
    squad_dir: Path,
    *,
    batch_id: str,
    journal_path: Path | None = None,
    index_path: Path | None = None,
) -> list[dict[str, Any]] | None:
    """Adopt one exact visible batch and repair only its stale RJ index."""
    journal, index = _indexed_paths(
        squad_dir,
        journal_path,
        index_path,
    )
    batch_digest = _batch_id_sha256(batch_id)
    try:
        with reasoning_journal_lock(squad_dir):
            _, existing = read_reasoning_journal(journal)
            index_value = _read_optional_json_object(index)
            adopted = _match_indexed_batch(
                existing,
                batch_id_sha256=batch_digest,
                expected_contents=None,
            )
            if adopted is None:
                return None
            _repair_journal_index(index, index_value, existing)
            return adopted
    except (JournalStoreError, ValueError):
        raise ValueError("journal_invalid") from None


def _load_cli_entries(input_format: str) -> list[Any]:
    content = sys.stdin.buffer.read(MAX_CLI_BATCH_BYTES + 1)
    if len(content) > MAX_CLI_BATCH_BYTES:
        raise ValueError("journal_invalid")
    try:
        if input_format == "json":
            value = json.loads(content)
            return value if type(value) is list else [value]
        entries = [
            json.loads(line)
            for line in content.splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        raise ValueError("journal_invalid") from None
    return entries


def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m harness.journal_entry_validator",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--journal-path", type=Path, required=True)
    append_parser.add_argument("--phase", required=True)
    append_parser.add_argument(
        "--policy",
        choices=("warn", "quarantine"),
        default="quarantine",
    )
    append_parser.add_argument(
        "--input-format",
        choices=("json", "jsonl"),
        default="json",
    )
    append_parser.add_argument("--schema-path", type=Path)
    append_parser.add_argument("--rj-index", type=Path)
    append_parser.add_argument("--batch-id")
    recover_parser = subparsers.add_parser("recover")
    recover_parser.add_argument(
        "--journal-path",
        type=Path,
        required=True,
    )
    recover_parser.add_argument("--rj-index", type=Path, required=True)
    recover_parser.add_argument("--batch-id", required=True)
    arguments = parser.parse_args()
    try:
        journal = canonicalize_store_path(arguments.journal_path)
        squad_dir = journal.parent
        if arguments.command == "recover":
            index = canonicalize_store_path(arguments.rj_index)
            adopted = recover_indexed_reasoning_journal_batch(
                squad_dir,
                batch_id=arguments.batch_id,
                journal_path=journal,
                index_path=index,
            )
            return 0 if adopted is not None else 3
        entries = _load_cli_entries(arguments.input_format)
        if arguments.rj_index is None:
            if arguments.batch_id is not None:
                raise ValueError("journal_invalid")
            append_reasoning_journal_entries(
                squad_dir,
                entries,
                phase_id=arguments.phase,
                schema_path=arguments.schema_path,
                invalid_registered_policy=arguments.policy,
                journal_path=journal,
            )
        else:
            append_indexed_reasoning_journal_entries(
                squad_dir,
                entries,
                phase_id=arguments.phase,
                journal_path=journal,
                index_path=canonicalize_store_path(
                    arguments.rj_index
                ),
                batch_id=arguments.batch_id,
            )
    except (JournalStoreError, ValueError, OSError):
        print("journal append failed: journal_invalid", file=sys.stderr)
        return 1
    return 0


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
        "agent": "echelon-commander",
        "timestamp": timestamp,
        "data": {
            "violating_entry_id": entry.get("id", "unknown"),
            "violating_entry_type": entry.get("type", "unknown"),
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


if __name__ == "__main__":
    raise SystemExit(_cli())

"""
yaml_safety.py — Safe YAML loading with size limits and schema validation.
Spec 018 T-SEC-3 (RAR-003) + T-SEC-4 (pattern store ceiling).

Mitigations:
  RAR-003: yaml.safe_load() exclusively — yaml.load() is NEVER called here.
  T-SEC-3: 10MB file size ceiling for impasse log (NFR-006).
  T-SEC-4: 5000-entry ceiling for F6 pattern store with LRU-style eviction.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .exceptions import YamlLoadError

# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------

# NFR-006: Maximum file size for codegen-impasse-log.yaml and rule pack files
IMPASSE_LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB

# T-SEC-4: Maximum entries in codegen-patterns.yaml (F6 pattern store)
PATTERN_STORE_MAX_ENTRIES: int = 5000

# Spec 018 AC-018-1: Archive threshold for impasse log (entry count trigger)
IMPASSE_LOG_ARCHIVE_THRESHOLD: int = 1000


class YamlSafety:
    """
    Safe YAML loading and size-limit enforcement for pipeline data files.
    All loads use yaml.safe_load() — arbitrary Python object construction is impossible.
    """

    @staticmethod
    def load(file_path: str | Path, max_bytes: int = IMPASSE_LOG_MAX_BYTES) -> Any:
        """
        Load a YAML file safely.

        Uses yaml.safe_load() exclusively (RAR-003).
        Enforces a file size ceiling before loading (prevents memory exhaustion).

        Args:
            file_path: Path to the YAML file.
            max_bytes: Maximum allowed file size in bytes. Default 10MB (NFR-006).

        Returns:
            The parsed Python object (dict, list, or None for empty files).

        Raises:
            YamlLoadError: If file exceeds size limit or is structurally invalid.
            yaml.YAMLError: If the file contains invalid YAML syntax.
            FileNotFoundError: If the file does not exist.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"YAML file not found: {file_path}")

        file_size = path.stat().st_size
        if file_size > max_bytes:
            raise YamlLoadError(
                file_path=str(file_path),
                reason=(
                    f"File size {file_size:,} bytes exceeds {max_bytes:,} byte limit "
                    f"({max_bytes // (1024 * 1024)}MB ceiling, NFR-006). "
                    "Archive stale entries before loading."
                ),
            )

        content = path.read_text(encoding="utf-8")
        # RAR-003: safe_load only — NO yaml.load() anywhere in this codebase
        return yaml.safe_load(content)

    @staticmethod
    def load_string(content: str) -> Any:
        """
        Load YAML from a string safely (yaml.safe_load only).
        Used for in-memory YAML processing without file I/O.
        """
        return yaml.safe_load(content)

    @staticmethod
    def enforce_pattern_store_ceiling(
        entries: list[dict],
        max_entries: int = PATTERN_STORE_MAX_ENTRIES,
        sort_key: str = "last_seen_run",
    ) -> list[dict]:
        """
        Enforce the F6 pattern store entry ceiling (T-SEC-4).

        If entries exceed max_entries, truncate by evicting the oldest entries
        (lowest `last_seen_run` value). This is an LRU-style eviction by run number.

        Args:
            entries: List of pattern store entry dicts.
            max_entries: Maximum allowed entries. Default 5000 (T-SEC-4).
            sort_key: Field to sort by for eviction. Default 'last_seen_run'.

        Returns:
            The (possibly truncated) entries list, sorted descending by sort_key.
            Original list is NOT mutated.
        """
        if len(entries) <= max_entries:
            return entries

        def _get_sort_val(entry: dict) -> int:
            val = entry.get(sort_key, 0)
            return int(val) if isinstance(val, (int, float)) else 0

        sorted_entries = sorted(entries, key=_get_sort_val, reverse=True)
        return sorted_entries[:max_entries]

    @staticmethod
    def check_impasse_log_archive_threshold(entries: list) -> bool:
        """
        Return True if the impasse log has reached the archive threshold (1000 entries).
        Spec 018 AC-018-1: pipeline should archive when this returns True.
        """
        return len(entries) >= IMPASSE_LOG_ARCHIVE_THRESHOLD

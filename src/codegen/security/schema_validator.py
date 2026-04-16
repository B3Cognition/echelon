"""
schema_validator.py — Post-load structural validation for pipeline YAML files.
Spec 018 T-SEC-3: validate structure after yaml.safe_load() to enforce invariants.
"""
from __future__ import annotations

from typing import Any

from .exceptions import YamlLoadError


def validate_impasse_log(data: Any, file_path: str = "<impasse-log>") -> list[dict]:
    """
    Validate the structure of a loaded codegen-impasse-log.yaml.

    Expected structure:
        entries: list of impasse entry dicts

    Returns:
        The validated entries list.

    Raises:
        YamlLoadError: If structure is invalid.
    """
    if data is None:
        return []  # Empty file is valid (fresh log)

    if not isinstance(data, dict):
        raise YamlLoadError(
            file_path=file_path,
            reason=f"Expected a dict with 'entries' key, got {type(data).__name__}",
        )

    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise YamlLoadError(
            file_path=file_path,
            reason=f"'entries' must be a list, got {type(entries).__name__}",
        )

    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise YamlLoadError(
                file_path=file_path,
                reason=f"Entry #{i} must be a dict, got {type(entry).__name__}",
            )

    return entries


def validate_pattern_store(data: Any, file_path: str = "<pattern-store>") -> list[dict]:
    """
    Validate the structure of a loaded codegen-patterns.yaml.

    Expected structure:
        patterns: list of pattern entry dicts

    Returns:
        The validated patterns list.

    Raises:
        YamlLoadError: If structure is invalid.
    """
    if data is None:
        return []

    if not isinstance(data, dict):
        raise YamlLoadError(
            file_path=file_path,
            reason=f"Expected a dict with 'patterns' key, got {type(data).__name__}",
        )

    patterns = data.get("patterns", [])
    if not isinstance(patterns, list):
        raise YamlLoadError(
            file_path=file_path,
            reason=f"'patterns' must be a list, got {type(patterns).__name__}",
        )

    for i, entry in enumerate(patterns):
        if not isinstance(entry, dict):
            raise YamlLoadError(
                file_path=file_path,
                reason=f"Pattern #{i} must be a dict, got {type(entry).__name__}",
            )

    return patterns

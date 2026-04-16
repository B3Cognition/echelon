"""
loader.py — Rule Pack Loader and Conflict Detector.
Spec 018 Wave 1 F2 T-007.

Loads CQ-ISC rule packs from YAML files, validates them, and detects conflicts
between packs and with the default library.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.codegen.security.yaml_safety import YamlSafety
from src.codegen.schema.validate_cq_isc import validate_library


# ---------------------------------------------------------------------------
# Exceptions and data classes
# ---------------------------------------------------------------------------


class PackLoadError(Exception):
    """Raised when a pack fails validation or cannot be loaded."""


@dataclass
class PackConflict:
    """Describes a conflict detected between rule packs."""

    conflict_type: str  # "id_collision" or "constitution_override"
    cq_isc_id: str
    pack_a: str
    pack_b: Optional[str] = None
    message: str = ""


# ---------------------------------------------------------------------------
# RulePackLoader
# ---------------------------------------------------------------------------


class RulePackLoader:
    """
    Loads and validates CQ-ISC rule packs from YAML files.

    Each YAML file must have an 'entries' list containing valid CQ-ISC entries.
    Validation is performed via validate_library() from validate_cq_isc.py.
    """

    def load(self, pack_paths: list[str]) -> list[dict]:
        """
        Load and validate one or more rule pack YAML files.

        Args:
            pack_paths: List of file paths to YAML rule pack files.

        Returns:
            Merged list of all valid entries from all packs.

        Raises:
            PackLoadError: If any pack fails validation.
        """
        all_entries: list[dict] = []

        for path_str in pack_paths:
            path = Path(path_str)
            # YamlSafety.load() uses yaml.safe_load() exclusively (RAR-003)
            raw = YamlSafety.load(path)

            if raw is None:
                raise PackLoadError(f"Pack file is empty or null: {path}")

            if isinstance(raw, dict):
                if "entries" not in raw:
                    raise PackLoadError(
                        f"Pack file has no 'entries' key: {path}"
                    )
                entries = raw.get("entries", [])
            elif isinstance(raw, list):
                entries = raw
            else:
                raise PackLoadError(
                    f"Unexpected YAML root type {type(raw).__name__} in {path}"
                )

            # Validate via validate_library (includes hash checks)
            is_valid, errors = validate_library(path)
            # Filter out pure warnings (those are not fatal)
            real_errors = [e for e in errors if not e.startswith("WARNING:")]
            if real_errors:
                raise PackLoadError(
                    f"Pack validation failed for {path}: "
                    + "; ".join(real_errors)
                )

            all_entries.extend(entries)

        return all_entries


# ---------------------------------------------------------------------------
# PackConflictDetector
# ---------------------------------------------------------------------------


class PackConflictDetector:
    """
    Detects conflicts between rule packs and with the default library.

    Conflict types:
      - id_collision: same cq_isc_id appears in two different packs
      - constitution_override: pack entry has same (constraint_class, language_scope)
        as a default library entry (marks pack entry as overridden)
    """

    def check(
        self,
        packs: list[tuple[str, list[dict]]],
    ) -> list[PackConflict]:
        """
        Check for conflicts across packs.

        Args:
            packs: List of (pack_name, entries) tuples.

        Returns:
            List of PackConflict instances. Empty list means no conflicts.
        """
        conflicts: list[PackConflict] = []

        # --- ID collision detection ---
        # Map cq_isc_id -> first pack that owns it
        id_to_pack: dict[str, str] = {}

        for pack_name, entries in packs:
            for entry in entries:
                cq_id = entry.get("cq_isc_id", "")
                if not cq_id:
                    continue
                if cq_id in id_to_pack:
                    conflicts.append(
                        PackConflict(
                            conflict_type="id_collision",
                            cq_isc_id=cq_id,
                            pack_a=id_to_pack[cq_id],
                            pack_b=pack_name,
                            message=(
                                f"ID collision: '{cq_id}' appears in both "
                                f"'{id_to_pack[cq_id]}' and '{pack_name}'"
                            ),
                        )
                    )
                else:
                    id_to_pack[cq_id] = pack_name

        # --- Constitution override detection ---
        # First pack is treated as the default library (reference)
        # Subsequent packs are checked against it
        if len(packs) < 2:
            return conflicts

        default_pack_name, default_entries = packs[0]
        default_dimensions: set[tuple[str, str]] = set()
        for entry in default_entries:
            cc = str(entry.get("constraint_class", "")).upper()
            ls = str(entry.get("language_scope", "")).lower()
            if cc and ls:
                default_dimensions.add((cc, ls))

        for pack_name, entries in packs[1:]:
            for entry in entries:
                cc = str(entry.get("constraint_class", "")).upper()
                ls = str(entry.get("language_scope", "")).lower()
                if (cc, ls) in default_dimensions:
                    # Mark the entry as overridden in-place
                    entry["policy_drift_status"] = "overridden"

        return conflicts

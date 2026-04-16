"""
memory.py — ImpasseMemory: persistent log of conflict-impasse resolutions.
Spec 018 Wave 3 F5 T-019.

INV-008: Conflict impasse = correct behaviour, NOT a failure.
RAR-002: All file reads/writes via PathSafety — path traversal blocked.
RAR-003: Only yaml.safe_load() — never yaml.load().
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict
from datetime import datetime
from typing import Optional

import yaml

from src.codegen.impasse.impasse_types import ImpasseResolution
from src.codegen.security.path_safety import PathSafety
from src.codegen.security.yaml_safety import YamlSafety

logger = logging.getLogger(__name__)

_DEFAULT_LOG_FILENAME = "codegen-impasse-log.yaml"


class ImpasseMemory:
    """
    Persistent log of conflict-impasse resolutions.

    Stores ImpasseResolution entries in a YAML file so that subsequent
    pipeline runs can auto-apply prior human decisions without re-escalating.

    Hash staleness semantics:
      - Exact match (rule_content_hash unchanged) → return entry
      - rule_content_hash changed, rule_text_normalized_hash unchanged
        (cosmetic change only) → return entry, log audit note
      - Both hashes changed (semantic change) → return None, caller escalates
    """

    def __init__(self, log_path: str | None = None) -> None:
        if log_path is None:
            ps = PathSafety(os.getcwd())
            log_path = ps.anchor_output(_DEFAULT_LOG_FILENAME)
        self._log_path = log_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(
        self,
        rule_pair_key: frozenset,
        language_context: str,
        current_normalized_hash: str = "",
    ) -> Optional[ImpasseResolution]:
        """
        Find an active resolution matching (rule_pair_key, language_context).

        rule_pair_key: frozenset of (cq_isc_id, rule_content_hash) tuples.

        Matching strategy:
          1. First try exact key match (matching_key == serialised rule_pair_key).
             If found and hashes agree → exact match, return entry.
          2. If no exact key match, try structural match: same cq_isc_ids regardless
             of content hash, then apply hash staleness logic.

        Hash staleness logic (applied when ids match but hashes differ):
          - rule_content_hash same as stored → exact match, return entry
          - rule_content_hash differs, rule_text_normalized_hash == current_normalized_hash
            → cosmetic change, auto-apply with audit note logged
          - Both hashes differ → semantic change, return None (caller must escalate)

        Returns:
            ImpasseResolution if active match found, None otherwise.
        """
        target_key = _serialize_key(rule_pair_key)
        # Extract (id, hash) pairs and id-only set from incoming key
        current_pairs: list[tuple[str, str]] = [
            (item[0], item[1]) for item in rule_pair_key if len(item) >= 2
        ]
        current_ids: frozenset[str] = frozenset(p[0] for p in current_pairs)
        current_content_hashes: set[str] = {p[1] for p in current_pairs}

        entries = self._load_entries()

        for raw in entries:
            if raw.get("status") != "active":
                continue
            if raw.get("language_context", "") != language_context:
                continue

            stored_key = raw.get("matching_key", "")
            resolution = _entry_to_resolution(raw)

            # --- Strategy 1: exact serialised key match ---
            if stored_key == target_key:
                return resolution  # hashes are identical by construction

            # --- Strategy 2: structural match on cq_isc_ids ---
            stored_ids = _extract_ids_from_key(stored_key)
            if stored_ids != current_ids:
                continue  # different rule pair entirely

            # Same ids, different hashes — apply staleness logic
            stored_content_hash = resolution.rule_content_hash

            if stored_content_hash in current_content_hashes or stored_content_hash == "":
                # Content hash still matches one of the current hashes → exact
                return resolution

            # Content hash differs — check normalized hash (cosmetic change?)
            if current_normalized_hash and resolution.rule_text_normalized_hash == current_normalized_hash:
                logger.info(
                    "ImpasseMemory audit: cosmetic rule change detected for entry %s "
                    "(content_hash changed, normalized_hash stable). Auto-applying.",
                    resolution.entry_id,
                )
                return resolution

            # Both hashes differ → semantic change, cannot auto-apply
            logger.info(
                "ImpasseMemory: semantic rule change detected for entry %s. "
                "Returning None — caller must escalate to human.",
                resolution.entry_id,
            )
            return None

        return None

    def store(
        self,
        resolution: ImpasseResolution,
        language_context: str = "",
    ) -> None:
        """
        Append (or update) a resolution in the log file.

        If an entry with the same entry_id already exists it is replaced
        (covers the apply_count increment path). Otherwise appended.
        Archive is triggered if threshold is reached.

        Args:
            resolution: The ImpasseResolution to persist.
            language_context: Language context tag stored alongside the entry
                              for lookup filtering. Preserved when updating
                              an existing entry.
        """
        entries = self._load_entries()

        # Replace existing entry by entry_id if present
        replaced = False
        for i, raw in enumerate(entries):
            if raw.get("entry_id") == resolution.entry_id:
                updated = _resolution_to_entry(resolution)
                # Preserve existing language_context if not supplied
                updated["language_context"] = language_context or raw.get("language_context", "")
                entries[i] = updated
                replaced = True
                break

        if not replaced:
            new_entry = _resolution_to_entry(resolution)
            new_entry["language_context"] = language_context
            entries.append(new_entry)

        self._save_entries(entries)
        self.archive_if_needed()

    def mark_stale(self, entry_id: str) -> None:
        """Set entry status to 'stale'."""
        entries = self._load_entries()
        for raw in entries:
            if raw.get("entry_id") == entry_id:
                raw["status"] = "stale"
                break
        self._save_entries(entries)

    def archive_if_needed(self) -> bool:
        """
        Archive active entries to a timestamped file if count exceeds 1000.

        Archive file: codegen-impasse-log-archive-{timestamp}-UTC.yaml
        Returns True if archive was written.
        """
        entries = self._load_entries()
        active_entries = [e for e in entries if e.get("status") == "active"]

        if not YamlSafety.check_impasse_log_archive_threshold(active_entries):
            return False

        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        archive_filename = f"codegen-impasse-log-archive-{timestamp}-UTC.yaml"

        ps = PathSafety(os.getcwd())
        archive_path = ps.anchor_output(archive_filename)

        archive_content = yaml.safe_dump(
            active_entries, default_flow_style=False, allow_unicode=True
        )
        with open(archive_path, "w", encoding="utf-8") as fh:
            fh.write(archive_content)

        logger.info(
            "ImpasseMemory: archived %d active entries to %s",
            len(active_entries),
            archive_path,
        )

        # Keep non-active entries in primary log; clear active ones
        remaining = [e for e in entries if e.get("status") != "active"]
        self._save_entries(remaining)
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_entries(self) -> list[dict]:
        """Load all entries from YAML log. Returns [] if file absent."""
        if not os.path.exists(self._log_path):
            return []
        try:
            data = YamlSafety.load(self._log_path)
        except FileNotFoundError:
            return []
        if data is None:
            return []
        if isinstance(data, list):
            return data
        return []

    def _save_entries(self, entries: list[dict]) -> None:
        """Write entries to YAML log via PathSafety.anchor_output()."""
        content = yaml.safe_dump(entries, default_flow_style=False, allow_unicode=True)
        with open(self._log_path, "w", encoding="utf-8") as fh:
            fh.write(content)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_key(rule_pair_key: frozenset) -> str:
    """Stable string representation of a frozenset rule_pair_key."""
    return str(sorted(rule_pair_key))


def _extract_ids_from_key(serialized_key: str) -> frozenset[str]:
    """
    Extract just the cq_isc_id components from a serialised matching_key.

    The serialized key looks like: "[('CQ-ISC-001', 'hash1'), ('CQ-ISC-002', 'hash2')]"
    We parse the id (first element of each tuple) to allow structural matching
    when content hashes have changed (cosmetic / semantic staleness detection).

    Returns a frozenset of id strings, or empty frozenset if parsing fails.
    """
    import ast
    try:
        parsed = ast.literal_eval(serialized_key)
        if isinstance(parsed, list):
            return frozenset(item[0] for item in parsed if isinstance(item, (tuple, list)) and len(item) >= 1)
    except (ValueError, SyntaxError):
        pass
    return frozenset()


def _resolution_to_entry(r: ImpasseResolution) -> dict:
    """Convert ImpasseResolution to a plain dict for YAML storage."""
    d = asdict(r)
    return d


def _entry_to_resolution(raw: dict) -> ImpasseResolution:
    """Convert a plain dict from YAML into an ImpasseResolution."""
    return ImpasseResolution(
        entry_id=raw.get("entry_id", ""),
        matching_key=raw.get("matching_key", ""),
        resolution_type=raw.get("resolution_type", "exception_wme"),
        exception_wme_value=raw.get("exception_wme_value", ""),
        resolved_in_run_id=raw.get("resolved_in_run_id", ""),
        resolution_timestamp=raw.get("resolution_timestamp", ""),
        apply_count=raw.get("apply_count", 0),
        status=raw.get("status", "active"),
        rule_content_hash=raw.get("rule_content_hash", ""),
        rule_text_normalized_hash=raw.get("rule_text_normalized_hash", ""),
    )

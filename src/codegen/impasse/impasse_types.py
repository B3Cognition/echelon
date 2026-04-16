"""
impasse_types.py — ImpasseResolution dataclass for Impasse Memory (T-019).
Spec 018 Wave 3 F5.

INV-008: Conflict impasse = correct behaviour, NOT a failure.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class ImpasseResolution:
    """
    A stored resolution for a past conflict impasse.

    When a human resolves an impasse, the resolution is stored so that
    subsequent runs with the same rule pair can be auto-applied without
    re-escalating to human (provided hashes remain stable).

    Fields:
        entry_id                  — unique UUID
        matching_key              — serialized frozenset key for lookup
        resolution_type           — "exception_wme" | "user_override"
        exception_wme_value       — the WME value to inject when auto-applying
        resolved_in_run_id        — run_id from when human resolved this
        resolution_timestamp      — ISO-8601 timestamp
        apply_count               — incremented each auto-apply
        status                    — "active" | "stale" | "archived"
        rule_content_hash         — SHA-256 of rule_text at time of resolution
        rule_text_normalized_hash — SHA-256 of rule_text.strip().lower()
    """

    entry_id: str
    matching_key: str
    resolution_type: str
    exception_wme_value: str
    resolved_in_run_id: str
    resolution_timestamp: str
    apply_count: int = 0
    status: str = "active"
    rule_content_hash: str = ""
    rule_text_normalized_hash: str = ""

    @staticmethod
    def compute_content_hash(rule_text: str) -> str:
        """SHA-256 of rule_text (exact)."""
        return hashlib.sha256(rule_text.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_normalized_hash(rule_text: str) -> str:
        """SHA-256 of rule_text.strip().lower()."""
        return hashlib.sha256(rule_text.strip().lower().encode("utf-8")).hexdigest()

"""
psi_dedup.py — Ψ Score Deduplication Extension.
Spec 018 Wave 1 F2 T-009.

Computes the Ψ (Psi) score with deduplication by (constraint_class, language_scope)
dimension, preventing duplicate entries from inflating the score.
"""
from __future__ import annotations


def compute_psi_deduplicated(entries: list[dict]) -> dict:
    """
    Compute Ψ score with deduplication by (constraint_class, language_scope).

    Dedup logic:
    - Group entries by (constraint_class, language_scope) dimension
    - Each unique (constraint_class, language_scope) pair counts as 1 dimension
    - A dimension is "covered" if it has at least one entry with policy_drift_status == "current"
    - Ψ score = dimensions_with_current_entry / total_unique_dimensions
    - If no dimensions exist, Ψ score = 0.0

    Args:
        entries: List of CQ-ISC entry dicts.

    Returns:
        Dict with keys:
          - psi_score: float in [0.0, 1.0]
          - psi_raw_entry_count: int — total entries before deduplication
          - psi_dimension_count: int — unique (constraint_class, language_scope) pairs
    """
    psi_raw_entry_count = len(entries)

    if not entries:
        return {
            "psi_score": 0.0,
            "psi_raw_entry_count": 0,
            "psi_dimension_count": 0,
        }

    # Group entries by dimension
    # dimension key: (constraint_class.upper(), language_scope.lower())
    dimensions: dict[tuple[str, str], list[dict]] = {}

    for entry in entries:
        cc = str(entry.get("constraint_class", "")).upper()
        ls = str(entry.get("language_scope", "")).lower()
        dim_key = (cc, ls)
        if dim_key not in dimensions:
            dimensions[dim_key] = []
        dimensions[dim_key].append(entry)

    psi_dimension_count = len(dimensions)

    # Count dimensions that have at least one "current" entry
    dimensions_with_current = sum(
        1
        for dim_entries in dimensions.values()
        if any(
            str(e.get("policy_drift_status", "")).lower() == "current"
            for e in dim_entries
        )
    )

    psi_score = dimensions_with_current / psi_dimension_count if psi_dimension_count > 0 else 0.0

    return {
        "psi_score": psi_score,
        "psi_raw_entry_count": psi_raw_entry_count,
        "psi_dimension_count": psi_dimension_count,
    }

"""
anchoring_types.py — Data types for Anchoring Mode.
Spec 018 T-015: F4 Anchoring Mode type definitions.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AnchoringConstraint:
    constraint_id: str           # e.g. "ANCHOR-naming-001"
    dimension: str               # "naming" | "imports" | "test_structure" | "comment_density" | "abstraction"
    constraint_text: str         # human-readable description
    source_path: str             # which file it was extracted from
    run_id: str                  # pipeline run UUID (for transient lifetime tracking)


@dataclass
class AnchoringViolation:
    constraint_id: str
    dimension: str
    matched_text: str
    line: int

    # WME dict representation (AC-014-new-2a)
    def to_wme_dict(self, constraint_id: str) -> dict:
        return {
            "class": "cq-isc",
            "rule-id": f"ANCHOR-{constraint_id}",
            "violation-type": "anchoring",
            "matched": True,
        }

"""Deterministic soft score for Tier-2 structural artifacts (audit layer)."""
from __future__ import annotations

from .structural import structural_validate


def structural_quality(text: str, entry: dict, spec_text: str = "") -> float:
    """1.0 when clean; -0.2 per finding; clamped to [0,1]. Advisory only."""
    report = structural_validate(text, entry, spec_text)
    return max(0.0, 1.0 - 0.2 * len(report.findings))

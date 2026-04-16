"""
summary.py — Pipeline summary generation for /codegen output.
Spec 018 T-026: per-criterion Ψ table + weighted/unweighted Ψ display.
"""
from __future__ import annotations

from ..metrics.psi import PsiResult, PsiCriterionRecord


def format_psi_summary(result: PsiResult) -> str:
    """
    Format pipeline Ψ summary for output.

    Includes:
    - Both weighted and unweighted Ψ values
    - Per-criterion table with columns: criterion_id, covered, trend, status,
      source_authority_type, weight
    """
    lines = [
        f"Ψ (unweighted): {result.psi:.4f}",
        f"Ψ (weighted):   {result.psi_weighted:.4f}",
        "",
        f"{'Criterion':<30} {'Covered':<8} {'Trend':>6} {'Status':<12} {'Authority':<20} {'Weight':>6}",
        "-" * 90,
    ]
    for rec in result.criteria_records:
        trend_str = f"{rec.trend:+.2f}"
        lines.append(
            f"{rec.criterion_id:<30} {str(rec.covered):<8} {trend_str:>6} "
            f"{rec.status:<12} {rec.source_authority_type:<20} {rec.weight:>6.1f}"
        )
    return "\n".join(lines)


def check_anchoring_excluded_from_smem(entry_source_authority_type: str) -> bool:
    """
    AC-026-3: ANCHORING-type entries must NOT be distilled into SMEM patterns.
    Returns True if entry should be excluded from SMEM distillation.
    """
    return entry_source_authority_type.upper() == "ANCHORING"

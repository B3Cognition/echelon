"""Shared deterministic quality-threshold decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class QualityThresholdDecision:
    """Numeric and effective verdicts for one configured score vector."""

    thresholds: dict[str, float]
    numeric_passes: dict[str, bool]
    effective_passes: dict[str, bool]
    passed: bool
    overall_pass_basis: str


def evaluate_quality_thresholds(
    scores: Mapping[str, object],
    configured_gates: Mapping[str, object],
) -> QualityThresholdDecision:
    """Evaluate category floors without enforcing their weighted aggregate twice."""
    raw_gates = configured_gates.get("spec")
    gates = raw_gates if isinstance(raw_gates, Mapping) else configured_gates
    thresholds = {
        str(name): float(value)
        for name, value in gates.items()
        if isinstance(value, (int, float))
    }
    numeric_passes = {
        name: (
            isinstance(scores.get(name), (int, float))
            and float(scores[name]) >= threshold
        )
        for name, threshold in thresholds.items()
    }
    effective_passes = dict(numeric_passes)
    category_names = [name for name in thresholds if name != "overall"]
    categories_pass = bool(category_names) and all(
        numeric_passes[name] for name in category_names
    )
    overall_pass_basis = "numeric_threshold"
    if "overall" in effective_passes and categories_pass:
        if not numeric_passes["overall"]:
            overall_pass_basis = "all_configured_categories_pass"
        effective_passes["overall"] = True
    return QualityThresholdDecision(
        thresholds=thresholds,
        numeric_passes=numeric_passes,
        effective_passes=effective_passes,
        passed=bool(thresholds) and all(effective_passes.values()),
        overall_pass_basis=overall_pass_basis,
    )

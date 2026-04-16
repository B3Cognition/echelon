"""
psi.py — Ψ (Psi) Coverage Metric Implementation.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-030: Full Ψ coverage metric per FR-PSI-001..005.

Ψ formula:
  Ψ = |I_covered| / |I_D|

Where:
  |I_covered| = number of active CQ-ISC rules that have WME evidence in EPMEM
                (excludes drifted entries — FR-PSI-004)
  |I_D|       = estimated implementation delta size (requirements count proxy)
                estimated from ≥2 signal sources (FR-RE-005)

Ψ_seed:
  Ψ_seed = |matching_default_library_entries| / |constitution_rules|
  (measures how well the default seed library covers the project constitution)

FR-PSI-001: Ψ ∈ [0.0, 1.0].
FR-PSI-002: Ψ = 0.0 when no CQ-ISC rules are active.
FR-PSI-003: Ψ_seed is reported separately from pipeline Ψ.
FR-PSI-004: Drifted entries excluded from numerator AND denominator.
FR-PSI-005: Low-confidence |I_D| estimate requires user confirmation.
FR-RE-005:  |I_D| estimated from ≥2 independent signal sources.
FR-GATE-004: Ψ ≥ psi-threshold required for DELIVER.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class IDConfidence(str, Enum):
    HIGH = "HIGH"       # ≥2 signals agree within 20%
    MEDIUM = "MEDIUM"   # ≥2 signals present but diverge by >20%
    LOW = "LOW"         # only 1 signal available


class DriftStatus(str, Enum):
    ACTIVE = "active"
    DRIFTED = "drifted"
    PENDING_REVIEW = "pending_review"


# ---------------------------------------------------------------------------
# |I_D| estimation (FR-RE-005)
# ---------------------------------------------------------------------------

@dataclass
class IDEstimate:
    """
    |I_D| (implementation delta) estimate from multiple signal sources.

    FR-RE-005: Must use ≥2 independent signal sources.
    FR-PSI-005: LOW confidence requires user confirmation before pipeline proceeds.

    Signal sources:
      1. test_count        — inferred from test file / function count
      2. api_surface_count — API endpoints, exported functions
      3. module_count      — modules × estimated requirements per module
    """
    # Raw signal values
    test_count: Optional[int] = None
    api_surface_count: Optional[int] = None
    module_count: Optional[int] = None
    requirements_per_module: float = 3.0   # calibration constant

    # Computed (set by estimate())
    value: int = 0
    confidence: IDConfidence = IDConfidence.LOW
    signals_used: list[str] = field(default_factory=list)
    signal_values: dict[str, int] = field(default_factory=dict)

    def estimate(self) -> "IDEstimate":
        """
        Compute the |I_D| estimate and confidence level.

        Uses all available signals; confidence depends on count and agreement.
        """
        signals: dict[str, int] = {}

        if self.test_count is not None and self.test_count > 0:
            signals["test_count"] = self.test_count
        if self.api_surface_count is not None and self.api_surface_count > 0:
            signals["api_surface_count"] = self.api_surface_count
        if self.module_count is not None and self.module_count > 0:
            val = int(math.ceil(self.module_count * self.requirements_per_module))
            signals["module_count"] = val

        self.signal_values = dict(signals)
        self.signals_used = list(signals.keys())

        if not signals:
            self.value = 0
            self.confidence = IDConfidence.LOW
            return self

        values = list(signals.values())

        if len(values) == 1:
            self.value = values[0]
            self.confidence = IDConfidence.LOW
        else:
            mean = sum(values) / len(values)
            max_deviation = max(abs(v - mean) / mean for v in values)

            # Use median for robustness
            sorted_vals = sorted(values)
            mid = len(sorted_vals) // 2
            self.value = sorted_vals[mid]

            if max_deviation <= 0.20:
                self.confidence = IDConfidence.HIGH
            else:
                self.confidence = IDConfidence.MEDIUM

        return self

    def requires_confirmation(self) -> bool:
        """FR-PSI-005: LOW confidence requires user confirmation."""
        return self.confidence == IDConfidence.LOW


# ---------------------------------------------------------------------------
# CQ-ISC entry for Ψ computation
# ---------------------------------------------------------------------------

@dataclass
class PsiEntry:
    """
    A CQ-ISC library entry with drift status for Ψ computation.

    FR-PSI-004: Drifted entries are excluded from numerator AND denominator.
    """
    cq_isc_id: str
    constraint_class: str
    language_scope: str
    drift_status: DriftStatus = DriftStatus.ACTIVE
    covered: bool = False          # True if EPMEM has evidence for this entry
    # T-024: new fields (backward compatible — absent in state file → use defaults)
    weight: float = 1.0                              # T-024
    diverging: bool = False                          # T-024
    source_authority_type: str = "DEFAULT_LIBRARY"  # T-024 (was stub in T-009)

    @property
    def eligible(self) -> bool:
        """Entry is eligible for Ψ computation (not drifted)."""
        return self.drift_status == DriftStatus.ACTIVE


# ---------------------------------------------------------------------------
# PsiCriterionRecord — per-criterion state persistence (T-025)
# ---------------------------------------------------------------------------

@dataclass
class PsiCriterionRecord:
    """
    Per-criterion record for time-series tracking and pipeline summary display.
    T-025: Enables trend computation and status reporting across retry cycles.
    """
    criterion_id: str
    covered: bool
    trend: float      # delta from prior cycle (0.0 if first cycle)
    status: str       # "ACTIVE" | "DIVERGING"
    source_authority_type: str = "DEFAULT_LIBRARY"
    weight: float = 1.0


# ---------------------------------------------------------------------------
# PsiTracker — per-criterion coverage history + DIVERGING detection (T-024)
# ---------------------------------------------------------------------------

class PsiTracker:
    """
    Tracks per-criterion coverage history across retry cycles.
    Detects DIVERGING: criterion uncovered for >= threshold consecutive cycles.
    """

    def __init__(self, diverging_threshold: int = 2) -> None:
        # diverging_threshold: from codegen-state.json:psi_diverging_threshold (default 2)
        self._threshold = diverging_threshold
        # Internal: dict[criterion_id, list[bool]] — True=covered, False=not covered
        self._history: dict[str, list[bool]] = {}
        # Track which criteria have already been declared DIVERGING (to avoid re-triggering)
        self._declared_diverging: set[str] = set()

    def update(self, criterion_id: str, covered: bool) -> None:
        """Record coverage status for this cycle."""
        if criterion_id not in self._history:
            self._history[criterion_id] = []
        self._history[criterion_id].append(covered)

    def check_divergence(self, criterion_id: str) -> bool:
        """
        Returns True ONCE when DIVERGING is first declared for this criterion.
        DIVERGING condition: last `threshold` entries are all False (not covered)
        AND delta (improvement) between consecutive cycles < 0.01.

        Returns False on first non-coverage cycle (not yet DIVERGING).
        Returns True only on cycle `threshold` (e.g. cycle 2 if threshold=2).
        Returns False on subsequent cycles after first declaration (already declared).

        Reset: if criterion becomes covered, remove from _declared_diverging so it can
        trigger again if it regresses.
        """
        history = self._history.get(criterion_id, [])

        if len(history) < self._threshold:
            return False  # Not enough history yet

        # Check if last `threshold` cycles are all uncovered
        recent = history[-self._threshold:]
        if any(recent):  # At least one covered → not diverging
            # Reset declaration if criterion recovered
            self._declared_diverging.discard(criterion_id)
            return False

        # All recent cycles uncovered — DIVERGING
        if criterion_id in self._declared_diverging:
            return False  # Already declared, don't re-trigger

        self._declared_diverging.add(criterion_id)
        return True

    def reset_diverging(self, criterion_id: str) -> None:
        """Call after human resolution to reset criterion to ACTIVE."""
        self._declared_diverging.discard(criterion_id)
        if criterion_id in self._history:
            del self._history[criterion_id]


# ---------------------------------------------------------------------------
# Ψ computation (FR-PSI-001..004)
# ---------------------------------------------------------------------------

@dataclass
class PsiResult:
    """
    Ψ coverage metric result.

    FR-PSI-001: Ψ ∈ [0.0, 1.0].
    FR-PSI-003: Ψ_seed reported separately.
    FR-PSI-004: Drifted entries excluded.
    """
    psi: float                          # pipeline Ψ
    psi_seed: float                     # seed library Ψ (FR-PSI-003)
    id_estimate: int                    # |I_D| used as denominator
    id_confidence: IDConfidence
    covered_count: int                  # |I_covered| (numerator)
    eligible_count: int                 # |active entries| (effective denominator)
    drifted_count: int                  # entries excluded by FR-PSI-004
    entries: list[PsiEntry] = field(default_factory=list)
    # T-025: new fields
    psi_weighted: float = 0.0           # weighted Ψ (same as psi if all weights=1.0)
    criteria_records: list[PsiCriterionRecord] = field(default_factory=list)

    def to_wme_dict(self) -> dict:
        """Serialize as SOAR WME."""
        return {
            "wme_type": "psi-metric",
            "psi": round(self.psi, 4),
            "psi-seed": round(self.psi_seed, 4),
            "id-estimate": self.id_estimate,
            "id-confidence": self.id_confidence.value,
            "covered-count": self.covered_count,
            "eligible-count": self.eligible_count,
            "drifted-count": self.drifted_count,
            "preference": "best",   # INV-003
        }


def compute_psi_weighted(entries: list[PsiEntry]) -> float:
    """
    Weighted Ψ formula: sum(weight × covered) / sum(weight × eligible)
    Backward compat: absent weight → 1.0, result identical to unweighted formula.

    T-025: Used by PsiComputer.compute() to populate PsiResult.psi_weighted.
    """
    eligible = [e for e in entries if e.eligible]
    if not eligible:
        return 0.0

    numerator = sum(e.weight * (1.0 if e.covered else 0.0) for e in eligible)
    denominator = sum(e.weight for e in eligible)

    if denominator == 0.0:
        return 0.0
    return min(1.0, numerator / denominator)


def compute_psi(
    entries: list[PsiEntry],
    id_estimate: int,
    id_confidence: IDConfidence,
) -> PsiResult:
    """
    Compute Ψ from the given CQ-ISC entries and |I_D| estimate.

    FR-PSI-001: Ψ = |I_covered| / |I_D|, clamped to [0.0, 1.0].
    FR-PSI-002: Ψ = 0.0 when no active entries.
    FR-PSI-004: Drifted entries excluded from numerator and denominator.
    """
    eligible = [e for e in entries if e.eligible]
    drifted = [e for e in entries if not e.eligible]
    covered = [e for e in eligible if e.covered]

    eligible_count = len(eligible)
    covered_count = len(covered)
    drifted_count = len(drifted)

    # FR-PSI-002: no active entries → Ψ = 0.0
    if eligible_count == 0 or id_estimate == 0:
        return PsiResult(
            psi=0.0,
            psi_seed=0.0,
            id_estimate=id_estimate,
            id_confidence=id_confidence,
            covered_count=0,
            eligible_count=eligible_count,
            drifted_count=drifted_count,
            entries=entries,
        )

    # FR-PSI-001: Ψ = |I_covered| / |I_D|, clamped to [0.0, 1.0]
    psi_raw = covered_count / id_estimate
    psi = min(1.0, max(0.0, psi_raw))

    # Ψ_seed placeholder — computed by compute_psi_seed() separately
    return PsiResult(
        psi=psi,
        psi_seed=0.0,   # filled in by compute_psi_seed
        id_estimate=id_estimate,
        id_confidence=id_confidence,
        covered_count=covered_count,
        eligible_count=eligible_count,
        drifted_count=drifted_count,
        entries=entries,
    )


def compute_psi_seed(
    default_library: list[dict],
    constitution_rules: list[str],
    language: str = "all",
) -> float:
    """
    Compute Ψ_seed: fraction of constitution rules covered by the default library.

    Ψ_seed = |library_entries matching project constitution rules| / |constitution_rules|

    FR-PSI-003: Ψ_seed is reported separately from pipeline Ψ.

    Args:
        default_library:    List of CQ-ISC library entry dicts.
        constitution_rules: List of constitution rule text strings.
        language:           Filter library to this language scope.

    Returns:
        Ψ_seed in [0.0, 1.0].
    """
    if not constitution_rules:
        return 0.0

    # Filter library to applicable language scope
    applicable = [
        e for e in default_library
        if _matches_language(e.get("language_scope", "all"), language)
    ]

    if not applicable:
        return 0.0

    # For each constitution rule, check if any library entry semantically matches
    matched = sum(
        1 for rule in constitution_rules
        if _library_covers_rule(applicable, rule)
    )

    return min(1.0, matched / len(constitution_rules))


def _library_covers_rule(library: list[dict], rule_text: str) -> bool:
    """
    Heuristic: check if any library entry covers the given constitution rule.

    Matching strategy: shared keyword overlap ≥ 2 keywords.
    """
    rule_keywords = _extract_keywords(rule_text)
    if not rule_keywords:
        return False

    for entry in library:
        entry_keywords = _extract_keywords(entry.get("rule_text", ""))
        overlap = rule_keywords & entry_keywords
        if len(overlap) >= 2:
            return True
    return False


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful lowercase keywords from text."""
    stopwords = {"a", "an", "the", "is", "are", "be", "in", "of", "for",
                 "to", "and", "or", "not", "must", "should", "no", "never"}
    words = set(re.findall(r"[a-zA-Z]{3,}", text.lower()))
    return words - stopwords


def _matches_language(scope: str, language: str) -> bool:
    if scope.strip().lower() == "all":
        return True
    langs = [l.strip().lower() for l in scope.split(",")]
    return language.lower() in langs


# ---------------------------------------------------------------------------
# PsiComputer — public API
# ---------------------------------------------------------------------------

class PsiComputer:
    """
    Full Ψ coverage metric engine.

    Wraps IDEstimate + compute_psi + compute_psi_seed into a single callable.
    """

    def __init__(self, psi_threshold: float = 0.70) -> None:
        self.psi_threshold = psi_threshold

    def compute(
        self,
        cq_isc_entries: list[PsiEntry],
        covered_ids: set[str],
        test_count: Optional[int] = None,
        api_surface_count: Optional[int] = None,
        module_count: Optional[int] = None,
        default_library: Optional[list[dict]] = None,
        constitution_rules: Optional[list[str]] = None,
        language: str = "all",
        prior_criteria_records: Optional[dict[str, PsiCriterionRecord]] = None,
    ) -> PsiResult:
        """
        Compute full Ψ.

        Args:
            cq_isc_entries:       Active CQ-ISC entries (with drift status).
            covered_ids:          Set of cq_isc_ids with EPMEM evidence.
            test_count:           Signal 1 for |I_D|.
            api_surface_count:    Signal 2 for |I_D|.
            module_count:         Signal 3 for |I_D|.
            default_library:      Full default CQ-ISC library (for Ψ_seed).
            constitution_rules:   Project constitution rule texts (for Ψ_seed).
            language:             Project language.
            prior_criteria_records: Optional mapping of criterion_id →
                                    PsiCriterionRecord from prior cycle, used to
                                    compute trend deltas. T-025.

        Returns:
            PsiResult with psi, psi_seed, id_estimate, id_confidence,
            psi_weighted, and criteria_records.
        """
        # Mark coverage
        for entry in cq_isc_entries:
            entry.covered = entry.cq_isc_id in covered_ids

        # |I_D| estimation
        id_est = IDEstimate(
            test_count=test_count,
            api_surface_count=api_surface_count,
            module_count=module_count,
        ).estimate()

        # Fallback: use eligible entry count as proxy if no signals
        if id_est.value == 0:
            eligible_count = sum(1 for e in cq_isc_entries if e.eligible)
            id_est.value = max(1, eligible_count)

        result = compute_psi(cq_isc_entries, id_est.value, id_est.confidence)

        # Ψ_seed (FR-PSI-003)
        if default_library and constitution_rules:
            result.psi_seed = compute_psi_seed(
                default_library, constitution_rules, language,
            )

        # T-025: weighted Ψ
        result.psi_weighted = compute_psi_weighted(cq_isc_entries)

        # T-025: populate per-criterion records with trend deltas
        prior = prior_criteria_records or {}
        criteria_records: list[PsiCriterionRecord] = []
        for entry in cq_isc_entries:
            if not entry.eligible:
                continue
            prior_rec = prior.get(entry.cq_isc_id)
            if prior_rec is not None:
                trend = float(entry.covered) - float(prior_rec.covered)
            else:
                trend = 0.0
            status = "DIVERGING" if entry.diverging else "ACTIVE"
            criteria_records.append(PsiCriterionRecord(
                criterion_id=entry.cq_isc_id,
                covered=entry.covered,
                trend=trend,
                status=status,
                source_authority_type=entry.source_authority_type,
                weight=entry.weight,
            ))
        result.criteria_records = criteria_records

        return result

    def meets_threshold(self, psi: float) -> bool:
        return psi >= self.psi_threshold

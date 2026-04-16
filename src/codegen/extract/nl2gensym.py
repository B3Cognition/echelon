"""
nl2gensym.py — NL2GenSym confidence formula and category classification.
Spec 018 F3 T-012.

Three sub-scorers feed a weighted formula:
  confidence = (source_coverage * 0.4) + (pattern_consistency * 0.4) + (rule_count_adequacy * 0.2)

Classification thresholds:
  >= 0.85 → Category S
  0.70 <= c < 0.85 → Category S_HUMAN (requires human predicate)
  < 0.70 → Category B
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.codegen.extract.constitution_extractor import ExtractedRule


# ---------------------------------------------------------------------------
# Sub-scorers
# ---------------------------------------------------------------------------

class SourceCoverageScorer:
    """Scores how many of the expected 8 source types were found."""

    @staticmethod
    def score(sources_found: int, total_expected: int = 8) -> float:
        """
        Returns the fraction of expected source types found, capped at 1.0.

        Args:
            sources_found:  Number of source types that yielded at least one rule.
            total_expected: Total expected source types (default 8).

        Returns:
            Float in [0.0, 1.0].
        """
        if total_expected <= 0:
            return 1.0
        return min(1.0, sources_found / total_expected)


class PatternConsistencyScorer:
    """Scores consistency between extracted patterns and known template patterns."""

    @staticmethod
    def score(
        extracted_patterns: set[str],
        template_patterns: set[str],
    ) -> float:
        """
        Jaccard similarity: |intersection| / |union|.

        Args:
            extracted_patterns: Pattern strings found in the codebase.
            template_patterns:  Pattern strings expected from templates.

        Returns:
            Float in [0.0, 1.0]. Returns 1.0 if both sets are empty.
        """
        if not extracted_patterns and not template_patterns:
            return 1.0
        union = extracted_patterns | template_patterns
        intersection = extracted_patterns & template_patterns
        return len(intersection) / len(union)


class RuleCountAdequacyScorer:
    """Scores whether enough rules were extracted relative to sources present."""

    @staticmethod
    def score(count: int, sources_present: int) -> float:
        """
        Returns min(1.0, count / (3 * sources_present)).
        Expects at least 3 rules per source for full score.

        Args:
            count:           Total number of rules extracted.
            sources_present: Number of source types that produced rules.

        Returns:
            Float in [0.0, 1.0].
        """
        if sources_present == 0:
            return 0.0
        return min(1.0, count / (3 * sources_present))


# ---------------------------------------------------------------------------
# NL2GenSym
# ---------------------------------------------------------------------------

class NL2GenSym:
    """
    Computes the NL2GenSym confidence score and classifies rules into categories.
    """

    @staticmethod
    def score(
        rule: ExtractedRule,  # noqa: ARG004  (not used in current formula, reserved)
        source_coverage: float,
        pattern_consistency: float,
        rule_count_adequacy: float,
    ) -> float:
        """
        Weighted confidence formula.

        confidence = (source_coverage * 0.4) + (pattern_consistency * 0.4) + (rule_count_adequacy * 0.2)

        Args:
            rule:                 The ExtractedRule being scored (reserved for future use).
            source_coverage:      Score from SourceCoverageScorer.
            pattern_consistency:  Score from PatternConsistencyScorer.
            rule_count_adequacy:  Score from RuleCountAdequacyScorer.

        Returns:
            Float in [0.0, 1.0].
        """
        return (
            (source_coverage * 0.4)
            + (pattern_consistency * 0.4)
            + (rule_count_adequacy * 0.2)
        )

    @staticmethod
    def classify(confidence: float) -> tuple[str, float]:
        """
        Classify a confidence score into a category.

        Thresholds:
            >= 0.85 → ("S", confidence)       — auto-enforceable
            0.70 <= c < 0.85 → ("S_HUMAN", confidence) — requires human predicate
            < 0.70 → ("B", confidence)         — advisory only

        Args:
            confidence: Float confidence value.

        Returns:
            Tuple of (category_string, confidence).
        """
        if confidence >= 0.85:
            return ("S", confidence)
        elif confidence >= 0.70:
            return ("S_HUMAN", confidence)
        else:
            return ("B", confidence)

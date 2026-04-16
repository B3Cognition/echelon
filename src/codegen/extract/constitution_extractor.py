"""
constitution_extractor.py — Auto-Constitution Extraction core.
Spec 018 F3 T-011.

Dispatches to five sub-extractors and aggregates results into a ConstitutionDraft.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ExtractedRule:
    """A single rule extracted from a source artifact."""
    source_type: str   # "tsconfig" | "eslint" | "editorconfig" | "test_pattern" | "naming_convention"
    raw_text: str
    category: str      # "S" or "B"
    confidence: float
    source: str        # "direct" | "active-correction" | "absent"


@dataclass
class ConstitutionDraft:
    """Aggregated result of a constitution extraction run."""
    rules: list[ExtractedRule]
    sources_found: list[str]       # which of the 8 source types were found
    sources_absent: list[str]      # which were absent
    overall_confidence: float
    extraction_degraded: bool      # True if < 2 sources
    banners: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ExtractionFailedError(Exception):
    """Raised when no source files were found during extraction."""


# ---------------------------------------------------------------------------
# Extractor registry
# ---------------------------------------------------------------------------

_ALL_SOURCE_TYPES = [
    "tsconfig",
    "eslint",
    "editorconfig",
    "test_pattern",
    "naming_convention",
]

# All 8 source types declared for sources_absent tracking
_EXPECTED_SOURCE_TYPES = [
    "tsconfig",
    "eslint",
    "editorconfig",
    "test_pattern",
    "naming_convention",
    "package_json",     # not yet implemented — always absent
    "prettier",         # not yet implemented — always absent
    "gitignore",        # not yet implemented — always absent
]


# ---------------------------------------------------------------------------
# ConstitutionExtractor
# ---------------------------------------------------------------------------

class ConstitutionExtractor:
    """
    Dispatches to all five sub-extractors and assembles a ConstitutionDraft.
    """

    def run(
        self,
        target_path: Path | str,
        force: bool = False,
    ) -> ConstitutionDraft:
        """
        Run all sub-extractors against target_path and return a ConstitutionDraft.

        Args:
            target_path: Root directory of the codebase to extract from.
            force:       Passed through for downstream use (not used here).

        Returns:
            ConstitutionDraft with all extracted rules.

        Raises:
            ExtractionFailedError: If no source artifacts were found at all.
        """
        from src.codegen.security.path_safety import PathSafety

        safety = PathSafety(str(target_path))
        normalized_path = safety.normalize(target_path)

        from src.codegen.extract.extractors import (
            tsconfig_extractor,
            eslint_extractor,
            editorconfig_extractor,
            test_pattern_extractor,
            naming_convention_extractor,
        )

        extractors = {
            "tsconfig": tsconfig_extractor,
            "eslint": eslint_extractor,
            "editorconfig": editorconfig_extractor,
            "test_pattern": test_pattern_extractor,
            "naming_convention": naming_convention_extractor,
        }

        all_rules: list[ExtractedRule] = []
        sources_found: list[str] = []
        sources_absent: list[str] = []

        for source_type, extractor_module in extractors.items():
            try:
                extracted = extractor_module.extract(normalized_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "constitution_extractor: extractor '%s' raised %s — skipping",
                    source_type,
                    exc,
                )
                extracted = []

            if extracted:
                sources_found.append(source_type)
                all_rules.extend(extracted)
            else:
                sources_absent.append(source_type)
                logger.debug("constitution_extractor: source '%s' absent at %s", source_type, normalized_path)

        # Mark the three non-implemented source types as absent
        for phantom in ("package_json", "prettier", "gitignore"):
            sources_absent.append(phantom)

        if not sources_found:
            raise ExtractionFailedError(
                f"No source artifacts found at '{normalized_path}'. "
                "Cannot extract constitution."
            )

        banners: list[str] = ["UNVALIDATED"]
        extraction_degraded = len(sources_found) < 2

        if extraction_degraded:
            banners.append("EXTRACTION_DEGRADED")
            logger.warning(
                "constitution_extractor: only %d source(s) found — extraction degraded",
                len(sources_found),
            )

        overall_confidence = _compute_overall_confidence(all_rules)

        if overall_confidence < 0.70:
            banners.append("EXTRACTION_CONFIDENCE_LOW")

        return ConstitutionDraft(
            rules=all_rules,
            sources_found=sources_found,
            sources_absent=sources_absent,
            overall_confidence=overall_confidence,
            extraction_degraded=extraction_degraded,
            banners=banners,
        )


def _compute_overall_confidence(rules: list[ExtractedRule]) -> float:
    """Compute average confidence across all extracted rules."""
    if not rules:
        return 0.0
    return sum(r.confidence for r in rules) / len(rules)

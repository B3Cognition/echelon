"""Versioned semantic-completeness vocabulary for reverse engineering."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal


SEMANTIC_COMPLETENESS_VERSION = 1

SemanticCategory = Literal[
    "public-surface",
    "configuration",
    "error-recovery",
    "boundary",
    "operator-observable",
    "test-demonstrated",
    "evidence-scope",
]

_CATEGORY_PATTERNS: tuple[tuple[SemanticCategory, re.Pattern[str]], ...] = (
    (
        "error-recovery",
        re.compile(r"\b(error|failure|uncaught|unhandled|recover|recovery|retry)\b", re.I),
    ),
    (
        "configuration",
        re.compile(
            r"\b(config|option|constraint|invalid|frontmatter|retention)\b", re.I
        ),
    ),
    (
        "public-surface",
        re.compile(r"\b(public|operation|method|function|command|api)\b", re.I),
    ),
    (
        "operator-observable",
        re.compile(r"\b(warning|exit|diagnostic|output|log)\b", re.I),
    ),
    (
        "test-demonstrated",
        re.compile(r"\b(test|fixture|assert)\b", re.I),
    ),
    (
        "boundary",
        re.compile(r"\b(edge|boundary|empty|partial|limit)\b", re.I),
    ),
)


@dataclass(frozen=True)
class ReSemanticFindingRecord:
    finding_id: str
    category: SemanticCategory
    text: str
    source_evidence: tuple[str, ...]


def classify_semantic_finding(text: str) -> SemanticCategory:
    """Classify a finding using stable, ordered lexical rules."""
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return "evidence-scope"


def stable_finding_id(
    category: str,
    text: str,
    evidence: tuple[str, ...],
) -> str:
    """Return a content-derived local correlation ID without retaining content."""
    payload = {
        "category": _normalize(category),
        "text": _normalize(text),
        "evidence": sorted(_normalize(item) for item in evidence),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"ref-{digest[:16]}"


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.casefold().split())

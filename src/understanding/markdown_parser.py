#!/usr/bin/env python3
"""
Markdown-aware requirement extraction.

Replaces naive re.split(r'[.!?]+', text) which breaks on:
- Decimal numbers (2.5 seconds)
- Abbreviations (e.g., i.e.)
- URLs (api.example.com)
- Markdown formatting

Four-phase extraction:
1. Structured IDs (FR-NNN, REQ-NNN, NFR-NNN)
2. Markdown bullets (-, *, +)
3. Gherkin blocks (Given/When/Then)
4. Prose fallback (spaCy or guarded regex)
"""

import re
from typing import List

# Optional spaCy import — gracefully degrade if not installed
try:
    import spacy
    SPACY_AVAILABLE = True
    try:
        _nlp = spacy.load("en_core_web_sm")
    except OSError:
        SPACY_AVAILABLE = False
        _nlp = None
except ImportError:
    SPACY_AVAILABLE = False
    _nlp = None

# ---------- Pre-processing ----------

_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->", re.MULTILINE)


def _preprocess(text: str) -> str:
    """Strip markdown code blocks and HTML comments."""
    text = _CODE_BLOCK_RE.sub("", text)
    text = _HTML_COMMENT_RE.sub("", text)
    return text


# ---------- Phase 1: Structured IDs ----------

_STRUCTURED_ID_RE = re.compile(
    r"^.*(?:[A-Z]+-)?(?:FR|REQ|NFR)-\d+.*$",
    re.MULTILINE,
)


def _extract_structured_ids(text: str) -> List[str]:
    """Extract full lines/paragraphs containing structured requirement IDs."""
    return [m.strip() for m in _STRUCTURED_ID_RE.findall(text)]


# ---------- Phase 2: Markdown bullets ----------

_BULLET_RE = re.compile(r"^[\s]*[-*+]\s+(.+)$", re.MULTILINE)


def _extract_bullets(text: str) -> List[str]:
    """Extract content from markdown bullet lists."""
    return [m.strip() for m in _BULLET_RE.findall(text)]


# ---------- Phase 3: Given/When/Then ----------

_GWT_RE = re.compile(
    r"^[\s]*(?:Given|When|Then|And|But)\s+(.+?)$",
    re.MULTILINE,
)


def _extract_gherkin(text: str) -> List[str]:
    """Extract Gherkin-style requirement lines."""
    return [m.strip() for m in _GWT_RE.findall(text)]


# ---------- Phase 4: Prose fallback ----------

# Guarded sentence-end regex: split on . ! ? that are NOT preceded by a digit
# (avoids splitting "2.5") and NOT inside common abbreviations.
_PROSE_SPLIT_RE = re.compile(r"(?<!\d)[.!?]+(?=\s|$)")


def _extract_prose(text: str) -> List[str]:
    """Split prose into sentences using spaCy (preferred) or guarded regex."""
    if SPACY_AVAILABLE and _nlp is not None:
        doc = _nlp(text)
        return [sent.text.strip() for sent in doc.sents]

    # Fallback: guarded regex split
    parts = _PROSE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


# ---------- Post-processing ----------


def _deduplicate_filter(items: List[str]) -> List[str]:
    """Deduplicate while preserving order, filter short strings."""
    seen: set = set()
    result: List[str] = []
    for item in items:
        stripped = item.strip()
        if len(stripped) > 10 and stripped not in seen:
            seen.add(stripped)
            result.append(stripped)
    return result


# ---------- Public API ----------


def extract_requirements(text: str) -> List[str]:
    """
    Extract requirements from markdown text using four strategies in
    priority order:

    1. Structured IDs  (FR-NNN, REQ-NNN, NFR-NNN)
    2. Markdown bullets (-, *, +)
    3. Gherkin blocks   (Given/When/Then/And/But)
    4. Prose fallback   (spaCy sentences or guarded regex)

    Returns a deduplicated list of requirement strings (len > 10).
    """
    cleaned = _preprocess(text)

    requirements: List[str] = []

    # Phase 1 — structured IDs (highest priority)
    requirements.extend(_extract_structured_ids(cleaned))

    # Phase 2 — markdown bullets
    requirements.extend(_extract_bullets(cleaned))

    # Phase 3 — Gherkin
    requirements.extend(_extract_gherkin(cleaned))

    # Phase 4 — prose fallback (only if earlier phases found nothing)
    if not requirements:
        requirements.extend(_extract_prose(cleaned))

    return _deduplicate_filter(requirements)

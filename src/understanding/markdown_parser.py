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
from typing import List, Tuple

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


# ---------- Phase 0: Lexicon controlled grammar ----------
#
# When spec.md is authored in the Lexicon controlled grammar (ARTIFACT: SPEC
# header + REQ:/GIVEN:/WHEN:/THEN: blocks) there are NO `- **FR-001**:` bullets,
# so the bullet/structured-ID strategies below either find nothing or wrongly
# grab the `REQ: FR-001` id line. This strategy extracts the real normative
# prose — the THEN main clause of each REQ block — so the 34 metrics score the
# requirement statement, not an id line.

_LEXICON_HEADER_RE = re.compile(r"^\s*ARTIFACT:\s*(?:SPEC|STORY|ARTICLE)\b", re.MULTILINE)
_LEXICON_REQ_LINE_RE = re.compile(r"^\s*REQ:\s*\S")
_LEXICON_REQ_ID_RE = re.compile(r"^\s*REQ:\s*(\S+)\s*$")
_LEXICON_GIVEN_RE = re.compile(r"^\s*GIVEN:\s*(.+\S)\s*$")
_LEXICON_WHEN_RE = re.compile(r"^\s*WHEN:\s*(.+\S)\s*$")
_LEXICON_THEN_RE = re.compile(r"^\s*THEN:\s*(.+\S)\s*$")
_LEXICON_OUTPUT_RE = re.compile(r"^\s*OUTPUT:\s*(.+\S)\s*$")
_LEXICON_CONSTRAINT_RE = re.compile(r"^\s*CONSTRAINT:\s*(.+\S)\s*$")


def is_lexicon_spec(text: str) -> bool:
    """True if the text is authored in the Lexicon controlled grammar."""
    if _LEXICON_HEADER_RE.search(text):
        return True
    return any(_LEXICON_REQ_LINE_RE.match(line) for line in text.splitlines())


def extract_lexicon_requirements(
    text: str, fold_output_constraint: bool = True
) -> List[Tuple[str, str]]:
    """Return (req_id, requirement_text) for every REQ block in a Lexicon spec.

    The THEN main clause (actor + modal + action + object) is the atomic
    requirement statement. With ``fold_output_constraint=True`` (default) the
    full requirement context is reconstructed as an EARS-style sentence — GIVEN
    (guard) + WHEN (trigger) + THEN (action) + OUTPUT (outcome) + CONSTRAINT
    (threshold) — so semantic (trigger/outcome), behavioral (guard→action→
    outcome), and testability (constraint) metrics see every part. With
    ``fold_output_constraint=False`` the THEN clause is returned alone — correct
    for atomicity/structure metrics, which would read the folded form as
    multiple statements.
    AC / ERROR / RULE blocks are not normative requirements and are skipped."""
    out: List[Tuple[str, str]] = []
    for block in re.split(r"\n\s*\n", text):
        lines = block.strip().splitlines()
        if not lines:
            continue
        m_id = _LEXICON_REQ_ID_RE.match(lines[0])
        if not m_id:  # only blocks that open with `REQ:` are normative requirements
            continue
        given = when = then = output = constraint = None
        for line in lines[1:]:
            if given is None and _LEXICON_GIVEN_RE.match(line):
                given = _LEXICON_GIVEN_RE.match(line).group(1).strip()
            elif when is None and _LEXICON_WHEN_RE.match(line):
                when = _LEXICON_WHEN_RE.match(line).group(1).strip()
            elif then is None and _LEXICON_THEN_RE.match(line):
                then = _LEXICON_THEN_RE.match(line).group(1).strip()
            elif output is None and _LEXICON_OUTPUT_RE.match(line):
                output = _LEXICON_OUTPUT_RE.match(line).group(1).strip()
            elif constraint is None and _LEXICON_CONSTRAINT_RE.match(line):
                constraint = _LEXICON_CONSTRAINT_RE.match(line).group(1).strip()
        if then is None:
            continue
        if fold_output_constraint:
            head = []
            if given:
                head.append(f"Given {given.rstrip('.')}")
            if when:
                head.append(f"when {when.rstrip('.')}")
            head.append(then.rstrip("."))
            req_text = ", ".join(head) + "."
            for extra in (output, constraint):
                if extra:
                    req_text += " " + extra.rstrip(".") + "."
        else:
            req_text = then
        out.append((m_id.group(1), req_text))
    return out


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

    # Phase 0 — Lexicon controlled grammar (highest priority, exclusive).
    # If this is a Lexicon spec, the bullet/ID/Gherkin strategies would only
    # produce id-line noise, so use the THEN-clause extraction alone.
    if is_lexicon_spec(cleaned):
        return _deduplicate_filter(
            [then for _id, then in extract_lexicon_requirements(cleaned)]
        )

    # Strategies in PRIORITY ORDER — use the first that yields results, do NOT
    # union them. A "- **FR-001**: ..." line matches both the structured-ID and
    # bullet strategies, and unrelated bullets/GWT lines inflate the count, so
    # summing over-counts a spec's requirements several-fold.
    for strategy in (
        _extract_structured_ids,  # Phase 1 — canonical FR/REQ/NFR requirements
        _extract_bullets,         # Phase 2 — markdown bullets
        _extract_gherkin,         # Phase 3 — Given/When/Then
        _extract_prose,           # Phase 4 — prose fallback
    ):
        found = _deduplicate_filter(strategy(cleaned))
        if found:
            return found

    return []

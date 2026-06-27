"""Lexicon term resolver — computes T(A), the term-resolution gate.

Every *content term* in an artifact must bind to an approved concept in the
project glossary (the controlled vocabulary). T(A) = resolved / total.

Deterministic v1 scope: "content terms" are domain identifiers — snake_case
(``due_date``, ``authorization_request``) and CamelCase (``Payment_Gateway``)
tokens that appear in value text. These are the tokens that most clearly must
be governed. Full natural-language noun extraction is future work; until then
plain English words are not treated as content terms.
"""

from __future__ import annotations

import re

from .linter import Finding

# Domain identifier shapes: snake_case or CamelCase (each needs an internal
# boundary so plain lowercase words like "user" are not counted).
_TERM_RE = re.compile(
    r"\b("
    r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+"  # snake_case / Mixed_Snake
    r"|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+"  # CamelCase
    r")\b"
)

# Strip a leading "KEYWORD:" label so grammar labels (ERROR_CODE:, VALID_WHEN:,
# RESOLVE_BY:) are not mistaken for content terms.
_LABEL_RE = re.compile(r"^\s*[A-Z][A-Z_]*:\s*")


def content_terms(text: str) -> list[tuple[str, int]]:
    """Return (term, 1-based line) for every content term in value text."""
    out: list[tuple[str, int]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        value = _LABEL_RE.sub("", line)
        for match in _TERM_RE.finditer(value):
            out.append((match.group(1), lineno))
    return out


def unresolved_terms(text: str, glossary: set[str]) -> list[Finding]:
    """Return a Finding for every content term not in ``glossary``."""
    findings: list[Finding] = []
    for term, lineno in content_terms(text):
        if term not in glossary:
            findings.append(
                Finding(
                    code="unresolved-term",
                    message=f"unresolved term {term!r} — not in glossary",
                    line=lineno,
                    span=term,
                )
            )
    return findings


def term_resolution(text: str, glossary: set[str]) -> float:
    """T(A): fraction of content terms that resolve to the glossary.

    An artifact with no content terms vacuously resolves (T == 1.0)."""
    terms = content_terms(text)
    if not terms:
        return 1.0
    resolved = sum(1 for term, _ in terms if term in glossary)
    return resolved / len(terms)

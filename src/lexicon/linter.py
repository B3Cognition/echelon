"""Lexicon semantic linter — deterministic checks above the parse gate.

The first check is the banned-word policy: vague adjectives, vague
quantifiers, and weak phrasing are ambiguity signals (INCOSE / NASA / STE).
A banned word is only legal when immediately followed by a measurable
restatement or a cited constraint; that allowance is not yet implemented, so
v1 flags every occurrence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Vague/weak terms that are ambiguity signals (Deterministic Grammar doc p.14;
# INCOSE / NASA / STE). Longer phrases first so the alternation prefers them.
BANNED_WORDS: tuple[str, ...] = (
    "user-friendly",
    "high-quality",
    "as needed",
    "intuitive",
    "seamless",
    "efficient",
    "optimized",
    "appropriate",
    "various",
    "robust",
    "simple",
    "easy",
    "fast",
    "slow",
    "some",
)

_BANNED_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in BANNED_WORDS) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    """A single deterministic lint finding."""

    code: str  # machine-readable check id, e.g. "banned-word"
    message: str  # human-readable, localized to the offending span
    line: int  # 1-based line number
    span: str  # the offending text


def banned_word_findings(text: str) -> list[Finding]:
    """Return a Finding for every banned word occurrence (empty = clean)."""
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _BANNED_RE.finditer(line):
            word = match.group(0)
            findings.append(
                Finding(
                    code="banned-word",
                    message=(
                        f"banned word {word!r} — replace with a measurable "
                        f"constraint or delete"
                    ),
                    line=lineno,
                    span=word,
                )
            )
    return findings

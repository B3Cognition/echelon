"""Lexicon completeness gate — computes C(A).

A required slot is "filled" only if its value is not a leftover template
placeholder. Authors (human or LLM) routinely emit a block skeleton with
``<observable result>`` style angle-bracket placeholders still in place; those
parse fine as TEXT but are not actually filled. C(A) = filled / total.
"""

from __future__ import annotations

import re

from .linter import Finding

_PLACEHOLDER_RE = re.compile(r"<[^>\n]+>")


def placeholder_findings(text: str) -> list[Finding]:
    """Flag every value line still holding an angle-bracket placeholder."""
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _PLACEHOLDER_RE.finditer(line):
            findings.append(
                Finding(
                    code="incomplete-slot",
                    message=f"unfilled placeholder {match.group(0)!r}",
                    line=lineno,
                    span=match.group(0),
                )
            )
    return findings


def completeness(text: str) -> float:
    """C(A): fraction of value lines that are filled (no placeholder).

    No value lines -> vacuously complete (1.0)."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return 1.0
    placeholder_lines = {f.line for f in placeholder_findings(text)}
    return 1.0 - len(placeholder_lines) / len(lines)

"""Tier-2 structural gate — deterministic checks for Phase-2 free-markdown."""
from __future__ import annotations

import re

from .linter import Finding
from .manifest import _norm_heading

_HEADING = re.compile(r"^(#{1,6})\s+(?P<title>\S.*?)\s*$")


def _sections(text: str) -> dict[str, tuple[int, str]]:
    """Map normalized H2 heading -> (1-based line, body text until next heading)."""
    lines = text.splitlines()
    out: dict[str, tuple[int, str]] = {}
    i = 0
    while i < len(lines):
        m = _HEADING.match(lines[i])
        if m and len(m.group(1)) == 2:
            title = _norm_heading(m.group("title"))
            body, j = [], i + 1
            while j < len(lines) and not _HEADING.match(lines[j]):
                body.append(lines[j])
                j += 1
            out[title] = (i + 1, "\n".join(body))
            i = j
        else:
            i += 1
    return out


def section_findings(text: str, required: list[str]) -> list[Finding]:
    """Flag each required H2 that is absent or has an empty body."""
    present = _sections(text)
    findings: list[Finding] = []
    for name in required:
        entry = present.get(name)
        if entry is None:
            findings.append(Finding("missing-section",
                                    f"required section {name!r} is absent", 0, name))
        elif not entry[1].strip():
            findings.append(Finding("missing-section",
                                    f"required section {name!r} is empty", entry[0], name))
    return findings

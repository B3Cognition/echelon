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


def verdict_findings(text: str, section: str, enum: list[str]) -> list[Finding]:
    """Flag missing-verdict when the named section carries no enum value.

    The decision must be machine-extractable: the section body must contain at
    least one enum token as a whole word (case-insensitive)."""
    entry = _sections(text).get(section)
    line = entry[0] if entry else 0
    body = entry[1] if entry else ""
    pattern = re.compile(r"\b(" + "|".join(re.escape(v) for v in enum) + r")\b", re.IGNORECASE)
    if pattern.search(body):
        return []
    return [Finding("missing-verdict",
                    f"section {section!r} carries no decision in {enum}", line, section)]


from .crossdoc import _spec_ids


def unresolved_ref_findings(text: str, id_pattern: str, spec_text: str) -> list[Finding]:
    """Flag <PREFIX>-<n> ids cited in text that do not exist in the spec.

    No spec (empty/unparseable) → no findings (nothing to resolve against)."""
    if not spec_text.strip():
        return []
    try:
        req_ids, _examples, ac_ids = _spec_ids(spec_text)
    except Exception:
        return []
    known = req_ids | ac_ids
    if not known:
        return []
    token = re.compile(r"\b(?:" + id_pattern + r")-\d+\b")
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in token.finditer(line):
            ref = m.group(0)
            if ref not in known:
                findings.append(Finding("unresolved-ref",
                                        f"reference {ref!r} matches no spec id", lineno, ref))
    return findings

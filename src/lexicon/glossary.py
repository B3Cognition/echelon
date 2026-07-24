"""Shared glossary parsing for every Lexicon validation path."""

from __future__ import annotations

import re
from pathlib import Path


_BOLD_TERM_RE = re.compile(r"\*\*([^*]+)\*\*")
_HEADING_TERM_RE = re.compile(r"^#{3,6}\s+(.+?)(?:\s+#+)?$")


def load_glossary_terms(path: Path | None) -> set[str]:
    """Return approved terms from plain lines, glossary headings, or bold text."""
    if path is None or not path.is_file():
        return set()

    terms: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = _HEADING_TERM_RE.match(line)
        if heading:
            terms.add(heading.group(1).strip())
            continue
        if line.startswith("#"):
            continue
        bold = _BOLD_TERM_RE.findall(line)
        if bold:
            terms.update(term.strip() for term in bold)
        else:
            terms.add(line)
    return terms

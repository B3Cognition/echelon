"""
md_parser.py — Shared Markdown extraction module for spec 017.

Implements the three extraction functions defined in contracts/ns003_interfaces.md §6.
This module is NOT a standalone CLI — it is imported by ns003_critic.py and ns003_agm.py.

Regex patterns reused from contradiction-scanner.py (cited per research.md Design
Integration Notes): _BOLD_KEY_RE, _KV_LINE_RE, _TABLE_ROW_RE.

Standard library only (re, typing). No external dependencies.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Regex patterns — reused from runtime/scripts/contradiction-scanner.py
# (cite: contradiction-scanner.py lines 99-101)
# ---------------------------------------------------------------------------

_BOLD_KEY_RE = re.compile(r"\*\*([^*]+)\*\*\s*[:：]\s*(.+)")
_KV_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 _/-]{1,40})\s*[:：]\s*(.+)$")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")

# Section header pattern: ## or ### level
_SECTION_HEADER_RE = re.compile(r"^#{2,3}\s+(.+)$")

# Table separator row (e.g. |---|---|) — skip these
_TABLE_SEP_RE = re.compile(r"^\|[-:| ]+\|$")

# Generic stop-keys from contradiction-scanner.py lines 115-142.
# These generate false positives across artifacts and are excluded from output.
_GENERIC_STOP_KEYS: frozenset[str] = frozenset({
    "statement",
    "description",
    "definition",
    "note",
    "notes",
    "source",
    "basis",
    "date",
    "agent",
    "mode",
    "author",
    "version",
    "example",
    "rationale",
    "implication",
    "evidence",
    "approach",
    "summary",
    "detail",
    "details",
    "comment",
    "verdict",
    "text",
    "type",
    "value",
    "result",
})


def _normalize_key(raw: str) -> str:
    """
    Normalize a raw key string to lowercase with underscores replacing spaces.
    Also strips leading/trailing whitespace.
    """
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


def _is_stop_key(normalized_key: str) -> bool:
    """Return True if the normalized key is in the generic stop-key list."""
    return normalized_key in _GENERIC_STOP_KEYS


def extract_kv_pairs(markdown_text: str) -> dict[str, str]:
    """
    Extract key-value assertions from Markdown text using three regex patterns
    from contradiction-scanner.py:
      - Bold-key pairs:  **Key**: value
      - KV lines:        Key: value  (at line start)
      - Table rows:      | key | value |  (two-column tables only)

    Returns a dict mapping normalized key (lowercase, underscores replace spaces)
    to value string. Generic stop-keys (_GENERIC_STOP_KEYS) are excluded.

    Per ns003_interfaces.md §6: keys are normalized (lowercase, underscores).
    Per T-004 AC: stop-key exclusion applied before returning.
    """
    result: dict[str, str] = {}

    for line in markdown_text.splitlines():
        stripped = line.strip()

        # Bold-key pairs: **Key**: value  (highest specificity — check first)
        m = _BOLD_KEY_RE.search(stripped)
        if m:
            key = _normalize_key(m.group(1))
            val = m.group(2).strip()
            if val and not _is_stop_key(key):
                result[key] = val
            continue

        # Table rows: | key | value | (two-column only; skip separator rows)
        if _TABLE_SEP_RE.match(stripped):
            continue
        m = _TABLE_ROW_RE.match(stripped)
        if m:
            cols = [c.strip() for c in m.group(1).split("|")]
            # Accept exactly two-column rows
            if len(cols) == 2 and cols[0] and cols[1]:
                key = _normalize_key(cols[0])
                val = cols[1].strip()
                if val and not _is_stop_key(key) and key not in result:
                    result[key] = val
            continue

        # KV lines: Key: value (at line start, no leading whitespace for the key)
        m = _KV_LINE_RE.match(stripped)
        if m:
            key = _normalize_key(m.group(1))
            val = m.group(2).strip()
            if val and not _is_stop_key(key) and key not in result:
                result[key] = val

    return result


def extract_section_headers(markdown_text: str) -> list[str]:
    """
    Extract ## and ### level section header names from Markdown text.

    Returns a list of header strings (without # characters), in document order.
    Per ns003_interfaces.md §6 contract.
    """
    headers: list[str] = []
    for line in markdown_text.splitlines():
        m = _SECTION_HEADER_RE.match(line.strip())
        if m:
            headers.append(m.group(1).strip())
    return headers


def compute_prose_ratio(markdown_text: str) -> float:
    """
    Compute the ratio of prose characters to total characters in Markdown text.

    Prose characters are those NOT in:
      - Section headers (## / ###)
      - Table rows (| ... |)
      - Bold-key pairs (**Key**: value)
      - KV lines (Key: value at line start)
      - Blank lines

    Returns a float in [0.0, 1.0]. Returns 0.0 for empty input.
    Per ns003_interfaces.md §6 and T-004 AC.
    """
    if not markdown_text:
        return 0.0

    total_chars = 0
    prose_chars = 0

    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue  # skip blank lines for ratio calculation

        line_len = len(stripped)
        total_chars += line_len

        # Classify line as structured (non-prose) or prose
        is_structured = False

        # Section header
        if _SECTION_HEADER_RE.match(stripped):
            is_structured = True
        # Table separator
        elif _TABLE_SEP_RE.match(stripped):
            is_structured = True
        # Table row
        elif _TABLE_ROW_RE.match(stripped):
            is_structured = True
        # Bold-key pair
        elif _BOLD_KEY_RE.search(stripped):
            is_structured = True
        # KV line
        elif _KV_LINE_RE.match(stripped):
            is_structured = True

        if not is_structured:
            prose_chars += line_len

    if total_chars == 0:
        return 0.0

    ratio = prose_chars / total_chars
    # Clamp to [0.0, 1.0] for safety
    return max(0.0, min(1.0, ratio))

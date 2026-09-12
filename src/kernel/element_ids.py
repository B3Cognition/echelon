"""Shared formatting and ordering for numeric element identifiers."""

from __future__ import annotations

import re


_NUMERIC_ELEMENT_ID_RE = re.compile(r"(AC|FR|NFR|ISS|U|A|T)-(\d+)\Z")


def format_element_id(prefix: str, ordinal: int) -> str:
    """Format a positive ordinal with a six-digit minimum display width."""
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Z]+", prefix):
        raise ValueError("invalid element prefix")
    if type(ordinal) is not int or ordinal <= 0:
        raise ValueError("ordinal must be a positive integer")
    return f"{prefix}-{ordinal:06d}"


def element_id_sort_key(value: str) -> tuple[str, int, int, str]:
    """Return a numeric key for known labels and a deterministic opaque key."""
    match = _NUMERIC_ELEMENT_ID_RE.fullmatch(value)
    if match is not None:
        return (match.group(1), 0, int(match.group(2)), value)
    return (value.split("-", 1)[0], 1, 0, value)

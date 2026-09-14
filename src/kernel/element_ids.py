"""Shared formatting and ordering for numeric element identifiers."""

from __future__ import annotations

import re


_NUMERIC_ELEMENT_ID_RE = re.compile(r"(AC|FR|NFR|ISS|UI|II|U|A|T)-(\d+)\Z")


def decimal_to_int(value: str) -> int:
    """Parse decimal digits without Python's whole-string conversion ceiling.

    Padding and Unicode decimal digits remain valid for legacy ID sorting.
    Storage callers enforce their stricter canonical ASCII representation.
    """
    if not isinstance(value, str) or not value or not value.isdecimal():
        raise ValueError("value must contain decimal digits")
    number = 0
    for start in range(0, len(value), 9):
        chunk = value[start:start + 9]
        number = number * (10 ** len(chunk)) + int(chunk)
    return number


def int_to_decimal(value: int) -> str:
    """Format a nonnegative integer without changing global digit-limit settings."""
    if type(value) is not int or value < 0:
        raise ValueError("value must be a nonnegative integer")
    # Fewer than 2,000 bits fit even Python's lowest configurable limit (640 digits).
    if value.bit_length() < 2000:
        return str(value)
    chunks = []
    while value:
        value, remainder = divmod(value, 1_000_000_000)
        chunks.append(remainder)
    return str(chunks[-1]) + "".join(f"{part:09d}" for part in reversed(chunks[:-1]))


def format_element_id(prefix: str, ordinal: int) -> str:
    """Format a positive ordinal with a six-digit minimum display width."""
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Z]+", prefix):
        raise ValueError("invalid element prefix")
    if type(ordinal) is not int or ordinal <= 0:
        raise ValueError("ordinal must be a positive integer")
    return f"{prefix}-{int_to_decimal(ordinal).zfill(6)}"


def element_id_sort_key(value: str) -> tuple[str, int, int, str]:
    """Return a numeric key for known labels and a deterministic opaque key."""
    match = _NUMERIC_ELEMENT_ID_RE.fullmatch(value)
    if match is not None:
        return (match.group(1), 0, decimal_to_int(match.group(2)), value)
    return (value.split("-", 1)[0], 1, 0, value)

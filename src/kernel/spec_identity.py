"""Shared normalization for user-facing spec identities."""

from __future__ import annotations

import re


_NUMERIC_PREFIX = re.compile(r"^(?P<number>\d+)-.+$")


def spec_identity_aliases(value: str) -> tuple[str, ...]:
    """Return an identity followed by its numeric compatibility alias."""
    match = _NUMERIC_PREFIX.fullmatch(value)
    if match is None:
        return (value,)
    return (value, match.group("number"))

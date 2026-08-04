"""Small strict-JSON decoder helpers for controller-owned ledgers."""

from __future__ import annotations

import json
from typing import Any


def _object_without_duplicate_members(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def loads_strict_json(value: str) -> object:
    return json.loads(value, object_pairs_hook=_object_without_duplicate_members)

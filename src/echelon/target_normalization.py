"""Canonical target-reference normalization shared by retarget boundaries."""

from __future__ import annotations

import posixpath
import re
from typing import Iterable


def normalize_target_reference(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    collapsed = re.sub(r"/+", "/", raw)
    normalized = posixpath.normpath(collapsed)
    return "" if normalized == "/" else normalized


def normalize_target_set(values: Iterable[object]) -> tuple[str, ...]:
    ordered: list[str] = []
    for value in values:
        target = normalize_target_reference(value)
        if target and target not in ordered:
            ordered.append(target)
    return tuple(ordered)

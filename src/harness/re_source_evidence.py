"""Recognition of source path-and-line references in RE artifacts."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path


SOURCE_REFERENCE = re.compile(
    r"`(?P<path>[^`\n:]+):(?P<start>\d+)(?:[-–—](?P<end>\d+))?"
    r"(?P<additional>(?:\s*,\s*\d+(?:[-–—]\d+)?)*?)`"
)
_ADDITIONAL_RANGE = re.compile(r"(?P<start>\d+)(?:[-–—](?P<end>\d+))?")

_KNOWN_EXTENSIONLESS_SOURCE_FILES = {
    "dockerfile",
    "gemfile",
    "license",
    "makefile",
    "procfile",
    "readme",
}


def is_source_reference_path(raw_path: str) -> bool:
    """Distinguish file-like paths from host/port and other prose literals."""
    normalized = raw_path.strip()
    if not normalized:
        return False
    path = Path(normalized)
    return (
        "/" in normalized
        or bool(path.suffix)
        or path.name.casefold() in _KNOWN_EXTENSIONLESS_SOURCE_FILES
    )


def source_reference_matches(text: str) -> Iterator[re.Match[str]]:
    for match in SOURCE_REFERENCE.finditer(text):
        if is_source_reference_path(match.group("path")):
            yield match


def source_reference_ranges(match: re.Match[str]) -> tuple[tuple[int, int], ...]:
    """Return every line range encoded by one source-reference match."""
    start = int(match.group("start"))
    ranges = [(start, int(match.group("end") or start))]
    ranges.extend(
        (
            int(item.group("start")),
            int(item.group("end") or item.group("start")),
        )
        for item in _ADDITIONAL_RANGE.finditer(match.group("additional") or "")
    )
    return tuple(ranges)


def contains_source_reference(text: str) -> bool:
    return next(source_reference_matches(text), None) is not None


def source_references(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in source_reference_matches(text))

"""Shared CodeGraph release contract for generated and historical evidence."""

from __future__ import annotations


CURRENT_CODEGRAPH_VERSION = "1.6.0"
SUPPORTED_CODEGRAPH_VERSIONS = frozenset({"1.4.1", CURRENT_CODEGRAPH_VERSION})


def is_supported_codegraph_version(value: object) -> bool:
    return isinstance(value, str) and value in SUPPORTED_CODEGRAPH_VERSIONS


__all__ = (
    "CURRENT_CODEGRAPH_VERSION",
    "SUPPORTED_CODEGRAPH_VERSIONS",
    "is_supported_codegraph_version",
)

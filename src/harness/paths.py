"""Canonical path constants for echelon harness runtime artifacts.

All runtime artifacts live under .specify/extensions/echelon/harness/ so that
ownership is unambiguous — the echelon extension owns this subtree, not the
top-level .specify/harness/ namespace.
"""

from __future__ import annotations

from pathlib import Path

HARNESS_REL_BASE = ".specify/extensions/echelon/harness"
MIRROR_REL_PATH = f"{HARNESS_REL_BASE}/mirror.git"


def harness_dir(base: Path) -> Path:
    """Return the echelon harness directory for a given project root."""
    return base / HARNESS_REL_BASE

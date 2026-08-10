"""Canonical project constitution location and compatibility migration."""

from __future__ import annotations

import shutil
from pathlib import Path


_CANONICAL_RELATIVE_PATH = Path(".echelon") / "constitution.md"
_LEGACY_RELATIVE_PATH = Path(".specify") / "memory" / "constitution.md"


def canonical_constitution_path(project_root: Path) -> Path:
    """Resolve the Echelon-owned constitution path."""
    return project_root.resolve() / _CANONICAL_RELATIVE_PATH


def migrate_legacy_constitution(project_root: Path) -> Path | None:
    """Copy a legacy constitution into Echelon's canonical location if needed."""
    root = project_root.resolve()
    canonical = root / _CANONICAL_RELATIVE_PATH
    if canonical.exists():
        return canonical
    legacy = root / _LEGACY_RELATIVE_PATH
    if not legacy.is_file():
        return None
    canonical.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, canonical)
    return canonical

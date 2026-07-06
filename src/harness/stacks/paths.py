from __future__ import annotations

from pathlib import Path


def find_stack_extension_root(base_dir: Path) -> Path:
    """Return the extension root that owns bundled stack definitions."""
    source_root = Path(__file__).resolve().parents[3] / "extension"
    for candidate in (
        base_dir / "extension",
        base_dir / ".specify" / "extensions" / "echelon",
        source_root,
    ):
        if (candidate / "stacks").is_dir():
            return candidate
    return base_dir / "extension"

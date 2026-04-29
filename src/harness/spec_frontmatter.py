"""Spec frontmatter: parse/write YAML front-matter in spec markdown files,
and walk-up spec directory discovery."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(?:\n|$)", re.DOTALL)


def _find_spec_md(spec_dir: Path) -> Optional[Path]:
    """Return first .md file in spec_dir (sorted), or None."""
    for p in sorted(spec_dir.glob("*.md")):
        return p
    return None


def read_frontmatter(spec_dir: Path) -> Dict[str, Any]:
    """Parse YAML frontmatter from spec_dir's first markdown file.

    Returns empty dict when no frontmatter block is present or parsing fails.
    """
    md = _find_spec_md(spec_dir)
    if md is None:
        return {}
    text = md.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def write_targets(spec_dir: Path, targets: List[str]) -> Path:
    """Write (or replace) the ``targets:`` list in spec_dir's frontmatter.

    Creates a frontmatter block if none exists. Returns the modified file path.
    Preserves all other frontmatter keys.
    """
    md = _find_spec_md(spec_dir)
    if md is None:
        raise FileNotFoundError(f"No .md file found in {spec_dir}")

    text = md.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text

    try:
        data: Dict[str, Any] = yaml.safe_load(m.group(1)) if m else {}
        data = data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        data = {}

    data["targets"] = targets
    front = yaml.dump(data, default_flow_style=False, sort_keys=False,
                      allow_unicode=True).rstrip()
    md.write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")
    return md


def find_spec_dir(spec_id: str, start_dir: Path) -> Optional[Path]:
    """Walk up from start_dir to find specs/{spec_id}-* directory.

    Stops before walking into a parent directory that contains .git (git
    boundary), or at the filesystem root. Local matches (closer to start_dir)
    take precedence over parent matches.

    Args:
        spec_id: Spec numeric prefix, e.g. "024".
        start_dir: Directory to start searching from.

    Returns:
        First alphabetically-sorted matching spec directory, or None.
    """
    current = start_dir.resolve()
    while True:
        matches = sorted(current.glob(f"specs/{spec_id}-*"))
        if matches:
            return matches[0]
        parent = current.parent
        if parent == current:          # filesystem root
            break
        if (parent / ".git").exists(): # would cross into a git repo boundary
            break
        current = parent
    return None

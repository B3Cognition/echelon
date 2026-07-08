"""Spec frontmatter: parse/write YAML front-matter in spec markdown files,
and walk-up spec directory discovery."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(?:\n|$)", re.DOTALL)
TARGETS_FILENAME = "targets.yml"


def _target_id_from_path(path: str) -> str:
    normalized = str(path).strip().rstrip("/")
    if not normalized or normalized == ".":
        return "workspace"
    return Path(normalized).name or "target"


def _normalize_target_entry(spec_dir: Path, item: Any, index: int) -> Dict[str, Any] | None:
    if isinstance(item, str):
        path = item.strip()
        if not path:
            return None
        return {
            "id": _target_id_from_path(path),
            "path": path,
            "role": "primary" if index == 0 else "secondary",
            "branch": spec_dir.name,
        }

    if not isinstance(item, dict):
        return None

    raw_path = item.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    path = raw_path.strip()
    entry: Dict[str, Any] = dict(item)
    entry["path"] = path
    entry.setdefault("id", _target_id_from_path(path))
    entry.setdefault("role", "primary" if index == 0 else "secondary")
    entry.setdefault("branch", spec_dir.name)
    return entry


def _read_targets_file_entries(spec_dir: Path) -> List[Dict[str, Any]]:
    targets_file = spec_dir / TARGETS_FILENAME
    if not targets_file.exists():
        return []
    try:
        data = yaml.safe_load(targets_file.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    raw_targets = data.get("targets")
    if not isinstance(raw_targets, list):
        return []
    entries: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_targets):
        entry = _normalize_target_entry(spec_dir, item, index)
        if entry is not None:
            entries.append(entry)
    return entries


def _read_frontmatter_only(spec_dir: Path) -> Dict[str, Any]:
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


def read_target_entries(spec_dir: Path) -> List[Dict[str, Any]]:
    """Read canonical target entries from targets.yml, falling back to spec.md frontmatter."""
    entries = _read_targets_file_entries(spec_dir)
    if entries:
        return entries

    frontmatter = _read_frontmatter_only(spec_dir)
    raw_targets = frontmatter.get("targets")
    if not isinstance(raw_targets, list):
        return []
    fallback_entries: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_targets):
        entry = _normalize_target_entry(spec_dir, item, index)
        if entry is not None:
            fallback_entries.append(entry)
    return fallback_entries


def read_targets(spec_dir: Path) -> List[str]:
    """Read target paths from canonical targets.yml, falling back to spec.md frontmatter."""
    return [str(entry["path"]) for entry in read_target_entries(spec_dir)]


def _find_spec_md(spec_dir: Path) -> Optional[Path]:
    """Return spec.md if present, otherwise the first .md file (sorted), or None."""
    spec_md = spec_dir / "spec.md"
    if spec_md.exists():
        return spec_md
    for p in sorted(spec_dir.glob("*.md")):
        return p
    return None


def read_frontmatter(spec_dir: Path) -> Dict[str, Any]:
    """Parse YAML frontmatter from spec_dir's first markdown file.

    Returns empty dict when no frontmatter block is present or parsing fails.
    For compatibility, canonical targets.yml entries are exposed as
    ``data["targets"]`` when spec.md no longer carries target paths inline.
    """
    data = _read_frontmatter_only(spec_dir)
    targets = read_targets(spec_dir)
    if targets and "targets" not in data:
        data["targets"] = targets
    if targets and "targets_file" not in data:
        data["targets_file"] = TARGETS_FILENAME
    return data


def write_targets(spec_dir: Path, targets: List[str]) -> Path:
    """Write (or replace) canonical target entries in spec_dir/targets.yml.

    Creates a frontmatter block if none exists so spec.md points to
    ``targets_file: targets.yml``. Returns the modified targets.yml path.
    Preserves all other frontmatter keys and removes legacy inline targets.
    """
    md = _find_spec_md(spec_dir)
    if md is None:
        raise FileNotFoundError(f"No .md file found in {spec_dir}")

    existing_by_path = {
        str(entry["path"]): entry
        for entry in _read_targets_file_entries(spec_dir)
        if isinstance(entry.get("path"), str)
    }
    entries: List[Dict[str, Any]] = []
    for index, target in enumerate(targets):
        path = str(target).strip()
        if not path:
            continue
        entry = dict(existing_by_path.get(path) or {})
        entry["id"] = str(entry.get("id") or _target_id_from_path(path))
        entry["path"] = path
        entry["role"] = "primary" if index == 0 else str(entry.get("role") or "secondary")
        entry["branch"] = str(entry.get("branch") or spec_dir.name)
        entries.append(entry)

    targets_path = spec_dir / TARGETS_FILENAME
    targets_data = {
        "schema_version": 1,
        "targets": entries,
    }
    targets_path.write_text(
        yaml.dump(
            targets_data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    text = md.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text

    try:
        data: Dict[str, Any] = yaml.safe_load(m.group(1)) if m else {}
        data = data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        logger.warning("write_targets: corrupt YAML frontmatter in %s — dropping existing keys", md)
        data = {}

    data.pop("targets", None)
    data["targets_file"] = TARGETS_FILENAME
    front = yaml.dump(data, default_flow_style=False, sort_keys=False,
                      allow_unicode=True).rstrip()
    md.write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")
    return targets_path


def write_target_delivery(spec_dir: Path, target_path: str, delivery: Dict[str, Any]) -> Path:
    """Merge delivery metadata for one target entry in targets.yml."""
    entries = read_target_entries(spec_dir)
    if not entries:
        raise ValueError(f"No targets configured in {spec_dir}")

    target_path = str(target_path).strip()
    changed = False
    for entry in entries:
        if str(entry.get("path") or "") != target_path:
            continue
        existing = entry.get("delivery")
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(delivery)
        entry["delivery"] = merged
        changed = True
        break

    if not changed:
        raise ValueError(f"Target {target_path!r} not configured in {spec_dir}")

    targets_path = spec_dir / TARGETS_FILENAME
    targets_path.write_text(
        yaml.dump(
            {"schema_version": 1, "targets": entries},
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return targets_path


def write_status(spec_dir: Path, status: str) -> Path:
    """Write (or replace) the ``status:`` field in spec_dir's frontmatter and
    the ``**Status**: ...`` display line in the document body (if present).

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
        logger.warning("write_status: corrupt YAML frontmatter in %s — dropping existing keys", md)
        data = {}

    data["status"] = status
    front = yaml.dump(data, default_flow_style=False, sort_keys=False,
                      allow_unicode=True).rstrip()

    # Keep the human-readable **Status**: line in the body in sync when present.
    body = re.sub(r'(\*\*Status\*\*:\s*).*', rf'\g<1>{status}', body, count=1)

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
        exact = current / "specs" / spec_id
        if exact.is_dir():
            return exact
        matches = sorted(current.glob(f"specs/{spec_id}-*"))
        if matches:
            return matches[0]
        parent = current.parent
        if parent == current:          # filesystem root
            break
        # Check parent (not current) so we search the current dir before stopping at its git boundary
        if (parent / ".git").exists(): # would cross into a git repo boundary
            break
        current = parent
    return None

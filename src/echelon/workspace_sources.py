from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from echelon.workspace_model import discover_sources_directory_roots
from harness.config import CANONICAL_CONFIG_PATH


@dataclass(frozen=True)
class WorkspaceSourcesSyncResult:
    config_path: Path
    dry_run: bool
    discovered: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)


def ensure_source_config_entry(root: Path, source_path: str) -> bool:
    workspace_root = root.resolve()
    config_path = workspace_root / CANONICAL_CONFIG_PATH
    raw = _read_config(config_path)
    entries = raw.get("sources") if isinstance(raw.get("sources"), list) else []
    normalized_path = _normalize_source_path(workspace_root, source_path)
    source_id = _source_id_from_path(normalized_path)

    for entry in entries:
        if _source_path(entry) == normalized_path or _source_id(entry) == source_id:
            return False

    raw.setdefault("workspace", {"git_role": "orchestration"})
    raw["sources"] = [*entries, {"id": source_id, "path": normalized_path}]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )
    return True


def sync_sources_config(root: Path, *, write: bool) -> WorkspaceSourcesSyncResult:
    workspace_root = root.resolve()
    config_path = workspace_root / CANONICAL_CONFIG_PATH
    raw = _read_config(config_path)
    current_sources = raw.get("sources") if isinstance(raw.get("sources"), list) else []
    current_entries = [item for item in current_sources if _source_path(item)]

    current_canonical_by_id = {
        str(_source_id(item)): str(_source_path(item))
        for item in current_entries
        if _is_canonical_sources_path(str(_source_path(item)))
    }
    preserved_entries = [
        item
        for item in current_entries
        if not _is_canonical_sources_path(str(_source_path(item)))
    ]

    discovered_roots = discover_sources_directory_roots(workspace_root)
    discovered_entries = [
        {"id": source.id, "path": source.path}
        for source in discovered_roots
    ]
    discovered_by_id = {source.id: source.path for source in discovered_roots}

    added = tuple(
        source_id
        for source_id in discovered_by_id
        if current_canonical_by_id.get(source_id) != discovered_by_id[source_id]
    )
    removed = tuple(
        source_id
        for source_id in current_canonical_by_id
        if source_id not in discovered_by_id
    )
    unchanged = tuple(
        source_id
        for source_id in discovered_by_id
        if current_canonical_by_id.get(source_id) == discovered_by_id[source_id]
    )

    if write:
        raw.setdefault("workspace", {"git_role": "orchestration"})
        raw["sources"] = preserved_entries + discovered_entries
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(raw, sort_keys=False),
            encoding="utf-8",
        )

    return WorkspaceSourcesSyncResult(
        config_path=config_path,
        dry_run=not write,
        discovered=tuple(source.id for source in discovered_roots),
        added=added,
        removed=removed,
        unchanged=unchanged,
    )


def _read_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def _source_id(item: Any) -> str:
    if isinstance(item, str):
        return _source_id_from_path(item)
    if isinstance(item, dict):
        path = str(item.get("path") or item.get("repo") or "").strip()
        explicit_id = str(item.get("id") or "").strip()
        return explicit_id or _source_id_from_path(path)
    return ""


def _source_path(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("path") or item.get("repo") or "").strip()
    return ""


def _is_canonical_sources_path(path: str) -> bool:
    stripped = path.strip().strip("/")
    return stripped.startswith("sources/")


def _source_id_from_path(path: str) -> str:
    stripped = path.strip()
    if _is_canonical_sources_path(stripped):
        return Path(stripped).name
    return stripped


def _normalize_source_path(workspace_root: Path, source_path: str) -> str:
    raw = source_path.strip()
    path = Path(raw).expanduser()
    if path.is_absolute():
        try:
            return path.resolve().relative_to(workspace_root).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()

"""One-way import of valid legacy reverse-engineering cache entries."""

from __future__ import annotations

import json
import re
import shutil
import warnings
from pathlib import Path

from harness.re_registry import ensure_re_layout


_SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_FINGERPRINT = re.compile(r"^[A-Fa-f0-9]{32,128}$")


def import_legacy_re_cache(workspace_root: Path) -> tuple[Path, ...]:
    """Copy valid absent legacy cache entries into the workspace RE cache."""
    root = workspace_root.resolve()
    legacy_sources = root / ".echelon" / "cache" / "re" / "sources"
    if not legacy_sources.is_dir():
        return ()

    destination_root = ensure_re_layout(root).cache / "sources"
    imported: list[Path] = []
    for source_dir in sorted(path for path in legacy_sources.iterdir() if path.is_dir()):
        source_id = source_dir.name
        for entry in sorted(path for path in source_dir.iterdir() if path.is_dir()):
            fingerprint = entry.name
            if not _legacy_entry_is_valid(entry, source_id, fingerprint):
                warnings.warn(
                    f"Skipping invalid legacy RE cache entry: {entry}",
                    UserWarning,
                    stacklevel=2,
                )
                continue
            destination = destination_root / source_id / fingerprint
            if destination.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(entry, destination)
            imported.append(destination)
    return tuple(imported)


def _legacy_entry_is_valid(entry: Path, source_id: str, fingerprint: str) -> bool:
    if not _SAFE_SOURCE_ID.fullmatch(source_id):
        return False
    if not _SAFE_FINGERPRINT.fullmatch(fingerprint):
        return False
    if not (entry / "analysis.json").is_file():
        return False

    manifest_path = (
        entry / "manifest.json"
        if (entry / "manifest.json").is_file()
        else entry / "cache-manifest.json"
    )
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return False
    if data.get("source_id") != source_id:
        return False

    raw_fingerprint = data.get("fingerprint")
    if isinstance(raw_fingerprint, dict):
        value = raw_fingerprint.get("value")
        profile_hash = raw_fingerprint.get("profile_hash")
    else:
        value = raw_fingerprint
        profile_hash = data.get("profile_hash")
    return value == fingerprint and isinstance(profile_hash, str) and bool(
        profile_hash.strip()
    )

"""Persistent source-scoped reverse-engineering cache helpers."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.re_fingerprint import SourceFingerprint


RE_CACHE_SCHEMA_VERSION = 1
_SAFE_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class ReCacheRecord:
    """Manifest metadata for one cached source RE artifact set."""

    source_id: str
    source_path: str
    fingerprint: SourceFingerprint
    profile: dict[str, Any]

    def to_json_dict(self, artifacts: list[str]) -> dict[str, Any]:
        return {
            "schema_version": RE_CACHE_SCHEMA_VERSION,
            "source_id": self.source_id,
            "source_path": self.source_path,
            "fingerprint": {
                "value": self.fingerprint.value,
                "kind": self.fingerprint.kind,
                "dirty": self.fingerprint.dirty,
                "profile_hash": self.fingerprint.profile_hash,
                "git_head": self.fingerprint.git_head,
            },
            "profile": self.profile,
            "artifacts": artifacts,
        }


class ReCacheStore:
    """Stores per-source reverse-engineering artifacts by source fingerprint."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.root = self.workspace_root / "re" / ".cache"
        self.legacy_root = self.workspace_root / ".echelon" / "cache" / "re"

    def entry_path(self, source_id: str, fingerprint: SourceFingerprint) -> Path:
        return cache_source_dir(self.root, source_id, fingerprint)

    def is_hit(
        self,
        source_id: str,
        fingerprint: SourceFingerprint,
        *,
        required_files: tuple[str, ...] = (),
    ) -> bool:
        entry = self.entry_path(source_id, fingerprint)
        if not _manifest_matches(entry, source_id, fingerprint):
            return False
        return all((entry / required).is_file() for required in required_files)

    def write_entry(
        self,
        source_id: str,
        fingerprint: SourceFingerprint,
        artifacts_dir: Path,
    ) -> Path:
        if not artifacts_dir.is_dir():
            raise ValueError(f"artifacts dir does not exist: {artifacts_dir}")

        entry = self.entry_path(source_id, fingerprint)
        temp = entry.parent / f".{entry.name}.tmp-{uuid.uuid4().hex}"
        temp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(artifacts_dir, temp)
        manifest = {
            "schema_version": RE_CACHE_SCHEMA_VERSION,
            "source_id": source_id,
            "fingerprint": fingerprint.value,
            "kind": fingerprint.kind,
            "dirty": fingerprint.dirty,
            "profile_hash": fingerprint.profile_hash,
            "git_head": fingerprint.git_head,
        }
        _write_json_atomic(temp / "cache-manifest.json", manifest)
        if entry.exists():
            shutil.rmtree(entry)
        temp.replace(entry)
        return entry


def cache_source_dir(cache_root: Path, source_id: str, fingerprint: SourceFingerprint) -> Path:
    """Return the cache directory for one source/fingerprint pair."""
    return cache_root / "sources" / _safe_source_id(source_id) / fingerprint.value


def cache_hit(cache_root: Path, source_id: str, fingerprint: SourceFingerprint) -> bool:
    """Return True when the source cache exists and has required artifacts."""
    cache_dir = cache_source_dir(cache_root, source_id, fingerprint)
    return _manifest_matches(cache_dir, source_id, fingerprint) and (cache_dir / "analysis.json").is_file()


def write_cache_record(
    source_output_dir: Path,
    cache_dir: Path,
    record: ReCacheRecord,
) -> Path:
    """Copy source RE artifacts into cache and write an atomic manifest."""
    if not (source_output_dir / "analysis.json").is_file():
        raise FileNotFoundError(f"required RE artifact missing: {source_output_dir / 'analysis.json'}")

    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    for source in _iter_files(source_output_dir):
        relative = source.relative_to(source_output_dir)
        if relative.as_posix() in {"manifest.json", "cache-manifest.json"}:
            continue
        target = cache_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    artifacts = [
        path.relative_to(cache_dir).as_posix()
        for path in _iter_files(cache_dir)
        if path.name not in {"manifest.json", "cache-manifest.json"}
    ]
    manifest = record.to_json_dict(sorted(artifacts))
    _write_json_atomic(cache_dir / "manifest.json", manifest)
    _write_json_atomic(
        cache_dir / "cache-manifest.json",
        {
            "schema_version": RE_CACHE_SCHEMA_VERSION,
            "source_id": record.source_id,
            "fingerprint": record.fingerprint.value,
            "kind": record.fingerprint.kind,
            "dirty": record.fingerprint.dirty,
            "profile_hash": record.fingerprint.profile_hash,
            "git_head": record.fingerprint.git_head,
        },
    )
    return cache_dir


def copy_cached_source(cache_dir: Path, run_source_dir: Path) -> Path:
    """Copy cached artifacts into a run-local source directory."""
    if not _has_cache_manifest(cache_dir):
        raise FileNotFoundError(f"cache manifest missing: {cache_dir / 'manifest.json'}")
    if run_source_dir.exists():
        shutil.rmtree(run_source_dir)
    run_source_dir.mkdir(parents=True, exist_ok=True)
    for source in _iter_files(cache_dir):
        relative = source.relative_to(cache_dir)
        target = run_source_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return run_source_dir


def _safe_source_id(source_id: str) -> str:
    if not source_id or not _SAFE_SOURCE_ID_RE.fullmatch(source_id):
        raise ValueError(f"unsafe source id: {source_id!r}")
    return source_id


def _has_cache_manifest(cache_dir: Path) -> bool:
    return (cache_dir / "manifest.json").is_file() or (cache_dir / "cache-manifest.json").is_file()


def _manifest_matches(cache_dir: Path, source_id: str, fingerprint: SourceFingerprint) -> bool:
    manifest_path = cache_dir / "manifest.json"
    legacy_manifest_path = cache_dir / "cache-manifest.json"
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        return (
            data.get("schema_version") == RE_CACHE_SCHEMA_VERSION
            and data.get("source_id") == source_id
            and data.get("fingerprint", {}).get("value") == fingerprint.value
            and data.get("fingerprint", {}).get("profile_hash") == fingerprint.profile_hash
        )
    if legacy_manifest_path.is_file():
        try:
            data = json.loads(legacy_manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        return (
            data.get("schema_version") == RE_CACHE_SCHEMA_VERSION
            and data.get("source_id") == source_id
            and data.get("fingerprint") == fingerprint.value
            and data.get("profile_hash") == fingerprint.profile_hash
        )
    return False


def _iter_files(root: Path) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp).replace(path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

"""Persistent reverse-engineering cache storage primitives."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

from harness.re_fingerprint import SourceFingerprint

_SAFE_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class ReCacheStore:
    """Stores per-source reverse-engineering artifacts by source fingerprint."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.root = self.workspace_root / ".echelon" / "cache" / "re"

    def entry_path(self, source_id: str, fingerprint: SourceFingerprint) -> Path:
        safe_source_id = _safe_source_id(source_id)
        return self.root / "sources" / safe_source_id / fingerprint.value

    def is_hit(
        self,
        source_id: str,
        fingerprint: SourceFingerprint,
        *,
        required_files: tuple[str, ...] = (),
    ) -> bool:
        entry = self.entry_path(source_id, fingerprint)
        manifest = entry / "cache-manifest.json"
        if not manifest.is_file():
            return False
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        if data.get("fingerprint") != fingerprint.value:
            return False
        if data.get("profile_hash") != fingerprint.profile_hash:
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
        (temp / "cache-manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_id": source_id,
                    "fingerprint": fingerprint.value,
                    "kind": fingerprint.kind,
                    "dirty": fingerprint.dirty,
                    "profile_hash": fingerprint.profile_hash,
                    "git_head": fingerprint.git_head,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if entry.exists():
            shutil.rmtree(entry)
        temp.replace(entry)
        return entry


def _safe_source_id(source_id: str) -> str:
    if not source_id or not _SAFE_SOURCE_ID_RE.fullmatch(source_id):
        raise ValueError(f"unsafe source id: {source_id!r}")
    return source_id

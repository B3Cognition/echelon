"""Durable, immutable RE v2 run-manifest storage."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import RE_V2_ENGINE, RE_V2_PROTOCOL, ReV2ModelError
from .canonical import canonical_json_bytes
from .model import RunManifest


class ReV2RunStoreError(RuntimeError):
    """Raised when an RE v2 run store is unsafe, incomplete, or unsupported."""


@dataclass(frozen=True, slots=True)
class ReV2Paths:
    """The authoritative v2 paths below one RE run directory."""

    root: Path
    manifest: Path
    events: Path
    projection: Path
    ledger: Path
    candidates: Path

    @classmethod
    def for_run(cls, run_dir: Path) -> "ReV2Paths":
        _reject_symlinked_run_path(run_dir)
        root = run_dir.resolve() / "v2"
        if root.is_symlink():
            raise ReV2RunStoreError(f"unsafe symlinked v2 run store: {root}")
        return cls(
            root=root,
            manifest=root / "run.json",
            events=root / "events.jsonl",
            projection=root / "projection.json",
            ledger=root / "ledger.jsonl",
            candidates=root / "candidates",
        )


def create_run_store(run_dir: Path, manifest: RunManifest) -> ReV2Paths:
    """Pin *manifest* exactly once under ``run_dir/v2/run.json``."""
    if manifest.run_id != run_dir.name:
        raise ReV2RunStoreError(
            f"manifest run_id {manifest.run_id!r} does not match run directory {run_dir.name!r}"
        )
    _validate_supported_manifest(manifest)
    _ensure_run_directory(run_dir)
    paths = ReV2Paths.for_run(run_dir)
    if paths.root.exists():
        if not paths.root.is_dir():
            raise ReV2RunStoreError(f"v2 run store is not a directory: {paths.root}")
        if paths.manifest.exists() or paths.manifest.is_symlink():
            raise ReV2RunStoreError(f"immutable v2 run manifest already exists: {paths.manifest}")
        raise ReV2RunStoreError("incomplete v2 run store has no immutable manifest")

    try:
        paths.root.mkdir(mode=0o700)
    except OSError as exc:
        raise ReV2RunStoreError(f"cannot create v2 run store {paths.root}: {exc}") from exc
    _fsync_directory(run_dir.resolve())

    payload = canonical_json_bytes(manifest.to_json_dict())
    temp_path: Path | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(prefix=".run.json.", suffix=".tmp", dir=paths.root)
        temp_path = Path(temporary_name)
        try:
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        if paths.manifest.exists() or paths.manifest.is_symlink():
            raise ReV2RunStoreError(f"immutable v2 run manifest already exists: {paths.manifest}")
        os.replace(temp_path, paths.manifest)
        temp_path = None
        _fsync_directory(paths.root)
    except ReV2RunStoreError:
        raise
    except OSError as exc:
        raise ReV2RunStoreError(f"cannot persist immutable v2 run manifest: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return paths


def load_run_manifest(run_dir: Path) -> RunManifest:
    """Load and validate the authoritative immutable v2 manifest."""
    paths = ReV2Paths.for_run(run_dir)
    if not paths.root.exists() or not paths.root.is_dir():
        raise ReV2RunStoreError(f"v2 run store does not exist: {paths.root}")
    if paths.manifest.is_symlink():
        raise ReV2RunStoreError(f"unsafe symlinked v2 run manifest: {paths.manifest}")
    if not paths.manifest.is_file():
        raise ReV2RunStoreError("incomplete v2 run store has no immutable manifest")
    try:
        payload = paths.manifest.read_bytes()
        raw = json.loads(payload)
        manifest = RunManifest.from_json_dict(raw)
    except (OSError, ValueError, ReV2ModelError) as exc:
        raise ReV2RunStoreError(f"unsupported or invalid immutable v2 run manifest: {exc}") from exc
    if manifest.run_id != run_dir.name:
        raise ReV2RunStoreError(
            f"manifest run_id {manifest.run_id!r} does not match run directory {run_dir.name!r}"
        )
    _validate_supported_manifest(manifest)
    if payload != canonical_json_bytes(manifest.to_json_dict()):
        raise ReV2RunStoreError("immutable v2 run manifest is not canonical JSON")
    return manifest


def detect_re_engine(run_dir: Path) -> Literal["v1", "v2"]:
    """Select v2 only from its immutable manifest, never mutable outer state."""
    paths = ReV2Paths.for_run(run_dir)
    if paths.root.exists() and not paths.manifest.exists():
        raise ReV2RunStoreError("incomplete v2 run store has no immutable manifest")
    if not paths.manifest.exists():
        return "v1"
    _validate_supported_manifest(load_run_manifest(run_dir))
    return "v2"


def _ensure_run_directory(run_dir: Path) -> None:
    _reject_symlinked_run_path(run_dir)
    if run_dir.exists():
        if not run_dir.is_dir():
            raise ReV2RunStoreError(f"RE run path is not a directory: {run_dir}")
        return
    try:
        run_dir.mkdir(parents=True, mode=0o700)
    except OSError as exc:
        raise ReV2RunStoreError(f"cannot create RE run directory {run_dir}: {exc}") from exc
    _fsync_directory(run_dir.parent.resolve())


def _reject_symlinked_run_path(run_dir: Path) -> None:
    if run_dir.is_symlink():
        raise ReV2RunStoreError(f"unsafe symlinked RE run directory: {run_dir}")
    if run_dir.exists() and not run_dir.is_dir():
        raise ReV2RunStoreError(f"RE run path is not a directory: {run_dir}")


def _validate_supported_manifest(manifest: RunManifest) -> None:
    if manifest.engine != RE_V2_ENGINE or manifest.engine_protocol_version != RE_V2_PROTOCOL:
        raise ReV2RunStoreError(
            "unsupported pinned RE engine/protocol "
            f"{manifest.engine!r}/{manifest.engine_protocol_version!r}"
        )


def _fsync_directory(path: Path) -> None:
    """Flush directory metadata when the platform permits directory fsync."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise OSError("short write while persisting immutable v2 run manifest")
        offset += written

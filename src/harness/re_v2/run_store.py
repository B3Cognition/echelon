"""Durable, immutable RE v2 run-manifest storage."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import RE_V2_ENGINE, RE_V2_SCHEMA_1_PROTOCOLS, ReV2ModelError
from .canonical import canonical_json_bytes
from .model import RE_V2_SCHEMA_2_PROTOCOLS, RE_V2_SCHEMA_3_PROTOCOLS, RunManifest
from .protocol_22.model import RunManifestV2
from .protocol_22.schema import Protocol22SchemaError, load_canonical_object
from .protocol_24.model import RunManifestV3


Manifest = RunManifest | RunManifestV2 | RunManifestV3


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
    objects: Path
    inputs: Path

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
            objects=root / "objects",
            inputs=root / "inputs",
        )


def create_run_store(run_dir: Path, manifest: RunManifest) -> ReV2Paths:
    """Pin *manifest* exactly once under ``run_dir/v2/run.json``."""
    if not isinstance(manifest, RunManifest):
        raise ReV2RunStoreError(
            "schema-2 manifests require protocol-2.2 manifest-last creation"
        )
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
    try:
        paths.objects.mkdir(mode=0o700)
    except OSError as exc:
        raise ReV2RunStoreError(
            f"cannot create run-local object store {paths.objects}: {exc}"
        ) from exc
    _fsync_directory(paths.root)

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
        # Linking within this directory is an atomic no-clobber publication:
        # unlike rename/replace, it cannot overwrite a competing creator.
        os.link(temp_path, paths.manifest)
        temp_path.unlink()
        temp_path = None
        _fsync_directory(paths.root)
    except ReV2RunStoreError:
        raise
    except FileExistsError as exc:
        raise ReV2RunStoreError(f"immutable v2 run manifest already exists: {paths.manifest}") from exc
    except OSError as exc:
        raise ReV2RunStoreError(f"cannot persist immutable v2 run manifest: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return paths


def load_run_manifest(run_dir: Path) -> Manifest:
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
        manifest = load_canonical_object(payload, _decode_manifest)
    except ReV2RunStoreError:
        raise
    except (OSError, ValueError, ReV2ModelError, Protocol22SchemaError) as exc:
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


def _decode_manifest(raw: object) -> Manifest:
    if not isinstance(raw, dict):
        raise ReV2RunStoreError("immutable v2 run manifest must be an object")
    pair = (raw.get("schema_version"), raw.get("engine_protocol_version"))
    if pair in {(1, "2.0"), (1, "2.1")}:
        return RunManifest.from_json_dict(raw)
    if pair[0] == 2 and pair[1] in RE_V2_SCHEMA_2_PROTOCOLS:
        return RunManifestV2.from_json_dict(raw)
    if pair[0] == 3 and pair[1] in RE_V2_SCHEMA_3_PROTOCOLS:
        return RunManifestV3.from_json_dict(raw)
    raise ReV2RunStoreError(
        f"unsupported pinned manifest schema/protocol {pair!r}"
    )


def _validate_supported_manifest(manifest: Manifest) -> None:
    valid = (
        isinstance(manifest, RunManifest)
        and manifest.engine == RE_V2_ENGINE
        and manifest.engine_protocol_version in RE_V2_SCHEMA_1_PROTOCOLS
    ) or (
        isinstance(manifest, RunManifestV2)
        and manifest.engine == RE_V2_ENGINE
        and manifest.engine_protocol_version in RE_V2_SCHEMA_2_PROTOCOLS
    ) or (
        isinstance(manifest, RunManifestV3)
        and manifest.engine == RE_V2_ENGINE
        and manifest.engine_protocol_version in RE_V2_SCHEMA_3_PROTOCOLS
    )
    if not valid:
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

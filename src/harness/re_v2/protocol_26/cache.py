"""Disposable, reconstructable workspace cache for RE v2 checkpoints."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from types import MappingProxyType
from typing import Iterator, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_26.model import CheckpointManifestV1
from harness.re_v2.protocol_26.reconstruction import (
    OriginCheckpointRejectionV1,
    reconstruct_origin_checkpoints,
)


_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")


class CheckpointCacheError(RuntimeError):
    """Raised when the disposable checkpoint projection cannot be published."""


@dataclass(frozen=True, slots=True)
class CheckpointCachePaths:
    root: Path
    index: Path
    lock: Path
    manifests: Path
    quarantine: Path

    @classmethod
    def for_workspace(cls, workspace_root: Path) -> "CheckpointCachePaths":
        workspace = Path(workspace_root)
        if workspace.is_symlink():
            raise CheckpointCacheError("workspace root must not be a symlink")
        try:
            resolved = workspace.resolve(strict=True)
        except OSError as exc:
            raise CheckpointCacheError(f"workspace root is unavailable: {exc}") from exc
        if not resolved.is_dir():
            raise CheckpointCacheError("workspace root must be a directory")
        root = resolved / ".echelon" / "re-v2" / "checkpoints"
        return cls(
            root=root,
            index=root / "index-v1.json",
            lock=root / "index-v1.lock",
            manifests=root / "manifests",
            quarantine=root / "quarantine-v1.json",
        )


@dataclass(frozen=True, slots=True)
class CheckpointCacheEntryV1:
    schema_version: int
    checkpoint_manifest_id: str
    origin_run_id: str
    origin_engine_protocol_version: str
    origin_run_schema_version: int
    work_item_id: str
    artifact_key_id: str
    artifact_hash: str
    source_id: str
    domain_key: str | None
    layer: str
    artifact_kind: str
    audit_epoch_id: str | None
    rank_policy_hash: str
    rank_vector: tuple[int, ...]

    FIELDS = (
        "schema_version",
        "checkpoint_manifest_id",
        "origin_run_id",
        "origin_engine_protocol_version",
        "origin_run_schema_version",
        "work_item_id",
        "artifact_key_id",
        "artifact_hash",
        "source_id",
        "domain_key",
        "layer",
        "artifact_kind",
        "audit_epoch_id",
        "rank_policy_hash",
        "rank_vector",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise CheckpointCacheError("cache entry schema_version must be 1")
        for field in (
            "checkpoint_manifest_id",
            "work_item_id",
            "artifact_key_id",
            "artifact_hash",
            "rank_policy_hash",
        ):
            if not _is_digest(getattr(self, field)):
                raise CheckpointCacheError(f"cache entry {field} is invalid")
        if self.audit_epoch_id is not None and not _is_digest(self.audit_epoch_id):
            raise CheckpointCacheError("cache entry audit_epoch_id is invalid")
        for field in ("origin_run_id", "source_id", "artifact_kind"):
            if not _is_safe_id(getattr(self, field)):
                raise CheckpointCacheError(f"cache entry {field} is invalid")
        if self.domain_key is not None and not _is_safe_id(self.domain_key):
            raise CheckpointCacheError("cache entry domain_key is invalid")
        if self.layer not in {"L0", "L1", "L2", "L3"}:
            raise CheckpointCacheError("cache entry layer is invalid")
        if (
            not isinstance(self.origin_engine_protocol_version, str)
            or not self.origin_engine_protocol_version
            or not isinstance(self.origin_run_schema_version, int)
            or isinstance(self.origin_run_schema_version, bool)
        ):
            raise CheckpointCacheError("cache entry origin protocol is invalid")
        vector = tuple(self.rank_vector)
        if not vector or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in vector
        ):
            raise CheckpointCacheError("cache entry rank_vector is invalid")
        object.__setattr__(self, "rank_vector", vector)

    @classmethod
    def from_checkpoint(
        cls, checkpoint: CheckpointManifestV1
    ) -> "CheckpointCacheEntryV1":
        scope = checkpoint.work_item.output_key.scope
        return cls(
            schema_version=1,
            checkpoint_manifest_id=checkpoint.identity,
            origin_run_id=checkpoint.origin_run_id,
            origin_engine_protocol_version=checkpoint.origin_engine_protocol_version,
            origin_run_schema_version=checkpoint.origin_run_schema_version,
            work_item_id=checkpoint.work_item.work_item_id,
            artifact_key_id=checkpoint.artifact_key_id,
            artifact_hash=checkpoint.artifact_hash,
            source_id=scope.source_id,
            domain_key=scope.domain_key,
            layer=checkpoint.work_item.output_key.layer,
            artifact_kind=checkpoint.work_item.output_key.artifact_kind,
            audit_epoch_id=checkpoint.audit_epoch_id,
            rank_policy_hash=checkpoint.rank_policy_hash,
            rank_vector=checkpoint.rank.vector,
        )

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["rank_vector"] = list(self.rank_vector)
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointCacheEntryV1":
        raw = _exact_object(value, cls.FIELDS, "checkpoint cache entry")
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class CheckpointCacheIndexV1:
    schema_version: int
    entries: tuple[CheckpointCacheEntryV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise CheckpointCacheError("checkpoint cache index schema_version must be 1")
        entries = tuple(self.entries)
        if any(not isinstance(item, CheckpointCacheEntryV1) for item in entries):
            raise CheckpointCacheError("checkpoint cache index entries are invalid")
        keys = tuple(item.checkpoint_manifest_id for item in entries)
        if keys != tuple(sorted(set(keys))):
            raise CheckpointCacheError(
                "checkpoint cache index entries must be sorted and unique"
            )
        object.__setattr__(self, "entries", entries)

    @property
    def manifest_ids(self) -> tuple[str, ...]:
        return tuple(item.checkpoint_manifest_id for item in self.entries)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "entries": [item.to_json_dict() for item in self.entries],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointCacheIndexV1":
        raw = _exact_object(value, ("schema_version", "entries"), "cache index")
        entries = raw["entries"]
        if not isinstance(entries, list):
            raise CheckpointCacheError("checkpoint cache index entries must be an array")
        return cls(
            schema_version=raw["schema_version"],
            entries=tuple(
                CheckpointCacheEntryV1.from_json_dict(item) for item in entries
            ),
        )


@dataclass(frozen=True, slots=True)
class CheckpointCacheGenerationV1:
    paths: CheckpointCachePaths
    index: CheckpointCacheIndexV1
    manifests: Mapping[str, CheckpointManifestV1]
    quarantine: tuple[OriginCheckpointRejectionV1, ...]
    reconstructed_manifest_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        manifests = MappingProxyType(dict(sorted(self.manifests.items())))
        reconstructed = tuple(self.reconstructed_manifest_ids)
        if tuple(manifests) != self.index.manifest_ids or reconstructed != tuple(
            manifests
        ):
            raise CheckpointCacheError(
                "cache generation differs from reconstructed checkpoint authority"
            )
        object.__setattr__(self, "manifests", manifests)
        object.__setattr__(self, "quarantine", tuple(self.quarantine))
        object.__setattr__(self, "reconstructed_manifest_ids", reconstructed)


def rebuild_checkpoint_cache(workspace_root: Path) -> CheckpointCacheGenerationV1:
    """Reconstruct all safe origins and atomically replace cache projections."""
    paths = CheckpointCachePaths.for_workspace(workspace_root)
    _ensure_cache_layout(paths)
    with _checkpoint_cache_lock(paths.lock):
        manifests: dict[str, CheckpointManifestV1] = {}
        quarantine: list[OriginCheckpointRejectionV1] = []
        for origin in _enumerate_origins(paths.root.parents[2]):
            if origin.is_symlink() or not origin.is_dir():
                quarantine.append(
                    OriginCheckpointRejectionV1(
                        origin_run_id=origin.name,
                        reason="checkpoint_manifest_invalid",
                    )
                )
                continue
            result = reconstruct_origin_checkpoints(paths.root.parents[2], origin)
            quarantine.extend(result.rejected)
            for checkpoint in result.manifests:
                existing = manifests.get(checkpoint.identity)
                if existing is not None and existing != checkpoint:
                    quarantine.append(
                        OriginCheckpointRejectionV1(
                            origin_run_id=checkpoint.origin_run_id,
                            reason="checkpoint_authority_conflict",
                        )
                    )
                    continue
                manifests[checkpoint.identity] = checkpoint
        ordered_manifests = dict(sorted(manifests.items()))
        ordered_quarantine = tuple(
            sorted(quarantine, key=lambda item: (item.origin_run_id, item.reason))
        )
        index = CheckpointCacheIndexV1(
            schema_version=1,
            entries=tuple(
                CheckpointCacheEntryV1.from_checkpoint(checkpoint)
                for checkpoint in ordered_manifests.values()
            ),
        )
        _publish_generation(paths, index, ordered_manifests, ordered_quarantine)
        return _load_published_generation(
            paths,
            expected_index=index,
            reconstructed_manifest_ids=tuple(ordered_manifests),
        )


def _enumerate_origins(workspace_root: Path) -> tuple[Path, ...]:
    runs = workspace_root / "runs"
    if not os.path.lexists(runs):
        return ()
    metadata = os.lstat(runs)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise CheckpointCacheError("workspace runs path must be a real directory")
    return tuple(
        sorted(
            (path for path in runs.iterdir() if path.name.startswith("re-")),
            key=lambda value: value.name,
        )
    )


def _ensure_cache_layout(paths: CheckpointCachePaths) -> None:
    workspace = paths.root.parents[2]
    current = workspace
    for name in (".echelon", "re-v2", "checkpoints"):
        current = current / name
        _ensure_real_directory(current)
    _ensure_real_directory(paths.manifests)


def _ensure_real_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise CheckpointCacheError(f"cache path must be a real directory: {path.name}")


@contextmanager
def _checkpoint_cache_lock(path: Path) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise CheckpointCacheError(f"cannot open checkpoint cache lock: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise CheckpointCacheError("checkpoint cache lock must be a regular file")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _publish_generation(
    paths: CheckpointCachePaths,
    index: CheckpointCacheIndexV1,
    manifests: Mapping[str, CheckpointManifestV1],
    quarantine: tuple[OriginCheckpointRejectionV1, ...],
) -> None:
    stage = Path(tempfile.mkdtemp(prefix=".generation-", dir=paths.root))
    try:
        staged_manifests = stage / "manifests"
        staged_manifests.mkdir(mode=0o700)
        for manifest_id, manifest in manifests.items():
            _write_new_file(
                staged_manifests / f"{manifest_id}.json",
                canonical_json_bytes(manifest.to_json_dict()),
            )
        quarantine_payload = canonical_json_bytes(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "origin_run_id": item.origin_run_id,
                        "reason": item.reason,
                    }
                    for item in quarantine
                ],
            }
        )
        _write_new_file(stage / "quarantine-v1.json", quarantine_payload)
        _write_new_file(stage / "index-v1.json", canonical_json_bytes(index.to_json_dict()))
        _fsync_directory(staged_manifests)
        _fsync_directory(stage)

        for manifest_id in manifests:
            os.replace(
                staged_manifests / f"{manifest_id}.json",
                paths.manifests / f"{manifest_id}.json",
            )
        _fsync_directory(paths.manifests)
        os.replace(stage / "quarantine-v1.json", paths.quarantine)
        _fsync_directory(paths.root)
        os.replace(stage / "index-v1.json", paths.index)
        _fsync_directory(paths.root)
        _retire_unreferenced_manifests(paths, frozenset(manifests))
    except (CheckpointCacheError, OSError):
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _retire_unreferenced_manifests(
    paths: CheckpointCachePaths, retained: frozenset[str]
) -> None:
    for projection in paths.manifests.iterdir():
        expected = (
            projection.name.removesuffix(".json")
            if projection.name.endswith(".json")
            else ""
        )
        if expected not in retained:
            if projection.is_dir() and not projection.is_symlink():
                shutil.rmtree(projection)
            else:
                projection.unlink()
    _fsync_directory(paths.manifests)


def _load_published_generation(
    paths: CheckpointCachePaths,
    *,
    expected_index: CheckpointCacheIndexV1,
    reconstructed_manifest_ids: tuple[str, ...],
) -> CheckpointCacheGenerationV1:
    index = CheckpointCacheIndexV1.from_json_dict(_load_canonical(paths.index))
    if index != expected_index or index.manifest_ids != reconstructed_manifest_ids:
        raise CheckpointCacheError("published cache index differs from reconstruction")
    manifests: dict[str, CheckpointManifestV1] = {}
    for manifest_id in index.manifest_ids:
        projection = paths.manifests / f"{manifest_id}.json"
        manifest = CheckpointManifestV1.from_json_dict(_load_canonical(projection))
        if manifest.identity != manifest_id:
            raise CheckpointCacheError("checkpoint manifest projection identity mismatch")
        manifests[manifest_id] = manifest
    quarantine = _load_quarantine(paths.quarantine)
    return CheckpointCacheGenerationV1(
        paths=paths,
        index=index,
        manifests=manifests,
        quarantine=quarantine,
        reconstructed_manifest_ids=reconstructed_manifest_ids,
    )


def _load_quarantine(path: Path) -> tuple[OriginCheckpointRejectionV1, ...]:
    raw = _exact_object(
        _load_canonical(path), ("schema_version", "entries"), "cache quarantine"
    )
    if raw["schema_version"] != 1 or not isinstance(raw["entries"], list):
        raise CheckpointCacheError("checkpoint quarantine schema is invalid")
    result = []
    for value in raw["entries"]:
        entry = _exact_object(value, ("origin_run_id", "reason"), "quarantine entry")
        if not _is_safe_id(entry["origin_run_id"]) or not _is_safe_id(entry["reason"]):
            raise CheckpointCacheError("checkpoint quarantine entry is invalid")
        result.append(OriginCheckpointRejectionV1(**entry))
    ordered = tuple(sorted(result, key=lambda item: (item.origin_run_id, item.reason)))
    if tuple(result) != ordered:
        raise CheckpointCacheError("checkpoint quarantine entries are not sorted")
    return ordered


def _load_canonical(path: Path) -> object:
    payload = _safe_regular_read(path)
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointCacheError(f"checkpoint cache JSON is invalid: {path.name}") from exc
    if canonical_json_bytes(decoded) != payload:
        raise CheckpointCacheError(f"checkpoint cache JSON is not canonical: {path.name}")
    return decoded


def _write_new_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise CheckpointCacheError("short checkpoint cache write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _safe_regular_read(path: Path) -> bytes:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CheckpointCacheError(f"checkpoint cache path is unsafe: {path.name}")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise CheckpointCacheError("checkpoint cache path changed during open")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _exact_object(value: object, fields, label: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    if not isinstance(value, dict) or set(value) != set(fields):
        raise CheckpointCacheError(f"{label} has unknown or missing fields")
    return value


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST_RE.fullmatch(value) is not None


def _is_safe_id(value: object) -> bool:
    return isinstance(value, str) and _SAFE_ID_RE.fullmatch(value) is not None


__all__ = (
    "CheckpointCacheEntryV1",
    "CheckpointCacheError",
    "CheckpointCacheGenerationV1",
    "CheckpointCacheIndexV1",
    "CheckpointCachePaths",
    "rebuild_checkpoint_cache",
)

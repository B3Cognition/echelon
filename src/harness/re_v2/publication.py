"""Atomic publication of exact certified RE v2 artifact-root sets."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Callable, Iterable, Iterator

from .canonical import canonical_json_bytes, content_digest


PUBLICATION_SCHEMA_VERSION = 1
EMPTY_INDEX_HASH = content_digest(b"")

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
_MANIFEST_FIELDS = {
    "accepted_root_hashes",
    "generation_id",
    "run_id",
    "schema_version",
    "synthesis_policy_hash",
}
_INDEX_FIELDS = {
    "generation_id",
    "generation_manifest_hash",
    "schema_version",
}


class ReV2PublicationError(RuntimeError):
    """Raised when v2 publication state or input is unsafe or malformed."""


class ReV2PublicationConflict(ReV2PublicationError):
    """Raised when the workspace index does not match the caller's CAS value."""


@dataclass(frozen=True, slots=True)
class GenerationManifest:
    """Immutable identity of one exact accepted-root set and synthesis policy."""

    schema_version: int
    generation_id: str
    run_id: str
    accepted_root_hashes: tuple[str, ...]
    synthesis_policy_hash: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != PUBLICATION_SCHEMA_VERSION
        ):
            raise ReV2PublicationError("unsupported generation manifest schema_version")
        _run_id(self.run_id)
        roots = _canonical_roots(self.accepted_root_hashes)
        if roots != self.accepted_root_hashes:
            raise ReV2PublicationError(
                "accepted_root_hashes must be canonical, unique, and sorted"
            )
        _digest(self.synthesis_policy_hash, "synthesis_policy_hash")
        _digest(self.generation_id, "generation_id")
        if self.generation_id != content_digest(self.identity_dict()):
            raise ReV2PublicationError("generation_id does not match manifest identity")

    @classmethod
    def create(
        cls,
        run_id: str,
        accepted_root_hashes: Iterable[str],
        synthesis_policy_hash: str,
    ) -> "GenerationManifest":
        safe_run_id = _run_id(run_id)
        roots = _canonical_roots(accepted_root_hashes)
        policy_hash = _digest(synthesis_policy_hash, "synthesis_policy_hash")
        identity = {
            "accepted_root_hashes": list(roots),
            "run_id": safe_run_id,
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "synthesis_policy_hash": policy_hash,
        }
        return cls(
            schema_version=PUBLICATION_SCHEMA_VERSION,
            generation_id=content_digest(identity),
            run_id=safe_run_id,
            accepted_root_hashes=roots,
            synthesis_policy_hash=policy_hash,
        )

    @classmethod
    def from_bytes(cls, payload: bytes) -> "GenerationManifest":
        raw = _json_object(payload, "generation manifest")
        _exact_fields(raw, _MANIFEST_FIELDS, "generation manifest")
        roots = raw["accepted_root_hashes"]
        if not isinstance(roots, list):
            raise ReV2PublicationError(
                "generation manifest accepted_root_hashes must be an array"
            )
        try:
            manifest = cls(
                schema_version=raw["schema_version"],  # type: ignore[arg-type]
                generation_id=raw["generation_id"],  # type: ignore[arg-type]
                run_id=raw["run_id"],  # type: ignore[arg-type]
                accepted_root_hashes=tuple(roots),  # type: ignore[arg-type]
                synthesis_policy_hash=raw["synthesis_policy_hash"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise ReV2PublicationError(
                f"generation manifest fields are malformed: {exc}"
            ) from exc
        if payload != canonical_json_bytes(manifest.to_json_dict()):
            raise ReV2PublicationError("generation manifest is not canonical JSON")
        return manifest

    def identity_dict(self) -> dict[str, object]:
        return {
            "accepted_root_hashes": list(self.accepted_root_hashes),
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "synthesis_policy_hash": self.synthesis_policy_hash,
        }

    def to_json_dict(self) -> dict[str, object]:
        return {
            "accepted_root_hashes": list(self.accepted_root_hashes),
            "generation_id": self.generation_id,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "synthesis_policy_hash": self.synthesis_policy_hash,
        }


@dataclass(frozen=True, slots=True)
class PublishedV2Index:
    """Canonical last-pointer to one complete immutable generation."""

    schema_version: int
    generation_id: str
    generation_manifest_hash: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != PUBLICATION_SCHEMA_VERSION
        ):
            raise ReV2PublicationError("unsupported published v2 index schema_version")
        _digest(self.generation_id, "generation_id")
        _digest(self.generation_manifest_hash, "generation_manifest_hash")

    @classmethod
    def create(cls, manifest: GenerationManifest) -> "PublishedV2Index":
        if not isinstance(manifest, GenerationManifest):
            raise ReV2PublicationError("manifest must be a GenerationManifest")
        manifest_bytes = canonical_json_bytes(manifest.to_json_dict())
        return cls(
            schema_version=PUBLICATION_SCHEMA_VERSION,
            generation_id=manifest.generation_id,
            generation_manifest_hash=content_digest(manifest_bytes),
        )

    @classmethod
    def from_bytes(cls, payload: bytes) -> "PublishedV2Index":
        raw = _json_object(payload, "published v2 index")
        _exact_fields(raw, _INDEX_FIELDS, "published v2 index")
        try:
            index = cls(
                schema_version=raw["schema_version"],  # type: ignore[arg-type]
                generation_id=raw["generation_id"],  # type: ignore[arg-type]
                generation_manifest_hash=raw["generation_manifest_hash"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise ReV2PublicationError(
                f"published v2 index fields are malformed: {exc}"
            ) from exc
        if payload != canonical_json_bytes(index.to_json_dict()):
            raise ReV2PublicationError("published v2 index is not canonical JSON")
        return index

    @property
    def index_hash(self) -> str:
        return content_digest(canonical_json_bytes(self.to_json_dict()))

    def to_json_dict(self) -> dict[str, object]:
        return {
            "generation_id": self.generation_id,
            "generation_manifest_hash": self.generation_manifest_hash,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class _PublicationPaths:
    workspace: Path
    root: Path
    generations: Path
    index: Path
    lock: Path


@dataclass(frozen=True, slots=True)
class _OwnedTemporary:
    path: Path
    device: int
    inode: int


def publish_generation(
    workspace_root: Path,
    run_id: str,
    accepted_root_hashes: Iterable[str],
    synthesis_policy_hash: str,
    *,
    expected_index_hash: str,
    fault_hook: Callable[[str], None] | None = None,
) -> PublishedV2Index:
    """Publish exactly the caller-certified roots with index compare-and-swap.

    This primitive deliberately does not infer certification, completeness, or
    synthesis eligibility.  Its roots and policy are explicit caller inputs.
    """
    manifest = GenerationManifest.create(
        run_id, accepted_root_hashes, synthesis_policy_hash
    )
    expected = _digest(expected_index_hash, "expected_index_hash")
    paths = _paths(workspace_root, create=True)

    try:
        with _publication_lock(paths):
            _validate_layout(paths)
            current = _load_index(paths)
            observed = current.index_hash if current is not None else EMPTY_INDEX_HASH
            if observed != expected:
                raise ReV2PublicationConflict(
                    f"expected index {expected}, found {observed}"
                )

            _create_or_reuse_generation(paths, manifest, fault_hook)
            desired = PublishedV2Index.create(manifest)
            if current == desired:
                return desired
            _replace_index(paths, desired, fault_hook)
            installed = _load_index(paths)
            if installed != desired:
                raise ReV2PublicationError(
                    "installed published v2 index failed exact validation"
                )
            return desired
    except (ReV2PublicationError, KeyboardInterrupt, SystemExit):
        raise
    except OSError as exc:
        raise ReV2PublicationError(f"cannot publish v2 generation: {exc}") from exc


def current_index_hash(workspace_root: Path) -> str:
    """Return the canonical current-index hash or the explicit empty sentinel."""
    paths = _paths(workspace_root, create=False)
    if not _path_exists(paths.root):
        return EMPTY_INDEX_HASH
    index = _load_index(paths)
    return index.index_hash if index is not None else EMPTY_INDEX_HASH


def load_published_v2_index(workspace_root: Path) -> PublishedV2Index | None:
    """Load and validate the canonical index and its complete generation."""
    paths = _paths(workspace_root, create=False)
    if not _path_exists(paths.root):
        return None
    return _load_index(paths)


def _paths(workspace_root: Path, *, create: bool) -> _PublicationPaths:
    workspace = _workspace(workspace_root)
    re_root = workspace / "re"
    root = re_root / "v2"
    generations = root / "generations"
    paths = _PublicationPaths(
        workspace=workspace,
        root=root,
        generations=generations,
        index=root / "index.json",
        lock=root / ".publication.lock",
    )
    if create:
        _ensure_directory(re_root, workspace, "re publication parent")
        _ensure_directory(root, re_root, "v2 publication root")
        _ensure_directory(generations, root, "generation namespace")
    else:
        if _path_exists(re_root):
            _require_directory(re_root, "re publication parent")
        if _path_exists(root):
            _require_directory(root, "v2 publication root")
        if _path_exists(generations):
            _require_directory(generations, "generation namespace")
    return paths


def _workspace(value: Path) -> Path:
    try:
        raw = Path(value)
    except TypeError as exc:
        raise ReV2PublicationError("workspace path is malformed") from exc
    try:
        details = os.lstat(raw)
    except OSError as exc:
        raise ReV2PublicationError(
            f"workspace path must be an existing directory: {raw}"
        ) from exc
    if stat.S_ISLNK(details.st_mode):
        raise ReV2PublicationError("workspace path must not be a symlink")
    if not stat.S_ISDIR(details.st_mode):
        raise ReV2PublicationError("workspace path must be a directory")
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise ReV2PublicationError("workspace path cannot be resolved safely") from exc
    if resolved != raw.absolute():
        raise ReV2PublicationError(
            "workspace path must not traverse a symlink or relative segment"
        )
    return resolved


def _validate_layout(paths: _PublicationPaths) -> None:
    _require_directory(paths.workspace, "workspace")
    _require_directory(paths.root.parent, "re publication parent")
    _require_directory(paths.root, "v2 publication root")
    _require_directory(paths.generations, "generation namespace")


@contextmanager
def _publication_lock(paths: _PublicationPaths) -> Iterator[None]:
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    existed = _path_exists(paths.lock)
    fd = _open(paths.lock, flags, 0o600)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            raise ReV2PublicationError("publication lock is not a regular file")
        _require_same_inode(paths.lock, details, "publication lock")
        if not existed:
            _fsync(fd)
            _fsync_directory(paths.root)
        _flock(fd, fcntl.LOCK_EX)
        _require_same_inode(paths.lock, details, "publication lock")
        yield
    finally:
        try:
            _flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _create_or_reuse_generation(
    paths: _PublicationPaths,
    manifest: GenerationManifest,
    fault_hook: Callable[[str], None] | None,
) -> None:
    payload = canonical_json_bytes(manifest.to_json_dict())
    final = paths.generations / manifest.generation_id
    if _path_exists(final):
        _validate_generation(final, manifest.generation_id, content_digest(payload), payload)
        return

    temporary_path = Path(
        tempfile.mkdtemp(
            prefix=".generation.", suffix=".tmp", dir=paths.generations
        )
    )
    temporary = _owned_temporary(temporary_path)
    promoted = False
    try:
        manifest_path = temporary.path / "manifest.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = _open(manifest_path, flags, 0o600)
        try:
            _write_all(fd, payload)
            os.fchmod(fd, 0o400)
            _fsync(fd)
        finally:
            os.close(fd)
        os.chmod(temporary.path, 0o500, follow_symlinks=False)
        _fsync_directory(temporary.path)
        _hook(fault_hook, "generation_temporary_written")
        try:
            _rename_no_replace(temporary.path, final)
        except FileExistsError:
            _validate_generation(
                final, manifest.generation_id, content_digest(payload), payload
            )
            return
        promoted = True
        _fsync_directory(final)
        _fsync_directory(paths.generations)
        _hook(fault_hook, "generation_promoted")
    finally:
        if not promoted:
            _cleanup_owned_temporary(temporary)


def _replace_index(
    paths: _PublicationPaths,
    index: PublishedV2Index,
    fault_hook: Callable[[str], None] | None,
) -> None:
    payload = canonical_json_bytes(index.to_json_dict())
    fd, name = tempfile.mkstemp(
        prefix=".index.json.", suffix=".tmp", dir=paths.root
    )
    temporary = _owned_temporary(Path(name))
    replaced = False
    try:
        try:
            _write_all(fd, payload)
            os.fchmod(fd, 0o400)
            _fsync(fd)
        finally:
            os.close(fd)
        _hook(fault_hook, "index_temporary_written")
        _replace(temporary.path, paths.index)
        replaced = True
        _fsync_directory(paths.root)
        _hook(fault_hook, "index_replaced")
    finally:
        if not replaced:
            _cleanup_owned_temporary(temporary)


def _load_index(paths: _PublicationPaths) -> PublishedV2Index | None:
    if not _path_exists(paths.index):
        return None
    payload = _read_regular(paths.index, "published v2 index")
    index = PublishedV2Index.from_bytes(payload)
    _validate_generation(
        paths.generations / index.generation_id,
        index.generation_id,
        index.generation_manifest_hash,
        None,
    )
    return index


def _validate_generation(
    directory: Path,
    generation_id: str,
    expected_manifest_hash: str,
    expected_payload: bytes | None,
) -> GenerationManifest:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        details = os.lstat(directory)
    except OSError as exc:
        raise ReV2PublicationError(
            f"generation manifest is missing for {generation_id}"
        ) from exc
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise ReV2PublicationError(f"generation collision at {generation_id}")
    directory_fd = _open(directory, flags)
    try:
        opened = os.fstat(directory_fd)
        if _identity(details) != _identity(opened):
            raise ReV2PublicationError(
                f"generation mutated during validation: {generation_id}"
            )
        entries = _directory_entries(directory_fd, generation_id)
        if "manifest.json" not in entries:
            raise ReV2PublicationError(
                f"generation manifest is missing for {generation_id}"
            )
        if entries != ["manifest.json"]:
            raise ReV2PublicationError(f"generation collision at {generation_id}")
        payload = _read_regular_at(
            directory_fd, "manifest.json", "generation manifest"
        )
        manifest = GenerationManifest.from_bytes(payload)
        if (
            manifest.generation_id != generation_id
            or content_digest(payload) != expected_manifest_hash
            or (expected_payload is not None and payload != expected_payload)
        ):
            raise ReV2PublicationError(f"generation collision at {generation_id}")
        confirmed = _directory_entries(directory_fd, generation_id)
        after = os.fstat(directory_fd)
        current = os.lstat(directory)
        if (
            confirmed != entries
            or _stable_directory_identity(opened)
            != _stable_directory_identity(after)
            or _identity(after) != _identity(current)
        ):
            raise ReV2PublicationError(
                f"generation mutated during validation: {generation_id}"
            )
        return manifest
    finally:
        os.close(directory_fd)


def _directory_entries(directory_fd: int, generation_id: str) -> list[str]:
    try:
        return sorted(entry.name for entry in os.scandir(directory_fd))
    except OSError as exc:
        raise ReV2PublicationError(
            f"cannot inspect generation {generation_id}: {exc}"
        ) from exc


def _json_object(payload: bytes, label: str) -> dict[str, object]:
    if not isinstance(payload, bytes):
        raise ReV2PublicationError(f"{label} payload must be bytes")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReV2PublicationError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReV2PublicationError(f"{label} must be a JSON object")
    return value


def _exact_fields(value: dict[str, object], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise ReV2PublicationError(f"{label} fields are malformed")


def _canonical_roots(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ReV2PublicationError("accepted_root_hashes must be a non-empty iterable")
    try:
        roots = tuple(values)
    except TypeError as exc:
        raise ReV2PublicationError(
            "accepted_root_hashes must be a non-empty iterable"
        ) from exc
    if not roots:
        raise ReV2PublicationError("accepted_root_hashes must be non-empty")
    for value in roots:
        _digest(value, "accepted_root_hash")
    return tuple(sorted(set(roots)))


def _run_id(value: object) -> str:
    if not isinstance(value, str) or not _RUN_ID_RE.fullmatch(value):
        raise ReV2PublicationError("run_id is unsafe or malformed")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReV2PublicationError(f"{field} must be a lowercase sha256 digest")
    return value


def _ensure_directory(path: Path, parent: Path, label: str) -> None:
    _require_directory(parent, f"{label} parent")
    try:
        details = os.lstat(path)
    except FileNotFoundError:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise ReV2PublicationError(f"cannot create {label}: {exc}") from exc
        else:
            _fsync_directory(parent)
        _require_directory(path, label)
        return
    except OSError as exc:
        raise ReV2PublicationError(f"cannot inspect {label}: {exc}") from exc
    if stat.S_ISLNK(details.st_mode):
        raise ReV2PublicationError(f"unsafe symlink for {label}: {path}")
    if not stat.S_ISDIR(details.st_mode):
        raise ReV2PublicationError(f"{label} is not a directory: {path}")


def _require_directory(path: Path, label: str) -> None:
    try:
        details = os.lstat(path)
    except OSError as exc:
        raise ReV2PublicationError(f"cannot inspect {label}: {exc}") from exc
    if stat.S_ISLNK(details.st_mode):
        raise ReV2PublicationError(f"unsafe symlink for {label}: {path}")
    if not stat.S_ISDIR(details.st_mode):
        raise ReV2PublicationError(f"{label} is not a directory: {path}")


def _require_same_inode(path: Path, expected: os.stat_result, label: str) -> None:
    try:
        current = os.lstat(path)
    except OSError as exc:
        raise ReV2PublicationError(f"{label} disappeared") from exc
    if stat.S_ISLNK(current.st_mode) or _identity(current) != _identity(expected):
        raise ReV2PublicationError(f"{label} was replaced during acquisition")


def _read_regular(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = _open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ReV2PublicationError(f"{label} is not a regular file")
        _require_same_inode(path, before, label)
        payload = _read_all(fd)
        after = os.fstat(fd)
        if _stable_file_identity(before) != _stable_file_identity(after):
            raise ReV2PublicationError(f"{label} mutated while being read")
        if len(payload) != after.st_size:
            raise ReV2PublicationError(f"{label} has an unstable size")
        _require_same_inode(path, after, label)
        return payload
    finally:
        os.close(fd)


def _read_regular_at(directory_fd: int, name: str, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = _open_at(directory_fd, name, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ReV2PublicationError(f"{label} is not a regular file")
        payload = _read_all(fd)
        after = os.fstat(fd)
        if (
            _stable_file_identity(before) != _stable_file_identity(after)
            or len(payload) != after.st_size
        ):
            raise ReV2PublicationError(f"{label} mutated while being read")
        return payload
    finally:
        os.close(fd)


def _open(path: Path, flags: int, mode: int | None = None) -> int:
    while True:
        try:
            return os.open(path, flags) if mode is None else os.open(path, flags, mode)
        except InterruptedError:
            continue


def _open_at(directory_fd: int, name: str, flags: int) -> int:
    while True:
        try:
            return os.open(name, flags, dir_fd=directory_fd)
        except InterruptedError:
            continue


def _flock(fd: int, operation: int) -> None:
    while True:
        try:
            fcntl.flock(fd, operation)
            return
        except InterruptedError:
            continue


def _read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            chunk = os.read(fd, 1024 * 1024)
        except InterruptedError:
            continue
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(fd, payload[offset:])
        except InterruptedError:
            continue
        if written <= 0:
            raise OSError("short write while persisting publication data")
        offset += written


def _fsync(fd: int) -> None:
    while True:
        try:
            os.fsync(fd)
            return
        except InterruptedError:
            continue


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = _open(path, flags)
    try:
        details = os.fstat(fd)
        if not stat.S_ISDIR(details.st_mode):
            raise ReV2PublicationError(f"cannot fsync non-directory: {path}")
        _require_same_inode(path, details, "publication directory")
        _fsync(fd)
    finally:
        os.close(fd)


def _rename_no_replace(source: Path, destination: Path) -> None:
    while True:
        libc = ctypes.CDLL(None, use_errno=True)
        source_bytes = os.fsencode(source)
        destination_bytes = os.fsencode(destination)
        if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
            operation = libc.renameat2
            operation.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            operation.restype = ctypes.c_int
            result = operation(
                -100, source_bytes, -100, destination_bytes, 0x00000001
            )
        elif sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
            operation = libc.renameatx_np
            operation.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            operation.restype = ctypes.c_int
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            source_fd = _open(source, flags)
            frozen_mode = stat.S_IMODE(os.fstat(source_fd).st_mode)
            try:
                _fchmod(source_fd, frozen_mode | stat.S_IWUSR)
                result = operation(
                    -2, source_bytes, -2, destination_bytes, 0x00000004
                )
                saved_errno = ctypes.get_errno()
                _fchmod(source_fd, frozen_mode)
                _fsync(source_fd)
                ctypes.set_errno(saved_errno)
            finally:
                os.close(source_fd)
        else:
            raise ReV2PublicationError(
                "atomic no-replace generation promotion is unsupported"
            )
        if result == 0:
            return
        error = ctypes.get_errno()
        if error == errno.EINTR:
            continue
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(error, os.strerror(error), destination)
        raise OSError(error, os.strerror(error), destination)


def _replace(source: Path, destination: Path) -> None:
    while True:
        try:
            os.replace(source, destination)
            return
        except InterruptedError:
            if not _path_exists(source) and _path_exists(destination):
                return
            continue


def _fchmod(fd: int, mode: int) -> None:
    while True:
        try:
            os.fchmod(fd, mode)
            return
        except InterruptedError:
            continue


def _path_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ReV2PublicationError(f"cannot inspect publication path {path}: {exc}") from exc
    return True


def _owned_temporary(path: Path) -> _OwnedTemporary:
    details = os.lstat(path)
    return _OwnedTemporary(path, details.st_dev, details.st_ino)


def _cleanup_owned_temporary(temporary: _OwnedTemporary) -> None:
    try:
        details = os.lstat(temporary.path)
    except FileNotFoundError:
        return
    except OSError:
        return
    if (details.st_dev, details.st_ino) != (temporary.device, temporary.inode):
        return
    try:
        if stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode):
            os.chmod(temporary.path, 0o700, follow_symlinks=False)
            shutil.rmtree(temporary.path)
        else:
            temporary.path.unlink()
    except OSError:
        pass


def _identity(details: os.stat_result) -> tuple[int, int, int]:
    return details.st_dev, details.st_ino, stat.S_IFMT(details.st_mode)


def _stable_file_identity(details: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
    )


def _stable_directory_identity(
    details: os.stat_result,
) -> tuple[int, int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def _hook(hook: Callable[[str], None] | None, boundary: str) -> None:
    if hook is not None:
        hook(boundary)


__all__ = (
    "EMPTY_INDEX_HASH",
    "GenerationManifest",
    "PUBLICATION_SCHEMA_VERSION",
    "PublishedV2Index",
    "ReV2PublicationConflict",
    "ReV2PublicationError",
    "current_index_hash",
    "load_published_v2_index",
    "publish_generation",
)

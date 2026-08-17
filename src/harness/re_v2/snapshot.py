"""Immutable, content-addressed source snapshots for RE v2."""
from __future__ import annotations

import json
import ctypes
import errno
import fcntl
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Literal, TypeVar

from .canonical import canonical_json_bytes, content_digest

_CAPTURE_VERSION = 1
_MANIFEST_NAME = "manifest.json"
_OWNER_NAME = ".snapshot-owner.json"
_OWNER_VERSION = 1
_STAGE_PREFIX = ".snapshot-stage-"
_COMMIT_DIRECTORY = ".snapshot-commits"
_LOCK_DIRECTORY = ".snapshot-locks"

_T = TypeVar("_T")
FaultHook = Callable[[str], None]


class ReV2SnapshotError(RuntimeError):
    """Raised when a source cannot be frozen or a snapshot is no longer valid."""


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    path: str
    digest: str
    mode: int
    size: int

    def to_json_dict(self) -> dict[str, object]:
        return {"digest": self.digest, "mode": self.mode, "path": self.path, "size": self.size}


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    snapshot_id: str
    kind: Literal["git-worktree", "content-snapshot"]
    entries: tuple[SnapshotEntry, ...]
    exclusions: tuple[str, ...]
    git: dict[str, object] | None
    capture_version: int = _CAPTURE_VERSION

    def identity_dict(self) -> dict[str, object]:
        return {"capture_version": self.capture_version, "entries": [x.to_json_dict() for x in self.entries], "exclusions": list(self.exclusions), "git": self.git, "kind": self.kind}

    def to_json_dict(self) -> dict[str, object]:
        return {"snapshot_id": self.snapshot_id, **self.identity_dict()}


@dataclass(frozen=True, slots=True)
class CapturedSnapshot:
    snapshot_id: str
    kind: Literal["git-worktree", "content-snapshot"]
    read_root: Path
    manifest_path: Path


@dataclass(frozen=True, slots=True)
class _GitTreeEntry:
    mode: str
    kind: str
    object_id: str
    path: str


@dataclass(frozen=True, slots=True)
class _SubmoduleSource:
    path: str
    commit: str
    repository: Path


def run_git(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return completed.stdout


def capture_source_snapshot(
    source_root: Path,
    destination_root: Path,
    *,
    exclusions: tuple[str, ...],
    fault_hook: FaultHook | None = None,
) -> CapturedSnapshot:
    source = _safe_source_root(source_root)
    destination = _safe_destination_root(destination_root, source)
    excluded = _normalize_exclusions(exclusions)
    commit = _clean_git_commit(source)
    if commit is None:
        return _capture_copy(source, destination, excluded, fault_hook)
    return _capture_git_worktree(source, destination, excluded, commit, fault_hook)


def validate_source_snapshot(snapshot: CapturedSnapshot) -> None:
    _validate_commit_marker(snapshot)
    _validate_snapshot_payload(snapshot)


def _validate_snapshot_payload(snapshot: CapturedSnapshot) -> None:
    if snapshot.read_root.is_symlink() or snapshot.manifest_path.is_symlink():
        raise ReV2SnapshotError("unsafe symlink in source snapshot")
    try:
        manifest_payload = snapshot.manifest_path.read_bytes()
        manifest = _manifest_from_json(json.loads(manifest_payload))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ReV2SnapshotError(f"invalid snapshot manifest: {exc}") from exc
    if manifest_payload != canonical_json_bytes(manifest.to_json_dict()):
        raise ReV2SnapshotError("snapshot manifest is not canonical")
    if manifest.snapshot_id != snapshot.snapshot_id or manifest.kind != snapshot.kind:
        raise ReV2SnapshotError("snapshot handle does not match manifest")
    if content_digest(manifest.identity_dict()) != manifest.snapshot_id:
        raise ReV2SnapshotError("snapshot manifest content address mismatch")
    operational_git = manifest.kind == "git-worktree"
    actual = _inventory(snapshot.read_root, (), allow_worktree_git=operational_git)
    expected = {entry.path: entry for entry in manifest.entries}
    found = {entry.path: entry for entry in actual}
    missing, extra = sorted(expected.keys() - found.keys()), sorted(found.keys() - expected.keys())
    if missing:
        raise ReV2SnapshotError(f"snapshot missing file: {missing[0]}")
    if extra:
        raise ReV2SnapshotError(f"snapshot has extra file: {extra[0]}")
    for path, entry in expected.items():
        observed = found[path]
        if observed.digest != entry.digest:
            raise ReV2SnapshotError(f"snapshot hash mismatch: {path}")
        if observed.size != entry.size:
            raise ReV2SnapshotError(f"snapshot size mismatch: {path}")
        if observed.mode != _frozen_mode(entry.mode):
            raise ReV2SnapshotError(f"snapshot mode mismatch: {path}")


def _capture_copy(
    source: Path,
    destination: Path,
    exclusions: tuple[str, ...],
    fault_hook: FaultHook | None,
) -> CapturedSnapshot:
    entries = _inventory(source, (".git", *exclusions))
    manifest = _new_manifest("content-snapshot", entries, exclusions, None)
    temporary = Path(tempfile.mkdtemp(prefix=_STAGE_PREFIX, dir=destination))
    try:
        staged = temporary / "source"
        _copy_regular_files(source, staged, entries)
        # The staged bytes, not a prior source walk, are what would be published.
        if _inventory(source, (".git", *exclusions)) != entries or _inventory(staged, ()) != entries:
            raise ReV2SnapshotError("source changed while staging snapshot")
        _write_owner(temporary, manifest, source_repo=None)
        _fault(fault_hook, "source_installed")
        _publish_manifest(temporary / _MANIFEST_NAME, manifest)
        _fault(fault_hook, "manifest_installed")
        _make_read_only(temporary)
        _fault(fault_hook, "permissions_normalized")
        _fsync_tree(temporary)
        _fault(fault_hook, "bundle_fsynced")
        return _publish_staged_bundle(
            temporary,
            destination,
            manifest,
            source_repo=None,
            fault_hook=fault_hook,
        )
    finally:
        if temporary.exists():
            _remove_tree(temporary)


def _capture_git_worktree(
    source: Path,
    destination: Path,
    exclusions: tuple[str, ...],
    commit: str,
    fault_hook: FaultHook | None,
) -> CapturedSnapshot:
    temporary = Path(tempfile.mkdtemp(prefix=_STAGE_PREFIX, dir=destination))
    worktree = temporary / "worktree"
    registered: Path | None = None
    published = False
    preserve_temporary = False
    manifest: SnapshotManifest | None = None
    try:
        run_git(["-C", str(source), "worktree", "add", "--detach", str(worktree), commit])
        registered = worktree
        staged = temporary / "source"
        run_git(["-C", str(source), "worktree", "move", str(worktree), str(staged)])
        registered = staged
        submodules = _submodule_sources(source, commit)
        _materialize_submodules(staged, submodules)
        _remove_excluded_paths(staged, exclusions)
        entries = _inventory(staged, (), allow_worktree_git=True)
        manifest = _new_manifest(
            "git-worktree",
            entries,
            exclusions,
            {
                "commit": commit,
                "submodules": [
                    {"commit": item.commit, "path": item.path}
                    for item in submodules
                ],
            },
        )
        _write_owner(temporary, manifest, source_repo=source)
        _fault(fault_hook, "source_installed")
        _publish_manifest(temporary / _MANIFEST_NAME, manifest)
        _fault(fault_hook, "manifest_installed")
        _make_read_only(temporary)
        _fault(fault_hook, "permissions_normalized")
        _fsync_tree(temporary)
        _fault(fault_hook, "bundle_fsynced")
        captured = _publish_staged_bundle(
            temporary,
            destination,
            manifest,
            source_repo=source,
            fault_hook=fault_hook,
        )
        if temporary.exists():
            # An identical committed writer won. Remove our registered staging
            # worktree before returning its immutable snapshot.
            _make_owned_writable(temporary)
            run_git(["-C", str(source), "worktree", "remove", "--force", str(registered)])
            registered = None
        else:
            registered = captured.read_root
            published = True
        return captured
    except Exception as exc:
        bundle = temporary if temporary.exists() else (
            destination / manifest.snapshot_id if manifest is not None else None
        )
        if bundle is not None and registered is not None:
            registered = bundle / "source" if (bundle / "source").exists() else registered
        cleanup_error, deregistered = _cleanup_git_failure(source, registered, bundle)
        preserve_temporary = temporary.exists() and not deregistered
        registered = None
        if cleanup_error:
            raise ReV2SnapshotError(f"snapshot capture failed: {exc}; cleanup failed: {cleanup_error}") from exc
        if isinstance(exc, ReV2SnapshotError):
            raise
        raise ReV2SnapshotError(f"snapshot capture failed: {exc}") from exc
    finally:
        if registered is not None and not published:
            run_git(["-C", str(source), "worktree", "remove", "--force", str(registered)])
        if temporary.exists() and not preserve_temporary:
            _remove_tree(temporary)


def _cleanup_git_failure(source: Path, registered: Path | None, bundle: Path | None) -> tuple[Exception | None, bool]:
    if registered is not None:
        try:
            if bundle is not None and os.path.lexists(bundle):
                _make_owned_writable(bundle)
            run_git(["-C", str(source), "worktree", "remove", "--force", str(registered)])
        except Exception as exc:  # cleanup is an observable correctness failure
            return exc, False
    if bundle is not None and os.path.lexists(bundle):
        try:
            _remove_tree(bundle)
        except Exception as exc:
            return exc, True
    return None, True


def _publish_staged_bundle(
    temporary: Path,
    destination: Path,
    manifest: SnapshotManifest,
    *,
    source_repo: Path | None,
    fault_hook: FaultHook | None,
) -> CapturedSnapshot:
    with _snapshot_lock(destination, manifest.snapshot_id):
        _cleanup_owned_stages(destination, manifest, source_repo, exclude=temporary)
        existing = _existing_snapshot(destination, manifest, source_repo)
        if existing is not None:
            return existing
        bundle = destination / manifest.snapshot_id
        try:
            _rename_noreplace(temporary, bundle)
        except FileExistsError:
            existing = _existing_snapshot(destination, manifest, source_repo)
            if existing is not None:
                return existing
            raise ReV2SnapshotError(
                f"snapshot ID already exists: {manifest.snapshot_id}"
            )
        # Make the directory-name transition durable before the crash hook. A
        # promoted Git bundle remains hidden by its commit marker until its
        # administrative link is repaired below.
        _fsync_directory(destination)
        _fault(fault_hook, "final_promoted")
        if source_repo is not None:
            _repair_git_worktree(source_repo, bundle / "source", manifest)
        _fsync_directory(destination)
        captured = CapturedSnapshot(
            manifest.snapshot_id,
            manifest.kind,
            bundle / "source",
            bundle / _MANIFEST_NAME,
        )
        _validate_snapshot_payload(captured)
        _publish_commit_marker(captured)
        validate_source_snapshot(captured)
        return captured


def _existing_snapshot(
    destination: Path,
    manifest: SnapshotManifest,
    source_repo: Path | None,
) -> CapturedSnapshot | None:
    bundle = destination / manifest.snapshot_id
    marker = _commit_marker_path(destination, manifest.snapshot_id)
    if not os.path.lexists(bundle):
        if os.path.lexists(marker):
            raise ReV2SnapshotError(
                f"snapshot commit marker exists without bundle: {manifest.snapshot_id}"
            )
        return None
    if bundle.is_symlink() or not bundle.is_dir():
        raise ReV2SnapshotError(f"snapshot ID already exists: {manifest.snapshot_id}")
    captured = CapturedSnapshot(manifest.snapshot_id, manifest.kind, bundle / "source", bundle / _MANIFEST_NAME)
    if os.path.lexists(marker):
        try:
            validate_source_snapshot(captured)
        except ReV2SnapshotError as exc:
            raise ReV2SnapshotError(f"snapshot ID already exists and is invalid: {manifest.snapshot_id}: {exc}") from exc
        return captured

    owner = _read_owner(bundle)
    if not _owner_matches(owner, manifest, source_repo):
        raise ReV2SnapshotError(
            f"snapshot ID already exists without a valid owner: {manifest.snapshot_id}"
        )
    try:
        if source_repo is not None:
            _repair_git_worktree(source_repo, captured.read_root, manifest)
        _validate_snapshot_payload(captured)
        _fsync_tree(bundle)
        _publish_commit_marker(captured)
        validate_source_snapshot(captured)
        return captured
    except (OSError, ReV2SnapshotError):
        _remove_owned_bundle(bundle, owner)
        _fsync_directory(destination)
        return None


def _fault(fault_hook: FaultHook | None, point: str) -> None:
    if fault_hook is not None:
        fault_hook(point)


def _owner_payload(
    manifest: SnapshotManifest, source_repo: Path | None
) -> dict[str, object]:
    manifest_payload = canonical_json_bytes(manifest.to_json_dict())
    return {
        "kind": manifest.kind,
        "manifest_digest": content_digest(manifest_payload),
        "owner_version": _OWNER_VERSION,
        "snapshot_id": manifest.snapshot_id,
        "source_repo": str(source_repo) if source_repo is not None else None,
    }


def _write_owner(
    bundle: Path, manifest: SnapshotManifest, source_repo: Path | None
) -> None:
    _write_new_file(
        bundle / _OWNER_NAME,
        canonical_json_bytes(_owner_payload(manifest, source_repo)),
    )


def _read_owner(bundle: Path) -> dict[str, object] | None:
    path = bundle / _OWNER_NAME
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _owner_matches(
    owner: dict[str, object] | None,
    manifest: SnapshotManifest,
    source_repo: Path | None,
) -> bool:
    return owner == _owner_payload(manifest, source_repo)


def _commit_marker_path(destination: Path, snapshot_id: str) -> Path:
    return destination / _COMMIT_DIRECTORY / f"{snapshot_id}.json"


def _marker_payload(snapshot: CapturedSnapshot) -> dict[str, object]:
    return {
        "capture_version": _CAPTURE_VERSION,
        "manifest_digest": content_digest(snapshot.manifest_path.read_bytes()),
        "snapshot_id": snapshot.snapshot_id,
    }


def _validate_commit_marker(snapshot: CapturedSnapshot) -> None:
    bundle = snapshot.manifest_path.parent
    if snapshot.read_root != bundle / "source" or bundle.name != snapshot.snapshot_id:
        raise ReV2SnapshotError("snapshot handle paths do not match snapshot ID")
    if snapshot.manifest_path.is_symlink() or not snapshot.manifest_path.is_file():
        raise ReV2SnapshotError("snapshot manifest is not a safe regular file")
    marker = _commit_marker_path(bundle.parent, snapshot.snapshot_id)
    if marker.is_symlink() or not marker.is_file():
        raise ReV2SnapshotError("snapshot is not committed")
    try:
        observed = json.loads(marker.read_bytes())
        expected = _marker_payload(snapshot)
    except (OSError, ValueError, TypeError) as exc:
        raise ReV2SnapshotError(f"invalid snapshot commit marker: {exc}") from exc
    if observed != expected:
        raise ReV2SnapshotError("snapshot commit marker does not match manifest")


def _publish_commit_marker(snapshot: CapturedSnapshot) -> None:
    destination = snapshot.manifest_path.parent.parent
    marker_root = destination / _COMMIT_DIRECTORY
    if marker_root.is_symlink():
        raise ReV2SnapshotError("snapshot commit directory is symlinked")
    marker_root.mkdir(mode=0o700, exist_ok=True)
    if not marker_root.is_dir():
        raise ReV2SnapshotError("snapshot commit path is not a directory")
    marker = _commit_marker_path(destination, snapshot.snapshot_id)
    payload = canonical_json_bytes(_marker_payload(snapshot))
    temporary = marker_root / f".{snapshot.snapshot_id}.{uuid.uuid4().hex}.tmp"
    _write_new_file(temporary, payload)
    temporary.chmod(0o400)
    try:
        try:
            os.link(temporary, marker, follow_symlinks=False)
        except FileExistsError:
            if marker.is_symlink() or not marker.is_file() or marker.read_bytes() != payload:
                raise ReV2SnapshotError(
                    f"snapshot commit marker already exists and is invalid: {snapshot.snapshot_id}"
                )
        _fsync_directory(marker_root)
        _fsync_directory(destination)
    finally:
        if os.path.lexists(temporary):
            temporary.chmod(0o600)
            temporary.unlink()


@contextmanager
def _snapshot_lock(destination: Path, snapshot_id: str) -> Iterator[None]:
    lock_root = destination / _LOCK_DIRECTORY
    if lock_root.is_symlink():
        raise ReV2SnapshotError("snapshot lock directory is symlinked")
    lock_root.mkdir(mode=0o700, exist_ok=True)
    if not lock_root.is_dir():
        raise ReV2SnapshotError("snapshot lock path is not a directory")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_root / f"{snapshot_id}.lock", flags, 0o600)
    try:
        _retry_eintr(fcntl.flock, fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            _retry_eintr(fcntl.flock, fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _cleanup_owned_stages(
    destination: Path,
    manifest: SnapshotManifest,
    source_repo: Path | None,
    *,
    exclude: Path,
) -> None:
    for stage in sorted(destination.glob(f"{_STAGE_PREFIX}*")):
        if stage == exclude or stage.is_symlink() or not stage.is_dir():
            continue
        owner = _read_owner(stage)
        if not _owner_matches(owner, manifest, source_repo):
            continue
        _remove_owned_bundle(stage, owner)


def _remove_owned_bundle(bundle: Path, owner: dict[str, object] | None) -> None:
    if owner is None:
        raise ReV2SnapshotError(f"refusing to remove unowned snapshot bundle: {bundle}")
    if owner.get("kind") == "git-worktree":
        source_value = owner.get("source_repo")
        if not isinstance(source_value, str) or not source_value:
            raise ReV2SnapshotError("Git snapshot owner is missing source repository")
        source_repo = Path(source_value)
        worktree = bundle / "source"
        if os.path.lexists(worktree):
            _make_owned_writable(bundle)
            run_git(["-C", str(source_repo), "worktree", "repair", str(worktree)])
            run_git(
                ["-C", str(source_repo), "worktree", "remove", "--force", str(worktree)]
            )
    if os.path.lexists(bundle):
        _remove_tree(bundle)


def _repair_git_worktree(
    source_repo: Path, worktree: Path, manifest: SnapshotManifest
) -> None:
    metadata = worktree / ".git"
    if metadata.is_symlink() or not metadata.is_file():
        raise ReV2SnapshotError("published Git worktree metadata is invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(metadata, flags)
    try:
        # `git worktree repair` updates both the main repository's administrative
        # link and this file. The bundle remains uncommitted while this one
        # operational metadata file is temporarily writable.
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    try:
        run_git(["-C", str(source_repo), "worktree", "repair", str(worktree)])
    finally:
        fd = os.open(metadata, flags)
        os.fchmod(fd, 0o400)
        _retry_eintr(os.fsync, fd)
        os.close(fd)
    expected = manifest.git.get("commit") if manifest.git is not None else None
    observed = run_git(["-C", str(worktree), "rev-parse", "HEAD^{commit}"]).strip()
    if not isinstance(expected, str) or observed != expected:
        raise ReV2SnapshotError("published Git worktree commit does not match manifest")


def _rename_noreplace(source: Path, target: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    target_bytes = os.fsencode(target)
    while True:
        if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
            operation = libc.renameat2
            operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            operation.restype = ctypes.c_int
            result = operation(-100, source_bytes, -100, target_bytes, 0x00000001)
        elif sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
            operation = libc.renameatx_np
            operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            operation.restype = ctypes.c_int
            source_fd = _open_directory(source)
            frozen_mode = stat.S_IMODE(os.fstat(source_fd).st_mode)
            try:
                os.fchmod(source_fd, frozen_mode | stat.S_IWUSR)
                result = operation(-2, source_bytes, -2, target_bytes, 0x00000004)
                saved_errno = ctypes.get_errno()
                os.fchmod(source_fd, frozen_mode)
                _retry_eintr(os.fsync, source_fd)
                ctypes.set_errno(saved_errno)
            finally:
                os.close(source_fd)
        else:
            raise ReV2SnapshotError(
                "atomic no-replace snapshot promotion is unsupported"
            )
        if result == 0:
            return
        error = ctypes.get_errno()
        if error == errno.EINTR:
            continue
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(error, os.strerror(error), target)
        raise OSError(error, os.strerror(error), target)


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


def _write_new_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            written = _retry_eintr(os.write, fd, payload[offset:])
            if written <= 0:
                raise OSError("short write while persisting snapshot data")
            offset += written
        _retry_eintr(os.fsync, fd)
    finally:
        os.close(fd)


def _fsync_tree(root: Path) -> None:
    paths = sorted(root.rglob("*"), key=lambda value: len(value.parts), reverse=True)
    for path in paths:
        if path.is_symlink():
            raise ReV2SnapshotError(f"source snapshot rejects symlink: {path}")
        fd = _open_directory(path) if path.is_dir() else os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            _retry_eintr(os.fsync, fd)
        finally:
            os.close(fd)
    _fsync_directory(root)


def _fsync_directory(path: Path) -> None:
    fd = _open_directory(path)
    try:
        _retry_eintr(os.fsync, fd)
    finally:
        os.close(fd)


def _retry_eintr(operation: Callable[..., _T], *args: object) -> _T:
    while True:
        try:
            return operation(*args)
        except InterruptedError:
            continue


def _new_manifest(kind: Literal["git-worktree", "content-snapshot"], entries: tuple[SnapshotEntry, ...], exclusions: tuple[str, ...], git: dict[str, object] | None) -> SnapshotManifest:
    partial = SnapshotManifest("", kind, entries, exclusions, git)
    return SnapshotManifest(content_digest(partial.identity_dict()), kind, entries, exclusions, git)


def _safe_source_root(source: Path) -> Path:
    if source.is_symlink() or not source.is_dir():
        raise ReV2SnapshotError(f"source root is not a safe directory: {source}")
    return source.resolve()


def _safe_destination_root(destination: Path, source: Path) -> Path:
    if destination.is_symlink():
        raise ReV2SnapshotError(f"destination root is symlinked: {destination}")
    resolved = destination.resolve(strict=False)
    if resolved == source or source in resolved.parents:
        raise ReV2SnapshotError("destination root must be outside source root")
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise ReV2SnapshotError(f"destination root is not a directory: {destination}")
    return destination.resolve()


def _normalize_exclusions(exclusions: tuple[str, ...]) -> tuple[str, ...]:
    values: set[str] = set()
    for exclusion in exclusions:
        path, parts = Path(exclusion), exclusion.split("/")
        if not exclusion or path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
            raise ReV2SnapshotError(f"unsafe exclusion path: {exclusion!r}")
        values.add(path.as_posix())
    return tuple(sorted(values))


def _is_excluded(relative: str, exclusions: tuple[str, ...]) -> bool:
    return any(relative == item or relative.startswith(item + "/") for item in exclusions)


def _remove_excluded_paths(root: Path, exclusions: tuple[str, ...]) -> None:
    """Remove only caller-approved paths from an owned temporary worktree."""
    for relative in exclusions:
        path = root.joinpath(*relative.split("/"))
        if root not in path.resolve(strict=False).parents:
            raise ReV2SnapshotError(f"unsafe exclusion path: {relative!r}")
        if not os.path.lexists(path):
            continue
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            _remove_tree(path)
        else:
            raise ReV2SnapshotError(f"source snapshot rejects special file: {relative}")


def _inventory(root: Path, exclusions: tuple[str, ...], *, allow_worktree_git: bool = False) -> tuple[SnapshotEntry, ...]:
    entries: list[SnapshotEntry] = []
    def visit(directory: Path, prefix: str = "") -> None:
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            relative = f"{prefix}/{child.name}" if prefix else child.name
            info = child.lstat()
            if child.name == ".git" and ".git" in exclusions:
                # Content snapshots include source bytes, never operational Git
                # administration from either the root or nested submodules.
                continue
            if relative == ".git" and allow_worktree_git:
                if not stat.S_ISREG(info.st_mode):
                    raise ReV2SnapshotError("invalid Git worktree metadata")
                continue
            if _is_excluded(relative, exclusions):
                continue
            if stat.S_ISLNK(info.st_mode):
                raise ReV2SnapshotError(f"source snapshot rejects symlink: {relative}")
            if stat.S_ISDIR(info.st_mode):
                visit(child, relative)
            elif stat.S_ISREG(info.st_mode):
                payload = child.read_bytes()
                entries.append(SnapshotEntry(relative, content_digest(payload), stat.S_IMODE(info.st_mode), len(payload)))
            else:
                raise ReV2SnapshotError(f"source snapshot rejects special file: {relative}")
    visit(root)
    return tuple(entries)


def _copy_regular_files(source: Path, target: Path, entries: tuple[SnapshotEntry, ...]) -> None:
    target.mkdir(mode=0o700)
    for entry in entries:
        destination = target / entry.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (source / entry.path).open("rb") as input_file, destination.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file)
        destination.chmod(entry.mode)


def _publish_manifest(path: Path, manifest: SnapshotManifest) -> None:
    _write_new_file(path, canonical_json_bytes(manifest.to_json_dict()))


def _frozen_mode(mode: int) -> int:
    return mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            raise ReV2SnapshotError(f"source snapshot rejects symlink: {path}")
        path.chmod(_frozen_mode(stat.S_IMODE(path.stat().st_mode)))
    root.chmod(_frozen_mode(stat.S_IMODE(root.stat().st_mode)))


def _remove_tree(root: Path) -> None:
    _make_owned_writable(root)
    shutil.rmtree(root)


def _make_owned_writable(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            continue
        path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
    root.chmod(stat.S_IMODE(root.stat().st_mode) | stat.S_IWUSR)


def _clean_git_commit(source: Path) -> str | None:
    try:
        top = Path(run_git(["-C", str(source), "rev-parse", "--show-toplevel"]).strip()).resolve()
        if top != source:
            return None
        commit = run_git(["-C", str(source), "rev-parse", "HEAD^{commit}"]).strip()
        status = run_git(["-C", str(source), "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"])
    except (OSError, subprocess.CalledProcessError):
        return None
    return commit if commit and not status.strip() else None


def _submodule_sources(source: Path, commit: str) -> tuple[_SubmoduleSource, ...]:
    sources: list[_SubmoduleSource] = []
    paths: set[str] = set()

    def visit(repository: Path, pinned_commit: str, prefix: str) -> None:
        for entry in _git_tree_entries(repository, pinned_commit):
            if entry.mode != "160000":
                continue
            full_path = f"{prefix}/{entry.path}" if prefix else entry.path
            if full_path in paths:
                raise ReV2SnapshotError(
                    f"duplicate recursive submodule path: {full_path}"
                )
            module = repository.joinpath(*entry.path.split("/"))
            _verify_local_submodule(module, entry.object_id, full_path)
            paths.add(full_path)
            sources.append(_SubmoduleSource(full_path, entry.object_id, module))
            visit(module, entry.object_id, full_path)

    visit(source, commit, "")
    return tuple(sources)


def _verify_local_submodule(module: Path, commit: str, display_path: str) -> None:
    if module.is_symlink() or not module.is_dir():
        raise ReV2SnapshotError(
            f"submodule is not initialized locally (offline capture cannot fetch): {display_path}"
        )
    try:
        top = Path(
            run_git(["-C", str(module), "rev-parse", "--show-toplevel"]).strip()
        ).resolve()
        observed = run_git(
            ["-C", str(module), "rev-parse", "HEAD^{commit}"]
        ).strip()
        status = run_git(
            [
                "-C",
                str(module),
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ]
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReV2SnapshotError(
            f"submodule is not initialized locally (offline capture cannot fetch): {display_path}"
        ) from exc
    if top != module.resolve():
        raise ReV2SnapshotError(
            f"submodule is not initialized locally (offline capture cannot fetch): {display_path}"
        )
    if observed != commit:
        raise ReV2SnapshotError(f"submodule commit mismatch: {display_path}")
    if status.strip():
        raise ReV2SnapshotError(f"submodule is dirty: {display_path}")


def _git_tree_entries(repository: Path, commit: str) -> tuple[_GitTreeEntry, ...]:
    try:
        output = run_git(
            [
                "-C",
                str(repository),
                "ls-tree",
                "-r",
                "-z",
                "--full-tree",
                commit,
            ]
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReV2SnapshotError(
            f"required Git objects are unavailable locally for {commit}"
        ) from exc
    entries: list[_GitTreeEntry] = []
    for record in output.split("\0"):
        if not record:
            continue
        if "\t" not in record:
            raise ReV2SnapshotError("invalid Git tree output")
        metadata, relative = record.split("\t", 1)
        fields = metadata.split()
        if len(fields) != 3:
            raise ReV2SnapshotError("invalid Git tree output")
        mode, kind, object_id = fields
        _validate_git_relative_path(relative)
        if not object_id or any(character not in "0123456789abcdef" for character in object_id.lower()):
            raise ReV2SnapshotError("invalid Git tree object identity")
        entries.append(_GitTreeEntry(mode, kind, object_id, relative))
    return tuple(entries)


def _validate_git_relative_path(relative: str) -> None:
    path = Path(relative)
    parts = relative.split("/")
    if (
        not relative
        or path.is_absolute()
        or any(part in {"", ".", "..", ".git"} for part in parts)
    ):
        raise ReV2SnapshotError(f"unsafe Git tree path: {relative!r}")


def _materialize_submodules(
    snapshot_root: Path, sources: tuple[_SubmoduleSource, ...]
) -> None:
    for source in sources:
        target = snapshot_root.joinpath(*source.path.split("/"))
        if target.is_symlink():
            raise ReV2SnapshotError(
                f"source snapshot rejects symlink: {source.path}"
            )
        if os.path.lexists(target):
            if not target.is_dir():
                raise ReV2SnapshotError(
                    f"submodule target is not a directory: {source.path}"
                )
            _remove_tree(target)
        target.mkdir(parents=True, mode=0o700)
        for entry in _git_tree_entries(source.repository, source.commit):
            if entry.mode == "160000":
                continue
            if entry.mode == "120000":
                raise ReV2SnapshotError(
                    f"source snapshot rejects symlink: {source.path}/{entry.path}"
                )
            if entry.mode not in {"100644", "100755"} or entry.kind != "blob":
                raise ReV2SnapshotError(
                    f"source snapshot rejects Git tree entry: {source.path}/{entry.path}"
                )
            destination = target.joinpath(*entry.path.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            payload = _run_git_bytes(
                ["-C", str(source.repository), "cat-file", "blob", entry.object_id]
            )
            _write_new_file(destination, payload)
            destination.chmod(0o755 if entry.mode == "100755" else 0o644)


def _run_git_bytes(args: list[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReV2SnapshotError("required Git blob is unavailable locally") from exc
    return completed.stdout


def _manifest_from_json(value: object) -> SnapshotManifest:
    if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
        raise ValueError("manifest must be an object with entries")
    entries = tuple(SnapshotEntry(item["path"], item["digest"], item["mode"], item["size"]) for item in value["entries"])
    kind = value["kind"]
    if kind not in {"git-worktree", "content-snapshot"}:
        raise ValueError("unsupported snapshot kind")
    return SnapshotManifest(value["snapshot_id"], kind, entries, tuple(value["exclusions"]), value.get("git"), value["capture_version"])

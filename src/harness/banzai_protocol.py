"""Fail-closed identity and locking for deployed Banzai candidate protocols."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import os
from pathlib import Path
import stat
from typing import Iterator


_MAX_PROTOCOL_FILE_BYTES = 1024 * 1024
_PROTOCOL_FILES = (
    Path(".echelon/prosaic/subagents/echelon.sage.md"),
    Path(".echelon/runtime/workflow/definition.yaml"),
    Path(".echelon/runtime/workflow/phases/phase1-why2.md"),
)
_LOCK_FILENAME = ".banzai-default-protocol.lock"


class BanzaiProtocolLockError(RuntimeError):
    """Raised when a workspace protocol lock cannot be safely acquired."""


class _UnsafeProtocolPathError(ValueError):
    """Raised when a protocol path cannot be traversed without symlinks."""


@dataclass(frozen=True)
class BanzaiProtocolFingerprint:
    """One verified deployed protocol identity or its fail-closed diagnostic."""

    fingerprint: str | None
    diagnostic: str = ""


def active_banzai_default_protocol_fingerprint(
    project_root: Path,
) -> BanzaiProtocolFingerprint:
    """Identify the deployed files that define WHY2 candidate behavior.

    Each artifact is opened descriptor-relatively below the selected workspace.
    Every directory component and the final file must be non-symlinked. Files
    are opened nonblocking before fstat so special files cannot stall a
    controller retry.
    """
    digest = hashlib.sha256()
    for relative_path in _PROTOCOL_FILES:
        relative_name = relative_path.as_posix()
        payload_or_error = _read_protocol_file(project_root, relative_path)
        if isinstance(payload_or_error, str):
            return BanzaiProtocolFingerprint(
                fingerprint=None,
                diagnostic=f"{relative_name}: {payload_or_error}",
            )
        encoded_path = relative_name.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(payload_or_error).to_bytes(8, "big"))
        digest.update(payload_or_error)
    return BanzaiProtocolFingerprint(fingerprint=f"sha256:{digest.hexdigest()}")


@contextmanager
def banzai_default_protocol_bundle_lock(
    project_root: Path,
    *,
    exclusive: bool,
) -> Iterator[None]:
    """Serialize Echelon bundle refresh against fingerprint-and-consume work.

    This lock is advisory for Echelon-owned bundle deployment. It is held by
    the controller from fingerprint construction through its state CAS, and by
    package deployment while it replaces the managed bundle trees.
    """
    echelon_fd: int | None = None
    lock_fd: int | None = None
    locked = False
    try:
        echelon_fd = _open_echelon_directory(project_root, create=exclusive)
        lock_fd = os.open(
            _LOCK_FILENAME,
            os.O_RDWR | os.O_CREAT | _required_nofollow_flag(),
            0o600,
            dir_fd=echelon_fd,
        )
        metadata = os.fstat(lock_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise BanzaiProtocolLockError("Banzai protocol lock is not a regular file")
        fcntl.flock(lock_fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        locked = True
        yield
    except _UnsafeProtocolPathError as exc:
        raise BanzaiProtocolLockError(str(exc)) from exc
    except OSError as exc:
        raise BanzaiProtocolLockError(
            exc.strerror or "cannot lock Banzai protocol"
        ) from exc
    finally:
        if lock_fd is not None:
            try:
                if locked:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        if echelon_fd is not None:
            os.close(echelon_fd)


def _read_protocol_file(project_root: Path, relative_path: Path) -> bytes | str:
    descriptor: int | None = None
    parent_fd: int | None = None
    try:
        parent_fd = _open_workspace_directory(project_root)
        for component in relative_path.parts[:-1]:
            child_fd = _open_directory_at(parent_fd, component)
            os.close(parent_fd)
            parent_fd = child_fd
        descriptor = os.open(
            relative_path.name,
            os.O_RDONLY
            | os.O_NONBLOCK
            | _required_nofollow_flag()
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return "not a regular file"
        if metadata.st_size > _MAX_PROTOCOL_FILE_BYTES:
            return "exceeds 1 MiB"
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = None
            payload = stream.read(_MAX_PROTOCOL_FILE_BYTES + 1)
    except _UnsafeProtocolPathError as exc:
        return str(exc)
    except OSError as exc:
        return exc.strerror or "unreadable"
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_fd is not None:
            os.close(parent_fd)
    if len(payload) > _MAX_PROTOCOL_FILE_BYTES:
        return "exceeds 1 MiB"
    return payload


def _required_nofollow_flag() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if type(nofollow) is not int:
        raise _UnsafeProtocolPathError("symlink-safe open is unavailable")
    return nofollow


def _open_workspace_directory(project_root: Path) -> int:
    return _open_directory_path(Path(project_root).resolve())


def _open_echelon_directory(project_root: Path, *, create: bool) -> int:
    root_fd = _open_workspace_directory(project_root)
    try:
        if create:
            try:
                os.mkdir(".echelon", 0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
        return _open_directory_at(root_fd, ".echelon")
    finally:
        os.close(root_fd)


def _open_directory_path(path: Path) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | _required_nofollow_flag()
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise _UnsafeProtocolPathError("workspace root is not a directory")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_directory_at(parent_fd: int, name: str) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | _required_nofollow_flag()
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise _UnsafeProtocolPathError(f"{name}: not a directory")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise

"""Durable file-level staging for controller-independent squad publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised by the capability gate
    _fcntl = None


_SCHEMA_VERSION = 1
_OUTBOX_DIRECTORY = ".publication-outbox"
_PUBLICATION_CONTROL_DIRECTORY = Path(".echelon/runtime")
_PUBLICATION_LOCK_NAME = "publication.lock"
_PUBLICATION_LOCK_RELATIVE = (
    _PUBLICATION_CONTROL_DIRECTORY / _PUBLICATION_LOCK_NAME
)
_MANIFEST_NAME = "manifest.json"
_TRANSACTION_ID_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")
_SHA256_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")
_ERROR_CODES = frozenset(
    {
        "manifest_invalid",
        "manifest_mismatch",
        "publish_io",
        "stage_corrupt",
        "stage_missing",
        "state_finalize",
        "target_drift",
    }
)


class PublicationError(Exception):
    """Bounded publication failure that never includes a filesystem path."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in _ERROR_CODES:
            code = "publish_io"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PublicationMarker:
    """Exact state-store identity for one sealed publication manifest."""

    schema_version: int
    transaction_id: str
    manifest_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "transaction_id": self.transaction_id,
            "manifest_sha256": self.manifest_sha256,
        }


def _raise(code: str) -> None:
    raise PublicationError(code)


def _secure_posix_capabilities_available() -> bool:
    """Return whether descriptor-safe publication is available."""

    required_flags = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    required_dir_fd_functions = (
        os.open,
        os.mkdir,
        os.rmdir,
        os.stat,
        os.unlink,
    )
    return bool(
        os.name == "posix"
        and _fcntl is not None
        and callable(getattr(_fcntl, "flock", None))
        and type(getattr(_fcntl, "LOCK_EX", None)) is int
        and type(getattr(_fcntl, "LOCK_UN", None)) is int
        and all(
            type(getattr(os, name, None)) is int
            and getattr(os, name) != 0
            for name in required_flags
        )
        and all(
            function in os.supports_dir_fd
            for function in required_dir_fd_functions
        )
        and os.stat in os.supports_follow_symlinks
        and os.listdir in os.supports_fd
    )


def _require_secure_posix() -> None:
    if not _secure_posix_capabilities_available():
        _raise("publish_io")


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _regular_open_flags() -> int:
    # O_NONBLOCK prevents a hostile FIFO replacement from blocking.
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def _validate_transaction_id(value: object) -> str:
    if (
        type(value) is not str
        or _TRANSACTION_ID_PATTERN.fullmatch(value) is None
    ):
        _raise("manifest_invalid")
    return value


def _validate_sha256(value: object) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        _raise("manifest_invalid")
    return value


def _marker_from(value: object) -> PublicationMarker:
    if type(value) is PublicationMarker:
        candidate = value
    elif (
        type(value) is dict
        and frozenset(dict.keys(value))
        == frozenset(
            {"schema_version", "transaction_id", "manifest_sha256"}
        )
    ):
        candidate = PublicationMarker(
            schema_version=dict.__getitem__(value, "schema_version"),
            transaction_id=dict.__getitem__(value, "transaction_id"),
            manifest_sha256=dict.__getitem__(value, "manifest_sha256"),
        )
    else:
        _raise("manifest_invalid")
    if (
        type(candidate.schema_version) is not int
        or candidate.schema_version != _SCHEMA_VERSION
    ):
        _raise("manifest_invalid")
    return PublicationMarker(
        schema_version=_SCHEMA_VERSION,
        transaction_id=_validate_transaction_id(candidate.transaction_id),
        manifest_sha256=_validate_sha256(candidate.manifest_sha256),
    )


def _normalize_relative_path(value: object) -> Path:
    if isinstance(value, PurePosixPath):
        raw = value.as_posix()
    elif type(value) is str:
        raw = value
    else:
        _raise("manifest_invalid")
    if not raw or "\x00" in raw or "\\" in raw:
        _raise("manifest_invalid")
    posix = PurePosixPath(raw)
    if (
        posix.is_absolute()
        or raw in {".", ""}
        or any(part in {"", ".", ".."} for part in posix.parts)
        or posix.as_posix() != raw
    ):
        _raise("manifest_invalid")
    return Path(*posix.parts)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _lstat(path: Path, *, missing_code: str) -> os.stat_result:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        _raise(missing_code)
    except OSError:
        _raise("publish_io")


def _require_real_directory(
    path: Path,
    *,
    code: str,
    missing_code: str | None = None,
) -> Path:
    metadata = _lstat(path, missing_code=missing_code or code)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        _raise(code)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        _raise(code)
    if resolved != path.absolute():
        _raise(code)
    return resolved


def _open_directory(
    path: str | Path,
    *,
    dir_fd: int | None = None,
    missing_code: str,
    invalid_code: str,
) -> int:
    candidate = Path(path)
    if dir_fd is None and candidate.is_absolute() and candidate != Path("/"):
        try:
            current_fd = os.open(Path("/"), _directory_open_flags())
        except OSError:
            _raise(invalid_code)
        try:
            for part in candidate.parts[1:]:
                next_fd = _open_directory(
                    part,
                    dir_fd=current_fd,
                    missing_code=missing_code,
                    invalid_code=invalid_code,
                )
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except BaseException:
            os.close(current_fd)
            raise
    try:
        fd = os.open(path, _directory_open_flags(), dir_fd=dir_fd)
    except FileNotFoundError:
        _raise(missing_code)
    except OSError:
        _raise(invalid_code)
    try:
        metadata = os.fstat(fd)
    except OSError:
        os.close(fd)
        _raise(invalid_code)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        os.close(fd)
        _raise(invalid_code)
    return fd


def _open_regular_at(
    root_fd: int,
    relative: Path,
    *,
    missing_code: str,
    invalid_code: str,
) -> int:
    """Open a descendant regular file without following any path component."""

    try:
        current_fd = os.dup(root_fd)
    except OSError:
        _raise(invalid_code)
    try:
        for part in relative.parts[:-1]:
            next_fd = _open_directory(
                part,
                dir_fd=current_fd,
                missing_code=missing_code,
                invalid_code=invalid_code,
            )
            os.close(current_fd)
            current_fd = next_fd
        try:
            result_fd = os.open(
                relative.name,
                _regular_open_flags(),
                dir_fd=current_fd,
            )
        except FileNotFoundError:
            _raise(missing_code)
        except OSError:
            _raise(invalid_code)
        try:
            metadata = os.fstat(result_fd)
        except OSError:
            os.close(result_fd)
            _raise(invalid_code)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(result_fd)
            _raise(invalid_code)
        return result_fd
    finally:
        os.close(current_fd)


def _regular_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _hash_fd(fd: int, *, code: str) -> str:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        os.lseek(fd, 0, os.SEEK_SET)
        return digest.hexdigest()
    except OSError:
        _raise(code)


def _read_fd_bytes(fd: int, *, code: str) -> bytes:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                os.lseek(fd, 0, os.SEEK_SET)
                return b"".join(chunks)
            chunks.append(chunk)
    except OSError:
        _raise(code)


@dataclass(frozen=True)
class _PinnedRegular:
    relative: Path
    fd: int
    identity: tuple[int, ...]
    sha256: str


def _pin_regular_at(
    root_fd: int,
    relative: Path,
    *,
    missing_code: str,
    invalid_code: str,
) -> _PinnedRegular:
    fd = _open_regular_at(
        root_fd,
        relative,
        missing_code=missing_code,
        invalid_code=invalid_code,
    )
    try:
        before = os.fstat(fd)
        digest = _hash_fd(fd, code=invalid_code)
        after = os.fstat(fd)
    except PublicationError:
        os.close(fd)
        raise
    except OSError:
        os.close(fd)
        _raise(invalid_code)
    identity = _regular_identity(before)
    if identity != _regular_identity(after):
        os.close(fd)
        _raise(invalid_code)
    return _PinnedRegular(
        relative=relative,
        fd=fd,
        identity=identity,
        sha256=digest,
    )


def _verify_pinned_regular(
    root_fd: int,
    pinned: _PinnedRegular,
    *,
    missing_code: str,
    invalid_code: str,
) -> None:
    reopened = _pin_regular_at(
        root_fd,
        pinned.relative,
        missing_code=missing_code,
        invalid_code=invalid_code,
    )
    try:
        if (
            reopened.identity != pinned.identity
            or reopened.sha256 != pinned.sha256
        ):
            _raise(invalid_code)
    finally:
        os.close(reopened.fd)


def _fsync_relative_parent_directories(
    root_fd: int,
    relative: Path,
    *,
    code: str,
) -> None:
    opened: list[int] = []
    try:
        current_fd = os.dup(root_fd)
        opened.append(current_fd)
        for part in relative.parts[:-1]:
            current_fd = _open_directory(
                part,
                dir_fd=current_fd,
                missing_code=code,
                invalid_code=code,
            )
            opened.append(current_fd)
        for fd in reversed(opened):
            os.fsync(fd)
    except PublicationError:
        raise
    except OSError:
        _raise(code)
    finally:
        for fd in reversed(opened):
            try:
                os.close(fd)
            except OSError:
                pass


def _validate_existing_ancestors(
    root: Path,
    relative: Path,
    *,
    code: str,
) -> None:
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        try:
            metadata = os.lstat(cursor)
        except FileNotFoundError:
            break
        except (OSError, TypeError, NotImplementedError):
            _raise("publish_io")
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(
            metadata.st_mode
        ):
            _raise(code)
    try:
        resolved = (root / relative).resolve(strict=False)
    except (OSError, RuntimeError):
        _raise(code)
    if not _is_relative_to(resolved, root):
        _raise(code)


def _durable_write_bytes_at(
    parent_fd: int,
    name: str,
    content: bytes,
) -> None:
    temporary_name = f".{name}-{secrets.token_hex(12)}.tmp"
    temporary_fd: int | None = None
    try:
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        view = memoryview(content)
        while view:
            written = os.write(temporary_fd, view)
            view = view[written:]
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
        os.replace(
            temporary_name,
            name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        os.fsync(parent_fd)
    except (OSError, TypeError, NotImplementedError):
        if temporary_fd is not None:
            try:
                os.close(temporary_fd)
            except OSError:
                pass
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except OSError:
            pass
        _raise("publish_io")


def _open_regular(path: Path, *, missing_code: str, invalid_code: str) -> int:
    try:
        fd = os.open(path, _regular_open_flags())
    except FileNotFoundError:
        _raise(missing_code)
    except OSError:
        _raise(invalid_code)
    try:
        metadata = os.fstat(fd)
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        _raise(invalid_code)
    if not stat.S_ISREG(metadata.st_mode):
        try:
            os.close(fd)
        except OSError:
            pass
        _raise(invalid_code)
    return fd


def _hash_regular(
    path: Path,
    *,
    missing_code: str,
    invalid_code: str,
    sync: bool = False,
) -> str:
    fd = _open_regular(
        path,
        missing_code=missing_code,
        invalid_code=invalid_code,
    )
    try:
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if sync:
            os.fsync(fd)
        return digest.hexdigest()
    except OSError:
        _raise(invalid_code)
    finally:
        os.close(fd)


def _target_image(
    project_root: Path,
    relative: Path,
    *,
    invalid_code: str,
) -> dict[str, str]:
    _validate_existing_ancestors(
        project_root,
        relative,
        code=invalid_code,
    )
    target = project_root / relative
    try:
        metadata = os.lstat(target)
    except FileNotFoundError:
        return {"kind": "missing"}
    except OSError:
        _raise("publish_io")
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        _raise(invalid_code)
    return {
        "kind": "file",
        "sha256": _hash_regular(
            target,
            missing_code=invalid_code,
            invalid_code=invalid_code,
        ),
    }


def _target_image_at(parent_fd: int, name: str) -> dict[str, str]:
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return {"kind": "missing"}
    except OSError:
        _raise("publish_io")
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        _raise("target_drift")
    try:
        fd = os.open(name, _regular_open_flags(), dir_fd=parent_fd)
    except FileNotFoundError:
        return {"kind": "missing"}
    except OSError:
        _raise("target_drift")
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            _raise("target_drift")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        return {"kind": "file", "sha256": digest.hexdigest()}
    except OSError:
        _raise("target_drift")
    finally:
        os.close(fd)


def _open_parent_directory(
    project_root: Path,
    relative: Path,
    *,
    create: bool,
) -> int:
    current_fd = _open_directory(
        project_root,
        missing_code="target_drift",
        invalid_code="target_drift",
    )
    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(
                    part,
                    _directory_open_flags(),
                    dir_fd=current_fd,
                )
            except FileNotFoundError:
                if not create:
                    _raise("target_drift")
                try:
                    os.mkdir(part, dir_fd=current_fd)
                    os.fsync(current_fd)
                    next_fd = os.open(
                        part,
                        _directory_open_flags(),
                        dir_fd=current_fd,
                    )
                    os.fsync(next_fd)
                except FileExistsError:
                    try:
                        next_fd = os.open(
                            part,
                            _directory_open_flags(),
                            dir_fd=current_fd,
                        )
                    except OSError:
                        _raise("target_drift")
                except OSError:
                    _raise("publish_io")
            except OSError:
                _raise("target_drift")
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _fsync_target_directory_chain(
    project_root: Path,
    relative: Path,
) -> None:
    root_fd = _open_directory(
        project_root,
        missing_code="publish_io",
        invalid_code="publish_io",
    )
    try:
        _fsync_relative_parent_directories(
            root_fd,
            relative,
            code="publish_io",
        )
    finally:
        os.close(root_fd)


def _copy_pinned_stage_to_temporary(
    pinned: _PinnedRegular,
    parent_fd: int,
    expected_digest: str,
) -> str:
    try:
        before = os.fstat(pinned.fd)
    except OSError:
        _raise("stage_corrupt")
    if _regular_identity(before) != pinned.identity:
        _raise("stage_corrupt")
    temporary_name = f".echelon-publish-{secrets.token_hex(12)}.tmp"
    try:
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_fd,
        )
    except OSError:
        _raise("publish_io")
    try:
        os.lseek(pinned.fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while True:
            chunk = os.read(pinned.fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(temporary_fd, view)
                view = view[written:]
        os.fsync(temporary_fd)
        os.lseek(pinned.fd, 0, os.SEEK_SET)
        after = os.fstat(pinned.fd)
        if (
            digest.hexdigest() != expected_digest
            or _regular_identity(after) != pinned.identity
        ):
            _raise("stage_corrupt")
        return temporary_name
    except PublicationError:
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except OSError:
            pass
        raise
    except OSError:
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except OSError:
            pass
        _raise("stage_corrupt")
    finally:
        os.close(temporary_fd)


def _canonical_json(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, UnicodeError):
        _raise("manifest_invalid")


def _overlaps(left: Path, right: Path) -> bool:
    left_parts = left.parts
    right_parts = right.parts
    shortest = min(len(left_parts), len(right_parts))
    return left_parts[:shortest] == right_parts[:shortest]


def _validate_target_namespace(
    project_root: Path,
    squad_dir: Path,
    target: Path,
) -> None:
    protected = (
        squad_dir / _OUTBOX_DIRECTORY,
        project_root / _PUBLICATION_LOCK_RELATIVE,
    )
    for absolute in protected:
        try:
            relative = absolute.relative_to(project_root)
        except ValueError:
            continue
        if _overlaps(target, relative):
            _raise("manifest_invalid")


def _validate_image(value: object) -> dict[str, str]:
    if type(value) is not dict:
        _raise("manifest_invalid")
    keys = frozenset(dict.keys(value))
    kind = dict.get(value, "kind")
    if type(kind) is not str:
        _raise("manifest_invalid")
    if kind == "missing":
        if keys != frozenset({"kind"}):
            _raise("manifest_invalid")
        return {"kind": "missing"}
    if kind == "file":
        if keys != frozenset({"kind", "sha256"}):
            _raise("manifest_invalid")
        return {
            "kind": "file",
            "sha256": _validate_sha256(dict.get(value, "sha256")),
        }
    _raise("manifest_invalid")


def _validate_manifest(
    value: object,
    *,
    marker: PublicationMarker,
    project_root: Path,
    squad_dir: Path,
) -> dict[str, object]:
    if (
        type(value) is not dict
        or frozenset(dict.keys(value))
        != frozenset({"schema_version", "transaction_id", "operations"})
        or type(dict.get(value, "schema_version")) is not int
        or dict.get(value, "schema_version") != _SCHEMA_VERSION
        or dict.get(value, "transaction_id") != marker.transaction_id
        or type(dict.get(value, "operations")) is not list
    ):
        _raise("manifest_invalid")
    operations: list[dict[str, object]] = []
    previous_target: Path | None = None
    for raw_operation in dict.__getitem__(value, "operations"):
        if type(raw_operation) is not dict:
            _raise("manifest_invalid")
        action = dict.get(raw_operation, "action")
        if type(action) is not str or action not in {"write", "delete"}:
            _raise("manifest_invalid")
        expected_keys = (
            frozenset(
                {"action", "target", "preimage", "postimage", "staged"}
            )
            if action == "write"
            else frozenset({"action", "target", "preimage", "postimage"})
        )
        if frozenset(dict.keys(raw_operation)) != expected_keys:
            _raise("manifest_invalid")
        target = _normalize_relative_path(dict.get(raw_operation, "target"))
        _validate_target_namespace(project_root, squad_dir, target)
        _validate_existing_ancestors(
            project_root,
            target,
            code="target_drift",
        )
        if previous_target is not None:
            if target.as_posix() <= previous_target.as_posix():
                _raise("manifest_invalid")
            if _overlaps(previous_target, target):
                _raise("manifest_invalid")
        previous_target = target
        preimage = _validate_image(dict.get(raw_operation, "preimage"))
        postimage = _validate_image(dict.get(raw_operation, "postimage"))
        operation: dict[str, object] = {
            "action": action,
            "target": target.as_posix(),
            "preimage": preimage,
            "postimage": postimage,
        }
        if action == "write":
            if postimage["kind"] != "file":
                _raise("manifest_invalid")
            staged = _normalize_relative_path(
                dict.get(raw_operation, "staged")
            )
            if staged == Path(_MANIFEST_NAME):
                _raise("manifest_invalid")
            operation["staged"] = staged.as_posix()
        elif postimage != {"kind": "missing"}:
            _raise("manifest_invalid")
        operations.append(operation)
    return {
        "schema_version": _SCHEMA_VERSION,
        "transaction_id": marker.transaction_id,
        "operations": operations,
    }


def _directory_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode)


def _verify_directory_entry(
    parent_fd: int,
    name: str,
    opened_fd: int,
) -> None:
    try:
        opened = os.fstat(opened_fd)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except (OSError, TypeError, NotImplementedError):
        _raise("publish_io")
    if (
        stat.S_ISLNK(current.st_mode)
        or not stat.S_ISDIR(current.st_mode)
        or _directory_identity(opened) != _directory_identity(current)
    ):
        _raise("publish_io")


def _open_or_create_control_directory(
    parent_fd: int,
    name: str,
) -> int:
    created = False
    try:
        os.mkdir(name, dir_fd=parent_fd)
        created = True
    except FileExistsError:
        pass
    except (OSError, TypeError, NotImplementedError):
        _raise("publish_io")
    opened_fd = _open_directory(
        name,
        dir_fd=parent_fd,
        missing_code="publish_io",
        invalid_code="publish_io",
    )
    try:
        _verify_directory_entry(parent_fd, name, opened_fd)
        if created:
            os.fsync(opened_fd)
            os.fsync(parent_fd)
        return opened_fd
    except BaseException:
        os.close(opened_fd)
        raise


@contextmanager
def _publication_exclusivity(project_root: Path) -> Iterator[None]:
    """Serialize project-wide Echelon target prechecks and mutations."""

    _require_secure_posix()
    project_fd = _open_directory(
        project_root,
        missing_code="publish_io",
        invalid_code="publish_io",
    )
    echelon_fd: int | None = None
    control_fd: int | None = None
    lock_fd: int | None = None
    created = False
    try:
        echelon_fd = _open_or_create_control_directory(
            project_fd,
            _PUBLICATION_CONTROL_DIRECTORY.parts[0],
        )
        control_fd = _open_or_create_control_directory(
            echelon_fd,
            _PUBLICATION_CONTROL_DIRECTORY.parts[1],
        )
        create_flags = (
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | os.O_NONBLOCK
        )
        try:
            lock_fd = os.open(
                _PUBLICATION_LOCK_NAME,
                create_flags,
                0o600,
                dir_fd=control_fd,
            )
            created = True
        except FileExistsError:
            try:
                lock_fd = os.open(
                    _PUBLICATION_LOCK_NAME,
                    os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=control_fd,
                )
            except (OSError, TypeError, NotImplementedError):
                _raise("publish_io")
        except (OSError, TypeError, NotImplementedError):
            _raise("publish_io")
        try:
            opened = os.fstat(lock_fd)
            current = os.stat(
                _PUBLICATION_LOCK_NAME,
                dir_fd=control_fd,
                follow_symlinks=False,
            )
        except (OSError, TypeError, NotImplementedError):
            _raise("publish_io")
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (current.st_dev, current.st_ino)
        ):
            _raise("publish_io")
        if created:
            try:
                os.fsync(lock_fd)
                os.fsync(control_fd)
            except (OSError, TypeError, NotImplementedError):
                _raise("publish_io")
        try:
            assert _fcntl is not None
            _fcntl.flock(lock_fd, _fcntl.LOCK_EX)
            locked = os.fstat(lock_fd)
            current = os.stat(
                _PUBLICATION_LOCK_NAME,
                dir_fd=control_fd,
                follow_symlinks=False,
            )
        except (OSError, TypeError, NotImplementedError):
            _raise("publish_io")
        if (
            not stat.S_ISREG(current.st_mode)
            or (locked.st_dev, locked.st_ino)
            != (current.st_dev, current.st_ino)
        ):
            _raise("publish_io")
        _verify_directory_entry(
            project_fd,
            _PUBLICATION_CONTROL_DIRECTORY.parts[0],
            echelon_fd,
        )
        _verify_directory_entry(
            echelon_fd,
            _PUBLICATION_CONTROL_DIRECTORY.parts[1],
            control_fd,
        )
        try:
            yield
        finally:
            try:
                _fcntl.flock(lock_fd, _fcntl.LOCK_UN)
            except (OSError, TypeError, AttributeError, NotImplementedError):
                pass
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
        if control_fd is not None:
            try:
                os.close(control_fd)
            except OSError:
                pass
        if echelon_fd is not None:
            try:
                os.close(echelon_fd)
            except OSError:
                pass
        try:
            os.close(project_fd)
        except OSError:
            pass


@dataclass
class _PinnedTransaction:
    squad_fd: int
    outbox_fd: int
    outbox_identity: tuple[int, int, int]
    transaction_fd: int
    transaction_id: str
    transaction_identity: tuple[int, int, int]
    marker: PublicationMarker
    manifest: _PinnedRegular
    stages: dict[str, _PinnedRegular]

    def verify(self) -> None:
        _verify_transaction_directories(
            self.squad_fd,
            self.outbox_fd,
            self.outbox_identity,
            self.transaction_fd,
            self.transaction_id,
            self.transaction_identity,
        )
        _verify_pinned_regular(
            self.transaction_fd,
            self.manifest,
            missing_code="stage_missing",
            invalid_code="manifest_invalid",
        )
        if self.manifest.sha256 != self.marker.manifest_sha256:
            _raise("manifest_mismatch")
        for pinned in self.stages.values():
            _verify_pinned_regular(
                self.transaction_fd,
                pinned,
                missing_code="stage_missing",
                invalid_code="stage_corrupt",
            )

    def close(self) -> None:
        for pinned in self.stages.values():
            try:
                os.close(pinned.fd)
            except OSError:
                pass
        try:
            os.close(self.manifest.fd)
        except OSError:
            pass
        try:
            os.close(self.transaction_fd)
        except OSError:
            pass
        try:
            os.close(self.outbox_fd)
        except OSError:
            pass
        try:
            os.close(self.squad_fd)
        except OSError:
            pass


def _verify_transaction_directories(
    squad_fd: int,
    outbox_fd: int,
    outbox_identity: tuple[int, int, int],
    transaction_fd: int,
    transaction_id: str,
    transaction_identity: tuple[int, int, int],
) -> None:
    try:
        outbox_entry = os.stat(
            _OUTBOX_DIRECTORY,
            dir_fd=squad_fd,
            follow_symlinks=False,
        )
        opened_outbox = os.fstat(outbox_fd)
        transaction_entry = os.stat(
            transaction_id,
            dir_fd=outbox_fd,
            follow_symlinks=False,
        )
        opened_transaction = os.fstat(transaction_fd)
    except FileNotFoundError:
        _raise("stage_missing")
    except (OSError, TypeError, NotImplementedError):
        _raise("stage_corrupt")
    if (
        stat.S_ISLNK(outbox_entry.st_mode)
        or not stat.S_ISDIR(outbox_entry.st_mode)
        or _directory_identity(outbox_entry) != outbox_identity
        or _directory_identity(opened_outbox) != outbox_identity
        or stat.S_ISLNK(transaction_entry.st_mode)
        or not stat.S_ISDIR(transaction_entry.st_mode)
        or _directory_identity(transaction_entry) != transaction_identity
        or _directory_identity(opened_transaction) != transaction_identity
    ):
        _raise("stage_corrupt")


def _open_transaction_directories(
    squad_dir: Path,
    marker: PublicationMarker,
) -> tuple[
    int,
    int,
    tuple[int, int, int],
    int,
    tuple[int, int, int],
]:
    squad_fd = _open_directory(
        squad_dir,
        missing_code="stage_missing",
        invalid_code="stage_corrupt",
    )
    outbox_fd: int | None = None
    transaction_fd: int | None = None
    try:
        outbox_fd = _open_directory(
            _OUTBOX_DIRECTORY,
            dir_fd=squad_fd,
            missing_code="stage_missing",
            invalid_code="stage_corrupt",
        )
        opened_outbox = os.fstat(outbox_fd)
        outbox_entry = os.stat(
            _OUTBOX_DIRECTORY,
            dir_fd=squad_fd,
            follow_symlinks=False,
        )
        outbox_identity = _directory_identity(opened_outbox)
        if (
            stat.S_ISLNK(outbox_entry.st_mode)
            or not stat.S_ISDIR(outbox_entry.st_mode)
            or _directory_identity(outbox_entry) != outbox_identity
        ):
            _raise("stage_corrupt")
        transaction_fd = _open_directory(
            marker.transaction_id,
            dir_fd=outbox_fd,
            missing_code="stage_missing",
            invalid_code="stage_corrupt",
        )
        opened = os.fstat(transaction_fd)
        current = os.stat(
            marker.transaction_id,
            dir_fd=outbox_fd,
            follow_symlinks=False,
        )
    except PublicationError:
        if transaction_fd is not None:
            os.close(transaction_fd)
        if outbox_fd is not None:
            os.close(outbox_fd)
        os.close(squad_fd)
        raise
    except FileNotFoundError:
        if transaction_fd is not None:
            os.close(transaction_fd)
        if outbox_fd is not None:
            os.close(outbox_fd)
        os.close(squad_fd)
        _raise("stage_missing")
    except (OSError, TypeError, NotImplementedError):
        if transaction_fd is not None:
            os.close(transaction_fd)
        if outbox_fd is not None:
            os.close(outbox_fd)
        os.close(squad_fd)
        _raise("stage_corrupt")
    assert outbox_fd is not None
    assert transaction_fd is not None
    identity = _directory_identity(opened)
    if (
        stat.S_ISLNK(current.st_mode)
        or not stat.S_ISDIR(current.st_mode)
        or _directory_identity(current) != identity
    ):
        os.close(transaction_fd)
        os.close(outbox_fd)
        os.close(squad_fd)
        _raise("stage_corrupt")
    return (
        squad_fd,
        outbox_fd,
        outbox_identity,
        transaction_fd,
        identity,
    )


def _load_prepared_pinned(
    project_root: Path,
    squad_dir: Path,
    marker: object,
) -> tuple[PreparedSquadPublication, _PinnedTransaction]:
    _require_secure_posix()
    validated_marker = _marker_from(marker)
    try:
        project = _require_real_directory(
            Path(project_root),
            code="manifest_invalid",
        )
        squad = _require_real_directory(
            Path(squad_dir),
            code="manifest_invalid",
        )
    except TypeError:
        _raise("manifest_invalid")
    (
        squad_fd,
        outbox_fd,
        outbox_identity,
        transaction_fd,
        transaction_identity,
    ) = _open_transaction_directories(squad, validated_marker)
    manifest: _PinnedRegular | None = None
    stages: dict[str, _PinnedRegular] = {}
    try:
        manifest = _pin_regular_at(
            transaction_fd,
            Path(_MANIFEST_NAME),
            missing_code="stage_missing",
            invalid_code="manifest_invalid",
        )
        manifest_bytes = _read_fd_bytes(
            manifest.fd,
            code="manifest_invalid",
        )
        if hashlib.sha256(manifest_bytes).hexdigest() != manifest.sha256:
            _raise("manifest_invalid")
        if manifest.sha256 != validated_marker.manifest_sha256:
            _raise("manifest_mismatch")
        try:
            decoded = manifest_bytes.decode("utf-8")
            raw_manifest = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            _raise("manifest_invalid")
        decoded_manifest = _validate_manifest(
            raw_manifest,
            marker=validated_marker,
            project_root=project,
            squad_dir=squad,
        )
        if _canonical_json(decoded_manifest) != manifest_bytes:
            _raise("manifest_invalid")
        for operation in decoded_manifest["operations"]:
            if operation["action"] != "write":
                continue
            staged_name = str(operation["staged"])
            if staged_name not in stages:
                stages[staged_name] = _pin_regular_at(
                    transaction_fd,
                    Path(staged_name),
                    missing_code="stage_missing",
                    invalid_code="stage_corrupt",
                )
            if (
                stages[staged_name].sha256
                != dict(operation["postimage"])["sha256"]
            ):
                _raise("stage_corrupt")
        pinned = _PinnedTransaction(
            squad_fd=squad_fd,
            outbox_fd=outbox_fd,
            outbox_identity=outbox_identity,
            transaction_fd=transaction_fd,
            transaction_id=validated_marker.transaction_id,
            transaction_identity=transaction_identity,
            marker=validated_marker,
            manifest=manifest,
            stages=stages,
        )
        return (
            PreparedSquadPublication(
                _project_root=project,
                _squad_dir=squad,
                _transaction_root=(
                    squad
                    / _OUTBOX_DIRECTORY
                    / validated_marker.transaction_id
                ),
                _manifest=decoded_manifest,
                marker=validated_marker,
            ),
            pinned,
        )
    except BaseException:
        for pinned_stage in stages.values():
            os.close(pinned_stage.fd)
        if manifest is not None:
            os.close(manifest.fd)
        os.close(transaction_fd)
        os.close(outbox_fd)
        os.close(squad_fd)
        raise


def _remove_directory_contents(directory_fd: int) -> None:
    """Remove only descendants reached through a retained directory FD."""

    try:
        names = os.listdir(directory_fd)
    except (OSError, TypeError, NotImplementedError):
        _raise("publish_io")
    for name in names:
        try:
            metadata = os.stat(
                name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            _raise("stage_corrupt")
        except (OSError, TypeError, NotImplementedError):
            _raise("publish_io")
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(
            metadata.st_mode
        ):
            child_fd = _open_directory(
                name,
                dir_fd=directory_fd,
                missing_code="stage_corrupt",
                invalid_code="stage_corrupt",
            )
            try:
                opened = os.fstat(child_fd)
                if _directory_identity(opened) != _directory_identity(
                    metadata
                ):
                    _raise("stage_corrupt")
                _remove_directory_contents(child_fd)
                current = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if _directory_identity(current) != _directory_identity(
                    opened
                ):
                    _raise("stage_corrupt")
                os.rmdir(name, dir_fd=directory_fd)
            except PublicationError:
                raise
            except FileNotFoundError:
                _raise("stage_corrupt")
            except (OSError, TypeError, NotImplementedError):
                _raise("publish_io")
            finally:
                os.close(child_fd)
        else:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                _raise("stage_corrupt")
            except (OSError, TypeError, NotImplementedError):
                _raise("publish_io")
    try:
        os.fsync(directory_fd)
    except OSError:
        _raise("publish_io")


@dataclass(frozen=True)
class PreparedSquadPublication:
    """A sealed and verified transaction that is safe to publish later."""

    _project_root: Path
    _squad_dir: Path
    _transaction_root: Path
    _manifest: dict[str, object]
    marker: PublicationMarker

    def _publish_write(
        self,
        operation: dict[str, object],
        pinned: _PinnedRegular,
        transaction_fd: int,
    ) -> None:
        relative = Path(str(operation["target"]))
        expected_preimage = dict(operation["preimage"])
        expected_postimage = dict(operation["postimage"])
        expected_digest = str(expected_postimage["sha256"])
        _verify_pinned_regular(
            transaction_fd,
            pinned,
            missing_code="stage_missing",
            invalid_code="stage_corrupt",
        )
        if pinned.sha256 != expected_digest:
            _raise("stage_corrupt")
        parent_fd = _open_parent_directory(
            self._project_root,
            relative,
            create=True,
        )
        temporary_name: str | None = None
        try:
            temporary_name = _copy_pinned_stage_to_temporary(
                pinned,
                parent_fd,
                expected_digest,
            )
            if (
                _target_image_at(parent_fd, relative.name)
                != expected_preimage
            ):
                _raise("target_drift")
            try:
                os.replace(
                    temporary_name,
                    relative.name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                temporary_name = None
                os.fsync(parent_fd)
            except (OSError, TypeError, NotImplementedError):
                _raise("publish_io")
            if (
                _target_image_at(parent_fd, relative.name)
                != expected_postimage
            ):
                _raise("target_drift")
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name, dir_fd=parent_fd)
                except OSError:
                    pass
            os.close(parent_fd)
        _fsync_target_directory_chain(self._project_root, relative)
        if (
            _target_image(
                self._project_root,
                relative,
                invalid_code="target_drift",
            )
            != expected_postimage
        ):
            _raise("target_drift")

    def _publish_delete(self, operation: dict[str, object]) -> None:
        relative = Path(str(operation["target"]))
        expected_preimage = dict(operation["preimage"])
        parent_fd = _open_parent_directory(
            self._project_root,
            relative,
            create=False,
        )
        try:
            if (
                _target_image_at(parent_fd, relative.name)
                != expected_preimage
            ):
                _raise("target_drift")
            try:
                os.unlink(relative.name, dir_fd=parent_fd)
                os.fsync(parent_fd)
            except (OSError, TypeError, NotImplementedError):
                _raise("publish_io")
            if _target_image_at(parent_fd, relative.name) != {
                "kind": "missing"
            }:
                _raise("target_drift")
        finally:
            os.close(parent_fd)
        _fsync_target_directory_chain(self._project_root, relative)
        if _target_image(
            self._project_root,
            relative,
            invalid_code="target_drift",
        ) != {"kind": "missing"}:
            _raise("target_drift")

    def _durably_accept_postimage(
        self,
        operation: dict[str, object],
    ) -> None:
        relative = Path(str(operation["target"]))
        expected_postimage = dict(operation["postimage"])
        parent_fd = _open_parent_directory(
            self._project_root,
            relative,
            create=False,
        )
        try:
            if (
                _target_image_at(parent_fd, relative.name)
                != expected_postimage
            ):
                _raise("target_drift")
            if expected_postimage["kind"] == "file":
                try:
                    target_fd = os.open(
                        relative.name,
                        _regular_open_flags(),
                        dir_fd=parent_fd,
                    )
                except OSError:
                    _raise("target_drift")
                try:
                    before = os.fstat(target_fd)
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or _hash_fd(target_fd, code="target_drift")
                        != expected_postimage["sha256"]
                    ):
                        _raise("target_drift")
                    try:
                        os.fsync(target_fd)
                    except OSError:
                        _raise("publish_io")
                    after = os.fstat(target_fd)
                    if _regular_identity(after) != _regular_identity(before):
                        _raise("target_drift")
                except PublicationError:
                    raise
                except OSError:
                    _raise("target_drift")
                finally:
                    os.close(target_fd)
            try:
                os.fsync(parent_fd)
            except OSError:
                _raise("publish_io")
            if (
                _target_image_at(parent_fd, relative.name)
                != expected_postimage
            ):
                _raise("target_drift")
        finally:
            os.close(parent_fd)
        _fsync_target_directory_chain(self._project_root, relative)
        if (
            _target_image(
                self._project_root,
                relative,
                invalid_code="target_drift",
            )
            != expected_postimage
        ):
            _raise("target_drift")

    @staticmethod
    def _run_fault_hook(
        fault_hook: Callable[[int], None] | None,
        position: int,
    ) -> None:
        if fault_hook is None:
            return
        try:
            fault_hook(position)
        except PublicationError:
            raise
        except Exception:
            _raise("publish_io")

    def publish(
        self,
        fault_hook: Callable[[int], None] | None = None,
    ) -> None:
        _require_secure_posix()
        marker = _marker_from(self.marker)
        expected_root = (
            self._squad_dir
            / _OUTBOX_DIRECTORY
            / marker.transaction_id
        )
        if self._transaction_root != expected_root:
            _raise("manifest_invalid")
        with _publication_exclusivity(self._project_root):
            verified, pinned = _load_prepared_pinned(
                self._project_root,
                self._squad_dir,
                marker,
            )
            try:
                operations = list(verified._manifest["operations"])
                pinned.verify()
                for position, operation in enumerate(operations):
                    self._run_fault_hook(fault_hook, position)
                    pinned.verify()
                    relative = Path(str(operation["target"]))
                    current = _target_image(
                        verified._project_root,
                        relative,
                        invalid_code="target_drift",
                    )
                    postimage = dict(operation["postimage"])
                    if current == postimage:
                        verified._durably_accept_postimage(operation)
                        continue
                    if current != dict(operation["preimage"]):
                        _raise("target_drift")
                    if operation["action"] == "write":
                        staged_name = str(operation["staged"])
                        verified._publish_write(
                            operation,
                            pinned.stages[staged_name],
                            pinned.transaction_fd,
                        )
                    else:
                        verified._publish_delete(operation)
                self._run_fault_hook(fault_hook, len(operations))
                pinned.verify()
                for operation in operations:
                    relative = Path(str(operation["target"]))
                    if _target_image(
                        verified._project_root,
                        relative,
                        invalid_code="target_drift",
                    ) != dict(operation["postimage"]):
                        _raise("target_drift")
            finally:
                pinned.close()

    def discard(self) -> None:
        _require_secure_posix()
        marker = _marker_from(self.marker)
        expected_root = (
            self._squad_dir
            / _OUTBOX_DIRECTORY
            / marker.transaction_id
        )
        if self._transaction_root != expected_root:
            _raise("manifest_invalid")
        with _publication_exclusivity(self._project_root):
            try:
                (
                    squad_fd,
                    outbox_fd,
                    outbox_identity,
                    transaction_fd,
                    transaction_identity,
                ) = _open_transaction_directories(
                    self._squad_dir,
                    marker,
                )
            except PublicationError as error:
                if error.code == "stage_missing":
                    return
                raise
            try:
                _verify_transaction_directories(
                    squad_fd,
                    outbox_fd,
                    outbox_identity,
                    transaction_fd,
                    marker.transaction_id,
                    transaction_identity,
                )
                _remove_directory_contents(transaction_fd)
                _verify_transaction_directories(
                    squad_fd,
                    outbox_fd,
                    outbox_identity,
                    transaction_fd,
                    marker.transaction_id,
                    transaction_identity,
                )
                try:
                    os.rmdir(
                        marker.transaction_id,
                        dir_fd=outbox_fd,
                    )
                    outbox_entry = os.stat(
                        _OUTBOX_DIRECTORY,
                        dir_fd=squad_fd,
                        follow_symlinks=False,
                    )
                    opened_outbox = os.fstat(outbox_fd)
                    if (
                        _directory_identity(outbox_entry)
                        != outbox_identity
                        or _directory_identity(opened_outbox)
                        != outbox_identity
                    ):
                        _raise("stage_corrupt")
                    os.fsync(outbox_fd)
                except PublicationError:
                    raise
                except FileNotFoundError:
                    _raise("stage_corrupt")
                except (OSError, TypeError, NotImplementedError):
                    _raise("publish_io")
            finally:
                os.close(transaction_fd)
                os.close(outbox_fd)
                os.close(squad_fd)


class SquadPublicationTransaction:
    """Mutable builder for one immutable file-level publication manifest."""

    def __init__(
        self,
        project_root: Path,
        squad_dir: Path,
        transaction_id: str,
        transaction_root: Path,
    ) -> None:
        self._project_root = project_root
        self._squad_dir = squad_dir
        self._transaction_id = transaction_id
        self._transaction_root = transaction_root
        self._operations: list[dict[str, object]] = []
        self._targets: list[Path] = []
        self._sealed = False

    @classmethod
    def begin(
        cls,
        project_root: Path,
        squad_dir: Path,
        transaction_id: str,
    ) -> SquadPublicationTransaction:
        _require_secure_posix()
        validated_id = _validate_transaction_id(transaction_id)
        try:
            project = _require_real_directory(
                Path(project_root),
                code="manifest_invalid",
            )
            squad = _require_real_directory(
                Path(squad_dir),
                code="manifest_invalid",
            )
        except TypeError:
            _raise("manifest_invalid")
        outbox = squad / _OUTBOX_DIRECTORY
        transaction_root = outbox / validated_id
        squad_fd = _open_directory(
            squad,
            missing_code="manifest_invalid",
            invalid_code="manifest_invalid",
        )
        try:
            try:
                os.mkdir(_OUTBOX_DIRECTORY, dir_fd=squad_fd)
                os.fsync(squad_fd)
            except FileExistsError:
                pass
            except OSError:
                _raise("publish_io")
            outbox_fd = _open_directory(
                _OUTBOX_DIRECTORY,
                dir_fd=squad_fd,
                missing_code="manifest_invalid",
                invalid_code="manifest_invalid",
            )
            try:
                try:
                    os.mkdir(validated_id, dir_fd=outbox_fd)
                except FileExistsError:
                    _raise("manifest_invalid")
                except OSError:
                    _raise("publish_io")
                transaction_fd = _open_directory(
                    validated_id,
                    dir_fd=outbox_fd,
                    missing_code="publish_io",
                    invalid_code="publish_io",
                )
                try:
                    os.fsync(transaction_fd)
                    os.fsync(outbox_fd)
                except OSError:
                    _raise("publish_io")
                finally:
                    os.close(transaction_fd)
            finally:
                os.close(outbox_fd)
        finally:
            os.close(squad_fd)
        return cls(
            project,
            squad,
            validated_id,
            transaction_root,
        )

    def build_path(self, name: str | Path) -> Path:
        relative = _normalize_relative_path(name)
        if relative == Path(_MANIFEST_NAME):
            _raise("manifest_invalid")
        _validate_existing_ancestors(
            self._transaction_root,
            relative,
            code="manifest_invalid",
        )
        return self._transaction_root / relative

    def _assert_mutable(self) -> None:
        if self._sealed:
            _raise("manifest_invalid")

    def _open_transaction(
        self,
    ) -> tuple[
        int,
        int,
        tuple[int, int, int],
        int,
        tuple[int, int, int],
    ]:
        marker = PublicationMarker(
            schema_version=_SCHEMA_VERSION,
            transaction_id=self._transaction_id,
            manifest_sha256="0" * 64,
        )
        return _open_transaction_directories(self._squad_dir, marker)

    def _normalize_owned_paths(
        self,
        owned_paths: Iterable[Path],
    ) -> frozenset[Path]:
        if isinstance(owned_paths, (str, bytes, Path)):
            _raise("manifest_invalid")
        try:
            return frozenset(
                _normalize_relative_path(path) for path in owned_paths
            )
        except TypeError:
            _raise("manifest_invalid")

    def _validate_new_target(
        self,
        target: Path,
        *,
        owned_paths: Iterable[Path],
    ) -> Path:
        self._assert_mutable()
        relative = _normalize_relative_path(target)
        if relative not in self._normalize_owned_paths(owned_paths):
            _raise("manifest_invalid")
        _validate_target_namespace(
            self._project_root,
            self._squad_dir,
            relative,
        )
        for existing in self._targets:
            if _overlaps(existing, relative):
                _raise("manifest_invalid")
        _validate_existing_ancestors(
            self._project_root,
            relative,
            code="manifest_invalid",
        )
        return relative

    def add_write(
        self,
        target: Path,
        staged: Path,
        *,
        owned_paths: Iterable[Path],
    ) -> None:
        relative = self._validate_new_target(
            target,
            owned_paths=owned_paths,
        )
        try:
            staged_path = Path(staged)
        except TypeError:
            _raise("manifest_invalid")
        try:
            staged_relative = staged_path.relative_to(
                self._transaction_root
            )
        except ValueError:
            _raise("manifest_invalid")
        staged_relative = _normalize_relative_path(staged_relative)
        if staged_relative == Path(_MANIFEST_NAME):
            _raise("manifest_invalid")
        (
            squad_fd,
            outbox_fd,
            _,
            transaction_fd,
            _,
        ) = self._open_transaction()
        try:
            pinned = _pin_regular_at(
                transaction_fd,
                staged_relative,
                missing_code="manifest_invalid",
                invalid_code="manifest_invalid",
            )
            try:
                post_digest = pinned.sha256
            finally:
                os.close(pinned.fd)
        finally:
            os.close(transaction_fd)
            os.close(outbox_fd)
            os.close(squad_fd)
        preimage = _target_image(
            self._project_root,
            relative,
            invalid_code="manifest_invalid",
        )
        self._operations.append(
            {
                "action": "write",
                "target": relative.as_posix(),
                "preimage": preimage,
                "postimage": {
                    "kind": "file",
                    "sha256": post_digest,
                },
                "staged": staged_relative.as_posix(),
            }
        )
        self._targets.append(relative)

    def add_delete(
        self,
        target: Path,
        *,
        owned_paths: Iterable[Path],
    ) -> None:
        relative = self._validate_new_target(
            target,
            owned_paths=owned_paths,
        )
        preimage = _target_image(
            self._project_root,
            relative,
            invalid_code="manifest_invalid",
        )
        self._operations.append(
            {
                "action": "delete",
                "target": relative.as_posix(),
                "preimage": preimage,
                "postimage": {"kind": "missing"},
            }
        )
        self._targets.append(relative)

    def seal(self) -> PreparedSquadPublication:
        self._assert_mutable()
        operations = sorted(
            self._operations,
            key=lambda operation: str(operation["target"]),
        )
        manifest = {
            "schema_version": _SCHEMA_VERSION,
            "transaction_id": self._transaction_id,
            "operations": operations,
        }
        manifest_bytes = _canonical_json(manifest)
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        (
            squad_fd,
            outbox_fd,
            outbox_identity,
            transaction_fd,
            transaction_identity,
        ) = self._open_transaction()
        stage_pins: dict[str, _PinnedRegular] = {}
        manifest_pin: _PinnedRegular | None = None
        try:
            for operation in operations:
                if operation["action"] != "write":
                    continue
                staged_name = str(operation["staged"])
                if staged_name not in stage_pins:
                    stage_pins[staged_name] = _pin_regular_at(
                        transaction_fd,
                        Path(staged_name),
                        missing_code="stage_missing",
                        invalid_code="stage_corrupt",
                    )
                pinned = stage_pins[staged_name]
                expected = dict(operation["postimage"])["sha256"]
                if pinned.sha256 != expected:
                    _raise("stage_corrupt")
                try:
                    os.fsync(pinned.fd)
                except OSError:
                    _raise("stage_corrupt")
                _fsync_relative_parent_directories(
                    transaction_fd,
                    pinned.relative,
                    code="stage_corrupt",
                )
            _durable_write_bytes_at(
                transaction_fd,
                _MANIFEST_NAME,
                manifest_bytes,
            )
            manifest_pin = _pin_regular_at(
                transaction_fd,
                Path(_MANIFEST_NAME),
                missing_code="manifest_mismatch",
                invalid_code="manifest_mismatch",
            )
            reread = _read_fd_bytes(
                manifest_pin.fd,
                code="manifest_mismatch",
            )
            if (
                reread != manifest_bytes
                or manifest_pin.sha256 != manifest_digest
            ):
                _raise("manifest_mismatch")
            try:
                _verify_transaction_directories(
                    squad_fd,
                    outbox_fd,
                    outbox_identity,
                    transaction_fd,
                    self._transaction_id,
                    transaction_identity,
                )
            except PublicationError:
                raise
            for pinned in stage_pins.values():
                _verify_pinned_regular(
                    transaction_fd,
                    pinned,
                    missing_code="stage_missing",
                    invalid_code="stage_corrupt",
                )
            try:
                os.fsync(transaction_fd)
                os.fsync(outbox_fd)
            except OSError:
                _raise("publish_io")
        finally:
            if manifest_pin is not None:
                os.close(manifest_pin.fd)
            for pinned in stage_pins.values():
                os.close(pinned.fd)
            os.close(transaction_fd)
            os.close(outbox_fd)
            os.close(squad_fd)
        marker = PublicationMarker(
            schema_version=_SCHEMA_VERSION,
            transaction_id=self._transaction_id,
            manifest_sha256=manifest_digest,
        )
        prepared = load_prepared_publication(
            self._project_root,
            self._squad_dir,
            marker,
        )
        self._sealed = True
        return prepared


def load_prepared_publication(
    project_root: Path,
    squad_dir: Path,
    marker: object,
) -> PreparedSquadPublication:
    prepared, pinned = _load_prepared_pinned(
        project_root,
        squad_dir,
        marker,
    )
    try:
        pinned.verify()
        return prepared
    finally:
        pinned.close()

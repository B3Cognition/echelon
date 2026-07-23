"""Durable file-level staging for controller-independent squad publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


_SCHEMA_VERSION = 1
_OUTBOX_DIRECTORY = ".publication-outbox"
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
        except OSError:
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


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        _raise("publish_io")


def _durable_mkdir(path: Path) -> None:
    try:
        path.mkdir()
    except OSError:
        _raise("publish_io")
    _fsync_directory(path)
    _fsync_directory(path.parent)


def _durable_write_bytes(path: Path, content: bytes) -> None:
    try:
        fd, temporary = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=f".{path.name}-",
            suffix=".tmp",
        )
    except OSError:
        _raise("publish_io")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except PublicationError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        _raise("publish_io")


def _open_regular(path: Path, *, missing_code: str, invalid_code: str) -> int:
    # O_NONBLOCK prevents a hostile FIFO replacement from blocking between
    # path validation and fstat; it has no effect on regular-file reads.
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        fd = os.open(path, flags)
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


def _read_regular_bytes(
    path: Path,
    *,
    missing_code: str,
    invalid_code: str,
) -> bytes:
    fd = _open_regular(
        path,
        missing_code=missing_code,
        invalid_code=invalid_code,
    )
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
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
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
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
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        current_fd = os.open(project_root, flags)
    except OSError:
        _raise("target_drift")
    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    _raise("target_drift")
                try:
                    os.mkdir(part, dir_fd=current_fd)
                    os.fsync(current_fd)
                    next_fd = os.open(part, flags, dir_fd=current_fd)
                    os.fsync(next_fd)
                except FileExistsError:
                    try:
                        next_fd = os.open(
                            part,
                            flags,
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


def _copy_stage_to_temporary(
    staged: Path,
    parent_fd: int,
    expected_digest: str,
) -> str:
    stage_fd = _open_regular(
        staged,
        missing_code="stage_missing",
        invalid_code="stage_corrupt",
    )
    try:
        before = os.fstat(stage_fd)
    except OSError:
        try:
            os.close(stage_fd)
        except OSError:
            pass
        _raise("stage_corrupt")
    temporary_name = f".echelon-publish-{secrets.token_hex(12)}.tmp"
    temporary_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        temporary_fd = os.open(
            temporary_name,
            temporary_flags,
            0o600,
            dir_fd=parent_fd,
        )
    except OSError:
        os.close(stage_fd)
        _raise("publish_io")
    try:
        digest = hashlib.sha256()
        while True:
            chunk = os.read(stage_fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(temporary_fd, view)
                view = view[written:]
        os.fsync(temporary_fd)
        after = os.fstat(stage_fd)
        if (
            digest.hexdigest() != expected_digest
            or (before.st_dev, before.st_ino, before.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            _raise("stage_corrupt")
        try:
            current = os.lstat(staged)
        except FileNotFoundError:
            _raise("stage_missing")
        except OSError:
            _raise("stage_corrupt")
        if (
            not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino, current.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
            or current.st_mtime_ns != after.st_mtime_ns
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
        _raise("publish_io")
    finally:
        os.close(temporary_fd)
        os.close(stage_fd)


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
    transaction_root: Path,
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
        expected_keys = (
            frozenset(
                {"action", "target", "preimage", "postimage", "staged"}
            )
            if action == "write"
            else frozenset({"action", "target", "preimage", "postimage"})
        )
        if action not in {"write", "delete"} or frozenset(
            dict.keys(raw_operation)
        ) != expected_keys:
            _raise("manifest_invalid")
        target = _normalize_relative_path(dict.get(raw_operation, "target"))
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
            _validate_existing_ancestors(
                transaction_root,
                staged,
                code="stage_corrupt",
            )
            operation["staged"] = staged.as_posix()
        elif postimage != {"kind": "missing"}:
            _raise("manifest_invalid")
        operations.append(operation)
    return {
        "schema_version": _SCHEMA_VERSION,
        "transaction_id": marker.transaction_id,
        "operations": operations,
    }


@dataclass
class PreparedSquadPublication:
    """A sealed and verified transaction that is safe to publish later."""

    _project_root: Path
    _squad_dir: Path
    _transaction_root: Path
    _manifest: dict[str, object]
    marker: PublicationMarker

    def _verified(self) -> PreparedSquadPublication:
        return load_prepared_publication(
            self._project_root,
            self._squad_dir,
            self.marker,
        )

    def _publish_write(self, operation: dict[str, object]) -> None:
        relative = Path(str(operation["target"]))
        staged = self._transaction_root / str(operation["staged"])
        expected_preimage = dict(operation["preimage"])
        expected_postimage = dict(operation["postimage"])
        expected_digest = str(expected_postimage["sha256"])
        actual_stage_digest = _hash_regular(
            staged,
            missing_code="stage_missing",
            invalid_code="stage_corrupt",
        )
        if actual_stage_digest != expected_digest:
            _raise("stage_corrupt")
        parent_fd = _open_parent_directory(
            self._project_root,
            relative,
            create=True,
        )
        temporary_name: str | None = None
        try:
            temporary_name = _copy_stage_to_temporary(
                staged,
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
            except OSError:
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
            except OSError:
                _raise("publish_io")
            if _target_image_at(parent_fd, relative.name) != {
                "kind": "missing"
            }:
                _raise("target_drift")
        finally:
            os.close(parent_fd)
        if _target_image(
            self._project_root,
            relative,
            invalid_code="target_drift",
        ) != {"kind": "missing"}:
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
        verified = self._verified()
        operations = list(verified._manifest["operations"])
        for position, operation in enumerate(operations):
            self._run_fault_hook(fault_hook, position)
            relative = Path(str(operation["target"]))
            current = _target_image(
                self._project_root,
                relative,
                invalid_code="target_drift",
            )
            postimage = dict(operation["postimage"])
            if current == postimage:
                continue
            if current != dict(operation["preimage"]):
                _raise("target_drift")
            if operation["action"] == "write":
                self._publish_write(operation)
            else:
                self._publish_delete(operation)
        self._run_fault_hook(fault_hook, len(operations))
        self._verified()
        for operation in operations:
            relative = Path(str(operation["target"]))
            if _target_image(
                self._project_root,
                relative,
                invalid_code="target_drift",
            ) != dict(operation["postimage"]):
                _raise("target_drift")

    def discard(self) -> None:
        outbox = self._squad_dir / _OUTBOX_DIRECTORY
        flags = os.O_RDONLY
        flags |= getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            outbox_fd = os.open(outbox, flags)
        except FileNotFoundError:
            return
        except OSError:
            _raise("stage_corrupt")
        try:
            metadata = os.stat(
                self.marker.transaction_id,
                dir_fd=outbox_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            os.close(outbox_fd)
            return
        except OSError:
            os.close(outbox_fd)
            _raise("publish_io")
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
            metadata.st_mode
        ):
            os.close(outbox_fd)
            _raise("stage_corrupt")
        try:
            shutil.rmtree(
                self.marker.transaction_id,
                dir_fd=outbox_fd,
            )
            os.fsync(outbox_fd)
        except (OSError, TypeError):
            _raise("publish_io")
        finally:
            os.close(outbox_fd)


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
        if not outbox.exists():
            _durable_mkdir(outbox)
        else:
            _require_real_directory(outbox, code="manifest_invalid")
        transaction_root = outbox / validated_id
        if transaction_root.exists() or transaction_root.is_symlink():
            _raise("manifest_invalid")
        _durable_mkdir(transaction_root)
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
        _validate_existing_ancestors(
            self._transaction_root,
            staged_relative,
            code="manifest_invalid",
        )
        post_digest = _hash_regular(
            staged_path,
            missing_code="manifest_invalid",
            invalid_code="manifest_invalid",
        )
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
        for operation in operations:
            if operation["action"] != "write":
                continue
            staged = self._transaction_root / str(operation["staged"])
            actual = _hash_regular(
                staged,
                missing_code="stage_missing",
                invalid_code="stage_corrupt",
                sync=True,
            )
            expected = dict(operation["postimage"])["sha256"]
            if actual != expected:
                _raise("stage_corrupt")
            cursor = staged.parent
            while True:
                _fsync_directory(cursor)
                if cursor == self._transaction_root:
                    break
                cursor = cursor.parent
        manifest = {
            "schema_version": _SCHEMA_VERSION,
            "transaction_id": self._transaction_id,
            "operations": operations,
        }
        manifest_bytes = _canonical_json(manifest)
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_path = self._transaction_root / _MANIFEST_NAME
        _durable_write_bytes(manifest_path, manifest_bytes)
        reread = _read_regular_bytes(
            manifest_path,
            missing_code="manifest_mismatch",
            invalid_code="manifest_mismatch",
        )
        if reread != manifest_bytes:
            _raise("manifest_mismatch")
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
    outbox = _require_real_directory(
        squad / _OUTBOX_DIRECTORY,
        code="stage_corrupt",
        missing_code="stage_missing",
    )
    transaction_root = _require_real_directory(
        outbox / validated_marker.transaction_id,
        code="stage_corrupt",
        missing_code="stage_missing",
    )
    manifest_path = transaction_root / _MANIFEST_NAME
    try:
        manifest_metadata = os.lstat(manifest_path)
    except FileNotFoundError:
        _raise("stage_missing")
    except OSError:
        _raise("publish_io")
    if stat.S_ISLNK(manifest_metadata.st_mode) or not stat.S_ISREG(
        manifest_metadata.st_mode
    ):
        _raise("manifest_invalid")
    manifest_bytes = _read_regular_bytes(
        manifest_path,
        missing_code="stage_missing",
        invalid_code="manifest_invalid",
    )
    if (
        hashlib.sha256(manifest_bytes).hexdigest()
        != validated_marker.manifest_sha256
    ):
        _raise("manifest_mismatch")
    try:
        decoded = manifest_bytes.decode("utf-8")
        raw_manifest = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _raise("manifest_invalid")
    manifest = _validate_manifest(
        raw_manifest,
        marker=validated_marker,
        project_root=project,
        transaction_root=transaction_root,
    )
    if _canonical_json(manifest) != manifest_bytes:
        _raise("manifest_invalid")
    for operation in manifest["operations"]:
        if operation["action"] != "write":
            continue
        staged = transaction_root / str(operation["staged"])
        actual = _hash_regular(
            staged,
            missing_code="stage_missing",
            invalid_code="stage_corrupt",
        )
        if actual != dict(operation["postimage"])["sha256"]:
            _raise("stage_corrupt")
    return PreparedSquadPublication(
        _project_root=project,
        _squad_dir=squad,
        _transaction_root=transaction_root,
        _manifest=manifest,
        marker=validated_marker,
    )

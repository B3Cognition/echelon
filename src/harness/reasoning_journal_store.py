"""Lightweight cross-language-compatible reasoning-journal transaction store."""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


REASONING_JOURNAL_LOCK_RANK = 5
REASONING_JOURNAL_LOCK_NAME = "reasoning-journal.lock"
MAX_JOURNAL_BYTES = 268_435_456


class JournalStoreError(Exception):
    """A bounded journal-store failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _raise(code: str) -> None:
    raise JournalStoreError(code)


def _require_real_directory(path: Path, *, code: str) -> Path:
    try:
        metadata = os.lstat(path)
    except OSError:
        _raise(code)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        _raise(code)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        _raise(code)
    if resolved != path.absolute():
        _raise(code)
    return resolved


def canonicalize_store_path(path: Path) -> Path:
    """Resolve parent aliases while preserving the final leaf for nofollow."""
    if not isinstance(path, Path) or not path.name:
        _raise("journal_invalid")
    absolute = path.absolute()
    try:
        parent = absolute.parent.resolve(strict=True)
    except (OSError, RuntimeError):
        _raise("journal_invalid")
    directory = _require_real_directory(
        parent,
        code="journal_invalid",
    )
    return directory / absolute.name


@contextmanager
def reasoning_journal_lock(squad_dir: Path) -> Iterator[None]:
    """Hold the one fcntl lock shared by every reasoning-journal writer."""
    if not isinstance(squad_dir, Path):
        _raise("journal_invalid")
    directory = _require_real_directory(
        squad_dir,
        code="journal_invalid",
    )
    lock_path = directory / REASONING_JOURNAL_LOCK_NAME
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError:
        _raise("journal_io")
    locked = False
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            _raise("journal_invalid")
        try:
            current = os.lstat(lock_path)
        except OSError:
            _raise("journal_invalid")
        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino)
            != (metadata.st_dev, metadata.st_ino)
        ):
            _raise("journal_invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError:
            _raise("journal_io")
        locked = True
        yield
    finally:
        if locked:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(descriptor)


def read_reasoning_journal(
    journal: Path,
) -> tuple[bytes, list[dict[str, object]]]:
    """Read and validate a complete JSON-object-per-line journal."""
    if not isinstance(journal, Path):
        _raise("journal_invalid")
    try:
        metadata = os.lstat(journal)
    except FileNotFoundError:
        return b"", []
    except OSError:
        _raise("journal_io")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size > MAX_JOURNAL_BYTES
    ):
        _raise("journal_invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(journal, flags)
    except OSError:
        _raise("journal_io")
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (metadata.st_dev, metadata.st_ino)
        ):
            _raise("journal_invalid")
        chunks = []
        remaining = MAX_JOURNAL_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1_048_576, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(content) > MAX_JOURNAL_BYTES
            or (after.st_dev, after.st_ino, after.st_size)
            != (opened.st_dev, opened.st_ino, opened.st_size)
        ):
            _raise("journal_invalid")
    except OSError:
        _raise("journal_io")
    finally:
        os.close(descriptor)

    rows = []
    for serialized in content.split(b"\n"):
        if not serialized.strip():
            continue
        try:
            row = json.loads(serialized)
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            RecursionError,
        ):
            _raise("journal_invalid")
        if type(row) is not dict:
            _raise("journal_invalid")
        rows.append(row)
    return content, rows


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        _raise("journal_io")
    try:
        os.fsync(descriptor)
    except OSError:
        _raise("journal_io")
    finally:
        os.close(descriptor)


def durably_replace_file(
    path: Path,
    content: bytes,
    *,
    directory_sync: Callable[[Path], None] = fsync_directory,
) -> None:
    """Fsync a sibling temp, replace atomically, then fsync the parent."""
    parent = _require_real_directory(
        path.parent,
        code="journal_invalid",
    )
    try:
        current = os.lstat(path)
    except FileNotFoundError:
        current = None
    except OSError:
        _raise("journal_io")
    if current is not None and (
        stat.S_ISLNK(current.st_mode)
        or not stat.S_ISREG(current.st_mode)
    ):
        _raise("journal_invalid")

    temporary = parent / (
        ".{}-{}.tmp".format(path.name, secrets.token_hex(12))
    )
    descriptor = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                _raise("journal_io")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        directory_sync(parent)
    except JournalStoreError:
        raise
    except OSError:
        _raise("journal_io")
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.unlink(temporary)
        except OSError:
            pass

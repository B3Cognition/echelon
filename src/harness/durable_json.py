"""Symlink-safe durable JSON replacement for run-local metadata."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile


class DurableJsonError(OSError):
    """Raised when a durable JSON destination is unsafe or unavailable."""


def write_json_atomic(path: Path, value: object) -> None:
    """Fsync a securely-created sibling temp, replace, then fsync the parent."""
    destination = Path(path)
    try:
        metadata = os.lstat(destination)
    except FileNotFoundError:
        metadata = None
    except OSError as exc:
        raise DurableJsonError(f"cannot inspect JSON destination: {destination}") from exc
    if metadata is not None:
        if stat.S_ISLNK(metadata.st_mode):
            raise DurableJsonError(f"JSON destination is symlinked: {destination}")
        if not stat.S_ISREG(metadata.st_mode):
            raise DurableJsonError(f"JSON destination is not a file: {destination}")

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=f".{destination.name}-",
            suffix=".tmp",
        )
    except OSError as exc:
        raise DurableJsonError(
            f"cannot create JSON temporary file: {destination}"
        ) from exc
    temporary = Path(temporary_name)
    open_descriptor: int | None = descriptor
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        open_descriptor = None
        with handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_NOFOLLOW", 0)
        directory = os.open(destination.parent, directory_flags)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        _cleanup_temporary(temporary)
        raise DurableJsonError(f"cannot durably replace JSON: {destination}") from exc
    except Exception:
        _cleanup_temporary(temporary)
        raise
    finally:
        if open_descriptor is not None:
            try:
                os.close(open_descriptor)
            except OSError:
                pass


def _cleanup_temporary(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

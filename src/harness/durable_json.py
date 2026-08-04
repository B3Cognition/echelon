"""Symlink-safe durable JSON replacement for run-local metadata."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import stat


class DurableJsonError(OSError):
    """Raised when a durable JSON destination is unsafe or unavailable."""


def write_json_atomic(
    path: Path,
    value: object,
    *,
    trusted_root: Path | None = None,
) -> None:
    """Replace JSON relative to a pinned parent directory descriptor."""
    destination = Path(os.path.abspath(os.fspath(path)))
    if not destination.name:
        raise DurableJsonError("JSON destination has no filename")
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    parent_fd = _open_destination_parent(
        destination,
        trusted_root=trusted_root,
    )
    temporary_name: str | None = None
    temporary_fd: int | None = None
    try:
        _require_regular_destination(parent_fd, destination.name)
        temporary_name, temporary_fd = _create_temporary(
            parent_fd,
            destination.name,
        )
        _write_all(temporary_fd, content)
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None

        _require_regular_destination(parent_fd, destination.name)
        os.replace(
            temporary_name,
            destination.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        temporary_name = None
        os.fsync(parent_fd)
    except DurableJsonError:
        raise
    except OSError as exc:
        raise DurableJsonError(f"cannot durably replace JSON: {destination}") from exc
    finally:
        if temporary_fd is not None:
            try:
                os.close(temporary_fd)
            except OSError:
                pass
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)


def _open_destination_parent(
    destination: Path,
    *,
    trusted_root: Path | None,
) -> int:
    if trusted_root is None:
        return _open_directory_strict(destination.parent)

    lexical_root = Path(os.path.abspath(os.fspath(trusted_root)))
    try:
        relative_destination = destination.relative_to(lexical_root)
    except ValueError as exc:
        raise DurableJsonError(
            f"JSON destination escapes trusted root: {destination}"
        ) from exc
    if not relative_destination.parts or relative_destination == Path("."):
        raise DurableJsonError("JSON destination has no filename below trusted root")
    try:
        canonical_root = lexical_root.resolve(strict=True)
    except OSError as exc:
        raise DurableJsonError(f"JSON trusted root is unavailable: {lexical_root}") from exc

    root_fd = _open_directory_strict(canonical_root)
    return _walk_directory_components(
        root_fd,
        relative_destination.parent.parts,
        display_path=destination.parent,
    )


def _open_directory_strict(directory: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        current_fd = os.open(directory.anchor or os.sep, flags)
    except OSError as exc:
        raise DurableJsonError(f"JSON directory is unsafe: {directory}") from exc
    components = directory.parts[1:] if directory.is_absolute() else directory.parts
    return _walk_directory_components(
        current_fd,
        components,
        display_path=directory,
    )


def _walk_directory_components(
    current_fd: int,
    components: tuple[str, ...],
    *,
    display_path: Path,
) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        for component in components:
            try:
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except OSError as exc:
                raise DurableJsonError(
                    f"JSON directory is unsafe: {display_path}"
                ) from exc
            try:
                if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                    raise DurableJsonError(
                        f"JSON directory is unsafe: {display_path}"
                    )
            except Exception:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd
        if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
            raise DurableJsonError(f"JSON directory is unsafe: {display_path}")
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _require_regular_destination(parent_fd: int, name: str) -> None:
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DurableJsonError(f"cannot inspect JSON destination: {name}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise DurableJsonError(f"JSON destination is symlinked: {name}")
    if not stat.S_ISREG(metadata.st_mode):
        raise DurableJsonError(f"JSON destination is not a file: {name}")


def _create_temporary(parent_fd: int, destination_name: str) -> tuple[str, int]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    for _ in range(128):
        name = f".{destination_name}-{secrets.token_hex(16)}.tmp"
        try:
            return name, os.open(name, flags, 0o600, dir_fd=parent_fd)
        except FileExistsError:
            continue
        except OSError as exc:
            raise DurableJsonError("cannot create JSON temporary file") from exc
    raise DurableJsonError("cannot allocate unique JSON temporary file")


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        try:
            written = os.write(descriptor, remaining)
        except OSError as exc:
            raise DurableJsonError("cannot write JSON temporary file") from exc
        if written <= 0:
            raise DurableJsonError("cannot write JSON temporary file")
        remaining = remaining[written:]

"""Bounded descriptor-pinned reads for host-serviced model inspection."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import unicodedata
from collections.abc import Mapping
from typing import Iterable

_MAX_FILE_BYTES = 1024 * 1024
_MAX_OUTPUT_BYTES = 64 * 1024
_MAX_LINES = 200
_MAX_DIRECTORY_ENTRIES = 500


class InspectionReadError(ValueError):
    """Raised when a host-serviced inspection read is invalid or unsafe."""


class BoundedReadChannel:
    """Expose only bounded reads below caller-named, descriptor-pinned roots."""

    def __init__(self, roots: Mapping[str, Path], *, forbidden_paths: tuple[Path, ...] = ()) -> None:
        if not isinstance(roots, Mapping) or not roots or any(
            type(name) is not str or not name for name in roots
        ):
            raise InspectionReadError("inspection read roots require nonempty named aliases")
        try:
            paths = {name: Path(path) for name, path in roots.items()}
            if any(not path.parts or ".." in path.parts for path in paths.values()):
                raise ValueError("unsafe root path")
            self._paths = {name: path.absolute() for name, path in paths.items()}
        except (TypeError, ValueError, OSError) as exc:
            raise InspectionReadError("inspection read roots are invalid") from exc
        try:
            if not isinstance(forbidden_paths, (tuple, list)):
                raise ValueError("invalid denied paths")
            denied = tuple(Path(path) for path in forbidden_paths)
            if any(".." in path.parts or "\0" in os.fspath(path) for path in denied):
                raise ValueError("unsafe denied path")
            self._forbidden = tuple(path.absolute() for path in denied)
        except (TypeError, ValueError, OSError) as exc:
            raise InspectionReadError("inspection denied paths are invalid") from exc
        self._denied_parts = tuple(_policy_parts(path) for path in self._forbidden)
        self._denied_locations = tuple(
            location for path in self._forbidden for location in _policy_locations(path)
        )
        if any(self._is_denied(path) for path in self._paths.values()):
            raise InspectionReadError("inspection read root is denied")
        self._roots: dict[str, int] = {}

    def _is_denied(self, path: Path) -> bool:
        parts = _policy_parts(path)
        if any(parts[:len(denied)] == denied for denied in self._denied_parts):
            return True
        return any(
            identity == denied_identity and suffix[:len(denied_suffix)] == denied_suffix
            for identity, suffix in (_policy_locations(path) if self._forbidden else ())
            for denied_identity, denied_suffix in self._denied_locations
        )

    def __enter__(self) -> BoundedReadChannel:
        if self._roots:
            raise InspectionReadError("review read channel is already open")
        opened: dict[str, int] = {}
        try:
            for name, path in self._paths.items():
                opened[name] = _open_root_directory(path)
        except (OSError, ValueError) as exc:
            _close_descriptors(opened.values())
            raise InspectionReadError("review read root is missing or unsafe") from exc
        self._roots = opened
        return self

    def __exit__(self, *args: object) -> None:
        _close_descriptors(self._roots.values())
        self._roots = {}

    def request(self, value: object) -> dict[str, object]:
        """Validate and service one closed-schema read request."""
        if not self._roots:
            raise InspectionReadError("review read channel is not open")
        if type(value) is not dict:
            raise InspectionReadError("review read request must be an object")
        operation = value.get("op")
        expected = (
            {"op", "root", "path", "start_line", "line_count"}
            if operation == "read_file"
            else {"op", "root", "path"}
            if operation == "list_directory"
            else None
        )
        if expected is None or set(value) != expected:
            raise InspectionReadError("review read request has an invalid schema")
        root = value.get("root")
        path = value.get("path")
        if type(root) is not str or root not in self._roots:
            raise InspectionReadError("review read request has an invalid root")
        components = _request_components(path)
        candidate = self._paths[root].joinpath(*components)
        if self._is_denied(candidate):
            raise InspectionReadError("inspection read path is denied")
        if operation == "read_file":
            start_line = value.get("start_line")
            line_count = value.get("line_count")
            if (
                type(start_line) is not int
                or type(line_count) is not int
                or start_line < 1
                or not 1 <= line_count <= _MAX_LINES
            ):
                raise InspectionReadError("review file read has invalid line bounds")
            return _read_file(
                self._roots[root],
                components,
                start_line=start_line,
                line_count=line_count,
            )
        parent = _policy_parts(candidate)
        denied_names = {parts[-1] for parts in self._denied_parts if parts[:-1] == parent}
        for identity, suffix in (_policy_locations(candidate) if self._forbidden else ()):
            denied_names.update(
                denied_suffix[-1]
                for denied_identity, denied_suffix in self._denied_locations
                if identity == denied_identity and denied_suffix and denied_suffix[:-1] == suffix
            )
        return _list_directory(self._roots[root], components, denied_names=frozenset(denied_names))


def _policy_locations(path: Path) -> tuple[tuple[tuple[int, int], tuple[str, ...]], ...]:
    # Firmlinks (and other filesystem aliases) need identity, not realpath or
    # spelling, comparisons. Anchor suffixes at every existing ancestor so an
    # absent denied leaf is protected too. This metadata-only check grants no
    # access: actual reads still traverse descriptor-pinned, no-follow paths.
    locations = []
    parts = _policy_parts(path)
    for ancestor in (path, *path.parents):
        try:
            info = os.stat(ancestor, follow_symlinks=False)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as exc:
            raise InspectionReadError("inspection denied-path identity is unavailable") from exc
        locations.append(((info.st_dev, info.st_ino), parts[len(ancestor.parts):]))
    return tuple(locations)


def _policy_parts(path: Path) -> tuple[str, ...]:
    # macOS volumes may alias case and Unicode normalization. Denials deliberately
    # match these spellings conservatively, including on case-sensitive volumes;
    # this never broadens read access and leaves no-exclusion triage unchanged.
    return tuple(unicodedata.normalize("NFD", part).casefold() for part in path.parts)


def _request_components(value: object) -> tuple[str, ...]:
    if type(value) is not str or not value or "\0" in value:
        raise InspectionReadError("review read path is invalid")
    if value == ".":
        return ()
    if value.startswith("/") or value.endswith("/"):
        raise InspectionReadError("review read path is invalid")
    components = tuple(value.split("/"))
    if any(component in {"", ".", ".."} for component in components):
        raise InspectionReadError("review read path is invalid")
    return components


def _open_root_directory(path: Path) -> int:
    raw = os.fspath(path)
    if not raw or "\0" in raw:
        raise OSError("unsafe root path")
    flags = _directory_flags()
    if os.path.isabs(raw):
        components = raw.split("/")[1:]
        current = os.open(os.path.sep, flags)
    else:
        components = raw.split("/")
        current = os.open(".", flags)
    try:
        if any(component in {"", ".", ".."} for component in components):
            raise OSError("unsafe root path component")
        for component in components:
            next_fd = os.open(component, flags, dir_fd=current)
            try:
                if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                    raise OSError("root path component is not a directory")
            except Exception:
                os.close(next_fd)
                raise
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


def _open_relative_directory(root_fd: int, components: tuple[str, ...]) -> int:
    current = os.dup(root_fd)
    flags = _directory_flags()
    try:
        for component in components:
            next_fd = os.open(component, flags, dir_fd=current)
            try:
                if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                    raise OSError("path component is not a directory")
            except Exception:
                os.close(next_fd)
                raise
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


def _read_file(
    root_fd: int,
    components: tuple[str, ...],
    *,
    start_line: int,
    line_count: int,
) -> dict[str, object]:
    if not components:
        raise InspectionReadError("review file path must name a file")
    parent_fd: int | None = None
    file_fd: int | None = None
    try:
        parent_fd = _open_relative_directory(root_fd, components[:-1])
        name = components[-1]
        try:
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return _unavailable("file does not exist")
        _require_single_regular_file(before)
        if before.st_size > _MAX_FILE_BYTES:
            return _unavailable("file exceeds the 1 MiB source limit")
        file_fd = os.open(name, _file_flags(), dir_fd=parent_fd)
        opened = os.fstat(file_fd)
        _require_single_regular_file(opened)
        if _file_identity(opened) != _file_identity(before):
            raise InspectionReadError("review file changed while opening")
        content = _read_exact(file_fd, opened.st_size)
        after = os.fstat(file_fd)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(current) != _file_identity(opened)
        ):
            raise InspectionReadError("review file changed while reading")
    except InspectionReadError:
        raise
    except FileNotFoundError:
        return _unavailable("file does not exist")
    except OSError as exc:
        raise InspectionReadError("review file is missing or unsafe") from exc
    finally:
        _close_descriptors(fd for fd in (file_fd, parent_fd) if fd is not None)
    if b"\0" in content:
        return _unavailable("file is not UTF-8 text")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return _unavailable("file is not UTF-8 text")
    lines = text.splitlines(keepends=True)
    selected = "".join(lines[start_line - 1 : start_line - 1 + line_count])
    if len(selected.encode("utf-8")) > _MAX_OUTPUT_BYTES:
        return _unavailable("requested text exceeds the 64 KiB output limit")
    response: dict[str, object] = {
        "status": "ok",
        "text": selected,
        "start_line": start_line,
        "total_lines": len(lines),
    }
    if _encoded_output_size(response) > _MAX_OUTPUT_BYTES:
        return _unavailable("requested reply exceeds the 64 KiB output limit")
    return response


def _list_directory(
    root_fd: int, components: tuple[str, ...], *, denied_names: frozenset[str] = frozenset()
) -> dict[str, object]:
    directory_fd: int | None = None
    try:
        directory_fd = _open_relative_directory(root_fd, components)
        before = _directory_identity(os.fstat(directory_fd))
        names = os.listdir(directory_fd)
        if len(names) > _MAX_DIRECTORY_ENTRIES:
            return _unavailable("directory exceeds the 500 entry limit")
        entries: list[dict[str, str]] = []
        encoded_size = _encoded_output_size({"status": "ok", "entries": entries})
        output_oversized = False
        for name in sorted(names):
            if _policy_parts(Path(name))[-1] in denied_names:
                continue
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                entry_type = "directory"
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                entry_type = "file"
            else:
                raise InspectionReadError("directory contains an unsafe entry")
            entry = {"name": name, "type": entry_type}
            if output_oversized:
                continue
            encoded_size += _encoded_output_size(entry) + (2 if entries else 0)
            if encoded_size > _MAX_OUTPUT_BYTES:
                output_oversized = True
                continue
            entries.append(entry)
        if _directory_identity(os.fstat(directory_fd)) != before:
            raise InspectionReadError("review directory changed while listing")
        if output_oversized:
            return _unavailable("directory reply exceeds the 64 KiB output limit")
        return {"status": "ok", "entries": entries}
    except InspectionReadError:
        raise
    except FileNotFoundError:
        return _unavailable("directory does not exist")
    except OSError as exc:
        raise InspectionReadError("review directory is missing or unsafe") from exc
    finally:
        if directory_fd is not None:
            _close_descriptors((directory_fd,))


def _require_single_regular_file(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise InspectionReadError("review file is not a single-linked regular file")


def _read_exact(descriptor: int, size: int) -> bytes:
    remaining = size
    chunks: list[bytes] = []
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            raise OSError("short bounded read")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _file_identity(metadata: os.stat_result) -> tuple[object, ...]:
    return (
        stat.S_IFMT(metadata.st_mode),
        metadata.st_mode,
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        getattr(metadata, "st_flags", None),
        getattr(metadata, "st_gen", None),
    )


def _directory_identity(metadata: os.stat_result) -> tuple[object, ...]:
    if not stat.S_ISDIR(metadata.st_mode):
        raise InspectionReadError("review path is not a directory")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _directory_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise OSError("no-follow directory opens are unavailable")
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | nofollow
        | getattr(os, "O_CLOEXEC", 0)
    )


def _file_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise OSError("no-follow file opens are unavailable")
    return (
        os.O_RDONLY
        | nofollow
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _close_descriptors(descriptors: Iterable[int]) -> None:
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _unavailable(reason: str) -> dict[str, object]:
    return {"status": "unavailable", "reason": reason}


def _encoded_output_size(value: object) -> int:
    return len(json.dumps(value).encode("utf-8"))

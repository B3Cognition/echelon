"""Bounded filesystem and Prosaic input boundary for PR review triage."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Iterable

from harness.prosaic_prompt_loader import (
    ProsaicCommandArtifact,
    ProsaicPromptLoadError,
    ProsaicPromptLoader,
)
from harness.prompt_companions import prompt_companion_references


_MAX_FILE_BYTES = 1024 * 1024
_MAX_OUTPUT_BYTES = 64 * 1024
_MAX_LINES = 200
_MAX_DIRECTORY_ENTRIES = 500
_MAX_PROSE_BYTES = 128 * 1024
_MODEL_TIERS = frozenset({"fast", "balanced", "strong"})
_EFFORT_LEVELS = frozenset({"low", "medium", "high"})
_PROVIDER_METADATA_KEYS = frozenset(
    {"model", "provider", "model_id", "model_name", "reasoning_effort"}
)
_REVIEW_PROSE = (
    ("echelon.review", "commands"),
    ("echelon.review-debugger", "subagents"),
    ("echelon.review-sentinel", "subagents"),
    ("echelon.review-spec-guard", "subagents"),
)


class ReviewTriageError(ValueError):
    """Raised when a PR-triage input request is invalid or unsafe."""


class ReviewReadChannel:
    """Expose only bounded reads below two caller-supplied pinned roots."""

    def __init__(self, worktree: Path, spec_dir: Path) -> None:
        self._paths = {"worktree": Path(worktree), "spec": Path(spec_dir)}
        self._roots: dict[str, int] = {}

    def __enter__(self) -> ReviewReadChannel:
        if self._roots:
            raise ReviewTriageError("review read channel is already open")
        opened: dict[str, int] = {}
        try:
            for name, path in self._paths.items():
                opened[name] = _open_root_directory(path)
        except (OSError, ValueError) as exc:
            _close_descriptors(opened.values())
            raise ReviewTriageError("review read root is missing or unsafe") from exc
        self._roots = opened
        return self

    def __exit__(self, *args: object) -> None:
        _close_descriptors(self._roots.values())
        self._roots = {}

    def request(self, value: object) -> dict[str, object]:
        """Validate and service one closed-schema read request."""
        if not self._roots:
            raise ReviewTriageError("review read channel is not open")
        if type(value) is not dict:
            raise ReviewTriageError("review read request must be an object")
        operation = value.get("op")
        expected = (
            {"op", "root", "path", "start_line", "line_count"}
            if operation == "read_file"
            else {"op", "root", "path"}
            if operation == "list_directory"
            else None
        )
        if expected is None or set(value) != expected:
            raise ReviewTriageError("review read request has an invalid schema")
        root = value.get("root")
        path = value.get("path")
        if type(root) is not str or root not in self._roots:
            raise ReviewTriageError("review read request has an invalid root")
        components = _request_components(path)
        if operation == "read_file":
            start_line = value.get("start_line")
            line_count = value.get("line_count")
            if (
                type(start_line) is not int
                or type(line_count) is not int
                or start_line < 1
                or not 1 <= line_count <= _MAX_LINES
            ):
                raise ReviewTriageError("review file read has invalid line bounds")
            return _read_file(
                self._roots[root],
                components,
                start_line=start_line,
                line_count=line_count,
            )
        return _list_directory(self._roots[root], components)


def load_review_prose(
    worktree: Path, *, timeout_s: float
) -> dict[str, ProsaicCommandArtifact]:
    """Capture and inspect the fixed neutral review-triage prose set."""
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or not math.isfinite(timeout_s)
        or timeout_s <= 0
    ):
        raise ReviewTriageError("review prose timeout must be positive")
    deadline = time.monotonic() + float(timeout_s)
    root_fd: int | None = None
    try:
        root_fd = _open_root_directory(Path(worktree))
        captured = {
            name: _capture_prose_source(root_fd, directory, name)
            for name, directory in _REVIEW_PROSE
        }
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReviewTriageError("required review prose is missing or unsafe") from exc
    finally:
        if root_fd is not None:
            _close_descriptors((root_fd,))

    for name, content in captured.items():
        source_text = content.decode("utf-8")
        if prompt_companion_references(source_text):
            raise ReviewTriageError(
                f"required review prose declares a companion: {name}"
            )

    artifacts: dict[str, ProsaicCommandArtifact] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="echelon-review-prose-") as raw_temp:
            project = Path(raw_temp)
            source = project / ".echelon" / "prosaic"
            for name, directory in _REVIEW_PROSE:
                destination = source / directory / f"{name}.md"
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination.write_bytes(captured[name])
            os.chmod(project, 0o700)
            for name, directory in _REVIEW_PROSE:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReviewTriageError("review prose inspection timed out")
                loader = ProsaicPromptLoader(project, timeout_s=remaining)
                artifact = (
                    loader.load_command(name)
                    if directory == "commands"
                    else loader.load_subagent(name)
                )
                if artifact is None:
                    raise ReviewTriageError(f"required review prose is missing: {name}")
                _validate_review_artifact(name, artifact)
                artifacts[name] = artifact
    except ReviewTriageError:
        raise
    except (OSError, ProsaicPromptLoadError, ValueError) as exc:
        raise ReviewTriageError("required review prose could not be inspected") from exc
    return artifacts


def _request_components(value: object) -> tuple[str, ...]:
    if type(value) is not str or not value or "\0" in value:
        raise ReviewTriageError("review read path is invalid")
    if value == ".":
        return ()
    if value.startswith("/") or value.endswith("/"):
        raise ReviewTriageError("review read path is invalid")
    components = tuple(value.split("/"))
    if any(component in {"", ".", ".."} for component in components):
        raise ReviewTriageError("review read path is invalid")
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
        raise ReviewTriageError("review file path must name a file")
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
            raise ReviewTriageError("review file changed while opening")
        content = _read_exact(file_fd, opened.st_size)
        after = os.fstat(file_fd)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(current) != _file_identity(opened)
        ):
            raise ReviewTriageError("review file changed while reading")
    except ReviewTriageError:
        raise
    except FileNotFoundError:
        return _unavailable("file does not exist")
    except OSError as exc:
        raise ReviewTriageError("review file is missing or unsafe") from exc
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
    root_fd: int, components: tuple[str, ...]
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
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                entry_type = "directory"
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                entry_type = "file"
            else:
                raise ReviewTriageError("directory contains an unsafe entry")
            entry = {"name": name, "type": entry_type}
            if output_oversized:
                continue
            encoded_size += _encoded_output_size(entry) + (2 if entries else 0)
            if encoded_size > _MAX_OUTPUT_BYTES:
                output_oversized = True
                continue
            entries.append(entry)
        if _directory_identity(os.fstat(directory_fd)) != before:
            raise ReviewTriageError("review directory changed while listing")
        if output_oversized:
            return _unavailable("directory reply exceeds the 64 KiB output limit")
        return {"status": "ok", "entries": entries}
    except ReviewTriageError:
        raise
    except FileNotFoundError:
        return _unavailable("directory does not exist")
    except OSError as exc:
        raise ReviewTriageError("review directory is missing or unsafe") from exc
    finally:
        if directory_fd is not None:
            _close_descriptors((directory_fd,))


def _capture_prose_source(root_fd: int, directory: str, name: str) -> bytes:
    parent_fd: int | None = None
    file_fd: int | None = None
    try:
        parent_fd = _open_relative_directory(
            root_fd, (".echelon", "prosaic", directory)
        )
        filename = f"{name}.md"
        before = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        _require_single_regular_file(before)
        if before.st_size > _MAX_PROSE_BYTES:
            raise OSError("review prose exceeds capture limit")
        file_fd = os.open(filename, _file_flags(), dir_fd=parent_fd)
        opened = os.fstat(file_fd)
        _require_single_regular_file(opened)
        if _file_identity(opened) != _file_identity(before):
            raise OSError("review prose changed while opening")
        content = _read_exact(file_fd, opened.st_size)
        after = os.fstat(file_fd)
        current = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(current) != _file_identity(opened)
        ):
            raise OSError("review prose changed while reading")
        content.decode("utf-8")
        if b"\0" in content:
            raise ValueError("review prose is not text")
        return content
    finally:
        _close_descriptors(fd for fd in (file_fd, parent_fd) if fd is not None)


def _validate_review_artifact(
    name: str, artifact: ProsaicCommandArtifact
) -> None:
    metadata = artifact.frontmatter
    if not artifact.body.strip():
        raise ReviewTriageError(f"required review prose is empty: {name}")
    if metadata.get("name") != name:
        raise ReviewTriageError(f"required review prose has the wrong name: {name}")
    if _PROVIDER_METADATA_KEYS.intersection(metadata):
        raise ReviewTriageError(f"required review prose is provider-specific: {name}")
    if (
        metadata.get("model_tier") not in _MODEL_TIERS
        or metadata.get("effort") not in _EFFORT_LEVELS
    ):
        raise ReviewTriageError(f"required review prose has invalid neutral metadata: {name}")


def _require_single_regular_file(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ReviewTriageError("review file is not a single-linked regular file")


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
        raise ReviewTriageError("review path is not a directory")
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

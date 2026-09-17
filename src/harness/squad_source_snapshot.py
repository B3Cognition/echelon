"""Detached selected-source observations during a short publication lock scope."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from harness import squad_publication as publication
from harness.squad_publication_snapshot import PublicationImageDescriptor, PublicationSnapshot


@dataclass(frozen=True, slots=True)
class ProjectDirectorySnapshot:
    path: str
    mode: int


@dataclass(frozen=True, slots=True)
class ProjectFileSnapshot:
    path: str
    image: PublicationImageDescriptor
    content: bytes


@dataclass(frozen=True, slots=True)
class ProjectTreeSnapshot:
    path: str
    exists: bool
    directories: tuple[ProjectDirectorySnapshot, ...]
    files: tuple[ProjectFileSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ProjectPathSnapshot:
    path: str
    image: PublicationImageDescriptor
    content: bytes | None


@dataclass(frozen=True, slots=True)
class PublicationSourcesSnapshot:
    publication: PublicationSnapshot
    trees: tuple[ProjectTreeSnapshot, ...]
    files: tuple[ProjectPathSnapshot, ...]


def _source_path(value: str) -> Path:
    if type(value) is not str:
        raise publication.PublicationError("manifest_invalid")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise publication.PublicationError("manifest_invalid") from None
    return publication._normalize_relative_path(value)


def _source_selection(
    tree_paths: Sequence[str], file_paths: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Copy and validate the complete controller selection before scope entry."""
    batches: list[tuple[str, ...]] = []
    selected: set[tuple[str, ...]] = set()
    for batch in (tree_paths, file_paths):
        if isinstance(batch, (str, bytes)) or not isinstance(batch, Sequence):
            raise publication.PublicationError("manifest_invalid")
        values = tuple(batch)
        for value in values:
            parts = _source_path(value).parts
            if parts in selected:
                raise publication.PublicationError("manifest_invalid")
            selected.add(parts)
        batches.append(tuple(sorted(values)))
    for parts in selected:
        if any(parts[:length] in selected for length in range(1, len(parts))):
            raise publication.PublicationError("manifest_invalid")
    return batches[0], batches[1]


def _capture_project_tree(
    paths: publication._InspectionPaths, project_fd: int, tree_path: str,
) -> ProjectTreeSnapshot:
    """Capture a validated selection using the caller's retained paths owner."""
    relative = Path(tree_path)
    tree_fd = paths.directory(
        project_fd, relative.parts, code="target_drift", allow_missing=True
    )
    directories: list[ProjectDirectorySnapshot] = []
    files: list[ProjectFileSnapshot] = []
    pending = [] if tree_fd is None else [(tree_path, tree_fd)]
    while pending:
        directory_path, directory_fd = pending.pop()
        names, mode = paths.membership(directory_fd, code="target_drift")
        directories.append(ProjectDirectorySnapshot(directory_path, mode))
        for name in names:
            child_path = directory_path + "/" + name
            try:
                metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError:
                raise publication.PublicationError("target_drift") from None
            if stat.S_ISDIR(metadata.st_mode):
                child_fd = paths.directory(directory_fd, (name,), code="target_drift")
                assert child_fd is not None
                pending.append((child_path, child_fd))
            elif stat.S_ISREG(metadata.st_mode):
                captured = _capture_project_path(paths, directory_fd, name)
                if captured.content is None:
                    raise publication.PublicationError("target_drift")
                files.append(ProjectFileSnapshot(
                    child_path, captured.image, captured.content,
                ))
            else:
                raise publication.PublicationError("target_drift")
    return ProjectTreeSnapshot(
        tree_path, tree_fd is not None,
        tuple(sorted(directories, key=lambda item: item.path)),
        tuple(sorted(files, key=lambda item: item.path)),
    )


def _capture_project_path(
    paths: publication._InspectionPaths, project_fd: int, file_path: str,
) -> ProjectPathSnapshot:
    pinned = paths.current(project_fd, Path(file_path))
    if pinned is None:
        return ProjectPathSnapshot(
            file_path, PublicationImageDescriptor("missing", None, None), None
        )
    return ProjectPathSnapshot(
        file_path,
        PublicationImageDescriptor("file", pinned.sha256, stat.S_IMODE(pinned.identity[2])),
        publication._read_pinned_bytes(pinned, code="target_drift"),
    )


@contextmanager
def inspect_project_tree(project_root: Path, tree_path: str) -> Iterator[ProjectTreeSnapshot]:
    """Inspect one complete project-relative tree under the existing lock.

    Success includes normal context exit. Keep this controller-owned scope short;
    do not run providers or recursively inspect, publish or discard inside it.
    Detached values convey no freshness or publication authority after exit.
    """
    _source_path(tree_path)
    with publication._project_inspection_scope(project_root) as (paths, _, project_fd):
        snapshot = _capture_project_tree(paths, project_fd, tree_path)
        paths.verify()
        yield snapshot
        paths.verify()

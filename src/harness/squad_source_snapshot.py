"""Complete detached observations of one selected tree during a short lock scope."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from harness import squad_publication as publication
from harness.squad_publication_snapshot import PublicationImageDescriptor


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


@contextmanager
def inspect_project_tree(project_root: Path, tree_path: str) -> Iterator[ProjectTreeSnapshot]:
    """Inspect one complete project-relative tree under the existing lock.

    Success includes normal context exit. Keep this controller-owned scope short;
    do not run providers or recursively inspect, publish or discard inside it.
    Detached values convey no freshness or publication authority after exit.
    """
    if type(tree_path) is not str:
        raise publication.PublicationError("manifest_invalid")
    try:
        tree_path.encode("utf-8")
    except UnicodeError:
        raise publication.PublicationError("manifest_invalid") from None
    relative = publication._normalize_relative_path(tree_path)
    with publication._project_inspection_scope(project_root) as (paths, _, project_fd):
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
                    pinned = paths.current(directory_fd, Path(name))
                    if pinned is None:
                        raise publication.PublicationError("target_drift")
                    files.append(ProjectFileSnapshot(
                        child_path,
                        PublicationImageDescriptor(
                            "file", pinned.sha256, stat.S_IMODE(pinned.identity[2])
                        ),
                        publication._read_pinned_bytes(pinned, code="target_drift"),
                    ))
                else:
                    raise publication.PublicationError("target_drift")
        snapshot = ProjectTreeSnapshot(
            tree_path, tree_fd is not None,
            tuple(sorted(directories, key=lambda item: item.path)),
            tuple(sorted(files, key=lambda item: item.path)),
        )
        paths.verify()
        yield snapshot
        paths.verify()

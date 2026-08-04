"""No-follow durability finalization for controller-owned directory trees."""

from __future__ import annotations

import os
from pathlib import Path
import stat


class DurableTreeError(RuntimeError):
    """Raised when an owned tree cannot be authenticated and synced safely."""


def _sync_descriptor(descriptor: int, _path: Path) -> None:
    os.fsync(descriptor)


def _entry_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        stat.S_IMODE(metadata.st_mode),
    )


def durably_sync_owned_tree(
    root: Path,
    *,
    directory_mode: int = 0o755,
    normalize_directory_modes: bool = False,
    max_entries: int = 100_000,
    max_depth: int = 128,
) -> None:
    """Finalize files then directories bottom-up without following links."""

    tree_root = Path(root)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_path_before = os.stat(tree_root, follow_symlinks=False)
        root_descriptor = os.open(tree_root, directory_flags)
    except OSError as exc:
        raise DurableTreeError(f"owned tree root is not a real directory: {tree_root}") from exc
    root_opened = os.fstat(root_descriptor)
    if (
        not stat.S_ISDIR(root_path_before.st_mode)
        or _entry_identity(root_path_before) != _entry_identity(root_opened)
    ):
        os.close(root_descriptor)
        raise DurableTreeError(f"owned tree root was swapped: {tree_root}")
    entries_seen = 0

    def walk(descriptor: int, path: Path, depth: int) -> None:
        nonlocal entries_seen
        if depth > max_depth:
            raise DurableTreeError("owned tree exceeds the maximum directory depth")
        if normalize_directory_modes:
            os.fchmod(descriptor, directory_mode)
        before = os.fstat(descriptor)
        if not stat.S_ISDIR(before.st_mode):
            raise DurableTreeError(f"owned tree entry is not a directory: {path}")
        if stat.S_IMODE(before.st_mode) != directory_mode:
            raise DurableTreeError(
                f"owned tree directory has noncanonical mode: {path}"
            )
        names = sorted(os.listdir(descriptor))
        entry_identities: dict[str, tuple[int, int, int, int]] = {}
        for name in names:
            entries_seen += 1
            if entries_seen > max_entries:
                raise DurableTreeError("owned tree exceeds the maximum entry count")
            child_path = path / name
            try:
                observed = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except OSError as exc:
                raise DurableTreeError(f"owned tree entry changed: {child_path}") from exc
            entry_identities[name] = _entry_identity(observed)
            if stat.S_ISLNK(observed.st_mode):
                raise DurableTreeError(f"owned tree contains a symlink: {child_path}")
            if stat.S_ISDIR(observed.st_mode):
                try:
                    child_descriptor = os.open(
                        name,
                        directory_flags,
                        dir_fd=descriptor,
                    )
                except OSError as exc:
                    raise DurableTreeError(
                        f"owned tree directory changed: {child_path}"
                    ) from exc
                try:
                    opened = os.fstat(child_descriptor)
                    if (opened.st_dev, opened.st_ino) != (
                        observed.st_dev,
                        observed.st_ino,
                    ):
                        raise DurableTreeError(
                            f"owned tree directory was swapped: {child_path}"
                        )
                    walk(child_descriptor, child_path, depth + 1)
                    try:
                        rebound = os.stat(
                            name,
                            dir_fd=descriptor,
                            follow_symlinks=False,
                        )
                    except OSError as exc:
                        raise DurableTreeError(
                            f"owned tree directory was swapped: {child_path}"
                        ) from exc
                    if _entry_identity(rebound) != _entry_identity(
                        os.fstat(child_descriptor)
                    ):
                        raise DurableTreeError(
                            f"owned tree directory was swapped: {child_path}"
                        )
                    entry_identities[name] = _entry_identity(rebound)
                finally:
                    os.close(child_descriptor)
                continue
            if not stat.S_ISREG(observed.st_mode):
                kind = "fifo" if stat.S_ISFIFO(observed.st_mode) else "special entry"
                raise DurableTreeError(f"owned tree contains a {kind}: {child_path}")
            if observed.st_nlink != 1:
                raise DurableTreeError(f"owned tree contains a hardlink: {child_path}")
            try:
                file_descriptor = os.open(name, file_flags, dir_fd=descriptor)
            except OSError as exc:
                raise DurableTreeError(f"owned tree file changed: {child_path}") from exc
            try:
                opened = os.fstat(file_descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino, opened.st_mode)
                    != (observed.st_dev, observed.st_ino, observed.st_mode)
                ):
                    raise DurableTreeError(f"owned tree file was swapped: {child_path}")
                _sync_descriptor(file_descriptor, child_path)
                after = os.fstat(file_descriptor)
                try:
                    rebound = os.stat(
                        name,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    raise DurableTreeError(
                        f"owned tree file was swapped: {child_path}"
                    ) from exc
                if (
                    not stat.S_ISREG(rebound.st_mode)
                    or rebound.st_nlink != 1
                    or _entry_identity(rebound) != _entry_identity(after)
                ):
                    raise DurableTreeError(
                        f"owned tree file was swapped: {child_path}"
                    )
                entry_identities[name] = _entry_identity(rebound)
                if (
                    after.st_size != opened.st_size
                    or after.st_mtime_ns != opened.st_mtime_ns
                    or after.st_ctime_ns != opened.st_ctime_ns
                    or after.st_mode != opened.st_mode
                ):
                    raise DurableTreeError(f"owned tree file mutated: {child_path}")
            finally:
                os.close(file_descriptor)
        after_names = sorted(os.listdir(descriptor))
        try:
            after_entry_identities = {
                name: _entry_identity(
                    os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                )
                for name in after_names
            }
        except OSError as exc:
            raise DurableTreeError(f"owned tree directory mutated: {path}") from exc
        after = os.fstat(descriptor)
        if (
            after_names != names
            or after_entry_identities != entry_identities
            or (after.st_dev, after.st_ino, after.st_mode)
            != (before.st_dev, before.st_ino, before.st_mode)
        ):
            raise DurableTreeError(f"owned tree directory mutated: {path}")
        _sync_descriptor(descriptor, path)

    try:
        walk(root_descriptor, tree_root, 0)
        root_after = os.fstat(root_descriptor)
        try:
            rebound_root = os.stat(tree_root, follow_symlinks=False)
        except OSError as exc:
            raise DurableTreeError(
                f"owned tree root was swapped: {tree_root}"
            ) from exc
        if _entry_identity(rebound_root) != _entry_identity(root_after):
            raise DurableTreeError(f"owned tree root was swapped: {tree_root}")
    finally:
        os.close(root_descriptor)

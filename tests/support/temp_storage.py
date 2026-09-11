"""Helpers that keep test-only filesystem staging bounded and cleanable."""

from __future__ import annotations

import shutil
import stat
from pathlib import Path
from typing import Iterator


_COPY_IGNORES = (
    ".git",
    ".pytest_cache",
    "*.egg-info",
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "node_modules",
)
_IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}


def copy_package_build_tree(
    source: Path,
    destination: Path,
    *,
    dirs_exist_ok: bool = False,
) -> None:
    """Copy package inputs with the same filtering used by the wheel test."""
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=dirs_exist_ok,
        ignore=shutil.ignore_patterns(*_COPY_IGNORES),
    )


def package_checkout_files(*roots: Path) -> dict[Path, tuple[bytes, int]]:
    """Capture package-source files so a test can detect checkout mutation."""
    paths = [path for root in roots for path in _iter_package_source_files(root)]
    return {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}


def restore_owner_write_permissions(root: Path) -> None:
    """Make a pytest temporary root writable again after immutable-tree tests."""
    if not root.exists() or root.is_symlink():
        return
    paths = sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in (*paths, root):
        if path.is_symlink():
            continue
        path.chmod(path.stat().st_mode | stat.S_IWUSR)


def _is_ignored_package_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in _IGNORED_DIRECTORY_NAMES for part in relative.parts[:-1]):
        return True
    name = relative.name
    return name == ".DS_Store" or name.endswith(".pyc") or any(
        part.endswith(".egg-info") for part in relative.parts
    )


def _iter_package_source_files(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            if path.is_dir():
                if path.name in _IGNORED_DIRECTORY_NAMES or path.name.endswith(
                    ".egg-info"
                ):
                    continue
                pending.append(path)
            elif path.is_file() and not _is_ignored_package_path(path, root):
                yield path

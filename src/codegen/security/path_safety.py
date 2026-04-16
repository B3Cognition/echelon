"""
path_safety.py — Path traversal prevention utilities.
Spec 018 T-SEC-2: RAR-002 mitigation.

Mitigations implemented:
  1. os.path.realpath() on all user-supplied paths (resolves symlinks + relative segments)
  2. Containment check: resolved path must be descendant of trusted_root
  3. safe_walk(): os.scandir() with follow_symlinks=False to prevent symlink following
  4. anchor_output(): all output file writes anchored to pipeline CWD, not input path
"""
from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from .exceptions import PathTraversalError


class PathSafety:
    """
    Path traversal prevention for user-supplied paths.
    All methods raise PathTraversalError if a path escapes the trusted root.
    """

    def __init__(self, trusted_root: str | Path) -> None:
        """
        Args:
            trusted_root: The directory boundary. All user-supplied paths must
                          resolve to this directory or a descendant.
                          Typically: os.path.realpath(os.path.expanduser("~"))
                          or the explicitly declared project root.
        """
        self._trusted_root = os.path.realpath(str(trusted_root))

    @property
    def trusted_root(self) -> str:
        return self._trusted_root

    def normalize(self, path: str | Path) -> str:
        """
        Normalize a path: resolve symlinks, expand user, make absolute.
        Returns the real absolute path string.
        Does NOT check containment — call assert_contained() separately.
        """
        return os.path.realpath(os.path.expanduser(str(path)))

    def assert_contained(self, path: str | Path, supplied_path: str | None = None) -> str:
        """
        Assert that path is a descendant of (or equal to) trusted_root.
        Returns the normalized path string if safe.
        Raises PathTraversalError if the path escapes trusted_root.

        Args:
            path: The path to check (may be unnormalized).
            supplied_path: The original user-supplied string for error messages.
        """
        normalized = self.normalize(path)
        supplied = str(supplied_path) if supplied_path is not None else str(path)

        # A path is contained if it equals trusted_root OR starts with trusted_root + os.sep
        if normalized != self._trusted_root and not normalized.startswith(
            self._trusted_root + os.sep
        ):
            raise PathTraversalError(
                supplied_path=supplied,
                resolved_path=normalized,
                trusted_root=self._trusted_root,
            )
        return normalized

    def safe_walk(
        self,
        root: str | Path,
        max_depth: int = 20,
        skip_hidden: bool = True,
    ) -> Generator[str, None, None]:
        """
        Recursively yield file paths under root without following symlinks.
        Spec 018 RAR-002 A2 mitigation: symlinks are not followed.

        Args:
            root: Directory to walk. Must be within trusted_root.
            max_depth: Maximum recursion depth (prevents infinite loops).
            skip_hidden: If True, skip files/dirs starting with '.'.

        Yields:
            Absolute path strings of regular files (not symlinks, not dirs).
        """
        normalized_root = self.assert_contained(root, supplied_path=str(root))
        yield from self._walk_dir(normalized_root, depth=0, max_depth=max_depth, skip_hidden=skip_hidden)

    def _walk_dir(
        self,
        directory: str,
        depth: int,
        max_depth: int,
        skip_hidden: bool,
    ) -> Generator[str, None, None]:
        if depth > max_depth:
            return
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    if skip_hidden and entry.name.startswith("."):
                        continue
                    # follow_symlinks=False: is_file()/is_dir() check the link itself
                    if entry.is_symlink():
                        continue  # RAR-002 A2: skip all symlinks
                    if entry.is_file(follow_symlinks=False):
                        yield entry.path
                    elif entry.is_dir(follow_symlinks=False):
                        yield from self._walk_dir(
                            entry.path, depth + 1, max_depth, skip_hidden
                        )
        except PermissionError:
            pass  # Skip directories we cannot read

    def anchor_output(self, filename: str, subdir: str | None = None) -> str:
        """
        Construct an output file path anchored to the pipeline CWD.
        Spec 018 RAR-002: all output writes (constitution.md, .bak, archive YAML)
        must be anchored to os.getcwd() at pipeline start, not the input path.

        Args:
            filename: The output filename (e.g. 'constitution.md').
                      Must not contain path separators or '..' segments.
            subdir: Optional subdirectory within CWD (e.g. 'archive').

        Returns:
            Absolute path string within CWD (and trusted_root).

        Raises:
            ValueError: If filename contains path separator characters.
            PathTraversalError: If the constructed path escapes trusted_root.
        """
        if os.sep in filename or (os.altsep and os.altsep in filename):
            raise ValueError(
                f"Output filename '{filename}' must not contain path separators. "
                "Use subdir parameter for subdirectory placement."
            )
        if ".." in filename.split(os.sep):
            raise ValueError(f"Output filename '{filename}' contains '..' segment")

        cwd = os.getcwd()
        if subdir:
            base = os.path.join(cwd, subdir)
        else:
            base = cwd

        output_path = os.path.join(base, filename)
        # Verify the constructed path is within trusted_root
        return self.assert_contained(output_path, supplied_path=filename)

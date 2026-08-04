"""Small platform-native atomic no-replace installation primitive."""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import sys


def _unsupported() -> OSError:
    return OSError(
        errno.ENOTSUP,
        f"atomic no-replace rename is unsupported on {sys.platform}",
    )


def atomic_rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename one sibling path, failing if destination exists."""

    source_path = Path(source)
    destination_path = Path(destination)
    if (
        source_path.name in {"", ".", ".."}
        or destination_path.name in {"", ".", ".."}
        or source_path.parent.resolve() != destination_path.parent.resolve()
    ):
        raise ValueError("atomic no-replace rename requires direct sibling paths")
    parent = source_path.parent.resolve()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = os.open(parent, flags)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        source_name = os.fsencode(source_path.name)
        destination_name = os.fsencode(destination_path.name)
        if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
            function = libc.renameatx_np
            function.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            function.restype = ctypes.c_int
            arguments = (
                parent_fd,
                source_name,
                parent_fd,
                destination_name,
                0x00000004,  # RENAME_EXCL
            )
        elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
            function = libc.renameat2
            function.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            function.restype = ctypes.c_int
            arguments = (
                parent_fd,
                source_name,
                parent_fd,
                destination_name,
                0x00000001,  # RENAME_NOREPLACE
            )
        else:
            raise _unsupported()
        ctypes.set_errno(0)
        if function(*arguments) != 0:
            error_number = ctypes.get_errno() or errno.EIO
            raise OSError(error_number, os.strerror(error_number), destination_path)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)

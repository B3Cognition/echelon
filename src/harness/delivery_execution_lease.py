"""Nonblocking native Delivery execution exclusion for one target root."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
import os
from pathlib import Path
import stat
from typing import Iterator

from harness.paths import runs_dir


class DeliveryExecutionLocked(RuntimeError):
    """A native Delivery command already owns this target's execution lease."""


@contextmanager
def target_delivery_execution_lease(harness_root: Path) -> Iterator[None]:
    """Hold an OS-released lease from native admission through controller exit."""
    path = runs_dir(Path(harness_root)) / ".delivery-execution.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("unsafe delivery execution lease")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise DeliveryExecutionLocked("delivery already running for this target") from exc
            raise
        yield
    finally:
        os.close(fd)

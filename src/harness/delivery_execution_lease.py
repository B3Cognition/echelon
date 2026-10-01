"""Nonblocking native Delivery execution exclusion for one target root."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import errno
import fcntl
import os
from pathlib import Path
import stat
import threading
from typing import Iterator

from harness.paths import runs_dir


class DeliveryExecutionLocked(RuntimeError):
    """A native Delivery command already owns this target's execution lease."""


_held_lease_keys: ContextVar[frozenset[tuple[int, int, str]]] = ContextVar(
    "delivery_execution_lease_keys", default=frozenset(),
)
_adapter_reentry_keys: ContextVar[frozenset[tuple[int, int, str]]] = ContextVar(
    "delivery_execution_adapter_reentry_keys", default=frozenset(),
)


@contextmanager
def target_delivery_execution_lease(
    harness_root: Path, *, adapter_reentry: bool = False,
    allow_adapter_reentry: bool = False,
) -> Iterator[None]:
    """Hold an OS-released lease from native admission through controller exit."""
    path = runs_dir(Path(harness_root).resolve()) / ".delivery-execution.lock"
    key = (os.getpid(), threading.get_ident(), str(path))
    if key in _held_lease_keys.get():
        if adapter_reentry and key in _adapter_reentry_keys.get():
            # Consume the CLI's one adapter entry while inside it; a nested
            # adapter or CLI command still contends with the running command.
            token = _adapter_reentry_keys.set(
                _adapter_reentry_keys.get() - {key}
            )
            try:
                yield
            finally:
                _adapter_reentry_keys.reset(token)
            return
        raise DeliveryExecutionLocked("delivery already running for this target")
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
        token = _held_lease_keys.set(frozenset((*_held_lease_keys.get(), key)))
        adapter_token = _adapter_reentry_keys.set(
            _adapter_reentry_keys.get() | {key}
            if allow_adapter_reentry else _adapter_reentry_keys.get()
        )
        try:
            yield
        finally:
            _adapter_reentry_keys.reset(adapter_token)
            _held_lease_keys.reset(token)
    finally:
        os.close(fd)

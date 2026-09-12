"""Invocation-scoped control of Echelon diagnostic output."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator


_verbose: ContextVar[bool] = ContextVar("echelon_verbose", default=False)


def is_verbose() -> bool:
    """Return whether the current Echelon CLI invocation requested diagnostics."""
    return _verbose.get()


@contextmanager
def verbose_mode(enabled: bool = True) -> Iterator[None]:
    """Apply the requested output detail only while one CLI invocation executes."""
    token = _verbose.set(enabled)
    try:
        yield
    finally:
        _verbose.reset(token)

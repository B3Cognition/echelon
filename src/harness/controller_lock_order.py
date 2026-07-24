"""Debug assertions for the squad controller's global lock hierarchy."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


CONTROLLER_LOCK_RANKS = {
    "phase_a": 1,
    "spec_run": 2,
    "publication": 3,
    "completion": 4,
    "checkpoint": 5,
    "journal": 6,
    "telemetry": 7,
    "state": 8,
}
_local = threading.local()


class LockOrderViolation(RuntimeError):
    """Raised before an operation can acquire a lower-ranked lock."""


@contextmanager
def controller_lock_order(
    name: str,
    identity: str,
) -> Iterator[None]:
    """Assert the controller's deterministic lock hierarchy for one scope."""
    rank = CONTROLLER_LOCK_RANKS.get(name)
    if rank is None:
        raise ValueError("unknown controller lock")
    if not isinstance(identity, str) or not identity:
        raise ValueError("controller lock identity must be a non-empty string")
    stack = getattr(_local, "stack", None)
    if stack is None:
        stack = []
        _local.stack = stack
    if stack:
        outer_name, outer_rank, outer_identity = stack[-1]
        if rank < outer_rank:
            raise LockOrderViolation(
                f"controller lock inversion: {outer_name} -> {name}"
            )
        if rank == outer_rank and (
            name != outer_name or identity != outer_identity
        ):
            raise LockOrderViolation(
                "controller same-rank lock mismatch: "
                f"{outer_name}[{outer_identity}] -> "
                f"{name}[{identity}]"
            )
    entry = (name, rank, identity)
    stack.append(entry)
    try:
        yield
    finally:
        current = stack.pop()
        if current != entry:
            raise AssertionError("controller lock stack corrupted")
        if not stack:
            del _local.stack

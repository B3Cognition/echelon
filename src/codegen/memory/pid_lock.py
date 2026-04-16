"""
pid_lock.py — PID lock acquire/release with stale-lock handling.
Spec 024 T-006: Create ~/.codegen/memory/ directory structure and PID lock.

FRs: FR-CFG-009, FR-CFG-010, FR-CFG-011, NFR-SEC-004
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_LOCK_PATH = Path.home() / ".echelon" / "pipeline.lock"


class PidLockError(Exception):
    """Raised when another live pipeline process holds the PID lock."""


def acquire(lock_path: Path = DEFAULT_LOCK_PATH) -> None:
    """
    Acquire the pipeline PID lock.

    - If no lock file: write current PID and return.
    - If lock file contains a live PID: raise PidLockError with the PID.
    - If lock file contains a stale PID (process not running): delete and re-acquire.

    Raises:
        PidLockError: If a live pipeline process holds the lock.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        try:
            existing_pid = int(lock_path.read_text().strip())
        except (ValueError, OSError):
            # Corrupted lock — treat as stale
            existing_pid = None

        if existing_pid is not None and _is_alive(existing_pid):
            raise PidLockError(
                f"pipeline.lock: another codegen process is running (PID {existing_pid}). "
                f"Wait for it to finish or delete {lock_path} if it is stale."
            )
        # Stale lock — remove it
        lock_path.unlink(missing_ok=True)

    lock_path.write_text(str(os.getpid()))


def release(lock_path: Path = DEFAULT_LOCK_PATH) -> None:
    """Release the PID lock if it belongs to the current process."""
    lock_path = Path(lock_path)
    if not lock_path.exists():
        return
    try:
        existing_pid = int(lock_path.read_text().strip())
    except (ValueError, OSError):
        return
    if existing_pid == os.getpid():
        lock_path.unlink(missing_ok=True)


def setup_memory_dirs(
    epmem_db_path: Path,
    smem_db_path: Path,
) -> None:
    """
    Create parent directories for EPMEM and SMEM databases.
    Sets Unix permissions 700 on ~/.codegen/memory/ (NFR-SEC-004).
    """
    for db_path in (epmem_db_path, smem_db_path):
        parent = Path(db_path).parent
        parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass


def _is_alive(pid: int) -> bool:
    """Return True if a process with the given PID is currently running."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it
        return True

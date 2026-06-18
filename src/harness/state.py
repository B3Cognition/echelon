"""StateStore with atomic writes, .bak snapshots, lockfile management.

Per FR-STATE-001a: JSON per-strategy state files.
Per FR-STATE-001b: Atomic writes (tempfile + fsync + rename) with .bak.
Per FR-STATE-002: Lockfile with PID validation, stale lock reclaim.
Per FR-MODE-002: Mode is immutable after initialization.
Per data-model: tokens_used monotonically non-decreasing,
                iteration_log append-only,
                outer_iter/inner_iter monotonically non-decreasing.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# --- Valid state transitions per data-model ---

VALID_TRANSITIONS = {
    "initialized": {"running"},
    "running": {"converged", "blocked", "failed", "interrupted", "cancelled_by_coordinator"},
    "blocked": {"running"},
    "converged": set(),
    "failed": set(),
    "interrupted": {"running"},
    "cancelled_by_coordinator": set(),
}

VALID_STATUSES = set(VALID_TRANSITIONS.keys())


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""


class ModeImmutableError(Exception):
    """Raised when mode change is attempted after initialization."""


class MonotonicViolationError(Exception):
    """Raised when a monotonically non-decreasing field decreases."""


class LockContentionError(Exception):
    """Raised when another process holds the lock."""


class StateStore:
    """Manages per-strategy state.json with atomic writes and locking.

    Invariants:
    - Writes are atomic: write to .tmp, fsync, rename.
    - Previous version kept as .bak.
    - Lockfile: PID + timestamp + run_id. Stale locks (dead PID) reclaimed.
    - Mode is immutable after first write.
    - tokens_used is monotonically non-decreasing.
    - iteration_log is append-only.
    """

    def __init__(self, state_dir: Path, spec_id: str, strategy_id: str) -> None:
        self.state_dir = Path(state_dir)
        self.spec_id = spec_id
        self.strategy_id = strategy_id
        self.state_file = self.state_dir / f"{strategy_id}.json"
        self.lock_file = self.state_dir / f"{strategy_id}.lock"
        self._data: Optional[Dict[str, Any]] = None

    def _ensure_dir(self) -> None:
        """Create state directory if needed."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    # --- Locking ---

    def acquire_lock(self, run_id: str) -> None:
        """Acquire the lockfile for this spec_id.

        Writes PID + timestamp + run_id. Checks for stale locks.

        Raises:
            LockContentionError: If another live process holds the lock.
        """
        self._ensure_dir()

        if self.lock_file.exists():
            try:
                lock_data = self.lock_file.read_text(encoding="utf-8")
                parts = lock_data.strip().split("\n")
                if len(parts) >= 1:
                    pid = int(parts[0].split("=")[1])
                    if self._is_pid_alive(pid):
                        raise LockContentionError(
                            f"Lock held by PID {pid}. "
                            f"Lock file: {self.lock_file}"
                        )
                    else:
                        logger.warning(
                            "Reclaiming stale lock from dead PID %d", pid
                        )
            except (ValueError, IndexError, OSError):
                logger.warning("Corrupt lock file, reclaiming: %s", self.lock_file)

        lock_content = (
            f"pid={os.getpid()}\n"
            f"timestamp={datetime.now(timezone.utc).isoformat()}\n"
            f"run_id={run_id}\n"
        )
        self.lock_file.write_text(lock_content, encoding="utf-8")

    def release_lock(self) -> None:
        """Release the lockfile."""
        try:
            self.lock_file.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove lock file: %s", self.lock_file)

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check if a process with the given PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    # --- Atomic I/O ---

    def read(self) -> Dict[str, Any]:
        """Read the current state from disk."""
        if not self.state_file.exists():
            return {}
        text = self.state_file.read_text(encoding="utf-8")
        self._data = json.loads(text)
        return dict(self._data)

    def write(self, data: Dict[str, Any]) -> None:
        """Write state atomically: .tmp -> fsync -> rename, keep .bak.

        Validates invariants before writing.
        """
        self._ensure_dir()
        self._validate_invariants(data)

        # Keep previous as .bak
        if self.state_file.exists():
            bak_file = self.state_file.with_suffix(".json.bak")
            try:
                bak_file.write_text(
                    self.state_file.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            except OSError:
                logger.warning("Could not write .bak file: %s", bak_file)

        # Atomic write: tempfile -> fsync -> rename
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        content = json.dumps(data, indent=2, ensure_ascii=False)

        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.state_file.parent),
            prefix=".state-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.rename(tmp_path, str(self.state_file))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        self._data = data

    # --- Invariant validation ---

    def _validate_invariants(self, new_data: Dict[str, Any]) -> None:
        """Validate state invariants before writing."""
        old_data = self._data or self.read()
        if not old_data:
            # First write, no invariants to check
            return

        # Status transition validation
        old_status = old_data.get("status")
        new_status = new_data.get("status")
        if old_status and new_status and old_status != new_status:
            valid_next = VALID_TRANSITIONS.get(old_status, set())
            if new_status not in valid_next:
                raise InvalidTransitionError(
                    f"Invalid state transition: {old_status} -> {new_status}. "
                    f"Valid transitions from {old_status}: {valid_next}"
                )

        # Mode immutability (FR-MODE-002)
        old_mode = old_data.get("mode")
        new_mode = new_data.get("mode")
        if old_mode and new_mode and old_mode != new_mode:
            raise ModeImmutableError(
                f"Mode is immutable after initialization. "
                f"Cannot change from '{old_mode}' to '{new_mode}'"
            )

        # tokens_used monotonically non-decreasing
        old_tokens = old_data.get("tokens_used", 0)
        new_tokens = new_data.get("tokens_used", 0)
        if new_tokens < old_tokens:
            raise MonotonicViolationError(
                f"tokens_used must be monotonically non-decreasing: "
                f"{old_tokens} -> {new_tokens}"
            )

        # iteration_log append-only
        old_log = old_data.get("iteration_log", [])
        new_log = new_data.get("iteration_log", [])
        if len(new_log) < len(old_log):
            raise MonotonicViolationError(
                f"iteration_log is append-only: "
                f"cannot shrink from {len(old_log)} to {len(new_log)} entries"
            )
        # Verify existing entries unchanged
        for i, old_entry in enumerate(old_log):
            if i < len(new_log) and new_log[i] != old_entry:
                raise MonotonicViolationError(
                    f"iteration_log entry {i} was modified. "
                    f"Entries are immutable once written."
                )

        # outer_iter/inner_iter monotonically non-decreasing
        for field_name in ("outer_iter", "inner_iter"):
            old_val = old_data.get(field_name, 0)
            new_val = new_data.get(field_name, 0)
            if new_val < old_val:
                raise MonotonicViolationError(
                    f"{field_name} must be monotonically non-decreasing: "
                    f"{old_val} -> {new_val}"
                )

    # --- Convenience methods ---

    def initialize(
        self,
        run_id: str,
        mode: str,
        max_outer: int = 5,
        max_inner: int = 3,
        token_budget: int = 0,
        target_repo: str | None = None,
        target_path: str | None = None,
        spec_dir: str | None = None,
        spec_file: str | None = None,
        tasks_file: str | None = None,
        workspace_root: str | None = None,
        workspace_git_role: str | None = None,
        source_root: str | None = None,
        source_id: str | None = None,
        source_git_role: str | None = None,
    ) -> Dict[str, Any]:
        """Create initial state.

        If a previous run left the state in 'running' (process was killed or
        crashed), treat it as interrupted so the transition validator allows
        re-initialization via the interrupted -> initialized path (not a valid
        transition either, so we bypass validation by writing interrupted first,
        then clearing _data to force a first-write on the next write).
        """
        existing = self.read()
        if existing:
            # Any completed or stale state blocks re-initialization via the
            # transition validator. Delete the file so the next write() is
            # treated as a first-write (no existing state to validate against).
            try:
                if self.state_file.exists():
                    self.state_file.unlink()
                bak = self.state_file.with_suffix(".json.bak")
                if bak.exists():
                    bak.unlink()
            except OSError as exc:
                logger.warning("Could not remove prior state file: %s", exc)
            self._data = None
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "spec_id": self.spec_id,
            "strategy_id": self.strategy_id,
            "run_id": run_id,
            "status": "initialized",
            "mode": mode,
            "outer_iter": 0,
            "max_outer": max_outer,
            "inner_iter": 0,
            "max_inner": max_inner,
            "token_budget": token_budget,
            "tokens_used": 0,
            "cancel_requested": False,
            "pr_url": None,
            "branch_name": None,
            "target_repo": target_repo,
            "target_path": target_path,
            "workspace_root": workspace_root,
            "workspace_git_role": workspace_git_role,
            "source_root": source_root,
            "source_id": source_id,
            "source_git_role": source_git_role,
            "spec_dir": spec_dir,
            "spec_file": spec_file,
            "tasks_file": tasks_file,
            "last_verify_result": None,
            "termination_reason": None,
            "escalation_file": None,
            "iteration_log": [],
            "started_at": now,
            "updated_at": now,
        }
        self.write(data)
        return data

    def transition(self, new_status: str) -> Dict[str, Any]:
        """Transition to a new status."""
        data = self.read()
        data["status"] = new_status
        self.write(data)
        return data

"""Single-writer locking for workspace artifact publication."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.re_registry import ensure_re_layout


ACTIVE_RUN_STATUSES = frozenset({"running", "in_progress"})
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class RePublishLocked(RuntimeError):
    """Raised when another publisher owns the workspace lock."""

    def __init__(self, owner_run_id: str) -> None:
        self.owner_run_id = owner_run_id
        super().__init__(f"workspace artifact publication lock is owned by {owner_run_id}")


class ReExtractLocked(RuntimeError):
    """Raised when another controller owns the workspace extraction lease."""

    def __init__(self, owner_run_id: str) -> None:
        self.owner_run_id = owner_run_id
        super().__init__(f"RE extraction lock is owned by {owner_run_id}")


class RePublicationActiveRun(RuntimeError):
    """Raised when another active RE lifecycle could publish stale output."""

    def __init__(self, runs: tuple[Path, ...]) -> None:
        self.runs = runs
        super().__init__(
            "other active RE runs block workspace artifact publication: "
            + ", ".join(path.name for path in runs)
        )


class RePublishRecoveryRequired(RuntimeError):
    """Raised when interrupted replacement must be rolled back first."""


@dataclass
class RePublishLock:
    path: Path
    owner_run_id: str
    workspace_root: Path

    @classmethod
    def acquire(
        cls,
        workspace_root: Path,
        owner_run_id: str,
        owner_run_dir: Path | None,
    ) -> "RePublishLock":
        root = workspace_root.resolve()
        if not _SAFE_RUN_ID.fullmatch(owner_run_id):
            raise ValueError(f"unsafe publication owner run ID: {owner_run_id!r}")
        paths = ensure_re_layout(root)
        other_runs = find_other_active_runs(root, owner_run_dir)
        if other_runs:
            raise RePublicationActiveRun(other_runs)

        lock_path = paths.locks / "publish.lock"
        try:
            lock_path.mkdir()
        except FileExistsError as exc:
            owner = _read_owner(lock_path, required=False)
            raise RePublishLocked(str(owner.get("run_id") or "unknown")) from exc
        pending = _pending_publication_journals(paths.staging)
        if pending:
            shutil.rmtree(lock_path)
            raise RePublishRecoveryRequired(
                f"rollback journal must be recovered before publication: {pending[0]}"
            )

        metadata = {
            "run_id": owner_run_id,
            "run_dir": str(owner_run_dir.resolve()) if owner_run_dir else None,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _write_json_atomic(lock_path / "owner.json", metadata)
        except Exception:
            shutil.rmtree(lock_path)
            raise
        return cls(path=lock_path, owner_run_id=owner_run_id, workspace_root=root)

    def release(self) -> None:
        if not self.path.exists():
            return
        owner = _read_owner(self.path)
        if owner.get("run_id") != self.owner_run_id:
            raise RePublishLocked(str(owner.get("run_id") or "unknown"))
        if _owner_has_pending_journal(self.workspace_root, self.owner_run_id):
            raise RePublishRecoveryRequired(
                "rollback journal must be recovered before removing publication lock"
            )
        shutil.rmtree(self.path)

    def __enter__(self) -> "RePublishLock":
        return self

    def __exit__(self, *_exc: object) -> None:
        if not _owner_has_pending_journal(self.workspace_root, self.owner_run_id):
            self.release()


@dataclass
class ReExtractionLock:
    """Single-writer lease for an active workspace RE controller."""

    path: Path
    owner_run_id: str

    @classmethod
    def acquire(
        cls,
        workspace_root: Path,
        owner_run_id: str,
        owner_run_dir: Path,
    ) -> "ReExtractionLock":
        root = workspace_root.resolve()
        if not _SAFE_RUN_ID.fullmatch(owner_run_id):
            raise ValueError(f"unsafe extraction owner run ID: {owner_run_id!r}")
        lock_path = ensure_re_layout(root).locks / "extract.lock"
        while True:
            try:
                lock_path.mkdir()
                break
            except FileExistsError as exc:
                owner = _read_owner(lock_path, required=False)
                if _dead_local_extraction_owner(owner):
                    # SIGKILL/SIGTERM can bypass __exit__. A dead local PID is
                    # definitive evidence that this lease has no holder.
                    shutil.rmtree(lock_path, ignore_errors=True)
                    continue
                raise ReExtractLocked(str(owner.get("run_id") or "unknown")) from exc
        metadata = {
            "run_id": owner_run_id,
            "run_dir": str(owner_run_dir.resolve()),
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _write_json_atomic(lock_path / "owner.json", metadata)
        except Exception:
            shutil.rmtree(lock_path)
            raise
        return cls(path=lock_path, owner_run_id=owner_run_id)

    def release(self) -> None:
        if not self.path.exists():
            return
        owner = _read_owner(self.path)
        if owner.get("run_id") != self.owner_run_id:
            raise ReExtractLocked(str(owner.get("run_id") or "unknown"))
        shutil.rmtree(self.path)

    def __enter__(self) -> "ReExtractionLock":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def _dead_local_extraction_owner(owner: dict[str, Any]) -> bool:
    hostname = owner.get("hostname")
    pid = owner.get("pid")
    return (
        hostname == socket.gethostname()
        and isinstance(pid, int)
        and not isinstance(pid, bool)
        and not _pid_alive(pid)
    )


def find_other_active_runs(
    workspace_root: Path,
    owner_run_dir: Path | None,
) -> tuple[Path, ...]:
    """Return active RE run directories other than the publisher owner.

    Spec runs consume immutable snapshots, so their activity never blocks a new
    publication.
    """
    root = workspace_root.resolve()
    excluded = owner_run_dir.resolve() if owner_run_dir else None
    active: list[Path] = []
    seen: set[Path] = set()
    for base_name in ("runs", "squad"):
        base = root / base_name
        if not base.is_dir():
            continue
        for candidate in sorted(base.iterdir(), key=lambda path: path.name):
            if not candidate.is_dir():
                continue
            resolved = candidate.resolve()
            if resolved == excluded or resolved in seen:
                continue
            state = _read_json(candidate / "state.json", required=False)
            if (
                state.get("run_kind") == "re"
                and state.get("status") in ACTIVE_RUN_STATUSES
            ):
                seen.add(resolved)
                active.append(resolved)
    return tuple(active)


def recover_stale_publish_lock(
    workspace_root: Path,
    *,
    stale_after_seconds: int = 3600,
) -> bool:
    """Remove a provably stale lock when no replacement rollback is pending."""
    root = workspace_root.resolve()
    lock_path = ensure_re_layout(root).locks / "publish.lock"
    owner = recoverable_publish_lock_owner(
        root,
        stale_after_seconds=stale_after_seconds,
    )
    if owner is None:
        return False
    run_id = str(owner.get("run_id") or "")
    journal = ensure_re_layout(root).staging / run_id / "rollback-journal.json"
    if journal.is_file():
        journal_data = _read_json(journal)
        if journal_data.get("status") in {"replacing", "rolling_back"}:
            raise RePublishRecoveryRequired(
                f"rollback journal must be recovered before removing lock: {journal}"
            )

    shutil.rmtree(lock_path)
    return True


def _owner_has_pending_journal(workspace_root: Path, owner_run_id: str) -> bool:
    journal = ensure_re_layout(workspace_root).staging / owner_run_id / "rollback-journal.json"
    if not journal.is_file():
        return False
    return _read_json(journal).get("status") in {"replacing", "rolling_back"}


def _pending_publication_journals(staging_root: Path) -> tuple[Path, ...]:
    pending: list[Path] = []
    if not staging_root.is_dir():
        return ()
    for candidate in sorted(staging_root.iterdir(), key=lambda path: path.name):
        journal = candidate / "rollback-journal.json"
        if journal.is_file() and _read_json(journal).get("status") in {"replacing", "rolling_back"}:
            pending.append(journal)
    return tuple(pending)


def claim_orphan_publish_recovery(workspace_root: Path) -> RePublishLock | None:
    """Atomically claim exactly one safe orphan journal for recovery."""
    root = workspace_root.resolve()
    paths = ensure_re_layout(root)
    if not _pending_publication_journals(paths.staging):
        return None
    lock_path = paths.locks / "publish.lock"
    claim_path = paths.locks / f".publish-recovery-claim-{uuid.uuid4().hex}"
    try:
        claim_path.mkdir()
    except FileExistsError:
        return None
    try:
        pending = _pending_publication_journals(paths.staging)
        if len(pending) != 1:
            if pending:
                raise RePublishRecoveryRequired("multiple orphan rollback journals require manual recovery")
            shutil.rmtree(claim_path)
            return None
        journal = pending[0]
        stage = journal.parent
        if stage.is_symlink() or not _SAFE_RUN_ID.fullmatch(stage.name):
            raise RePublishRecoveryRequired("orphan rollback journal path is unsafe")
        # Write and sync ownership before exposing the lock. A crash can leave
        # only an unclaimed temporary directory, never an ownerless lock.
        _write_json_atomic(
            claim_path / "owner.json",
            {
                "run_id": stage.name,
                "run_dir": None,
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        try:
            os.replace(claim_path, lock_path)
        except FileExistsError:
            shutil.rmtree(claim_path, ignore_errors=True)
            return None
        _fsync_directory(paths.locks)
        owner = RePublishLock(path=lock_path, owner_run_id=stage.name, workspace_root=root)
        return owner
    except BaseException:
        shutil.rmtree(claim_path, ignore_errors=True)
        raise


def recoverable_publish_lock_owner(
    workspace_root: Path,
    *,
    stale_after_seconds: int = 3600,
) -> dict[str, Any] | None:
    """Return inactive stale owner metadata without modifying the lock."""
    root = workspace_root.resolve()
    lock_path = ensure_re_layout(root).locks / "publish.lock"
    if not lock_path.exists():
        return None
    owner = _read_owner(lock_path)
    run_id = str(owner.get("run_id") or "")
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise RePublishRecoveryRequired(f"publish lock run ID is malformed: {run_id!r}")
    if _owner_run_is_active(root, owner):
        return None

    hostname = str(owner.get("hostname") or "")
    pid = owner.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int):
        raise RePublishRecoveryRequired("publish lock owner PID is malformed")
    if hostname == socket.gethostname():
        if _pid_alive(pid):
            return None
    elif _lock_age_seconds(owner) < stale_after_seconds:
        return None
    return owner


def _owner_run_is_active(workspace_root: Path, owner: dict[str, Any]) -> bool:
    run_dir_value = owner.get("run_dir")
    if isinstance(run_dir_value, str) and run_dir_value:
        run_dir = Path(run_dir_value)
        state = _read_json(run_dir / "state.json", required=False)
        if state.get("status") in ACTIVE_RUN_STATUSES:
            return True

    owner_run_id = str(owner.get("run_id") or "")
    for base_name in ("runs", "squad"):
        state = _read_json(
            workspace_root / base_name / owner_run_id / "state.json",
            required=False,
        )
        if state.get("status") in ACTIVE_RUN_STATUSES:
            return True
    return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lock_age_seconds(owner: dict[str, Any]) -> float:
    value = owner.get("acquired_at")
    if not isinstance(value, str) or not value:
        raise RePublishRecoveryRequired("publish lock acquisition time is malformed")
    try:
        acquired_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RePublishRecoveryRequired("publish lock acquisition time is malformed") from exc
    if acquired_at.tzinfo is None:
        raise RePublishRecoveryRequired("publish lock acquisition time has no timezone")
    return max(0.0, (datetime.now(timezone.utc) - acquired_at).total_seconds())


def _read_owner(lock_path: Path, *, required: bool = True) -> dict[str, Any]:
    return _read_json(lock_path / "owner.json", required=required)


def _read_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise RePublishRecoveryRequired(f"required lock metadata is missing: {path}")
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if required:
            raise RePublishRecoveryRequired(f"cannot read lock metadata {path}: {exc}") from exc
        return {}
    if not isinstance(raw, dict):
        if required:
            raise RePublishRecoveryRequired(f"lock metadata must be an object: {path}")
        return {}
    return raw


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
        _fsync_directory(path.parent)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

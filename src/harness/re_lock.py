"""Single-writer locking for workspace artifact publication."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import fcntl

from harness.re_registry import ReRegistryPaths, ensure_re_layout


ACTIVE_RUN_STATUSES = frozenset({"running", "in_progress"})
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_PUBLISH_CLAIM = ".publish-claim.json"
_PUBLISH_CLAIM_GUARD = ".publish-claim.guard"


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


@dataclass(frozen=True)
class _PublicationClaim:
    path: Path
    metadata: dict[str, Any]


@dataclass
class RePublishLock:
    path: Path
    owner_run_id: str
    workspace_root: Path
    claim: _PublicationClaim | None = None
    allow_ownerless_release: bool = False

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

        metadata = _owner_metadata(owner_run_id, owner_run_dir, claim_kind="publisher")
        claim = _acquire_publication_claim(paths, root, metadata)
        if claim is None:
            raise RePublishLocked(_publication_claim_owner_hint(paths))
        lock_path = paths.locks / "publish.lock"
        lock_owned = False
        try:
            lock_path.mkdir()
            lock_owned = True
            _fsync_directory(paths.locks)
        except FileExistsError as exc:
            _release_publication_claim(paths, claim)
            raise RePublishLocked(_publish_lock_owner_hint(lock_path, paths)) from exc
        except BaseException:
            if lock_owned:
                shutil.rmtree(lock_path, ignore_errors=True)
            _release_publication_claim(paths, claim)
            raise
        try:
            pending = _pending_publication_journals(paths.staging)
            if pending:
                raise RePublishRecoveryRequired(
                    f"rollback journal must be recovered before publication: {pending[0]}"
                )
            _write_json_atomic(lock_path / "owner.json", _owner_record(metadata))
            _release_publication_claim(paths, claim)
        except BaseException:
            if lock_owned:
                shutil.rmtree(lock_path, ignore_errors=True)
            _release_publication_claim(paths, claim)
            raise
        return cls(
            path=lock_path,
            owner_run_id=owner_run_id,
            workspace_root=root,
            claim=claim,
        )

    def release(self) -> None:
        if not self.path.exists():
            return
        owner_path = self.path / "owner.json"
        if owner_path.exists():
            owner = _read_owner(self.path)
            if owner.get("run_id") != self.owner_run_id:
                raise RePublishLocked(str(owner.get("run_id") or "unknown"))
        elif not (
            self.allow_ownerless_release
            and self.claim is not None
            and self.claim.metadata.get("run_id") == self.owner_run_id
        ):
            raise RePublishRecoveryRequired("ownerless publication lock has no matching claim")
        if _owner_has_pending_journal(self.workspace_root, self.owner_run_id):
            raise RePublishRecoveryRequired(
                "rollback journal must be recovered before removing publication lock"
            )
        shutil.rmtree(self.path)
        if self.claim is not None:
            _release_publication_claim(
                ensure_re_layout(self.workspace_root), self.claim
            )

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
    paths = ensure_re_layout(root)
    recovery_lock = claim_stale_publish_recovery(
        root,
        stale_after_seconds=stale_after_seconds,
    )
    if recovery_lock is None:
        return False
    journal = paths.staging / recovery_lock.owner_run_id / "rollback-journal.json"
    if journal.is_file():
        journal_data = _read_json(journal)
        if journal_data.get("status") in {"replacing", "rolling_back"}:
            _release_publication_claim(paths, recovery_lock.claim)
            raise RePublishRecoveryRequired(
                f"rollback journal must be recovered before removing lock: {journal}"
            )
    recovery_lock.release()
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


def _owner_metadata(
    owner_run_id: str,
    owner_run_dir: Path | None,
    *,
    claim_kind: str,
) -> dict[str, Any]:
    return {
        "run_id": owner_run_id,
        "run_dir": str(owner_run_dir.resolve()) if owner_run_dir else None,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "claim_kind": claim_kind,
    }


def _owner_record(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metadata[key]
        for key in ("run_id", "run_dir", "pid", "hostname", "acquired_at")
    }


@contextmanager
def _publication_claim_guard(locks_root: Path) -> Iterator[None]:
    guard = locks_root / _PUBLISH_CLAIM_GUARD
    _validate_guard_path(guard, required=False)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(guard, flags, 0o600)
    except OSError as exc:
        raise RePublishRecoveryRequired("publication claim guard cannot be opened safely") from exc
    try:
        _validate_guard_descriptor(guard, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _validate_guard_descriptor(guard, descriptor)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _validate_guard_path(path: Path, *, required: bool) -> None:
    try:
        details = os.lstat(path)
    except FileNotFoundError:
        if required:
            raise RePublishRecoveryRequired("publication claim guard disappeared")
        return
    if not stat.S_ISREG(details.st_mode):
        raise RePublishRecoveryRequired("publication claim guard path is unsafe")


def _validate_guard_descriptor(path: Path, descriptor: int) -> None:
    details = os.fstat(descriptor)
    if not stat.S_ISREG(details.st_mode):
        raise RePublishRecoveryRequired("publication claim guard is not a regular file")
    _validate_guard_path(path, required=True)
    path_details = os.lstat(path)
    if (details.st_dev, details.st_ino) != (path_details.st_dev, path_details.st_ino):
        raise RePublishRecoveryRequired("publication claim guard was replaced during acquisition")


def _read_publication_claim(paths: ReRegistryPaths) -> _PublicationClaim | None:
    claim_path = paths.locks / _PUBLISH_CLAIM
    if not claim_path.exists():
        return None
    if claim_path.is_symlink() or not claim_path.is_file():
        raise RePublishRecoveryRequired("publication claim path is unsafe")
    metadata = _read_json(claim_path)
    run_id = str(metadata.get("run_id") or "")
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise RePublishRecoveryRequired("publication claim run ID is malformed")
    if metadata.get("claim_kind") not in {"publisher", "recovery"}:
        raise RePublishRecoveryRequired("publication claim kind is malformed")
    return _PublicationClaim(path=claim_path, metadata=metadata)


def _write_claim_temp(locks_root: Path, metadata: dict[str, Any]) -> Path:
    descriptor, temporary = tempfile.mkstemp(
        dir=str(locks_root), prefix=".publish-claim-tmp-", suffix=".json"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return Path(temporary)


def _acquire_publication_claim(
    paths: ReRegistryPaths,
    workspace_root: Path,
    metadata: dict[str, Any],
    *,
    allow_locked_takeover: bool = False,
) -> _PublicationClaim | None:
    temporary = _write_claim_temp(paths.locks, metadata)
    claim_path = paths.locks / _PUBLISH_CLAIM
    published = False
    completed = False
    try:
        with _publication_claim_guard(paths.locks):
            existing = _read_publication_claim(paths)
            if existing is not None:
                stale = _recoverable_owner(
                    workspace_root,
                    existing.metadata,
                    stale_after_seconds=3600,
                )
                if (paths.locks / "publish.lock").exists() and not (
                    allow_locked_takeover and stale is not None
                ):
                    return None
                if stale is None:
                    return None
                os.unlink(existing.path)
                _fsync_directory(paths.locks)
            try:
                os.link(temporary, claim_path)
                published = True
            except FileExistsError:
                return None
            _fsync_directory(paths.locks)
            completed = True
        return _PublicationClaim(path=claim_path, metadata=metadata)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        if published and not completed:
            claim = _read_publication_claim(paths)
            if claim is not None and claim.metadata == metadata:
                try:
                    _release_publication_claim(paths, claim)
                except OSError:
                    pass


def _release_publication_claim(paths: ReRegistryPaths, claim: _PublicationClaim) -> None:
    with _publication_claim_guard(paths.locks):
        current = _read_publication_claim(paths)
        if current is not None and current.metadata == claim.metadata:
            os.unlink(current.path)
            _fsync_directory(paths.locks)


def _publication_claim_owner_hint(paths: ReRegistryPaths) -> str:
    claim = _read_publication_claim(paths)
    if claim is not None:
        return str(claim.metadata["run_id"])
    return "unknown"


def _publish_lock_owner_hint(lock_path: Path, paths: ReRegistryPaths) -> str:
    owner = _read_owner(lock_path, required=False)
    run_id = owner.get("run_id")
    if isinstance(run_id, str) and run_id:
        return run_id
    return _publication_claim_owner_hint(paths)


def claim_orphan_publish_recovery(workspace_root: Path) -> RePublishLock | None:
    """Atomically claim exactly one safe orphan journal for recovery."""
    root = workspace_root.resolve()
    paths = ensure_re_layout(root)
    initial_pending = _pending_publication_journals(paths.staging)
    if not initial_pending:
        return None
    if len(initial_pending) != 1:
        raise RePublishRecoveryRequired("multiple orphan rollback journals require manual recovery")
    initial_journal = initial_pending[0]
    initial_stage = initial_journal.parent
    if initial_stage.is_symlink() or not _SAFE_RUN_ID.fullmatch(initial_stage.name):
        raise RePublishRecoveryRequired("orphan rollback journal path is unsafe")
    metadata = _owner_metadata(initial_stage.name, None, claim_kind="recovery")
    claim = _acquire_publication_claim(paths, root, metadata)
    if claim is None:
        return None
    lock_path = paths.locks / "publish.lock"
    lock_acquired = False
    owner_install_started = False
    try:
        try:
            lock_path.mkdir()
            lock_acquired = True
            _fsync_directory(paths.locks)
        except FileExistsError:
            _release_publication_claim(paths, claim)
            return None
        except BaseException:
            if lock_acquired:
                shutil.rmtree(lock_path, ignore_errors=True)
            _release_publication_claim(paths, claim)
            raise
        pending = _pending_publication_journals(paths.staging)
        if len(pending) != 1 or pending[0].parent != initial_stage:
            shutil.rmtree(lock_path, ignore_errors=True)
            _release_publication_claim(paths, claim)
            if pending:
                raise RePublishRecoveryRequired("orphan rollback journals changed during claim")
            return None
        owner_install_started = True
        _write_json_atomic(lock_path / "owner.json", _owner_record(metadata))
        _release_publication_claim(paths, claim)
        owner = RePublishLock(
            path=lock_path,
            owner_run_id=initial_stage.name,
            workspace_root=root,
            claim=claim,
        )
        return owner
    except BaseException:
        if lock_acquired and owner_install_started:
            _fsync_directory(paths.locks)
        else:
            if lock_acquired:
                shutil.rmtree(lock_path, ignore_errors=True)
            _release_publication_claim(paths, claim)
        raise


def claim_stale_publish_recovery(
    workspace_root: Path,
    *,
    stale_after_seconds: int = 3600,
) -> RePublishLock | None:
    """Claim a stale owner lock before inspecting or recovering its journal."""
    root = workspace_root.resolve()
    paths = ensure_re_layout(root)
    owner = recoverable_publish_lock_owner(
        root,
        stale_after_seconds=stale_after_seconds,
    )
    if owner is None:
        return None
    run_id = str(owner["run_id"])
    ownerless = not (paths.locks / "publish.lock" / "owner.json").exists()
    claim = _acquire_publication_claim(
        paths,
        root,
        _owner_metadata(run_id, None, claim_kind="recovery"),
        allow_locked_takeover=True,
    )
    if claim is None:
        return None
    try:
        if ownerless:
            if (paths.locks / "publish.lock" / "owner.json").exists():
                _release_publication_claim(paths, claim)
                return None
        else:
            current = recoverable_publish_lock_owner(
                root,
                stale_after_seconds=stale_after_seconds,
            )
            if current is None or current.get("run_id") != run_id:
                _release_publication_claim(paths, claim)
                return None
        return RePublishLock(
            path=paths.locks / "publish.lock",
            owner_run_id=run_id,
            workspace_root=root,
            claim=claim,
            allow_ownerless_release=ownerless,
        )
    except BaseException:
        _release_publication_claim(paths, claim)
        raise


def recoverable_publish_lock_owner(
    workspace_root: Path,
    *,
    stale_after_seconds: int = 3600,
) -> dict[str, Any] | None:
    """Return inactive stale owner metadata without modifying the lock."""
    root = workspace_root.resolve()
    paths = ensure_re_layout(root)
    lock_path = paths.locks / "publish.lock"
    if not lock_path.exists():
        return None
    owner_path = lock_path / "owner.json"
    if owner_path.exists():
        owner = _read_owner(lock_path)
    else:
        claim = _read_publication_claim(paths)
        if claim is None:
            raise RePublishRecoveryRequired(
                "ownerless publish lock requires a complete publication claim"
            )
        owner = claim.metadata
    return _recoverable_owner(root, owner, stale_after_seconds=stale_after_seconds)


def _recoverable_owner(
    workspace_root: Path,
    owner: dict[str, Any],
    *,
    stale_after_seconds: int,
) -> dict[str, Any] | None:
    run_id = str(owner.get("run_id") or "")
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise RePublishRecoveryRequired(f"publish lock run ID is malformed: {run_id!r}")
    if _owner_run_is_active(workspace_root, owner):
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

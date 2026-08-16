"""Durable, untrusted provider candidates and exclusive dispatch leases."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from typing import Callable, Iterator, Literal, Mapping, TypeVar

from .canonical import canonical_json_bytes, content_digest
from .model import ExecutionObservation, ReV2ModelError, WorkItem
from .run_store import ReV2Paths


_SCHEMA_VERSION = 1
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_METADATA_NAME = "metadata.json"
_OBSERVATION_NAME = "observation.json"
_PAYLOAD_NAME = "payload"
_COMMITTED_DIR = ".committed"
_T = TypeVar("_T")
_HAS_DIRFD_OPEN = os.open in os.supports_dir_fd


class ReV2CandidateError(RuntimeError):
    """Raised when a lease or candidate is unsafe, conflicting, or corrupt."""


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """A PID bound to the stable identity of that specific process lifetime."""

    pid: int
    process_start_identity: str
    command_hash: str
    provider_identity: str
    started_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.pid, int) or isinstance(self.pid, bool) or self.pid <= 0:
            raise ReV2CandidateError("pid must be a positive integer")
        _safe_id(self.process_start_identity, "process_start_identity")
        _digest(self.command_hash, "command_hash")
        _digest(self.provider_identity, "provider_identity")
        _utc_timestamp(self.started_at, "started_at")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "command_hash": self.command_hash,
            "pid": self.pid,
            "process_start_identity": self.process_start_identity,
            "provider_identity": self.provider_identity,
            "started_at": self.started_at,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ProcessIdentity":
        raw = _exact_object(
            value,
            {
                "command_hash",
                "pid",
                "process_start_identity",
                "provider_identity",
                "started_at",
            },
            "process identity",
        )
        return cls(
            pid=raw["pid"],  # type: ignore[arg-type]
            process_start_identity=raw["process_start_identity"],  # type: ignore[arg-type]
            command_hash=raw["command_hash"],  # type: ignore[arg-type]
            provider_identity=raw["provider_identity"],  # type: ignore[arg-type]
            started_at=raw["started_at"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class DispatchLease:
    dispatch_id: str
    work_item_id: str
    work_item: WorkItem
    process_identity: ProcessIdentity
    leased_at: str

    def __post_init__(self) -> None:
        _safe_id(self.dispatch_id, "dispatch_id")
        _digest(self.work_item_id, "work_item_id")
        if not isinstance(self.work_item, WorkItem):
            raise ReV2CandidateError("work_item must be a WorkItem")
        if self.work_item.work_item_id != self.work_item_id:
            raise ReV2CandidateError("lease work_item_id does not match work_item")
        if not isinstance(self.process_identity, ProcessIdentity):
            raise ReV2CandidateError("process_identity must be a ProcessIdentity")
        _utc_timestamp(self.leased_at, "leased_at")
        if _parse_utc(self.leased_at, "leased_at") < _parse_utc(
            self.process_identity.started_at, "process_identity.started_at"
        ):
            raise ReV2CandidateError("leased_at precedes process start")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "dispatch_id": self.dispatch_id,
            "leased_at": self.leased_at,
            "process_identity": self.process_identity.to_json_dict(),
            "work_item": self.work_item.to_json_dict(),
            "work_item_id": self.work_item_id,
        }

    @property
    def lease_id(self) -> str:
        return content_digest(self.to_json_dict())

    @classmethod
    def from_json_dict(cls, value: object) -> "DispatchLease":
        raw = _exact_object(
            value,
            {"dispatch_id", "leased_at", "process_identity", "work_item", "work_item_id"},
            "dispatch lease",
        )
        try:
            work_item = WorkItem.from_json_dict(raw["work_item"])
        except ReV2ModelError as exc:
            raise ReV2CandidateError(f"invalid lease work item: {exc}") from exc
        return cls(
            dispatch_id=raw["dispatch_id"],  # type: ignore[arg-type]
            work_item_id=raw["work_item_id"],  # type: ignore[arg-type]
            work_item=work_item,
            process_identity=ProcessIdentity.from_json_dict(raw["process_identity"]),
            leased_at=raw["leased_at"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class CandidateInventoryEntry:
    path: str
    kind: Literal["directory", "file"]
    mode: int
    size: int
    digest: str | None

    def __post_init__(self) -> None:
        _relative_path(self.path)
        if self.kind not in {"directory", "file"}:
            raise ReV2CandidateError("candidate inventory kind is invalid")
        if not isinstance(self.mode, int) or isinstance(self.mode, bool) or not 0 <= self.mode <= 0o7777:
            raise ReV2CandidateError("candidate inventory mode is invalid")
        if not isinstance(self.size, int) or isinstance(self.size, bool) or self.size < 0:
            raise ReV2CandidateError("candidate inventory size is invalid")
        if self.kind == "file":
            if self.digest is None:
                raise ReV2CandidateError("candidate file inventory requires a digest")
            _digest(self.digest, "candidate inventory digest")
        elif self.digest is not None or self.size != 0:
            raise ReV2CandidateError("candidate directory inventory has file metadata")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "kind": self.kind,
            "mode": self.mode,
            "path": self.path,
            "size": self.size,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CandidateInventoryEntry":
        raw = _exact_object(value, {"digest", "kind", "mode", "path", "size"}, "inventory entry")
        return cls(
            path=raw["path"],  # type: ignore[arg-type]
            kind=raw["kind"],  # type: ignore[arg-type]
            mode=raw["mode"],  # type: ignore[arg-type]
            size=raw["size"],  # type: ignore[arg-type]
            digest=raw["digest"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class PersistedCandidate:
    candidate_id: str
    dispatch_id: str
    work_item_id: str
    work_item: WorkItem
    lease: DispatchLease
    observation: ExecutionObservation
    inventory: tuple[CandidateInventoryEntry, ...]
    persisted_at: str
    metadata_hash: str
    path: Path
    payload_path: Path

    def __post_init__(self) -> None:
        _safe_id(self.candidate_id, "candidate_id")
        _safe_id(self.dispatch_id, "dispatch_id")
        _digest(self.work_item_id, "work_item_id")
        _utc_timestamp(self.persisted_at, "persisted_at")
        _digest(self.metadata_hash, "metadata_hash")


@dataclass(frozen=True, slots=True)
class _ScannedEntry:
    entry: CandidateInventoryEntry
    identity: tuple[int, int, int, int, int, int]


class CandidateStore:
    """Persist dispatch output before any controller acceptance decision."""

    def __init__(
        self,
        paths: ReV2Paths,
        *,
        fault_hook: Callable[[str], None] | None = None,
        process_probe: Callable[[int], str | None] | None = None,
        clock: Callable[[], str] | None = None,
        rename_noreplace: Callable[[Path, Path], None] | None = None,
    ) -> None:
        if not isinstance(paths, ReV2Paths):
            raise ReV2CandidateError("candidate store requires ReV2Paths")
        self.paths = paths
        self._fault_hook = fault_hook
        self._process_probe = process_probe or _default_process_probe
        self._clock = clock or _canonical_utc_now
        self._rename_noreplace = rename_noreplace or _rename_noreplace
        self._validate_store_root(create=True)

    def begin(
        self,
        work_item: WorkItem,
        process_identity: ProcessIdentity,
        *,
        dispatch_id: str | None = None,
        leased_at: str | None = None,
    ) -> DispatchLease:
        """Write an exclusive immutable lease, or return its exact prior bytes."""
        if not isinstance(work_item, WorkItem):
            raise ReV2CandidateError("work_item must be a WorkItem")
        if not isinstance(process_identity, ProcessIdentity):
            raise ReV2CandidateError("process_identity must be a ProcessIdentity")
        observed_start = self._process_probe(process_identity.pid)
        if observed_start is None:
            raise ReV2CandidateError(f"process PID {process_identity.pid} is not live")
        if observed_start != process_identity.process_start_identity:
            raise ReV2CandidateError(
                f"process PID {process_identity.pid} start identity mismatch"
            )
        if dispatch_id is None:
            suffix = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "process_identity": process_identity.to_json_dict(),
                        "work_item_id": work_item.work_item_id,
                    }
                )
            ).hexdigest()
            dispatch_id = f"dispatch-{suffix}"
        _safe_id(dispatch_id, "dispatch_id")
        if dispatch_id.startswith("."):
            raise ReV2CandidateError("dispatch_id cannot name a private work area")
        timestamp = leased_at if leased_at is not None else process_identity.started_at
        lease = DispatchLease(
            dispatch_id=dispatch_id,
            work_item_id=work_item.work_item_id,
            work_item=work_item,
            process_identity=process_identity,
            leased_at=timestamp,
        )
        payload = canonical_json_bytes(
            {"lease": lease.to_json_dict(), "schema_version": _SCHEMA_VERSION}
        )
        with self._locked():
            leases = self._lease_root(create=True)
            target = leases / f"{dispatch_id}.json"
            if os.path.lexists(target):
                existing = self._read_canonical_json(target, "lease")
                if canonical_json_bytes(existing) != payload:
                    raise ReV2CandidateError(f"conflicting lease for dispatch {dispatch_id}")
                return self._lease_from_envelope(existing)
            temporary = leases / f".{dispatch_id}.{os.getpid()}.tmp"
            if os.path.lexists(temporary):
                raise ReV2CandidateError(f"unsafe existing lease temporary: {temporary.name}")
            try:
                _write_new_file(temporary, payload, mode=0o600)
                try:
                    os.link(temporary, target, follow_symlinks=False)
                except FileExistsError as exc:
                    raise ReV2CandidateError(
                        f"conflicting lease for dispatch {dispatch_id}"
                    ) from exc
                temporary.unlink()
                _fsync_directory(leases)
            finally:
                if os.path.lexists(temporary):
                    temporary.unlink()
            self._fault("lease_written")
        return lease

    def persist(
        self,
        lease: DispatchLease,
        output_root: Path,
        observation: ExecutionObservation,
    ) -> PersistedCandidate:
        """Copy and atomically publish one immutable, untrusted candidate."""
        if not isinstance(lease, DispatchLease):
            raise ReV2CandidateError("persist requires a DispatchLease")
        if not isinstance(observation, ExecutionObservation):
            raise ReV2CandidateError("persist requires an ExecutionObservation")
        persisted_at = _utc_timestamp(self._clock(), "persistence clock")
        _validate_candidate_timeline(lease, observation, persisted_at)
        source = _safe_source_root(Path(output_root), self.paths.candidates)
        with self._locked():
            self._require_active_lease(lease)
            final = self.paths.candidates / lease.dispatch_id
            if os.path.lexists(final):
                if final.is_symlink():
                    raise ReV2CandidateError(f"published candidate target is a symlink: {final}")
                committed = self._marker_exists(lease.dispatch_id)
                existing = self._load_candidate(final, allow_mutable_root=not committed)
                source_scan = _scan_tree(source, mutable=True)
                if not self._matches_retry(existing, lease, observation, source_scan):
                    raise ReV2CandidateError(
                        f"candidate target already exists with conflicting bytes: {lease.dispatch_id}"
                    )
                if committed:
                    self._validate_marker(existing)
                else:
                    self._freeze_published_root(final)
                    _fsync_directory(self.paths.candidates)
                    existing = self._load_candidate(final)
                    self._publish_marker(existing)
                return existing

            if self._marker_exists(lease.dispatch_id):
                raise ReV2CandidateError(
                    f"commit marker exists without candidate: {lease.dispatch_id}"
                )

            source_before = _scan_tree(source, mutable=True)
            temporary = self.paths.candidates / f".{lease.dispatch_id}.tmp"
            if os.path.lexists(temporary):
                if temporary.is_symlink() or not temporary.is_dir():
                    raise ReV2CandidateError(f"unsafe candidate temporary: {temporary}")
                _remove_owned_tree(temporary)
            temporary.mkdir(mode=0o700)
            payload_root = temporary / _PAYLOAD_NAME
            published = False
            try:
                _copy_scanned_tree(source, payload_root, source_before)
                self._fault("payload_copied")
                if _scan_tree(source, mutable=True) != source_before:
                    raise ReV2CandidateError("candidate source changed while copying")
                copied = _scan_tree(payload_root, mutable=True)
                if tuple(item.entry for item in copied) != tuple(
                    item.entry for item in source_before
                ):
                    raise ReV2CandidateError("candidate payload changed while copying")

                _make_tree_immutable(payload_root)
                inventory = tuple(
                    _frozen_entry(item.entry) for item in source_before
                )
                identity = _candidate_identity(
                    lease, observation, inventory, persisted_at
                )
                candidate_id = content_digest(identity)
                metadata = {
                    **identity,
                    "candidate_id": candidate_id,
                    "schema_version": _SCHEMA_VERSION,
                }
                _write_new_file(
                    temporary / _METADATA_NAME,
                    canonical_json_bytes(metadata),
                    mode=0o400,
                )
                _write_new_file(
                    temporary / _OBSERVATION_NAME,
                    canonical_json_bytes(observation.to_json_dict()),
                    mode=0o400,
                )
                _make_tree_immutable(temporary)
                _fsync_tree(temporary)
                self._fault("metadata_fsynced")

                try:
                    self._rename_noreplace(temporary, final)
                except FileExistsError as exc:
                    raise ReV2CandidateError(
                        f"candidate target already exists: {lease.dispatch_id}"
                    ) from exc
                except OSError as exc:
                    raise ReV2CandidateError(
                        f"cannot atomically publish candidate without replacement: {exc}"
                    ) from exc
                published = True
                self._freeze_published_root(final)
                _fsync_directory(self.paths.candidates)
                candidate = self._load_candidate(final)
                self._publish_marker(candidate)
                self._fault("candidate_renamed")
                return candidate
            finally:
                if not published and os.path.lexists(temporary):
                    if temporary.is_symlink() or not temporary.is_dir():
                        raise ReV2CandidateError(
                            f"unsafe candidate temporary during cleanup: {temporary}"
                        )
                    _remove_owned_tree(temporary)

    def discover(self) -> tuple[PersistedCandidate, ...]:
        """Validate and return every published candidate in deterministic order."""
        with self._locked():
            candidates: list[PersistedCandidate] = []
            marker_root = self._marker_root(create=False)
            if not os.path.lexists(marker_root):
                return ()
            root_fd = _open_directory_path_nofollow(self.paths.candidates)
            marker_fd = _open_directory_path_nofollow(marker_root)
            try:
                marker_names = sorted(_retry_eintr(os.listdir, marker_fd))
                for marker_name in marker_names:
                    if marker_name.startswith("."):
                        continue
                    if not marker_name.endswith(".json"):
                        raise ReV2CandidateError(
                            f"invalid candidate commit marker name: {marker_name}"
                        )
                    name = marker_name[:-5]
                    if name.startswith("."):
                        raise ReV2CandidateError("invalid private candidate commit marker")
                    _safe_id(name, "published candidate directory")
                    marker, marker_mode = self._read_marker_at(marker_fd, marker_name)
                    if marker["dispatch_id"] != name:
                        raise ReV2CandidateError("candidate commit marker dispatch mismatch")
                    if stat.S_IMODE(marker_mode) & 0o222:
                        raise ReV2CandidateError("candidate commit marker is mutable")
                    try:
                        child_fd = _openat(
                            root_fd,
                            name,
                            os.O_RDONLY | os.O_DIRECTORY | _nofollow_flag(),
                        )
                    except OSError as exc:
                        raise ReV2CandidateError(
                            f"candidate commit marker without matching directory: {name}"
                        ) from exc
                    try:
                        candidate = self._load_candidate_fd(
                            self.paths.candidates / name, child_fd
                        )
                        self._validate_marker_value(marker, candidate)
                        candidates.append(candidate)
                    finally:
                        os.close(child_fd)
            finally:
                os.close(marker_fd)
                os.close(root_fd)
            return tuple(candidates)

    def _validate_store_root(self, *, create: bool) -> None:
        root = self.paths.root
        if not root.is_absolute() or root.resolve(strict=False) != root:
            raise ReV2CandidateError(f"RE v2 root has a symlinked parent: {root}")
        if root.is_symlink() or not root.is_dir():
            raise ReV2CandidateError(f"RE v2 root is not a safe directory: {root}")
        expected = root / "candidates"
        if self.paths.candidates != expected:
            raise ReV2CandidateError("ReV2Paths candidates path must be root/candidates")
        candidates = self.paths.candidates
        if os.path.lexists(candidates):
            if candidates.is_symlink():
                raise ReV2CandidateError(f"candidate root is a symlink: {candidates}")
            if not candidates.is_dir():
                raise ReV2CandidateError(f"candidate root is not a directory: {candidates}")
        elif create:
            candidates.mkdir(mode=0o700)
            _fsync_directory(root)

    def _lease_root(self, *, create: bool) -> Path:
        leases = self.paths.candidates / ".leases"
        if os.path.lexists(leases):
            if leases.is_symlink():
                raise ReV2CandidateError(f"lease root is a symlink: {leases}")
            if not leases.is_dir():
                raise ReV2CandidateError(f"lease root is not a directory: {leases}")
        elif create:
            leases.mkdir(mode=0o700)
            _fsync_directory(self.paths.candidates)
        return leases

    def _marker_root(self, *, create: bool) -> Path:
        markers = self.paths.candidates / _COMMITTED_DIR
        if os.path.lexists(markers):
            if markers.is_symlink():
                raise ReV2CandidateError(f"commit marker root is a symlink: {markers}")
            if not markers.is_dir():
                raise ReV2CandidateError(f"commit marker root is not a directory: {markers}")
        elif create:
            markers.mkdir(mode=0o700)
            _fsync_directory(self.paths.candidates)
        return markers

    def _marker_exists(self, dispatch_id: str) -> bool:
        markers = self._marker_root(create=False)
        if not os.path.lexists(markers):
            return False
        marker = markers / f"{dispatch_id}.json"
        if marker.is_symlink():
            raise ReV2CandidateError(f"candidate commit marker is a symlink: {marker}")
        return os.path.lexists(marker)

    def _publish_marker(self, candidate: PersistedCandidate) -> None:
        markers = self._marker_root(create=True)
        marker = {
            "candidate_id": candidate.candidate_id,
            "dispatch_id": candidate.dispatch_id,
            "metadata_hash": candidate.metadata_hash,
            "schema_version": _SCHEMA_VERSION,
        }
        payload = canonical_json_bytes(marker)
        target = markers / f"{candidate.dispatch_id}.json"
        if os.path.lexists(target):
            existing = self._read_canonical_json(target, "candidate commit marker")
            if canonical_json_bytes(existing) != payload:
                raise ReV2CandidateError(
                    f"conflicting candidate commit marker: {candidate.dispatch_id}"
                )
            self._validate_marker_value(
                _exact_object(
                    existing,
                    {"candidate_id", "dispatch_id", "metadata_hash", "schema_version"},
                    "candidate commit marker",
                ),
                candidate,
            )
            return
        temporary = markers / f".{candidate.dispatch_id}.{os.getpid()}.tmp"
        if os.path.lexists(temporary):
            raise ReV2CandidateError(f"unsafe existing commit marker temporary: {temporary}")
        try:
            _write_new_file(temporary, payload, mode=0o400)
            try:
                os.link(temporary, target, follow_symlinks=False)
            except FileExistsError as exc:
                raise ReV2CandidateError(
                    f"conflicting candidate commit marker: {candidate.dispatch_id}"
                ) from exc
            temporary.unlink()
            _fsync_directory(markers)
            _fsync_directory(self.paths.candidates)
        finally:
            if os.path.lexists(temporary):
                temporary.unlink()

    def _read_marker_at(self, marker_fd: int, name: str) -> tuple[Mapping[str, object], int]:
        value, mode = _read_canonical_json_at(marker_fd, name, "candidate commit marker")
        marker = _exact_object(
            value,
            {"candidate_id", "dispatch_id", "metadata_hash", "schema_version"},
            "candidate commit marker",
        )
        if marker["schema_version"] != _SCHEMA_VERSION:
            raise ReV2CandidateError("unsupported candidate commit marker schema")
        _safe_id(marker["dispatch_id"], "commit marker dispatch_id")
        _digest(marker["candidate_id"], "commit marker candidate_id")
        _digest(marker["metadata_hash"], "commit marker metadata_hash")
        return marker, mode

    def _validate_marker(self, candidate: PersistedCandidate) -> None:
        markers = self._marker_root(create=False)
        marker_fd = _open_directory_path_nofollow(markers)
        try:
            marker, _mode = self._read_marker_at(
                marker_fd, f"{candidate.dispatch_id}.json"
            )
        finally:
            os.close(marker_fd)
        self._validate_marker_value(marker, candidate)

    @staticmethod
    def _validate_marker_value(
        marker: Mapping[str, object], candidate: PersistedCandidate
    ) -> None:
        expected = {
            "candidate_id": candidate.candidate_id,
            "dispatch_id": candidate.dispatch_id,
            "metadata_hash": candidate.metadata_hash,
            "schema_version": _SCHEMA_VERSION,
        }
        if dict(marker) != expected:
            raise ReV2CandidateError("candidate commit marker mismatch")

    @staticmethod
    def _freeze_published_root(path: Path) -> None:
        fd = _open_directory_path_nofollow(path)
        try:
            os.fchmod(fd, 0o500)
            _retry_eintr(os.fsync, fd)
        finally:
            os.close(fd)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._validate_store_root(create=False)
        lock_path = self.paths.candidates / ".store.lock"
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = _retry_eintr(os.open, lock_path, flags, 0o600)
        except OSError as exc:
            raise ReV2CandidateError(f"cannot safely open candidate-store lock: {exc}") from exc
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ReV2CandidateError("candidate-store lock is not a regular file")
            _retry_eintr(fcntl.flock, fd, fcntl.LOCK_EX)
            self._validate_store_root(create=False)
            yield
        finally:
            _retry_eintr(fcntl.flock, fd, fcntl.LOCK_UN)
            os.close(fd)

    def _require_active_lease(self, lease: DispatchLease) -> None:
        path = self._lease_root(create=False) / f"{lease.dispatch_id}.json"
        if not os.path.lexists(path):
            raise ReV2CandidateError(f"no active lease for dispatch {lease.dispatch_id}")
        envelope = self._read_canonical_json(path, "active lease")
        active = self._lease_from_envelope(envelope)
        if active != lease or canonical_json_bytes(active.to_json_dict()) != canonical_json_bytes(
            lease.to_json_dict()
        ):
            raise ReV2CandidateError(
                f"persist requires the exact active lease/work item for {lease.dispatch_id}"
            )

    def _read_canonical_json(self, path: Path, label: str) -> object:
        if path.is_symlink():
            raise ReV2CandidateError(f"{label} is a symlink: {path}")
        try:
            parent_fd = _open_directory_path_nofollow(path.parent)
            try:
                value, mode = _read_canonical_json_at(parent_fd, path.name, label)
            finally:
                os.close(parent_fd)
            if not stat.S_ISREG(mode):
                raise ReV2CandidateError(f"{label} is not a regular file: {path}")
        except (OSError, ValueError) as exc:
            raise ReV2CandidateError(f"invalid {label}: {exc}") from exc
        return value

    def _lease_from_envelope(self, value: object) -> DispatchLease:
        raw = _exact_object(value, {"lease", "schema_version"}, "lease envelope")
        if raw["schema_version"] != _SCHEMA_VERSION:
            raise ReV2CandidateError("unsupported lease schema version")
        return DispatchLease.from_json_dict(raw["lease"])

    def _load_candidate(
        self, path: Path, *, allow_mutable_root: bool = False
    ) -> PersistedCandidate:
        candidate_fd = _open_directory_path_nofollow(path)
        try:
            return self._load_candidate_fd(
                path, candidate_fd, allow_mutable_root=allow_mutable_root
            )
        finally:
            os.close(candidate_fd)

    def _load_candidate_fd(
        self, path: Path, candidate_fd: int, *, allow_mutable_root: bool = False
    ) -> PersistedCandidate:
        expected_children = {_METADATA_NAME, _OBSERVATION_NAME, _PAYLOAD_NAME}
        actual_children = set(_retry_eintr(os.listdir, candidate_fd))
        if actual_children != expected_children:
            missing = sorted(expected_children - actual_children)
            extra = sorted(actual_children - expected_children)
            detail = f"missing {missing[0]}" if missing else f"extra {extra[0]}"
            raise ReV2CandidateError(f"malformed published candidate {path.name}: {detail}")
        metadata_value, metadata_mode = _read_canonical_json_at(
            candidate_fd, _METADATA_NAME, "candidate metadata"
        )
        metadata = _exact_object(
            metadata_value,
            {
                "candidate_id",
                "dispatch_id",
                "inventory",
                "lease",
                "observation_hash",
                "persisted_at",
                "schema_version",
                "work_item",
                "work_item_id",
            },
            "candidate metadata",
        )
        metadata_hash = content_digest(canonical_json_bytes(dict(metadata)))
        if metadata["schema_version"] != _SCHEMA_VERSION:
            raise ReV2CandidateError("unsupported candidate schema version")
        dispatch_id = _safe_id(metadata["dispatch_id"], "dispatch_id")
        if dispatch_id != path.name:
            raise ReV2CandidateError("candidate dispatch_id does not match directory")
        candidate_id = _safe_id(metadata["candidate_id"], "candidate_id")
        work_item_id = _digest(metadata["work_item_id"], "work_item_id")
        persisted_at = _utc_timestamp(metadata["persisted_at"], "persisted_at")
        try:
            work_item = WorkItem.from_json_dict(metadata["work_item"])
            observation_value, observation_mode = _read_canonical_json_at(
                candidate_fd, _OBSERVATION_NAME, "candidate observation"
            )
            observation = ExecutionObservation.from_json_dict(
                observation_value
            )
        except ReV2ModelError as exc:
            raise ReV2CandidateError(f"invalid candidate model: {exc}") from exc
        lease = DispatchLease.from_json_dict(metadata["lease"])
        _validate_candidate_timeline(lease, observation, persisted_at)
        if (
            work_item.work_item_id != work_item_id
            or lease.work_item != work_item
            or lease.work_item_id != work_item_id
            or lease.dispatch_id != dispatch_id
        ):
            raise ReV2CandidateError("candidate ownership does not match exact lease/work item")
        raw_inventory = metadata["inventory"]
        if not isinstance(raw_inventory, list):
            raise ReV2CandidateError("candidate inventory must be an array")
        inventory = tuple(CandidateInventoryEntry.from_json_dict(item) for item in raw_inventory)
        if tuple(entry.path for entry in inventory) != tuple(
            sorted(entry.path for entry in inventory)
        ) or len({entry.path for entry in inventory}) != len(inventory):
            raise ReV2CandidateError("candidate inventory paths must be sorted and unique")
        payload_path = path / _PAYLOAD_NAME
        try:
            payload_fd = _openat(
                candidate_fd,
                _PAYLOAD_NAME,
                os.O_RDONLY | os.O_DIRECTORY | _nofollow_flag(),
            )
        except OSError as exc:
            raise ReV2CandidateError("candidate payload is missing or symlinked") from exc
        try:
            found = tuple(item.entry for item in _scan_tree_fd(payload_fd, mutable=True))
            payload_mode = os.fstat(payload_fd).st_mode
        finally:
            os.close(payload_fd)
        _compare_inventory(inventory, found)
        identity = _candidate_identity(lease, observation, inventory, persisted_at)
        expected_metadata = {
            **identity,
            "candidate_id": candidate_id,
            "schema_version": _SCHEMA_VERSION,
        }
        if dict(metadata) != expected_metadata:
            raise ReV2CandidateError("candidate metadata does not match persisted bytes")
        if content_digest(identity) != candidate_id:
            raise ReV2CandidateError("candidate identity hash mismatch")
        if _parse_utc(persisted_at, "persisted_at") < _parse_utc(
            observation.ended_at, "observation.ended_at"
        ):
            raise ReV2CandidateError("candidate persisted_at precedes observation end")
        protected_modes = {
            path.name: os.fstat(candidate_fd).st_mode,
            _PAYLOAD_NAME: payload_mode,
            _METADATA_NAME: metadata_mode,
            _OBSERVATION_NAME: observation_mode,
        }
        for name, mode in protected_modes.items():
            if allow_mutable_root and name == path.name:
                continue
            if stat.S_IMODE(mode) & 0o222:
                raise ReV2CandidateError(f"published candidate is mutable: {name}")
        return PersistedCandidate(
            candidate_id=candidate_id,
            dispatch_id=dispatch_id,
            work_item_id=work_item_id,
            work_item=work_item,
            lease=lease,
            observation=observation,
            inventory=inventory,
            persisted_at=persisted_at,
            metadata_hash=metadata_hash,
            path=path,
            payload_path=payload_path,
        )

    def _matches_retry(
        self,
        existing: PersistedCandidate,
        lease: DispatchLease,
        observation: ExecutionObservation,
        source: tuple[_ScannedEntry, ...],
    ) -> bool:
        return (
            existing.lease == lease
            and existing.observation == observation
            and existing.inventory == tuple(_frozen_entry(item.entry) for item in source)
        )

    def _fault(self, boundary: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(boundary)


def _candidate_identity(
    lease: DispatchLease,
    observation: ExecutionObservation,
    inventory: tuple[CandidateInventoryEntry, ...],
    persisted_at: str,
) -> dict[str, object]:
    return {
        "dispatch_id": lease.dispatch_id,
        "inventory": [entry.to_json_dict() for entry in inventory],
        "lease": lease.to_json_dict(),
        "observation_hash": content_digest(observation.to_json_dict()),
        "persisted_at": persisted_at,
        "work_item": lease.work_item.to_json_dict(),
        "work_item_id": lease.work_item_id,
    }


def _safe_source_root(source: Path, candidate_root: Path) -> Path:
    if source.is_symlink():
        raise ReV2CandidateError(f"candidate output root is a symlink: {source}")
    if not source.is_dir():
        raise ReV2CandidateError(f"candidate output root is not a directory: {source}")
    resolved = source.resolve()
    if resolved != source.absolute():
        raise ReV2CandidateError(f"candidate output has a symlinked parent or traversal: {source}")
    if resolved == candidate_root or candidate_root in resolved.parents:
        raise ReV2CandidateError("candidate output cannot be inside the candidate store")
    return resolved


def _scan_tree(root: Path, *, mutable: bool) -> tuple[_ScannedEntry, ...]:
    root_fd = _open_directory_path_nofollow(root)
    try:
        return _scan_tree_fd(root_fd, mutable=mutable)
    finally:
        os.close(root_fd)


def _scan_tree_fd(root_fd: int, *, mutable: bool) -> tuple[_ScannedEntry, ...]:
    scanned: list[_ScannedEntry] = []

    def visit(directory_fd: int, prefix: str = "") -> None:
        directory_before = os.fstat(directory_fd)
        try:
            children = sorted(_retry_eintr(os.listdir, directory_fd))
        except OSError as exc:
            raise ReV2CandidateError(f"cannot inventory candidate payload: {exc}") from exc
        for name in children:
            relative = f"{prefix}/{name}" if prefix else name
            _relative_path(relative)
            try:
                child_fd = _openat(
                    directory_fd,
                    name,
                    os.O_RDONLY | os.O_NONBLOCK | _nofollow_flag(),
                )
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.EMLINK}:
                    raise ReV2CandidateError(f"candidate payload rejects symlink: {relative}") from exc
                raise ReV2CandidateError(f"candidate source changed while opening: {relative}") from exc
            try:
                before = os.fstat(child_fd)
                identity = _stat_identity(before)
                mode = stat.S_IMODE(before.st_mode)
                if stat.S_ISDIR(before.st_mode):
                    scanned.append(
                        _ScannedEntry(
                            CandidateInventoryEntry(relative, "directory", mode, 0, None),
                            identity,
                        )
                    )
                    visit(child_fd, relative)
                elif stat.S_ISREG(before.st_mode):
                    payload = _read_all_fd(child_fd)
                    after = os.fstat(child_fd)
                    if _stat_identity(after) != identity or len(payload) != before.st_size:
                        raise ReV2CandidateError(f"candidate source changed while reading: {relative}")
                    scanned.append(
                        _ScannedEntry(
                            CandidateInventoryEntry(
                                relative, "file", mode, len(payload), content_digest(payload)
                            ),
                            identity,
                        )
                    )
                else:
                    raise ReV2CandidateError(f"candidate payload rejects special file: {relative}")
                after = os.fstat(child_fd)
                if mutable and _stat_identity(after) != identity:
                    raise ReV2CandidateError(f"candidate source changed while scanning: {relative}")
            finally:
                os.close(child_fd)
        if mutable:
            confirmed_children = sorted(_retry_eintr(os.listdir, directory_fd))
            if confirmed_children != children:
                raise ReV2CandidateError("candidate directory entries changed while scanning")
            if _stat_identity(os.fstat(directory_fd)) != _stat_identity(directory_before):
                raise ReV2CandidateError("candidate source changed while scanning directory")

    visit(root_fd)
    return tuple(scanned)


def _nofollow_flag() -> int:
    if not hasattr(os, "O_NOFOLLOW") or not _HAS_DIRFD_OPEN:
        raise ReV2CandidateError("descriptor-relative no-follow operations are unsupported")
    return os.O_NOFOLLOW


def _openat(parent_fd: int, name: str, flags: int, mode: int = 0o777) -> int:
    return _retry_eintr(os.open, name, flags, mode, dir_fd=parent_fd)


def _open_directory_path_nofollow(path: Path) -> int:
    absolute = path.absolute()
    if not absolute.is_absolute() or any(part in {".", ".."} for part in absolute.parts):
        raise ReV2CandidateError(f"unsafe directory traversal path: {path}")
    current = _retry_eintr(os.open, "/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            next_fd = _openat(
                current,
                part,
                os.O_RDONLY | os.O_DIRECTORY | _nofollow_flag(),
            )
            os.close(current)
            current = next_fd
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            raise ReV2CandidateError(f"path is not a directory: {path}")
        return current
    except Exception:
        os.close(current)
        raise


def _read_all_fd(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = _retry_eintr(os.read, fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _read_regular_at(
    parent_fd: int, name: str, label: str
) -> tuple[bytes, tuple[int, int, int, int, int, int], int]:
    try:
        fd = _openat(parent_fd, name, os.O_RDONLY | os.O_NONBLOCK | _nofollow_flag())
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK}:
            raise ReV2CandidateError(f"{label} is a symlink") from exc
        raise ReV2CandidateError(f"cannot safely read {label}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ReV2CandidateError(f"{label} is not a regular file")
        payload = _read_all_fd(fd)
        after = os.fstat(fd)
        if _stat_identity(before) != _stat_identity(after):
            raise ReV2CandidateError(f"{label} changed while reading")
        if len(payload) != before.st_size:
            raise ReV2CandidateError(f"{label} changed while reading")
        return payload, _stat_identity(after), before.st_mode
    finally:
        os.close(fd)


def _read_canonical_json_at(parent_fd: int, name: str, label: str) -> tuple[object, int]:
    payload, _identity, mode = _read_regular_at(parent_fd, name, label)
    try:
        value = json.loads(payload)
    except ValueError as exc:
        raise ReV2CandidateError(f"invalid {label}: {exc}") from exc
    if payload != canonical_json_bytes(value):
        raise ReV2CandidateError(f"invalid non-canonical {label}")
    return value, mode


def _read_relative_regular(
    root_fd: int, relative: str
) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    parts = relative.split("/")
    current = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = _openat(
                current,
                part,
                os.O_RDONLY | os.O_DIRECTORY | _nofollow_flag(),
            )
            os.close(current)
            current = next_fd
        payload, identity, _mode = _read_regular_at(current, parts[-1], relative)
        return payload, identity
    finally:
        os.close(current)


def _copy_scanned_tree(
    source: Path, target: Path, scanned: tuple[_ScannedEntry, ...]
) -> None:
    target.mkdir(mode=0o700)
    directories = [item for item in scanned if item.entry.kind == "directory"]
    for item in directories:
        destination = target.joinpath(*item.entry.path.split("/"))
        destination.mkdir(mode=0o700)
    source_fd = _open_directory_path_nofollow(source)
    try:
        for item in scanned:
            entry = item.entry
            destination = target.joinpath(*entry.path.split("/"))
            if entry.kind == "directory":
                continue
            payload, identity = _read_relative_regular(source_fd, entry.path)
            if identity != item.identity or len(payload) != entry.size or content_digest(payload) != entry.digest:
                raise ReV2CandidateError(f"candidate source changed while copying: {entry.path}")
            _write_new_file(destination, payload, mode=entry.mode)
    finally:
        os.close(source_fd)
    for item in sorted(directories, key=lambda value: len(value.entry.path.split("/")), reverse=True):
        target.joinpath(*item.entry.path.split("/")).chmod(item.entry.mode)


def _frozen_entry(entry: CandidateInventoryEntry) -> CandidateInventoryEntry:
    return CandidateInventoryEntry(
        path=entry.path,
        kind=entry.kind,
        mode=entry.mode & ~0o222,
        size=entry.size,
        digest=entry.digest,
    )


def _make_tree_immutable(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            raise ReV2CandidateError(f"candidate payload rejects symlink: {path}")
        path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o222)
    root.chmod(stat.S_IMODE(root.stat().st_mode) & ~0o222)


def _compare_inventory(
    expected: tuple[CandidateInventoryEntry, ...],
    found: tuple[CandidateInventoryEntry, ...],
) -> None:
    by_path = {entry.path: entry for entry in expected}
    actual = {entry.path: entry for entry in found}
    missing = sorted(by_path.keys() - actual.keys())
    extra = sorted(actual.keys() - by_path.keys())
    if missing:
        raise ReV2CandidateError(f"candidate payload missing entry: {missing[0]}")
    if extra:
        raise ReV2CandidateError(f"candidate payload has extra entry: {extra[0]}")
    for relative, wanted in by_path.items():
        observed = actual[relative]
        if observed.kind != wanted.kind:
            raise ReV2CandidateError(f"candidate payload kind mismatch: {relative}")
        if observed.mode != wanted.mode:
            raise ReV2CandidateError(f"candidate payload mode mismatch: {relative}")
        if observed.size != wanted.size:
            raise ReV2CandidateError(f"candidate payload size mismatch: {relative}")
        if observed.digest != wanted.digest:
            raise ReV2CandidateError(f"candidate payload hash mismatch: {relative}")


def _remove_owned_tree(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ReV2CandidateError(f"refusing to remove unsafe candidate temporary: {root}")
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_symlink():
            path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
    root.chmod(stat.S_IMODE(root.stat().st_mode) | stat.S_IWUSR)
    shutil.rmtree(root)


def _write_new_file(path: Path, payload: bytes, *, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = _retry_eintr(os.open, path, flags, mode)
    try:
        offset = 0
        while offset < len(payload):
            written = _retry_eintr(os.write, fd, payload[offset:])
            if written <= 0:
                raise OSError("short write while persisting candidate")
            offset += written
        os.fchmod(fd, mode)
        _retry_eintr(os.fsync, fd)
    finally:
        os.close(fd)


def _fsync_tree(root: Path) -> None:
    root_fd = _open_directory_path_nofollow(root)
    try:
        _fsync_tree_fd(root_fd)
    finally:
        os.close(root_fd)


def _fsync_tree_fd(directory_fd: int) -> None:
    for name in sorted(_retry_eintr(os.listdir, directory_fd)):
        try:
            child_fd = _openat(
                directory_fd,
                name,
                os.O_RDONLY | os.O_NONBLOCK | _nofollow_flag(),
            )
        except OSError as exc:
            raise ReV2CandidateError(f"cannot open staged candidate for durability: {name}") from exc
        try:
            mode = os.fstat(child_fd).st_mode
            if stat.S_ISDIR(mode):
                _fsync_tree_fd(child_fd)
            elif not stat.S_ISREG(mode):
                raise ReV2CandidateError(f"staged candidate contains special file: {name}")
            _retry_eintr(os.fsync, child_fd)
        finally:
            os.close(child_fd)
    _retry_eintr(os.fsync, directory_fd)


def _fsync_directory(path: Path) -> None:
    try:
        fd = _retry_eintr(os.open, path, os.O_RDONLY)
    except OSError as exc:
        raise ReV2CandidateError(f"cannot open directory for durability flush {path}: {exc}") from exc
    try:
        _retry_eintr(os.fsync, fd)
    except OSError as exc:
        raise ReV2CandidateError(f"cannot durably flush directory {path}: {exc}") from exc
    finally:
        os.close(fd)


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        stat.S_IMODE(info.st_mode),
    )


def _validate_candidate_timeline(
    lease: DispatchLease, observation: ExecutionObservation, persisted_at: str
) -> None:
    leased = _parse_utc(lease.leased_at, "lease.leased_at")
    started = _parse_utc(observation.started_at, "observation.started_at")
    ended = _parse_utc(observation.ended_at, "observation.ended_at")
    persisted = _parse_utc(persisted_at, "persisted_at")
    if started < leased:
        raise ReV2CandidateError("lease timestamp follows observation start")
    if ended < started:
        raise ReV2CandidateError("observation ended_at precedes started_at")
    if persisted < ended:
        raise ReV2CandidateError("persistence clock precedes observation end")


def _canonical_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _default_process_probe(pid: int) -> str | None:
    if sys.platform.startswith("linux"):
        try:
            data = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            fields = data[data.rfind(")") + 2 :].split()
            return f"linux:{fields[19]}" if len(fields) > 19 else None
        except (OSError, ValueError, IndexError):
            return None
    if sys.platform == "darwin":
        # argv execution with shell disabled avoids command injection; lstart is
        # stable for one PID lifetime and is normalized to a safe hash token.
        try:
            completed = subprocess.run(
                ["ps", "-o", "lstart=", "-p", str(pid)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            return None
        started = completed.stdout.strip()
        if completed.returncode != 0 or not started:
            return None
        return "macos:" + hashlib.sha256(started.encode("utf-8")).hexdigest()
    raise ReV2CandidateError("stable process probing is unsupported on this platform")


def _rename_noreplace(source: Path, target: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    target_bytes = os.fsencode(target)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        operation = libc.renameat2
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        operation.restype = ctypes.c_int
        result = operation(-100, source_bytes, -100, target_bytes, 1)
    elif sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        operation = libc.renameatx_np
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        operation.restype = ctypes.c_int
        # Darwin refuses to rename a non-writable directory. Keep an fd pinned
        # across the syscall and restore the frozen mode before returning; the
        # publication boundary is not exposed to callers until that restoration
        # and its durability flush complete.
        source_fd = _open_directory_path_nofollow(source)
        frozen_mode = stat.S_IMODE(os.fstat(source_fd).st_mode)
        try:
            os.fchmod(source_fd, frozen_mode | stat.S_IWUSR)
            result = operation(-2, source_bytes, -2, target_bytes, 0x00000004)
            saved_errno = ctypes.get_errno()
            os.fchmod(source_fd, frozen_mode)
            _retry_eintr(os.fsync, source_fd)
            ctypes.set_errno(saved_errno)
        finally:
            os.close(source_fd)
    else:
        raise ReV2CandidateError("atomic no-replace directory rename is unsupported")
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(error, os.strerror(error), target)
        raise OSError(error, os.strerror(error), target)


def _retry_eintr(
    operation: Callable[..., _T], *args: object, **kwargs: object
) -> _T:
    while True:
        try:
            return operation(*args, **kwargs)
        except InterruptedError:
            continue


def _utc_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReV2CandidateError(f"{field} must be an RFC3339 UTC timestamp")
    _parse_utc(value, field)
    return value


def _parse_utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError) as exc:
        raise ReV2CandidateError(f"{field} must be an RFC3339 UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ReV2CandidateError(f"{field} must be an RFC3339 UTC timestamp")
    return parsed


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ReV2CandidateError(f"{field} must be a nonempty safe ID")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReV2CandidateError(f"{field} must be a lowercase sha256 digest")
    return value


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ReV2CandidateError("candidate inventory path must be nonempty")
    parts = value.split("/")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in parts) or "\\" in value:
        raise ReV2CandidateError(f"unsafe candidate inventory traversal path: {value!r}")
    return value


def _exact_object(value: object, fields: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ReV2CandidateError(f"invalid {label}: expected an object")
    missing = fields - set(value)
    extra = set(value) - fields
    if missing:
        raise ReV2CandidateError(f"invalid {label}: missing {sorted(missing)[0]}")
    if extra:
        raise ReV2CandidateError(f"invalid {label}: extra {sorted(extra)[0]}")
    return value


__all__ = (
    "CandidateInventoryEntry",
    "CandidateStore",
    "DispatchLease",
    "PersistedCandidate",
    "ProcessIdentity",
    "ReV2CandidateError",
)

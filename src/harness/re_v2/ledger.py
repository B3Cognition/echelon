"""Immutable artifact objects and controller-owned certification receipts."""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from types import MappingProxyType
from typing import Iterable, Mapping, Protocol

from .canonical import canonical_json_bytes, content_digest
from .model import (
    ArtifactReceipt,
    CertificationReceipt,
    ReV2ModelError,
    WorkItem,
)
from .run_store import ReV2Paths, ReV2RunStoreError, load_run_manifest


LEDGER_SCHEMA_VERSION = 1
TREE_SCHEMA_VERSION = 1
TREE_OBJECT_MAGIC = b"\x00ECHELON_RE_V2_TREE\x00"

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TREE_FIELDS = {"entries", "schema_version", "type"}
_TREE_DIRECTORY_FIELDS = {"mode", "path", "type"}
_TREE_FILE_FIELDS = {"blob_hash", "mode", "path", "size", "type"}


class ReV2LedgerError(RuntimeError):
    """Raised when artifact or certification authority cannot be trusted."""


@dataclass(frozen=True, slots=True)
class CertificationDecision:
    """A controller decision; provider-authored verdict fields are not inputs."""

    certification_receipt: CertificationReceipt
    artifact_receipt: ArtifactReceipt | None

    def __post_init__(self) -> None:
        certification = self.certification_receipt
        artifact = self.artifact_receipt
        if not isinstance(certification, CertificationReceipt):
            raise ReV2LedgerError(
                "certification_receipt must be a CertificationReceipt"
            )
        if certification.verdict != "accepted" or not certification.scope_verified:
            if artifact is not None:
                raise ReV2LedgerError(
                    "a rejected or unscoped decision cannot contain an artifact receipt"
                )
            return
        if not isinstance(artifact, ArtifactReceipt):
            raise ReV2LedgerError(
                "an accepted decision requires an ArtifactReceipt"
            )
        _validate_artifact_authority(artifact, certification)


class Certifier(Protocol):
    """Controller verifier boundary. This protocol grants no provider authority."""

    @property
    def verifier_id(self) -> str: ...

    @property
    def verifier_version(self) -> str: ...

    def certify(
        self, candidate: "PersistedCandidate", work_item: WorkItem
    ) -> CertificationDecision: ...


class PersistedCandidate(Protocol):
    """Minimal forward-compatible candidate surface used by ``Certifier``."""

    @property
    def candidate_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class _TreeSource:
    path: Path
    relative: str
    type: str
    metadata: tuple[int, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class _TreeScan:
    root_metadata: tuple[int, int, int, int, int, int]
    entries: tuple[_TreeSource, ...]


class ObjectStore:
    """Race-safe content-addressed storage for blobs and canonical tree manifests."""

    def __init__(self, root: Path):
        self.root = Path(root)
        _ensure_directory(self.root, "object store")
        _ensure_directory(self.root / "sha256", "object namespace")

    def put_blob(self, payload: bytes) -> str:
        """Durably publish *payload* without replacing an existing object."""
        if not isinstance(payload, bytes):
            raise ReV2LedgerError("blob payload must be bytes")
        if payload.startswith(TREE_OBJECT_MAGIC):
            raise ReV2LedgerError("blob payload uses reserved tree object prefix")
        return self._put(payload)

    def put_tree(self, root: Path) -> str:
        """Ingest an unchanged regular-file tree into one canonical manifest."""
        tree_root = Path(root)
        initial = _scan_tree(tree_root)
        entries: list[dict[str, object]] = []
        for source in initial.entries:
            if source.type == "directory":
                entries.append(
                    {
                        "mode": stat.S_IMODE(source.metadata[2]),
                        "path": source.relative,
                        "type": "directory",
                    }
                )
                continue
            payload = _read_source_file(source)
            entries.append(
                {
                    "blob_hash": self.put_blob(payload),
                    "mode": stat.S_IMODE(source.metadata[2]),
                    "path": source.relative,
                    "size": len(payload),
                    "type": "file",
                }
            )
        if _scan_tree(tree_root) != initial:
            raise ReV2LedgerError("tree mutated during ingest")
        manifest = {
            "entries": entries,
            "schema_version": TREE_SCHEMA_VERSION,
            "type": "tree",
        }
        return self._put(TREE_OBJECT_MAGIC + canonical_json_bytes(manifest))

    def verify(self, object_hash: str) -> bool:
        """Verify an object and, for tree manifests, every referenced blob."""
        self._verify(object_hash, set())
        return True

    def _verify(self, object_hash: str, active: set[str]) -> bytes:
        path = self._path(object_hash)
        payload = _read_regular_file(path, f"object {object_hash}")
        if content_digest(payload) != object_hash:
            raise ReV2LedgerError(f"object hash mismatch: {object_hash}")
        manifest = _parse_tree_manifest(payload)
        if manifest is None:
            return payload
        if object_hash in active:
            raise ReV2LedgerError("tree object contains a reference cycle")
        active.add(object_hash)
        try:
            for entry in manifest["entries"]:
                if not isinstance(entry, dict):
                    raise ReV2LedgerError("tree manifest entry is invalid")
                if entry["type"] == "directory":
                    continue
                blob_hash = entry["blob_hash"]
                if not isinstance(blob_hash, str):
                    raise ReV2LedgerError("tree manifest blob hash is invalid")
                blob = self._verify(blob_hash, active)
                if len(blob) != entry["size"]:
                    raise ReV2LedgerError(
                        f"tree entry {entry['path']!r} has wrong blob size"
                    )
        finally:
            active.remove(object_hash)
        return payload

    def _put(self, payload: bytes) -> str:
        object_hash = content_digest(payload)
        path = self._path(object_hash)
        _ensure_directory(path.parent, "object bucket")
        temporary: Path | None = None
        try:
            fd, name = tempfile.mkstemp(prefix=".object.", suffix=".tmp", dir=path.parent)
            temporary = Path(name)
            try:
                _write_all(fd, payload)
                os.fchmod(fd, 0o400)
                _fsync(fd)
            finally:
                os.close(fd)
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                existing = _read_regular_file(path, f"existing object {object_hash}")
                if existing != payload or content_digest(existing) != object_hash:
                    raise ReV2LedgerError(
                        f"existing object is corrupt: {object_hash}"
                    )
            temporary.unlink()
            temporary = None
            # Flush both the final no-clobber link and temporary-name removal.
            _fsync_directory(path.parent)
            return object_hash
        except ReV2LedgerError:
            raise
        except OSError as exc:
            raise ReV2LedgerError(
                f"cannot publish immutable object {object_hash}: {exc}"
            ) from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _path(self, object_hash: str) -> Path:
        _digest(object_hash, "object_hash")
        suffix = object_hash.removeprefix("sha256:")
        return self.root / "sha256" / suffix[:2] / suffix[2:]


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    schema_version: int
    seq: int
    previous_record_hash: str | None
    type: str
    payload: Mapping[str, object]
    record_hash: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "payload": _thaw_json(self.payload),
            "previous_record_hash": self.previous_record_hash,
            "record_hash": self.record_hash,
            "schema_version": self.schema_version,
            "seq": self.seq,
            "type": self.type,
        }

    def identity_dict(self) -> dict[str, object]:
        value = self.to_json_dict()
        del value["record_hash"]
        return value


@dataclass(frozen=True, slots=True)
class LedgerView:
    """Narrow immutable authority consumed structurally by projection/planning."""

    accepted_artifacts: Mapping[str, ArtifactReceipt]
    certifications: Mapping[str, CertificationReceipt]
    certification_work_items: Mapping[str, WorkItem]


@dataclass(slots=True)
class _LedgerState:
    certifications: dict[str, CertificationReceipt]
    certifications_by_key: dict[str, tuple[CertificationReceipt, WorkItem]]
    certification_work_items: dict[str, WorkItem]
    accepted_artifacts: dict[str, ArtifactReceipt]

    @classmethod
    def empty(cls) -> "_LedgerState":
        return cls({}, {}, {}, {})

    def consume(
        self,
        record: LedgerRecord,
        object_store: ObjectStore,
        supported_verifiers: frozenset[tuple[str, str]],
        pinned_source_snapshot_id: str,
    ) -> None:
        if record.type == "certification":
            try:
                payload = _exact_object(
                    record.payload,
                    {"receipt", "work_item"},
                    "certification record payload",
                )
                receipt = CertificationReceipt.from_json_dict(payload["receipt"])
                work_item = WorkItem.from_json_dict(payload["work_item"])
            except (ReV2ModelError, TypeError, ValueError) as exc:
                raise ReV2LedgerError(f"invalid certification receipt: {exc}") from exc
            _validate_certification_work_item(
                receipt, work_item, pinned_source_snapshot_id
            )
            _validate_supported_verifier(receipt, supported_verifiers)
            object_store.verify(receipt.certification_key.artifact_hash)
            key_id = receipt.certification_key.identity
            existing = self.certifications_by_key.get(key_id)
            if existing is not None:
                if existing != (receipt, work_item):
                    raise ReV2LedgerError(
                        "conflicting certification receipt for certification key"
                    )
                return
            by_identity = self.certifications.get(receipt.identity)
            if by_identity is not None and by_identity != receipt:
                raise ReV2LedgerError("conflicting certification receipt identity")
            self.certifications[receipt.identity] = receipt
            self.certifications_by_key[key_id] = (receipt, work_item)
            self.certification_work_items[receipt.identity] = work_item
            return

        if record.type == "artifact":
            try:
                receipt = ArtifactReceipt.from_json_dict(record.payload)
            except (ReV2ModelError, TypeError, ValueError) as exc:
                raise ReV2LedgerError(f"invalid artifact receipt: {exc}") from exc
            if receipt.artifact_key.source_snapshot_id != pinned_source_snapshot_id:
                raise ReV2LedgerError(
                    "artifact receipt does not match pinned source snapshot"
                )
            existing = self.accepted_artifacts.get(receipt.artifact_key.identity)
            if existing is not None:
                if existing != receipt:
                    raise ReV2LedgerError(
                        "conflicting artifact receipt for artifact key"
                    )
                return
            certification = self.certifications.get(receipt.certification_id)
            if certification is None:
                raise ReV2LedgerError(
                    "artifact acceptance requires a preceding certification"
                )
            if certification.verdict != "accepted" or not certification.scope_verified:
                raise ReV2LedgerError(
                    "artifact acceptance requires an accepted certification"
                )
            work_item = self.certification_work_items[receipt.certification_id]
            _validate_artifact_authority(
                receipt,
                certification,
                work_item=work_item,
                pinned_source_snapshot_id=pinned_source_snapshot_id,
            )
            object_store.verify(receipt.artifact_hash)
            self.accepted_artifacts[receipt.artifact_key.identity] = receipt
            return

        raise ReV2LedgerError(f"unknown ledger record type: {record.type!r}")

    def view(self) -> LedgerView:
        return LedgerView(
            accepted_artifacts=MappingProxyType(dict(self.accepted_artifacts)),
            certifications=MappingProxyType(dict(self.certifications)),
            certification_work_items=MappingProxyType(
                dict(self.certification_work_items)
            ),
        )


class Ledger:
    """Append, lock, flush, and strictly replay certification authority."""

    def __init__(
        self,
        path: Path | ReV2Paths,
        object_store: ObjectStore,
        supported_verifiers: Mapping[str, str | Iterable[str]]
        | Iterable[tuple[str, str]],
        *,
        pinned_source_snapshot_id: str | None = None,
    ):
        if isinstance(path, ReV2Paths):
            self.path = path.ledger
            try:
                manifest_source = load_run_manifest(path.root.parent).source_snapshot_id
            except ReV2RunStoreError as exc:
                raise ReV2LedgerError(
                    f"cannot bind ledger to immutable run manifest: {exc}"
                ) from exc
            if (
                pinned_source_snapshot_id is not None
                and pinned_source_snapshot_id != manifest_source
            ):
                raise ReV2LedgerError(
                    "explicit pinned source does not match immutable run manifest"
                )
            pinned_source_snapshot_id = manifest_source
        else:
            self.path = Path(path)
            if pinned_source_snapshot_id is None:
                raise ReV2LedgerError(
                    "bare ledger path requires an explicit pinned source snapshot"
                )
        self.pinned_source_snapshot_id = _digest(
            pinned_source_snapshot_id, "pinned_source_snapshot_id"
        )
        self.lock_path = self.path.with_name("ledger.lock")
        self.object_store = object_store
        self.supported_verifiers = _normalize_supported_verifiers(
            supported_verifiers
        )

    def record_certification(
        self, receipt: CertificationReceipt, work_item: WorkItem
    ) -> LedgerRecord:
        if not isinstance(receipt, CertificationReceipt):
            raise ReV2LedgerError("receipt must be a CertificationReceipt")
        if not isinstance(work_item, WorkItem):
            raise ReV2LedgerError("work_item must be a WorkItem")
        return self._append("certification", receipt, work_item)

    def record_artifact(self, receipt: ArtifactReceipt) -> LedgerRecord:
        if not isinstance(receipt, ArtifactReceipt):
            raise ReV2LedgerError("receipt must be an ArtifactReceipt")
        return self._append("artifact", receipt)

    def replay(self) -> LedgerView:
        self._validate_parent()
        lock_fd = self._open_lock()
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            _, state = self._read_replay()
            return state.view()
        except ReV2LedgerError:
            raise
        except OSError as exc:
            raise ReV2LedgerError(f"cannot replay durable ledger: {exc}") from exc
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def _append(
        self,
        record_type: str,
        receipt: CertificationReceipt | ArtifactReceipt,
        work_item: WorkItem | None = None,
    ) -> LedgerRecord:
        self._validate_parent()
        lock_fd = self._open_lock()
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            history, state = self._read_replay()
            duplicate = _find_idempotent_record(
                history, state, record_type, receipt, work_item
            )
            if duplicate is not None:
                return duplicate

            payload = (
                {
                    "receipt": receipt.to_json_dict(),
                    "work_item": work_item.to_json_dict(),
                }
                if record_type == "certification" and work_item is not None
                else receipt.to_json_dict()
            )
            previous = history[-1].record_hash if history else None
            identity: dict[str, object] = {
                "payload": payload,
                "previous_record_hash": previous,
                "schema_version": LEDGER_SCHEMA_VERSION,
                "seq": len(history) + 1,
                "type": record_type,
            }
            record = LedgerRecord(
                payload=_freeze_json(payload),  # type: ignore[arg-type]
                previous_record_hash=previous,
                record_hash=content_digest(identity),
                schema_version=LEDGER_SCHEMA_VERSION,
                seq=len(history) + 1,
                type=record_type,
            )
            state.consume(
                record,
                self.object_store,
                self.supported_verifiers,
                self.pinned_source_snapshot_id,
            )

            existed = self.path.exists()
            fd = self._open_ledger_for_append()
            try:
                _write_all(fd, canonical_json_bytes(record.to_json_dict()))
                _fsync(fd)
            finally:
                os.close(fd)
            if not existed:
                _fsync_directory(self.path.parent)
            return record
        except ReV2LedgerError:
            raise
        except OSError as exc:
            raise ReV2LedgerError(f"cannot append durable ledger record: {exc}") from exc
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def _read_replay(self) -> tuple[tuple[LedgerRecord, ...], _LedgerState]:
        if not self.path.exists() and not self.path.is_symlink():
            return (), _LedgerState.empty()
        payload = _read_regular_file(self.path, "ledger")
        if not payload:
            return (), _LedgerState.empty()
        if not payload.endswith(b"\n"):
            raise ReV2LedgerError("partial final ledger record")

        records: list[LedgerRecord] = []
        state = _LedgerState.empty()
        previous: str | None = None
        if b"\r" in payload:
            raise ReV2LedgerError("ledger record framing rejects carriage returns")
        lines = payload[:-1].split(b"\n")
        if any(not line for line in lines):
            raise ReV2LedgerError("ledger records require exact single-LF framing")
        for index, line in enumerate(lines, start=1):
            try:
                raw = json.loads(
                    line,
                    parse_constant=_reject_json_constant,
                    parse_float=_finite_json_float,
                )
            except (UnicodeDecodeError, ValueError, OverflowError) as exc:
                raise ReV2LedgerError(
                    f"ledger record {index} is invalid JSON"
                ) from exc
            record = _record_from_raw(raw, index)
            if canonical_json_bytes(record.to_json_dict()) != line + b"\n":
                raise ReV2LedgerError(
                    f"ledger record {index} is not canonical JSON"
                )
            if record.seq != index:
                raise ReV2LedgerError(
                    f"ledger record {index} has nonconsecutive sequence {record.seq}"
                )
            if record.previous_record_hash != previous:
                raise ReV2LedgerError(
                    f"ledger record {index} has wrong previous record hash"
                )
            try:
                state.consume(
                    record,
                    self.object_store,
                    self.supported_verifiers,
                    self.pinned_source_snapshot_id,
                )
            except ReV2LedgerError as exc:
                raise ReV2LedgerError(
                    f"ledger record {index} is invalid: {exc}"
                ) from exc
            records.append(record)
            previous = record.record_hash
        return tuple(records), state

    def _validate_parent(self) -> None:
        if self.path.parent.is_symlink() or not self.path.parent.is_dir():
            raise ReV2LedgerError(
                f"ledger parent is not a safe directory: {self.path.parent}"
            )

    def _open_lock(self) -> int:
        if self.lock_path.is_symlink():
            raise ReV2LedgerError(f"unsafe ledger lock path: {self.lock_path}")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            return os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise ReV2LedgerError(f"cannot open ledger lock: {exc}") from exc

    def _open_ledger_for_append(self) -> int:
        if self.path.is_symlink():
            raise ReV2LedgerError(f"unsafe ledger path: {self.path}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        return os.open(self.path, flags, 0o600)


def _find_idempotent_record(
    history: tuple[LedgerRecord, ...],
    state: _LedgerState,
    record_type: str,
    receipt: CertificationReceipt | ArtifactReceipt,
    work_item: WorkItem | None,
) -> LedgerRecord | None:
    if record_type == "certification":
        if not isinstance(receipt, CertificationReceipt):
            raise ReV2LedgerError("certification record has wrong receipt type")
        if not isinstance(work_item, WorkItem):
            raise ReV2LedgerError("certification record requires a WorkItem")
        existing = state.certifications_by_key.get(receipt.certification_key.identity)
        if existing is None:
            return None
        if existing != (receipt, work_item):
            raise ReV2LedgerError(
                "conflicting certification work item for certification key"
            )
        identity = existing[0].identity
    else:
        if not isinstance(receipt, ArtifactReceipt):
            raise ReV2LedgerError("artifact record has wrong receipt type")
        existing = state.accepted_artifacts.get(receipt.artifact_key.identity)
        if existing is None:
            return None
        if existing != receipt:
            raise ReV2LedgerError("conflicting artifact receipt for artifact key")
        identity = existing.identity
    for record in history:
        if record.type != record_type:
            continue
        if record_type == "certification":
            record_payload = _exact_object(
                record.payload,
                {"receipt", "work_item"},
                "certification record payload",
            )
            model = CertificationReceipt.from_json_dict(record_payload["receipt"])
        else:
            model = ArtifactReceipt.from_json_dict(record.payload)
        if model.identity == identity:
            return record
    raise ReV2LedgerError("validated receipt has no ledger record")


def _record_from_raw(raw: object, index: int) -> LedgerRecord:
    fields = {
        "payload",
        "previous_record_hash",
        "record_hash",
        "schema_version",
        "seq",
        "type",
    }
    if not isinstance(raw, dict):
        raise ReV2LedgerError(f"ledger record {index} must be a JSON object")
    unknown = set(raw) - fields
    missing = fields - set(raw)
    if unknown:
        raise ReV2LedgerError(
            f"ledger record {index} has unknown fields: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise ReV2LedgerError(
            f"ledger record {index} is missing fields: {', '.join(sorted(missing))}"
        )
    if raw["schema_version"] != LEDGER_SCHEMA_VERSION or isinstance(
        raw["schema_version"], bool
    ):
        raise ReV2LedgerError(
            f"ledger record {index} has unknown ledger schema version"
        )
    if (
        not isinstance(raw["seq"], int)
        or isinstance(raw["seq"], bool)
        or raw["seq"] <= 0
    ):
        raise ReV2LedgerError(f"ledger record {index} has invalid sequence")
    if raw["type"] not in {"artifact", "certification"}:
        raise ReV2LedgerError(
            f"ledger record {index} has unknown ledger record type"
        )
    previous = raw["previous_record_hash"]
    if previous is not None:
        _digest(previous, "previous_record_hash")
    observed_hash = raw["record_hash"]
    _digest(observed_hash, "record_hash")
    identity = dict(raw)
    del identity["record_hash"]
    if content_digest(identity) != observed_hash:
        raise ReV2LedgerError(f"ledger record {index} has invalid record hash")
    if not isinstance(raw["payload"], dict):
        raise ReV2LedgerError(f"ledger record {index} payload must be an object")
    return LedgerRecord(
        payload=_freeze_json(raw["payload"]),  # type: ignore[arg-type]
        previous_record_hash=previous,
        record_hash=observed_hash,
        schema_version=LEDGER_SCHEMA_VERSION,
        seq=raw["seq"],
        type=raw["type"],
    )


def _validate_artifact_authority(
    artifact: ArtifactReceipt,
    certification: CertificationReceipt,
    *,
    work_item: WorkItem | None = None,
    pinned_source_snapshot_id: str | None = None,
) -> None:
    key = certification.certification_key
    if (
        artifact.certification_id != certification.identity
        or artifact.artifact_hash != key.artifact_hash
        or artifact.artifact_key.source_snapshot_id != key.source_snapshot_id
        or artifact.candidate_id != certification.candidate_id
        or artifact.work_item_id != certification.work_item_id
    ):
        raise ReV2LedgerError("artifact receipt does not match certification")
    if work_item is not None:
        if artifact.artifact_key != work_item.output_key:
            raise ReV2LedgerError(
                "artifact key does not match certified work item output key"
            )
        if artifact.work_item_id != work_item.work_item_id:
            raise ReV2LedgerError("artifact receipt does not match certified work item")
    if pinned_source_snapshot_id is not None and (
        artifact.artifact_key.source_snapshot_id != pinned_source_snapshot_id
        or key.source_snapshot_id != pinned_source_snapshot_id
    ):
        raise ReV2LedgerError("artifact authority does not match pinned source snapshot")


def _validate_certification_work_item(
    receipt: CertificationReceipt,
    work_item: WorkItem,
    pinned_source_snapshot_id: str,
) -> None:
    key = receipt.certification_key
    if receipt.work_item_id != work_item.work_item_id:
        raise ReV2LedgerError("certification receipt does not match work item identity")
    if (
        work_item.output_key.source_snapshot_id != pinned_source_snapshot_id
        or key.source_snapshot_id != pinned_source_snapshot_id
    ):
        raise ReV2LedgerError(
            "certification work item does not match pinned source snapshot"
        )
    if (
        key.verifier_id != work_item.verifier_id
        or key.verifier_version != work_item.verifier_version
    ):
        raise ReV2LedgerError(
            "certification verifier does not match immutable work item"
        )


def _validate_supported_verifier(
    receipt: CertificationReceipt,
    supported: frozenset[tuple[str, str]],
) -> None:
    observed = (
        receipt.certification_key.verifier_id,
        receipt.certification_key.verifier_version,
    )
    if observed not in supported:
        raise ReV2LedgerError(
            f"unsupported verifier version: {observed[0]}@{observed[1]}"
        )


def _normalize_supported_verifiers(
    value: Mapping[str, str | Iterable[str]] | Iterable[tuple[str, str]],
) -> frozenset[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    if isinstance(value, Mapping):
        for verifier_id, versions in value.items():
            selected = (versions,) if isinstance(versions, str) else tuple(versions)
            pairs.update((verifier_id, version) for version in selected)
    else:
        pairs.update(value)
    if any(
        not isinstance(verifier_id, str)
        or not verifier_id
        or not isinstance(version, str)
        or not version
        for verifier_id, version in pairs
    ):
        raise ReV2LedgerError("supported_verifiers must contain verifier/version pairs")
    return frozenset(pairs)


def _exact_object(
    value: object, fields: set[str], label: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ReV2LedgerError(f"{label} must be an object")
    present = set(value)
    unknown = present - fields
    missing = fields - present
    if unknown:
        raise ReV2LedgerError(
            f"{label} has unknown fields: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise ReV2LedgerError(
            f"{label} is missing fields: {', '.join(sorted(missing))}"
        )
    return value


def _scan_tree(root: Path) -> _TreeScan:
    if root.is_symlink():
        raise ReV2LedgerError("tree root may not be a symlink")
    try:
        root_stat = root.stat(follow_symlinks=False)
    except OSError as exc:
        raise ReV2LedgerError(f"cannot inspect tree root: {exc}") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ReV2LedgerError("tree root must be a directory")
    entries: list[_TreeSource] = []

    def walk(directory: Path, prefix: str) -> None:
        before = _lstat_metadata(directory, "tree directory")
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            raise ReV2LedgerError(f"cannot scan tree directory: {exc}") from exc
        for child in children:
            relative = f"{prefix}/{child.name}" if prefix else child.name
            _validate_tree_path(relative)
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise ReV2LedgerError(
                    f"cannot inspect tree entry {relative}: {exc}"
                ) from exc
            metadata = _metadata(child_stat)
            if stat.S_ISLNK(child_stat.st_mode):
                raise ReV2LedgerError(f"tree rejects symlink: {relative}")
            if stat.S_ISDIR(child_stat.st_mode):
                entries.append(
                    _TreeSource(
                        Path(child.path), relative, "directory", metadata
                    )
                )
                walk(Path(child.path), relative)
            elif stat.S_ISREG(child_stat.st_mode):
                entries.append(_TreeSource(Path(child.path), relative, "file", metadata))
            else:
                raise ReV2LedgerError(f"tree rejects special file: {relative}")
        if _lstat_metadata(directory, "tree directory") != before:
            raise ReV2LedgerError("tree mutated during ingest")

    walk(root, "")
    return _TreeScan(
        root_metadata=_metadata(root_stat),
        entries=tuple(sorted(entries, key=lambda source: source.relative)),
    )


def _read_source_file(source: _TreeSource) -> bytes:
    if source.type != "file":
        raise ReV2LedgerError("only regular files have blob payloads")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(source.path, flags)
    except OSError as exc:
        raise ReV2LedgerError(
            f"cannot open tree file {source.relative}: {exc}"
        ) from exc
    try:
        before = _metadata(os.fstat(fd))
        if before != source.metadata or not stat.S_ISREG(before[2]):
            raise ReV2LedgerError(f"tree file mutated during ingest: {source.relative}")
        payload = _read_all(fd)
        after = _metadata(os.fstat(fd))
        if after != before or len(payload) != before[3]:
            raise ReV2LedgerError(f"tree file mutated during ingest: {source.relative}")
        return payload
    finally:
        os.close(fd)


def _parse_tree_manifest(payload: bytes) -> dict[str, object] | None:
    if not payload.startswith(TREE_OBJECT_MAGIC):
        return None
    manifest_payload = payload[len(TREE_OBJECT_MAGIC) :]
    try:
        raw = json.loads(
            manifest_payload,
            parse_constant=_reject_json_constant,
            parse_float=_finite_json_float,
        )
    except (UnicodeDecodeError, ValueError, OverflowError) as exc:
        raise ReV2LedgerError("tree object envelope contains invalid JSON") from exc
    if not isinstance(raw, dict) or raw.get("type") != "tree":
        raise ReV2LedgerError("tree object envelope does not contain a tree manifest")
    if set(raw) != _TREE_FIELDS:
        raise ReV2LedgerError("tree manifest has unknown or missing fields")
    if raw["schema_version"] != TREE_SCHEMA_VERSION or isinstance(
        raw["schema_version"], bool
    ):
        raise ReV2LedgerError("tree manifest has unsupported schema version")
    if canonical_json_bytes(raw) != manifest_payload:
        raise ReV2LedgerError("tree manifest is not canonical JSON")
    entries = raw["entries"]
    if not isinstance(entries, list):
        raise ReV2LedgerError("tree manifest entries must be an array")
    paths: list[str] = []
    entry_types: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReV2LedgerError("tree manifest entry must be an object")
        entry_type = entry.get("type")
        expected_fields = (
            _TREE_DIRECTORY_FIELDS
            if entry_type == "directory"
            else _TREE_FILE_FIELDS
            if entry_type == "file"
            else set()
        )
        if not expected_fields or set(entry) != expected_fields:
            raise ReV2LedgerError("tree manifest entry has unknown or missing fields")
        path = entry["path"]
        if not isinstance(path, str):
            raise ReV2LedgerError("tree manifest path must be a string")
        _validate_tree_path(path)
        paths.append(path)
        entry_types[path] = entry_type
        mode = entry["mode"]
        if (
            not isinstance(mode, int)
            or isinstance(mode, bool)
            or mode < 0
            or mode > 0o7777
        ):
            raise ReV2LedgerError("tree entry mode is invalid")
        if entry_type == "file":
            _digest(entry["blob_hash"], "tree blob_hash")
            size = entry["size"]
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise ReV2LedgerError("tree entry size is invalid")
    if paths != sorted(set(paths)):
        raise ReV2LedgerError("tree manifest paths must be unique and sorted")
    for path in paths:
        parent = PurePosixPath(path).parent
        while parent != PurePosixPath("."):
            parent_path = parent.as_posix()
            if entry_types.get(parent_path) != "directory":
                raise ReV2LedgerError(
                    f"tree manifest omits parent directory: {parent_path}"
                )
            parent = parent.parent
    return raw


def _validate_tree_path(value: str) -> None:
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or PurePosixPath(value).is_absolute()
        or PurePosixPath(value).as_posix() != value
    ):
        raise ReV2LedgerError(f"unsafe tree path traversal: {value!r}")


def _ensure_directory(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ReV2LedgerError(f"unsafe symlink for {label}: {path}")
    if path.exists():
        if not path.is_dir():
            raise ReV2LedgerError(f"{label} is not a directory: {path}")
        return
    parent = path.parent
    if parent == path or parent.is_symlink() or not parent.is_dir():
        raise ReV2LedgerError(f"{label} parent is not a safe directory: {parent}")
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        if path.is_symlink() or not path.is_dir():
            raise ReV2LedgerError(f"unsafe concurrent {label}: {path}")
    except OSError as exc:
        raise ReV2LedgerError(f"cannot create {label}: {exc}") from exc
    else:
        _fsync_directory(parent)


def _read_regular_file(path: Path, label: str) -> bytes:
    if path.is_symlink():
        raise ReV2LedgerError(f"unsafe symlink for {label}: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ReV2LedgerError(f"cannot read {label}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ReV2LedgerError(f"{label} is not a regular file")
        payload = _read_all(fd)
        after = os.fstat(fd)
        if (
            _object_read_metadata(before) != _object_read_metadata(after)
            or len(payload) != after.st_size
        ):
            raise ReV2LedgerError(f"{label} mutated while being read")
        return payload
    finally:
        os.close(fd)


def _metadata(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _object_read_metadata(value: os.stat_result) -> tuple[int, int, int, int, int]:
    # Link-count changes during no-clobber publication update ctime but cannot
    # change bytes. Mode, size, and mtime still detect meaningful mutation.
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )


def _lstat_metadata(path: Path, label: str) -> tuple[int, int, int, int, int, int]:
    try:
        return _metadata(path.stat(follow_symlinks=False))
    except OSError as exc:
        raise ReV2LedgerError(f"cannot inspect {label}: {exc}") from exc


def _read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            chunk = os.read(fd, 1024 * 1024)
        except InterruptedError:
            continue
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(fd, payload[offset:])
        except InterruptedError:
            continue
        if written <= 0:
            raise OSError("short write while persisting immutable data")
        offset += written


def _fsync(fd: int) -> None:
    while True:
        try:
            os.fsync(fd)
            return
        except InterruptedError:
            continue


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        _fsync(fd)
    finally:
        os.close(fd)


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReV2LedgerError(f"{field} must be a lowercase sha256 digest")
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"nonfinite JSON number: {value}")


def _finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"overflowing JSON number: {value}")
    return parsed


__all__ = [
    "CertificationDecision",
    "Certifier",
    "LEDGER_SCHEMA_VERSION",
    "Ledger",
    "LedgerRecord",
    "LedgerView",
    "ObjectStore",
    "ReV2LedgerError",
    "TREE_OBJECT_MAGIC",
]

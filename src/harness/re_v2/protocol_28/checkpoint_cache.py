"""Protocol-2.8 checkpoint selection and child-local object adoption."""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.schema import digest_value
from harness.re_v2.protocol_28.checkpoints import (
    CheckpointDispositionV2,
    CheckpointManifestV2,
    CheckpointSelectionBundleV2,
    CheckpointSelectionEntryV2,
    L4CheckpointExpectationV1,
    Protocol28CheckpointError,
)
from harness.re_v2.protocol_28.artifacts import (
    normalize_candidate_result,
    normalize_verification_result,
)
from harness.re_v2.protocol_28.execution import (
    decode_provider_result_object,
    L4ExecutionCaptureV1,
    L4ExecutionEnvelopeV1,
)


@dataclass(frozen=True, slots=True)
class CheckpointCachePathsV2:
    """Physically versioned protocol-2.8 cache projection paths."""

    root: Path
    index: Path
    lock: Path
    manifests: Path
    quarantine: Path

    @classmethod
    def for_workspace(cls, workspace_root: Path) -> "CheckpointCachePathsV2":
        workspace = Path(workspace_root)
        if workspace.is_symlink():
            raise Protocol28CheckpointError("workspace root must not be a symlink")
        try:
            resolved = workspace.resolve(strict=True)
        except OSError as exc:
            raise Protocol28CheckpointError(
                f"workspace root is unavailable: {exc}"
            ) from exc
        if not resolved.is_dir():
            raise Protocol28CheckpointError("workspace root must be a directory")
        root = resolved / ".echelon" / "re-v2" / "checkpoints"
        return cls(
            root=root,
            index=root / "index-v2.json",
            lock=root / "index-v2.lock",
            manifests=root / "manifests-v2",
            quarantine=root / "quarantine-v2.json",
        )


@dataclass(frozen=True, slots=True)
class CheckpointCacheEntryV2:
    schema_version: int
    checkpoint_manifest_id: str
    origin_run_id: str
    output_artifact_key_id: str
    compatibility_id: str
    rank_vector: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 2 or isinstance(self.schema_version, bool):
            raise Protocol28CheckpointError("checkpoint cache entry schema must be 2")
        if not self.origin_run_id:
            raise Protocol28CheckpointError("checkpoint cache origin must not be empty")
        for field in (
            "checkpoint_manifest_id",
            "output_artifact_key_id",
            "compatibility_id",
        ):
            value = getattr(self, field)
            try:
                digest_value(value, f"CheckpointCacheEntryV2.{field}")
            except Exception as exc:
                raise Protocol28CheckpointError(
                    f"checkpoint cache {field} is invalid"
                ) from exc
        rank = tuple(self.rank_vector)
        if not rank or any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0
            for item in rank
        ):
            raise Protocol28CheckpointError("checkpoint cache rank vector is invalid")
        object.__setattr__(self, "rank_vector", rank)

    @classmethod
    def from_checkpoint(
        cls, checkpoint: CheckpointManifestV2
    ) -> "CheckpointCacheEntryV2":
        return cls(
            2,
            checkpoint.identity,
            checkpoint.origin_run_id,
            checkpoint.slice_spec.output_artifact_key_id,
            checkpoint.compatibility_id,
            checkpoint.rank_vector,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "checkpoint_manifest_id": self.checkpoint_manifest_id,
            "origin_run_id": self.origin_run_id,
            "output_artifact_key_id": self.output_artifact_key_id,
            "compatibility_id": self.compatibility_id,
            "rank_vector": list(self.rank_vector),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointCacheEntryV2":
        fields = {
            "schema_version",
            "checkpoint_manifest_id",
            "origin_run_id",
            "output_artifact_key_id",
            "compatibility_id",
            "rank_vector",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise Protocol28CheckpointError("checkpoint cache entry fields are invalid")
        rank = value["rank_vector"]
        if not isinstance(rank, list):
            raise Protocol28CheckpointError(
                "checkpoint cache rank vector must be an array"
            )
        return cls(
            value["schema_version"],
            value["checkpoint_manifest_id"],
            value["origin_run_id"],
            value["output_artifact_key_id"],
            value["compatibility_id"],
            tuple(rank),
        )


@dataclass(frozen=True, slots=True)
class CheckpointCacheIndexV2:
    schema_version: int
    entries: tuple[CheckpointCacheEntryV2, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 2 or isinstance(self.schema_version, bool):
            raise Protocol28CheckpointError("checkpoint cache index schema must be 2")
        entries = tuple(self.entries)
        if any(not isinstance(item, CheckpointCacheEntryV2) for item in entries):
            raise Protocol28CheckpointError(
                "checkpoint cache index entries are invalid"
            )
        ids = tuple(item.checkpoint_manifest_id for item in entries)
        if ids != tuple(sorted(set(ids))):
            raise Protocol28CheckpointError(
                "checkpoint cache index must be sorted and unique"
            )
        object.__setattr__(self, "entries", entries)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "entries": [item.to_json_dict() for item in self.entries],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointCacheIndexV2":
        if not isinstance(value, dict) or set(value) != {"schema_version", "entries"}:
            raise Protocol28CheckpointError("checkpoint cache index fields are invalid")
        entries = value["entries"]
        if not isinstance(entries, list):
            raise Protocol28CheckpointError(
                "checkpoint cache index entries must be an array"
            )
        return cls(
            value["schema_version"],
            tuple(CheckpointCacheEntryV2.from_json_dict(item) for item in entries),
        )


def _object_failure(
    checkpoint: CheckpointManifestV2,
    objects: Mapping[str, bytes] | None,
) -> str | None:
    if objects is None:
        return "checkpoint_object_inventory_missing"
    if set(objects) != set(checkpoint.immutable_object_hashes):
        return "checkpoint_object_inventory_mismatch"
    for object_id in checkpoint.immutable_object_hashes:
        payload = objects.get(object_id)
        if payload is None:
            return "checkpoint_object_missing"
        if not isinstance(payload, bytes):
            return "checkpoint_object_invalid"
        if len(payload) != checkpoint.immutable_object_byte_counts[object_id]:
            return "checkpoint_object_byte_count_mismatch"
        if content_digest(payload) != object_id:
            return "checkpoint_object_hash_mismatch"
    return _execution_authority_failure(checkpoint, objects)


def _execution_authority_failure(
    checkpoint: CheckpointManifestV2,
    objects: Mapping[str, bytes],
) -> str | None:
    executions: list[tuple[L4ExecutionEnvelopeV1, L4ExecutionCaptureV1]] = []
    expected = (
        (
            checkpoint.accepted_slice.producer_execution_capture_hash,
            "producer",
            checkpoint.plan_entry.producer_contract_hash,
            None,
            checkpoint.candidate.identity,
        ),
        (
            checkpoint.accepted_slice.verifier_execution_capture_hash,
            "verifier",
            checkpoint.plan_entry.verifier_contract_hash,
            checkpoint.candidate.identity,
            checkpoint.verification.identity,
        ),
    )
    for capture_id, role, contract_hash, candidate_id, result_id in expected:
        capture_payload = objects.get(capture_id)
        if capture_payload is None:
            return "checkpoint_execution_authority_incomplete"
        try:
            capture = L4ExecutionCaptureV1.from_json_dict(json.loads(capture_payload))
        except Exception:
            return "checkpoint_execution_authority_invalid"
        if (
            capture.identity != capture_id
            or capture.role != role
            or capture.result_kind != "provider_result"
        ):
            return "checkpoint_execution_authority_invalid"
        raw_result = objects.get(capture.raw_result_hash)
        if raw_result is None:
            return "checkpoint_execution_authority_incomplete"
        if len(raw_result) != capture.raw_byte_count:
            return "checkpoint_execution_authority_invalid"
        try:
            decoded = decode_provider_result_object(raw_result)
            normalized = (
                normalize_candidate_result(decoded)
                if role == "producer"
                else normalize_verification_result(decoded)
            )
        except Exception:
            return "checkpoint_execution_authority_invalid"
        if normalized.identity != result_id:
            return "checkpoint_execution_authority_invalid"
        envelope_payload = objects.get(capture.execution_envelope_id)
        if envelope_payload is None:
            return "checkpoint_execution_authority_incomplete"
        try:
            envelope = L4ExecutionEnvelopeV1.from_json_dict(
                json.loads(envelope_payload)
            )
        except Exception:
            return "checkpoint_execution_authority_invalid"
        if (
            envelope.identity != capture.execution_envelope_id
            or envelope.dispatch_id != capture.dispatch_id
            or envelope.role != role
            or envelope.slice_spec_id != checkpoint.slice_spec.identity
            or envelope.plan_entry_id != checkpoint.plan_entry.identity
            or envelope.agent_contract_hash != contract_hash
            or envelope.candidate_id != candidate_id
        ):
            return "checkpoint_execution_authority_invalid"
        executions.append((envelope, capture))
    if executions[0][0].context_bundle_hash == executions[1][0].context_bundle_hash:
        return "checkpoint_execution_authority_invalid"
    return None


def select_checkpoints_v2(
    expectations: tuple[L4CheckpointExpectationV1, ...],
    candidates: tuple[CheckpointManifestV2, ...],
    authority_objects: Mapping[str, Mapping[str, bytes]],
    *,
    direct_parent_output_artifact_key_ids: tuple[str, ...] = (),
) -> CheckpointSelectionBundleV2:
    """Select the best exact, slice-local checkpoint for every requested output."""
    expected_by_key: dict[str, L4CheckpointExpectationV1] = {}
    for expectation in expectations:
        if not isinstance(expectation, L4CheckpointExpectationV1):
            raise Protocol28CheckpointError("checkpoint expectation is invalid")
        key = expectation.output_artifact_key_id
        if key in expected_by_key:
            raise Protocol28CheckpointError("checkpoint expectations must be unique")
        expected_by_key[key] = expectation

    direct_parent_keys = set(direct_parent_output_artifact_key_ids)
    if len(direct_parent_keys) != len(direct_parent_output_artifact_key_ids):
        raise Protocol28CheckpointError("direct-parent checkpoint keys must be unique")
    if not direct_parent_keys <= set(expected_by_key):
        raise Protocol28CheckpointError(
            "direct-parent checkpoint key is outside selection"
        )

    compatible: dict[str, list[CheckpointManifestV2]] = {}
    rejected: list[CheckpointDispositionV2] = []
    quarantined: list[CheckpointDispositionV2] = []
    seen_ids: set[str] = set()
    for checkpoint in sorted(candidates, key=lambda item: item.identity):
        if not isinstance(checkpoint, CheckpointManifestV2):
            raise Protocol28CheckpointError("checkpoint candidate is invalid")
        checkpoint_id = checkpoint.identity
        if checkpoint_id in seen_ids:
            continue
        seen_ids.add(checkpoint_id)
        failure = _object_failure(checkpoint, authority_objects.get(checkpoint_id))
        if failure is not None:
            quarantined.append(
                CheckpointDispositionV2(
                    checkpoint_id,
                    checkpoint.slice_spec.output_artifact_key_id,
                    "quarantined",
                    failure,
                )
            )
            continue
        expectation = expected_by_key.get(checkpoint.slice_spec.output_artifact_key_id)
        if checkpoint.slice_spec.output_artifact_key_id in direct_parent_keys:
            rejected.append(
                CheckpointDispositionV2(
                    checkpoint_id,
                    checkpoint.slice_spec.output_artifact_key_id,
                    "rejected",
                    "direct_parent_precedence",
                )
            )
            continue
        if (
            expectation is None
            or checkpoint.compatibility_id != expectation.compatibility_id
        ):
            rejected.append(
                CheckpointDispositionV2(
                    checkpoint_id,
                    checkpoint.slice_spec.output_artifact_key_id,
                    "rejected",
                    "checkpoint_incompatible",
                )
            )
            continue
        compatible.setdefault(expectation.output_artifact_key_id, []).append(checkpoint)

    selected: list[CheckpointSelectionEntryV2] = []
    for key, eligible in sorted(compatible.items()):
        winner = max(eligible, key=lambda item: (item.rank_vector, item.identity))
        selected.append(
            CheckpointSelectionEntryV2(
                output_artifact_key_id=key,
                checkpoint_manifest_id=winner.identity,
                accepted_slice_id=winner.accepted_slice.identity,
            )
        )
        for checkpoint in eligible:
            if checkpoint.identity != winner.identity:
                rejected.append(
                    CheckpointDispositionV2(
                        checkpoint.identity,
                        key,
                        "rejected",
                        "checkpoint_superseded",
                    )
                )

    selected_keys = {item.output_artifact_key_id for item in selected}
    return CheckpointSelectionBundleV2(
        schema_version=2,
        selected=tuple(selected),
        rejected=tuple(
            sorted(
                rejected,
                key=lambda item: (
                    item.output_artifact_key_id,
                    item.checkpoint_manifest_id,
                ),
            )
        ),
        quarantined=tuple(
            sorted(
                quarantined,
                key=lambda item: (
                    item.output_artifact_key_id,
                    item.checkpoint_manifest_id,
                ),
            )
        ),
        missing_output_artifact_key_ids=tuple(
            sorted(set(expected_by_key) - selected_keys - direct_parent_keys)
        ),
    )


def publish_checkpoint_cache_v2(
    workspace_root: Path,
    manifests: tuple[CheckpointManifestV2, ...],
    quarantine: tuple[CheckpointDispositionV2, ...],
) -> CheckpointCacheIndexV2:
    """Atomically publish a disposable V2 cache, with the index written last."""
    paths = CheckpointCachePathsV2.for_workspace(workspace_root)
    _ensure_cache_layout(paths)
    by_id: dict[str, CheckpointManifestV2] = {}
    for manifest in manifests:
        if not isinstance(manifest, CheckpointManifestV2):
            raise Protocol28CheckpointError("checkpoint cache manifest is invalid")
        by_id.setdefault(manifest.identity, manifest)
        if by_id[manifest.identity] != manifest:
            raise Protocol28CheckpointError(
                "checkpoint cache manifest identity conflicts"
            )
    ordered = dict(sorted(by_id.items()))
    index = CheckpointCacheIndexV2(
        2,
        tuple(
            CheckpointCacheEntryV2.from_checkpoint(item) for item in ordered.values()
        ),
    )
    for item in quarantine:
        if (
            not isinstance(item, CheckpointDispositionV2)
            or item.disposition != "quarantined"
        ):
            raise Protocol28CheckpointError("checkpoint cache quarantine is invalid")

    lock_fd = _acquire_cache_lock(paths.lock)
    try:
        stage = Path(tempfile.mkdtemp(prefix=".generation-v2-", dir=paths.root))
        try:
            staged_manifests = stage / "manifests-v2"
            staged_manifests.mkdir(mode=0o700)
            for manifest_id, manifest in ordered.items():
                _write_new_file(
                    staged_manifests / f"{manifest_id}.json",
                    canonical_json_bytes(manifest.to_json_dict()),
                )
            _write_new_file(
                stage / "quarantine-v2.json",
                canonical_json_bytes(
                    {
                        "schema_version": 2,
                        "entries": [
                            item.to_json_dict()
                            for item in sorted(
                                quarantine,
                                key=lambda value: (
                                    value.output_artifact_key_id,
                                    value.checkpoint_manifest_id,
                                ),
                            )
                        ],
                    }
                ),
            )
            _write_new_file(
                stage / "index-v2.json", canonical_json_bytes(index.to_json_dict())
            )
            _fsync_directory(staged_manifests)
            _fsync_directory(stage)
            for manifest_id in ordered:
                os.replace(
                    staged_manifests / f"{manifest_id}.json",
                    paths.manifests / f"{manifest_id}.json",
                )
            _fsync_directory(paths.manifests)
            os.replace(stage / "quarantine-v2.json", paths.quarantine)
            _fsync_directory(paths.root)
            os.replace(stage / "index-v2.json", paths.index)
            _fsync_directory(paths.root)
            _retire_unreferenced(paths.manifests, set(ordered))
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    finally:
        _release_cache_lock(lock_fd)
    return index


def load_checkpoint_cache_v2(
    workspace_root: Path,
) -> tuple[
    CheckpointCacheIndexV2,
    Mapping[str, CheckpointManifestV2],
    tuple[CheckpointDispositionV2, ...],
]:
    """Load and authenticate the manifest-last V2 cache projection."""
    paths = CheckpointCachePathsV2.for_workspace(workspace_root)
    index = CheckpointCacheIndexV2.from_json_dict(_read_json(paths.index))
    manifests: dict[str, CheckpointManifestV2] = {}
    for entry in index.entries:
        manifest = CheckpointManifestV2.from_json_dict(
            _read_json(paths.manifests / f"{entry.checkpoint_manifest_id}.json")
        )
        if manifest.identity != entry.checkpoint_manifest_id:
            raise Protocol28CheckpointError(
                "checkpoint cache manifest identity mismatch"
            )
        if CheckpointCacheEntryV2.from_checkpoint(manifest) != entry:
            raise Protocol28CheckpointError(
                "checkpoint cache entry differs from manifest"
            )
        manifests[manifest.identity] = manifest
    quarantine_raw = _read_json(paths.quarantine)
    if (
        not isinstance(quarantine_raw, dict)
        or set(quarantine_raw) != {"schema_version", "entries"}
        or quarantine_raw["schema_version"] != 2
        or not isinstance(quarantine_raw["entries"], list)
    ):
        raise Protocol28CheckpointError("checkpoint cache quarantine is invalid")
    quarantine = tuple(
        CheckpointDispositionV2.from_json_dict(item)
        for item in quarantine_raw["entries"]
    )
    if any(item.disposition != "quarantined" for item in quarantine):
        raise Protocol28CheckpointError(
            "checkpoint cache quarantine disposition is invalid"
        )
    return index, manifests, quarantine


def _ensure_cache_layout(paths: CheckpointCachePathsV2) -> None:
    current = paths.root.parents[2]
    for name in (".echelon", "re-v2", "checkpoints", "manifests-v2"):
        current = current / name
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        metadata = os.lstat(current)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise Protocol28CheckpointError("checkpoint cache path is unsafe")


def _write_new_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def _acquire_cache_lock(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise Protocol28CheckpointError("cannot open checkpoint cache lock") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Protocol28CheckpointError(
                "checkpoint cache lock is not a regular file"
            )
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd
    except Exception:
        os.close(fd)
        raise


def _release_cache_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_json(path: Path) -> object:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        before = _stable_metadata(os.fstat(fd))
        if not stat.S_ISREG(before[2]):
            raise Protocol28CheckpointError(
                "checkpoint cache projection is not a regular file"
            )
        with os.fdopen(fd, "rb", closefd=False) as stream:
            payload = stream.read()
        if _stable_metadata(os.fstat(fd)) != before:
            raise Protocol28CheckpointError(
                "checkpoint cache projection changed while read"
            )
        return json.loads(payload)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Protocol28CheckpointError(
            "checkpoint cache projection is invalid"
        ) from exc
    finally:
        if "fd" in locals():
            os.close(fd)


def _stable_metadata(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _retire_unreferenced(directory: Path, retained: set[str]) -> None:
    for projection in directory.iterdir():
        manifest_id = projection.name.removesuffix(".json")
        if manifest_id not in retained:
            if projection.is_dir() and not projection.is_symlink():
                shutil.rmtree(projection)
            else:
                projection.unlink()
    _fsync_directory(directory)


def copy_selected_checkpoint_objects(
    selection: CheckpointSelectionBundleV2,
    manifests_by_id: Mapping[str, CheckpointManifestV2],
    authority_objects: Mapping[str, Mapping[str, bytes]],
    child_object_root: Path,
) -> tuple[str, ...]:
    """Authenticate then durably copy selected authority into the child run."""
    selected_manifests: list[CheckpointManifestV2] = []
    for selected in selection.selected:
        manifest = manifests_by_id.get(selected.checkpoint_manifest_id)
        if manifest is None or manifest.identity != selected.checkpoint_manifest_id:
            raise Protocol28CheckpointError(
                "selected checkpoint manifest is unavailable"
            )
        if manifest.accepted_slice.identity != selected.accepted_slice_id:
            raise Protocol28CheckpointError(
                "selected checkpoint acceptance is cross-bound"
            )
        failure = _object_failure(manifest, authority_objects.get(manifest.identity))
        if failure is not None:
            raise Protocol28CheckpointError(
                f"selected checkpoint failed authentication: {failure}"
            )
        selected_manifests.append(manifest)

    store = ObjectStore(Path(child_object_root))
    copied: set[str] = set()
    for manifest in selected_manifests:
        objects = authority_objects[manifest.identity]
        for object_id in manifest.immutable_object_hashes:
            if store.put_blob(objects[object_id]) != object_id:
                raise Protocol28CheckpointError(
                    "child-local checkpoint copy changed identity"
                )
            copied.add(object_id)
    return tuple(sorted(copied))


__all__ = (
    "CheckpointCacheIndexV2",
    "CheckpointCachePathsV2",
    "copy_selected_checkpoint_objects",
    "load_checkpoint_cache_v2",
    "publish_checkpoint_cache_v2",
    "select_checkpoints_v2",
)

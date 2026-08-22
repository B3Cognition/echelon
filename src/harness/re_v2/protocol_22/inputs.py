"""Immutable protocol-2.2 input publication and authenticated loading."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from types import MappingProxyType
from typing import Callable, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError, TREE_OBJECT_MAGIC
from harness.re_v2.run_store import (
    ReV2Paths,
    ReV2RunStoreError,
    load_run_manifest,
)

from .executors import (
    ExecutorContractCatalogV1,
    Protocol22ExecutorError,
)
from .model import CatalogReferenceV1, RunManifestV2
from .partition import (
    Protocol22PartitionError,
    WorkspacePartitionCatalogV1,
)
from .policies import (
    ArtifactPolicyCatalogV1,
    Protocol22PolicyError,
)
from .schema import (
    Protocol22SchemaError,
    digest_value,
    load_canonical_object,
)


FaultHook = Callable[[str], None]


class Protocol22InputStoreError(RuntimeError):
    """Raised when immutable protocol-2.2 run inputs are unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class Protocol22InputSet:
    workspace_partition: WorkspacePartitionCatalogV1
    artifact_policy: ArtifactPolicyCatalogV1
    executor_contract: ExecutorContractCatalogV1
    immutable_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_partition, WorkspacePartitionCatalogV1):
            raise Protocol22InputStoreError(
                "workspace_partition must be WorkspacePartitionCatalogV1"
            )
        if not isinstance(self.artifact_policy, ArtifactPolicyCatalogV1):
            raise Protocol22InputStoreError(
                "artifact_policy must be ArtifactPolicyCatalogV1"
            )
        if not isinstance(self.executor_contract, ExecutorContractCatalogV1):
            raise Protocol22InputStoreError(
                "executor_contract must be ExecutorContractCatalogV1"
            )
        if not isinstance(self.immutable_objects, Mapping):
            raise Protocol22InputStoreError("immutable_objects must be a mapping")
        copied: dict[str, bytes] = {}
        for object_hash, payload in self.immutable_objects.items():
            try:
                digest_value(object_hash, "Protocol22InputSet.immutable_objects key")
            except Protocol22SchemaError as exc:
                raise Protocol22InputStoreError(str(exc)) from exc
            if not isinstance(payload, bytes):
                raise Protocol22InputStoreError(
                    "Protocol22InputSet immutable object payloads must be bytes"
                )
            if content_digest(payload) != object_hash:
                raise Protocol22InputStoreError(
                    f"immutable object hash mismatch: {object_hash}"
                )
            if payload.startswith(TREE_OBJECT_MAGIC):
                raise Protocol22InputStoreError(
                    "protocol-2.2 input objects must be blobs, not tree objects"
                )
            copied[object_hash] = payload
        object.__setattr__(
            self,
            "immutable_objects",
            MappingProxyType(dict(sorted(copied.items()))),
        )


@dataclass(frozen=True, slots=True)
class ValidatedProtocol22Inputs:
    workspace_partition: WorkspacePartitionCatalogV1
    artifact_policy: ArtifactPolicyCatalogV1
    executor_contract: ExecutorContractCatalogV1
    immutable_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "immutable_objects",
            MappingProxyType(dict(sorted(self.immutable_objects.items()))),
        )


@dataclass(frozen=True, slots=True)
class _PreparedInputs:
    workspace_payload: bytes
    artifact_policy_payload: bytes
    executor_payload: bytes


def create_protocol_22_run_store(
    run_dir: Path,
    manifest: RunManifestV2,
    inputs: Protocol22InputSet,
    fault_hook: FaultHook | None = None,
) -> ReV2Paths:
    """Publish every immutable input before atomically linking the manifest."""
    if not isinstance(manifest, RunManifestV2):
        raise Protocol22InputStoreError(
            "protocol-2.2 input creation requires RunManifestV2"
        )
    if not isinstance(inputs, Protocol22InputSet):
        raise Protocol22InputStoreError(
            "protocol-2.2 input creation requires Protocol22InputSet"
        )
    if manifest.run_id != run_dir.name:
        raise Protocol22InputStoreError(
            f"manifest run_id {manifest.run_id!r} does not match run directory {run_dir.name!r}"
        )
    prepared = _prepare_inputs(manifest, inputs)
    _ensure_run_directory(run_dir)
    paths = ReV2Paths.for_run(run_dir)
    if paths.root.exists() or paths.root.is_symlink():
        if paths.manifest.exists() or paths.manifest.is_symlink():
            raise Protocol22InputStoreError(
                f"immutable v2 run manifest already exists: {paths.manifest}"
            )
        raise Protocol22InputStoreError(
            "incomplete v2 run store already exists without an immutable manifest"
        )

    try:
        paths.root.mkdir(mode=0o700)
        _fsync_directory(run_dir.resolve())
        paths.objects.mkdir(mode=0o700)
        paths.inputs.mkdir(mode=0o700)
        _fsync_directory(paths.root)

        try:
            object_store = ObjectStore(paths.objects)
            for object_hash, payload in inputs.immutable_objects.items():
                published = object_store.put_blob(payload)
                if published != object_hash:
                    raise Protocol22InputStoreError(
                        f"immutable object publication changed identity: {object_hash}"
                    )
                _fault(fault_hook, f"object_published:{object_hash}")
        except ReV2LedgerError as exc:
            raise Protocol22InputStoreError(
                f"cannot publish protocol-2.2 immutable object: {exc}"
            ) from exc
        _fsync_directory(paths.objects / "sha256")
        _fsync_directory(paths.objects)

        catalogs = (
            (
                "workspace_partition",
                manifest.workspace_partition_catalog,
                prepared.workspace_payload,
            ),
            (
                "artifact_policy",
                manifest.artifact_policy_catalog,
                prepared.artifact_policy_payload,
            ),
            (
                "executor_contract",
                manifest.executor_contract_catalog,
                prepared.executor_payload,
            ),
        )
        for name, reference, payload in catalogs:
            destination = _prepare_input_destination(paths.inputs, reference)
            _write_new_file(destination, payload, mode=0o400)
            _fault(fault_hook, f"catalog_published:{name}")
        _fsync_tree_directories(paths.inputs)
        _fault(fault_hook, "inputs_fsynced")

        _publish_manifest_last(paths, manifest, fault_hook)
        return paths
    except Protocol22InputStoreError:
        raise
    except OSError as exc:
        raise Protocol22InputStoreError(
            f"cannot publish immutable protocol-2.2 run inputs: {exc}"
        ) from exc


def load_protocol_22_inputs(
    paths: ReV2Paths,
    manifest: RunManifestV2,
) -> ValidatedProtocol22Inputs:
    """Authenticate all protocol-2.2 inputs before replay or execution."""
    if not isinstance(paths, ReV2Paths):
        raise Protocol22InputStoreError("paths must be ReV2Paths")
    if not isinstance(manifest, RunManifestV2):
        raise Protocol22InputStoreError("manifest must be RunManifestV2")
    canonical_paths = ReV2Paths.for_run(paths.root.parent)
    if paths != canonical_paths or manifest.run_id != paths.root.parent.name:
        raise Protocol22InputStoreError(
            "input paths do not match the protocol-2.2 manifest run"
        )
    try:
        authoritative = load_run_manifest(paths.root.parent)
    except ReV2RunStoreError as exc:
        raise Protocol22InputStoreError(
            f"cannot load authoritative manifest: {exc}"
        ) from exc
    if authoritative != manifest:
        raise Protocol22InputStoreError(
            "manifest argument does not equal the authoritative manifest"
        )
    if paths.inputs.is_symlink() or not paths.inputs.is_dir():
        raise Protocol22InputStoreError(
            f"protocol-2.2 input directory is unsafe or missing: {paths.inputs}"
        )
    if paths.objects.is_symlink() or not paths.objects.is_dir():
        raise Protocol22InputStoreError(
            f"protocol-2.2 object directory is unsafe or missing: {paths.objects}"
        )
    _validate_reference_layout(manifest)

    try:
        workspace_payload = _read_reference(
            paths.inputs, manifest.workspace_partition_catalog, "workspace partition"
        )
        workspace = load_canonical_object(
            workspace_payload, WorkspacePartitionCatalogV1.from_json_dict
        )
        policy_payload = _read_reference(
            paths.inputs, manifest.artifact_policy_catalog, "artifact policy"
        )
        policy = load_canonical_object(
            policy_payload, ArtifactPolicyCatalogV1.from_json_dict
        )
        executor_payload = _read_reference(
            paths.inputs, manifest.executor_contract_catalog, "executor contract"
        )
        executor = load_canonical_object(
            executor_payload, ExecutorContractCatalogV1.from_json_dict
        )
    except (
        Protocol22SchemaError,
        Protocol22PartitionError,
        Protocol22PolicyError,
        Protocol22ExecutorError,
    ) as exc:
        raise Protocol22InputStoreError(
            f"invalid immutable protocol-2.2 catalog: {exc}"
        ) from exc
    if workspace.snapshot_id != manifest.source_snapshot_id:
        raise Protocol22InputStoreError(
            "workspace partition snapshot does not match the run manifest"
        )

    roles = _referenced_object_roles(executor)
    objects: dict[str, bytes] = {}
    for object_hash, expected_roles in sorted(roles.items()):
        relative = _object_relative_path(object_hash)
        payload = _read_regular_beneath(
            paths.objects,
            relative,
            f"immutable object {object_hash}",
        )
        if content_digest(payload) != object_hash:
            raise Protocol22InputStoreError(
                f"immutable object hash mismatch: {object_hash}"
            )
        _validate_referenced_object(payload, expected_roles, object_hash)
        objects[object_hash] = payload
    return ValidatedProtocol22Inputs(
        workspace_partition=workspace,
        artifact_policy=policy,
        executor_contract=executor,
        immutable_objects=objects,
    )


def _prepare_inputs(
    manifest: RunManifestV2,
    inputs: Protocol22InputSet,
) -> _PreparedInputs:
    _validate_reference_layout(manifest)
    try:
        workspace_payload = canonical_json_bytes(
            inputs.workspace_partition.to_json_dict()
        )
        workspace = load_canonical_object(
            workspace_payload, WorkspacePartitionCatalogV1.from_json_dict
        )
        policy_payload = canonical_json_bytes(inputs.artifact_policy.to_json_dict())
        policy = load_canonical_object(
            policy_payload, ArtifactPolicyCatalogV1.from_json_dict
        )
        executor_payload, executor = _executor_catalog_payload(
            inputs.executor_contract
        )
    except (
        TypeError,
        ValueError,
        UnicodeError,
        Protocol22SchemaError,
        Protocol22PartitionError,
        Protocol22PolicyError,
        Protocol22ExecutorError,
    ) as exc:
        raise Protocol22InputStoreError(
            f"invalid protocol-2.2 immutable input: {exc}"
        ) from exc
    if workspace != inputs.workspace_partition or policy != inputs.artifact_policy:
        raise Protocol22InputStoreError(
            "typed protocol-2.2 catalogs do not round-trip canonically"
        )
    expected_catalogs = (
        (
            "workspace partition",
            manifest.workspace_partition_catalog,
            workspace_payload,
        ),
        ("artifact policy", manifest.artifact_policy_catalog, policy_payload),
        ("executor contract", manifest.executor_contract_catalog, executor_payload),
    )
    for name, reference, payload in expected_catalogs:
        if content_digest(payload) != reference.object_hash:
            raise Protocol22InputStoreError(f"{name} catalog hash mismatch")
    if workspace.snapshot_id != manifest.source_snapshot_id:
        raise Protocol22InputStoreError(
            "workspace partition snapshot does not match manifest source_snapshot_id"
        )
    roles = _referenced_object_roles(executor)
    supplied = set(inputs.immutable_objects)
    required = set(roles)
    if supplied != required:
        raise Protocol22InputStoreError(
            "immutable object set must exactly equal executor catalog references; "
            f"missing={sorted(required - supplied)}, extra={sorted(supplied - required)}"
        )
    for object_hash, expected_roles in roles.items():
        _validate_referenced_object(
            inputs.immutable_objects[object_hash], expected_roles, object_hash
        )
    return _PreparedInputs(
        workspace_payload=workspace_payload,
        artifact_policy_payload=policy_payload,
        executor_payload=executor_payload,
    )


def _executor_catalog_payload(
    value: object,
) -> tuple[bytes, ExecutorContractCatalogV1]:
    if not isinstance(value, ExecutorContractCatalogV1):
        raise Protocol22InputStoreError(
            "executor_contract must be ExecutorContractCatalogV1"
        )
    payload = canonical_json_bytes(value.to_json_dict())
    decoded = load_canonical_object(
        payload, ExecutorContractCatalogV1.from_json_dict
    )
    if decoded != value:
        raise Protocol22InputStoreError(
            "executor contract catalog does not round-trip canonically"
        )
    return payload, decoded


def _referenced_object_roles(
    executor: ExecutorContractCatalogV1,
) -> Mapping[str, frozenset[str]]:
    roles: dict[str, set[str]] = {}
    for entry in executor.entries:
        renderer = entry.request_renderer
        if renderer is None:
            continue
        agent_hash = renderer.agent_contract_hash
        roles.setdefault(agent_hash, set()).add("agent_contract")
        for schema in renderer.response_schemas:
            roles.setdefault(schema.schema_hash, set()).add("response_schema")
    return MappingProxyType(
        {key: frozenset(value) for key, value in sorted(roles.items())}
    )


def _validate_referenced_object(
    payload: bytes,
    roles: frozenset[str],
    object_hash: str,
) -> None:
    if content_digest(payload) != object_hash:
        raise Protocol22InputStoreError(
            f"immutable object hash mismatch: {object_hash}"
        )
    if payload.startswith(TREE_OBJECT_MAGIC):
        raise Protocol22InputStoreError(
            f"immutable input object is a tree, not a blob: {object_hash}"
        )
    if "agent_contract" in roles:
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise Protocol22InputStoreError(
                f"agent contract object must be UTF-8: {object_hash}"
            ) from exc
        if not text or "\x00" in text:
            raise Protocol22InputStoreError(
                f"agent contract object must be nonempty UTF-8 text: {object_hash}"
            )
    if "response_schema" in roles:
        try:
            load_canonical_object(payload, lambda value: value)
        except Protocol22SchemaError as exc:
            raise Protocol22InputStoreError(
                f"response schema object is not canonical JSON: {object_hash}: {exc}"
            ) from exc


def _validate_reference_layout(manifest: RunManifestV2) -> None:
    references = (
        manifest.workspace_partition_catalog,
        manifest.artifact_policy_catalog,
        manifest.executor_contract_catalog,
    )
    if any(not isinstance(reference, CatalogReferenceV1) for reference in references):
        raise Protocol22InputStoreError(
            "protocol-2.2 manifest has invalid catalog references"
        )
    paths = [PurePosixPath(reference.relative_path).parts for reference in references]
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            if (
                first == second
                or first == second[: len(first)]
                or second == first[: len(second)]
            ):
                raise Protocol22InputStoreError(
                    "protocol-2.2 catalog references alias or overlap"
                )


def _prepare_input_destination(
    inputs_root: Path,
    reference: CatalogReferenceV1,
) -> Path:
    parts = PurePosixPath(reference.relative_path).parts
    current = inputs_root
    for part in parts[:-1]:
        candidate = current / part
        if candidate.is_symlink():
            raise Protocol22InputStoreError(
                f"catalog input parent is symlinked: {candidate}"
            )
        if candidate.exists():
            if not candidate.is_dir():
                raise Protocol22InputStoreError(
                    f"catalog input parent is not a directory: {candidate}"
                )
        else:
            candidate.mkdir(mode=0o700)
            _fsync_directory(current)
        current = candidate
    destination = current / parts[-1]
    if destination.exists() or destination.is_symlink():
        raise Protocol22InputStoreError(
            f"immutable catalog input already exists: {destination}"
        )
    return destination


def _read_reference(
    root: Path,
    reference: CatalogReferenceV1,
    label: str,
) -> bytes:
    payload = _read_regular_beneath(root, reference.relative_path, label)
    if content_digest(payload) != reference.object_hash:
        raise Protocol22InputStoreError(f"{label} catalog hash mismatch")
    return payload


def _object_relative_path(object_hash: str) -> str:
    try:
        digest_value(object_hash, "immutable object hash")
    except Protocol22SchemaError as exc:
        raise Protocol22InputStoreError(str(exc)) from exc
    suffix = object_hash.removeprefix("sha256:")
    return f"sha256/{suffix[:2]}/{suffix[2:]}"


def _read_regular_beneath(root: Path, relative: str, label: str) -> bytes:
    if root.is_symlink() or not root.is_dir():
        raise Protocol22InputStoreError(f"{label} root is unsafe or missing")
    parts = PurePosixPath(relative).parts
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        current = os.open(root, directory_flags | nofollow)
        descriptors.append(current)
        for part in parts[:-1]:
            current = os.open(
                part,
                directory_flags | nofollow,
                dir_fd=current,
            )
            descriptors.append(current)
        descriptor = os.open(parts[-1], os.O_RDONLY | nofollow, dir_fd=current)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise Protocol22InputStoreError(f"{label} is not a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        hint = "symlink or unsafe path" if exc.errno in {40, 62} else "unsafe path"
        raise Protocol22InputStoreError(f"cannot read {label}: {hint}: {exc}") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mode,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mode,
        after.st_mtime_ns,
    ):
        raise Protocol22InputStoreError(f"{label} changed while read")
    return b"".join(chunks)


def _publish_manifest_last(
    paths: ReV2Paths,
    manifest: RunManifestV2,
    fault_hook: FaultHook | None,
) -> None:
    payload = canonical_json_bytes(manifest.to_json_dict())
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=".run.json.", suffix=".tmp", dir=paths.root
        )
        temporary = Path(name)
        try:
            _write_all(descriptor, payload)
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
            _fault(fault_hook, "manifest_temporary_fsynced")
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, paths.manifest, follow_symlinks=False)
        except FileExistsError as exc:
            raise Protocol22InputStoreError(
                f"immutable v2 run manifest already exists: {paths.manifest}"
            ) from exc
        _fault(fault_hook, "manifest_linked")
        temporary.unlink()
        temporary = None
        _fsync_directory(paths.root)
        _fault(fault_hook, "run_directory_fsynced")
        _fault(fault_hook, "manifest_published")
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _ensure_run_directory(run_dir: Path) -> None:
    if run_dir.is_symlink():
        raise Protocol22InputStoreError(
            f"unsafe symlinked RE run directory: {run_dir}"
        )
    if run_dir.exists():
        if not run_dir.is_dir():
            raise Protocol22InputStoreError(
                f"RE run path is not a directory: {run_dir}"
            )
        return
    try:
        run_dir.mkdir(parents=True, mode=0o700)
        _fsync_directory(run_dir.parent.resolve())
    except OSError as exc:
        raise Protocol22InputStoreError(
            f"cannot create RE run directory {run_dir}: {exc}"
        ) from exc


def _write_new_file(path: Path, payload: bytes, *, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, mode)
    try:
        _write_all(descriptor, payload)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short write while persisting protocol-2.2 input")
        offset += written


def _fsync_tree_directories(root: Path) -> None:
    directories = [path for path in root.rglob("*") if path.is_dir()]
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        if directory.is_symlink():
            raise Protocol22InputStoreError(
                f"protocol-2.2 input directory is symlinked: {directory}"
            )
        _fsync_directory(directory)
    _fsync_directory(root)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fault(fault_hook: FaultHook | None, point: str) -> None:
    if fault_hook is not None:
        fault_hook(point)


__all__ = (
    "Protocol22InputSet",
    "Protocol22InputStoreError",
    "ValidatedProtocol22Inputs",
    "create_protocol_22_run_store",
    "load_protocol_22_inputs",
)

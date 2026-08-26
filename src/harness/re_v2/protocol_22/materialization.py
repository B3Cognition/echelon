"""Disposable, run-local projections of accepted protocol-2.2 L1 artifacts."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import stat
from typing import Callable, Iterator, Literal

from harness.re_v2.canonical import content_digest
from harness.re_v2.run_store import ReV2Paths

from .artifacts import SourceBaselineRootV1
from .baseline import CompactBaselineArtifactV1, render_baseline_markdown
from .model import ArtifactKeyV2
from .partition import WorkspacePartitionCatalogV1
from .recovery import Protocol22RunContext
from .schema import Protocol22SchemaError, load_canonical_object


FaultHook = Callable[[str], None]
ProjectionKind = Literal["domain-baseline", "source-overview", "source-baseline-root"]

_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY_FLAGS = os.O_RDONLY | _DIRECTORY | _CLOEXEC | _NOFOLLOW
_PROJECTION_KINDS = frozenset(
    {"domain-baseline", "source-overview", "source-baseline-root"}
)
_PROJECTION_LAYERS = frozenset({"L1", "L2"})
_KIND_ORDER = {
    "domain-baseline": 0,
    "source-overview": 1,
    "source-baseline-root": 2,
}


class Protocol22MaterializationError(RuntimeError):
    """Raised when a projection cannot be verified, quarantined, or rebuilt."""


@dataclass(frozen=True, slots=True)
class MaterializedProjectionV1:
    artifact_kind: ProjectionKind
    artifact_hash: str
    artifact_key_id: str
    path: Path


@dataclass(frozen=True, slots=True)
class MaterializationReportV1:
    projections: tuple[MaterializedProjectionV1, ...]
    reused_count: int
    rebuilt_count: int
    quarantine_paths: tuple[Path, ...]

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(item.path for item in self.projections)

    @property
    def hashes(self) -> tuple[str, ...]:
        return tuple(item.artifact_hash for item in self.projections)

    @property
    def quarantined_count(self) -> int:
        return len(self.quarantine_paths)


@dataclass(frozen=True, slots=True)
class _ProjectionSpec:
    projection: MaterializedProjectionV1
    relative_parts: tuple[str, ...]
    payloads: tuple[tuple[str, bytes], ...]
    directory: bool | None = None

    @property
    def is_directory(self) -> bool:
        return (
            self.projection.artifact_kind != "source-baseline-root"
            if self.directory is None
            else self.directory
        )


def materialize_accepted_l1(
    context: Protocol22RunContext,
    fault_hook: FaultHook | None = None,
) -> MaterializationReportV1:
    """Verify or create every accepted L1 projection from object authority."""
    return _validate_or_materialize(context, fault_hook, frozenset({"L1"}))


def materialize_accepted_l2(
    context: Protocol22RunContext,
    fault_hook: FaultHook | None = None,
) -> MaterializationReportV1:
    """Verify or create every accepted L2 projection from object authority."""
    return _validate_or_materialize(context, fault_hook, frozenset({"L2"}))


def validate_or_repair_materialization(
    context: Protocol22RunContext,
    fault_hook: FaultHook | None = None,
    *,
    layers: frozenset[str] = frozenset({"L1"}),
) -> MaterializationReportV1:
    """Quarantine altered safe projections and rebuild exact accepted bytes."""
    return _validate_or_materialize(context, fault_hook, layers)


def materialized_path_for(
    paths: ReV2Paths,
    partition: WorkspacePartitionCatalogV1,
    artifact_key: ArtifactKeyV2,
    artifact_hash: str,
) -> Path:
    """Return the closed run-local path for one accepted layered projection."""
    if not isinstance(paths, ReV2Paths):
        raise Protocol22MaterializationError("materialized path requires ReV2Paths")
    if not isinstance(partition, WorkspacePartitionCatalogV1):
        raise Protocol22MaterializationError(
            "materialized path requires workspace partition authority"
        )
    if not isinstance(artifact_key, ArtifactKeyV2):
        raise Protocol22MaterializationError("materialized path requires ArtifactKeyV2")
    kind = artifact_key.artifact_kind
    if kind not in _PROJECTION_KINDS or artifact_key.layer not in _PROJECTION_LAYERS:
        raise Protocol22MaterializationError(
            "only accepted protocol-2.2/2.4 L1/L2 artifacts are materialized"
        )
    suffix = _digest_hex(artifact_hash)
    source_id = _path_component(artifact_key.scope.source_id, "source ID")
    root = paths.root / "materialized" / artifact_key.layer / "sources" / source_id
    if kind == "source-overview":
        return root / "overview" / suffix
    if kind == "source-baseline-root":
        return root / "root" / f"{suffix}.json"
    domain_key = artifact_key.scope.domain_key
    if domain_key is None:
        raise Protocol22MaterializationError(
            "domain baseline has no immutable domain key"
        )
    source = next(
        (item for item in partition.sources if item.source_id == source_id),
        None,
    )
    if source is None:
        raise Protocol22MaterializationError(
            f"materialized source is absent from partition: {source_id}"
        )
    domains = tuple(item for item in source.domains if item.domain_key == domain_key)
    if len(domains) != 1:
        raise Protocol22MaterializationError(
            "materialized domain does not resolve exactly once"
        )
    presentation = _path_component(
        domains[0].presentation_domain_id,
        "presentation domain ID",
    )
    return root / "domains" / presentation / suffix


def _validate_or_materialize(
    context: Protocol22RunContext,
    fault_hook: FaultHook | None,
    layers: frozenset[str],
) -> MaterializationReportV1:
    if not isinstance(context, Protocol22RunContext):
        raise Protocol22MaterializationError(
            "materialization requires Protocol22RunContext"
        )
    if fault_hook is not None and not callable(fault_hook):
        raise Protocol22MaterializationError(
            "materialization fault hook must be callable or null"
        )
    if not isinstance(layers, frozenset) or not layers or not layers <= _PROJECTION_LAYERS:
        raise Protocol22MaterializationError(
            "materialization layers must be a nonempty registered frozenset"
        )
    specs = _accepted_projection_specs(context, layers)
    reused = 0
    rebuilt = 0
    quarantined: list[Path] = []
    with _materialization_lock(context.paths) as run_fd:
        for spec in specs:
            parent_fd = _open_or_create_parents(run_fd, spec.relative_parts[:-1])
            try:
                name = spec.relative_parts[-1]
                if not spec.is_directory:
                    staging_name = f".{name}.staging"
                    staging_state = _root_staging_state(
                        parent_fd,
                        name,
                        staging_name,
                        spec.payloads[0][1],
                    )
                    if staging_state == "altered":
                        quarantined_path = _quarantine_entry(
                            context,
                            run_fd,
                            parent_fd,
                            staging_name,
                            spec.projection.artifact_hash,
                        )
                        quarantined.append(quarantined_path)
                        _fault(
                            fault_hook,
                            "materialization_quarantined:"
                            + spec.projection.artifact_hash,
                        )
                state = _projection_state(parent_fd, name, spec)
                if state == "exact":
                    reused += 1
                    continue
                if state == "altered":
                    quarantined_path = _quarantine_entry(
                        context,
                        run_fd,
                        parent_fd,
                        name,
                        spec.projection.artifact_hash,
                    )
                    quarantined.append(quarantined_path)
                    _fault(
                        fault_hook,
                        "materialization_quarantined:" + spec.projection.artifact_hash,
                    )
                _publish_projection(parent_fd, name, spec, fault_hook)
                rebuilt += 1
            finally:
                os.close(parent_fd)
        os.fsync(run_fd)
    return MaterializationReportV1(
        projections=tuple(spec.projection for spec in specs),
        reused_count=reused,
        rebuilt_count=rebuilt,
        quarantine_paths=tuple(quarantined),
    )


def _accepted_projection_specs(
    context: Protocol22RunContext,
    layers: frozenset[str],
) -> tuple[_ProjectionSpec, ...]:
    ledger = context.ledger.replay()
    specs: list[_ProjectionSpec] = []
    for receipt in ledger.accepted_artifacts.values():
        key = receipt.artifact_key
        if key.artifact_kind not in _PROJECTION_KINDS or key.layer not in layers:
            continue
        work_item = ledger.certification_work_items.get(
            receipt.certification_receipt_id
        )
        if work_item is None or work_item.output_key != key:
            raise Protocol22MaterializationError(
                "accepted projection lacks exact work-item authority"
            )
        try:
            payload = context.object_store.read_blob(receipt.artifact_hash)
        except Exception as exc:
            raise Protocol22MaterializationError(
                "accepted projection object is missing or corrupt"
            ) from exc
        _validate_projection_payload(key, payload)
        path = materialized_path_for(
            context.paths,
            context.inputs.workspace_partition,
            key,
            receipt.artifact_hash,
        )
        try:
            relative = path.relative_to(context.paths.root)
        except ValueError as exc:  # pragma: no cover - construction above is closed
            raise Protocol22MaterializationError(
                "materialized projection escaped the run store"
            ) from exc
        parts = tuple(
            _path_component(part, "materialization path component")
            for part in relative.parts
        )
        projection = MaterializedProjectionV1(
            artifact_kind=key.artifact_kind,  # type: ignore[arg-type]
            artifact_hash=receipt.artifact_hash,
            artifact_key_id=key.identity,
            path=path,
        )
        if key.artifact_kind == "source-baseline-root":
            projection_payloads = ((path.name, payload),)
        else:
            markdown = (
                render_baseline_markdown(payload)
                if key.layer == "L1"
                else _render_l2_baseline_markdown(payload)
            )
            projection_payloads = (
                ("baseline.json", payload),
                ("baseline.md", markdown),
            )
        specs.append(_ProjectionSpec(projection, parts, projection_payloads))
    return tuple(
        sorted(
            specs,
            key=lambda value: (
                value.projection.path.parts,
                _KIND_ORDER[value.projection.artifact_kind],
                value.projection.artifact_hash,
            ),
        )
    )


def _validate_projection_payload(key: ArtifactKeyV2, payload: bytes) -> None:
    try:
        if key.layer == "L2":
            from harness.re_v2.protocol_24.artifacts import (
                L2CompactBaselineArtifactV1,
                L2SourceBaselineRootV1,
            )

            value = load_canonical_object(
                payload,
                (
                    L2SourceBaselineRootV1.from_json_dict
                    if key.artifact_kind == "source-baseline-root"
                    else L2CompactBaselineArtifactV1.from_json_dict
                ),
            )
        elif key.artifact_kind == "source-baseline-root":
            value = load_canonical_object(payload, SourceBaselineRootV1.from_json_dict)
        else:
            value = load_canonical_object(
                payload,
                CompactBaselineArtifactV1.from_json_dict,
            )
        envelope = value.artifact
    except (Protocol22SchemaError, ValueError) as exc:
        raise Protocol22MaterializationError(
            "accepted projection object violates its canonical schema"
        ) from exc
    expected = (
        key.artifact_kind,
        key.layer,
        key.scope,
        key.partition_id,
        key.layer_policy_hash,
        key.dependency_hashes,
    )
    observed = (
        envelope.artifact_kind,
        envelope.layer,
        envelope.scope,
        envelope.partition_id,
        envelope.layer_policy_hash,
        envelope.dependency_hashes,
    )
    if observed != expected:
        raise Protocol22MaterializationError(
            "accepted projection envelope differs from artifact-key authority"
        )


def _render_l2_baseline_markdown(payload: bytes) -> bytes:
    from harness.re_v2.protocol_24.artifacts import render_l2_baseline_markdown

    return render_l2_baseline_markdown(payload)


@contextmanager
def _materialization_lock(paths: ReV2Paths) -> Iterator[int]:
    if not _NOFOLLOW or os.mkdir not in os.supports_dir_fd:
        raise Protocol22MaterializationError(
            "materialization requires directory-relative no-follow operations"
        )
    run_fd = _open_directory_path_nofollow(paths.root, "v2 run root")
    lock_fd: int | None = None
    try:
        flags = os.O_RDWR | os.O_CREAT | _CLOEXEC | _NOFOLLOW
        lock_fd = os.open(".materialization.lock", flags, 0o600, dir_fd=run_fd)
        metadata = os.fstat(lock_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise Protocol22MaterializationError(
                "materialization lock is not a regular file"
            )
        os.fchmod(lock_fd, 0o600)
        _retry_eintr(fcntl.flock, lock_fd, fcntl.LOCK_EX)
        yield run_fd
    except Protocol22MaterializationError:
        raise
    except OSError as exc:
        raise Protocol22MaterializationError(
            f"cannot lock materialization: {exc}"
        ) from exc
    finally:
        if lock_fd is not None:
            try:
                _retry_eintr(fcntl.flock, lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(run_fd)


def _open_or_create_parents(root_fd: int, parts: tuple[str, ...]) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o700, dir_fd=current)
                os.fsync(current)
            except FileExistsError:
                pass
            try:
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            except OSError as exc:
                raise Protocol22MaterializationError(
                    f"unsafe materialization parent {part}: {exc}"
                ) from exc
            metadata = os.fstat(next_fd)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(next_fd)
                raise Protocol22MaterializationError(
                    f"materialization parent is not a directory: {part}"
                )
            os.fchmod(next_fd, 0o700)
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


def _projection_state(
    parent_fd: int,
    name: str,
    spec: _ProjectionSpec,
) -> Literal["missing", "exact", "altered"]:
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        raise Protocol22MaterializationError(
            f"cannot inspect materialized projection: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise Protocol22MaterializationError(
            "materialized projection contains an unsafe symlink"
        )
    expected_directory = spec.is_directory
    if expected_directory and stat.S_ISDIR(metadata.st_mode):
        return _directory_projection_state(parent_fd, name, spec)
    if not expected_directory and stat.S_ISREG(metadata.st_mode):
        expected = spec.payloads[0][1]
        _finish_linked_root(parent_fd, name)
        return (
            "exact"
            if _regular_file_matches(parent_fd, name, expected, 0o400)
            else "altered"
        )
    if stat.S_ISREG(metadata.st_mode):
        _assert_safe_regular(metadata, "materialized projection")
        return "altered"
    if stat.S_ISDIR(metadata.st_mode):
        child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        try:
            _assert_safe_tree(child_fd)
        finally:
            os.close(child_fd)
        return "altered"
    raise Protocol22MaterializationError(
        "materialized projection is an unsafe special file"
    )


def _root_staging_state(
    parent_fd: int,
    target_name: str,
    name: str,
    expected: bytes,
) -> Literal["missing", "exact", "altered"]:
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        raise Protocol22MaterializationError(
            f"cannot inspect root materialization staging: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise Protocol22MaterializationError(
            "root materialization staging is an unsafe symlink"
        )
    if stat.S_ISREG(metadata.st_mode):
        try:
            target_metadata = os.stat(
                target_name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            target_metadata = None
        if target_metadata is not None:
            if stat.S_ISLNK(target_metadata.st_mode) or not (
                stat.S_ISREG(target_metadata.st_mode)
                or stat.S_ISDIR(target_metadata.st_mode)
            ):
                raise Protocol22MaterializationError(
                    "materialized root is an unsafe symlink or special file"
                )
            if stat.S_ISREG(target_metadata.st_mode) and (
                target_metadata.st_dev,
                target_metadata.st_ino,
            ) == (metadata.st_dev, metadata.st_ino):
                _finish_linked_root(parent_fd, target_name)
                return "missing"
            _assert_safe_regular(metadata, "root materialization staging")
            return "altered"
        _assert_safe_regular(metadata, "root materialization staging")
        return (
            "exact"
            if _regular_file_matches(parent_fd, name, expected, 0o400)
            else "altered"
        )
    if stat.S_ISDIR(metadata.st_mode):
        directory_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        try:
            _assert_safe_tree(directory_fd)
        finally:
            os.close(directory_fd)
        return "altered"
    raise Protocol22MaterializationError(
        "root materialization staging is an unsafe special file"
    )


def _directory_projection_state(
    parent_fd: int,
    name: str,
    spec: _ProjectionSpec,
) -> Literal["exact", "altered"]:
    directory_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    try:
        metadata = os.fstat(directory_fd)
        names = tuple(sorted(os.listdir(directory_fd)))
        expected = dict(spec.payloads)
        altered_type = False
        for child in names:
            child_metadata = os.stat(
                child,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            if stat.S_ISLNK(child_metadata.st_mode):
                raise Protocol22MaterializationError(
                    "materialized projection contains an unsafe symlink"
                )
            if stat.S_ISDIR(child_metadata.st_mode):
                child_fd = os.open(child, _DIRECTORY_FLAGS, dir_fd=directory_fd)
                try:
                    _assert_safe_tree(child_fd)
                finally:
                    os.close(child_fd)
                altered_type = True
                continue
            if not stat.S_ISREG(child_metadata.st_mode):
                raise Protocol22MaterializationError(
                    "materialized projection contains an unsafe special entry"
                )
            _assert_safe_regular(child_metadata, "materialized projection entry")
        if (
            names != tuple(sorted(expected))
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or altered_type
        ):
            return "altered"
        if any(
            not _regular_file_matches(directory_fd, child, payload, 0o400)
            for child, payload in spec.payloads
        ):
            return "altered"
        return "exact"
    except Protocol22MaterializationError:
        raise
    except OSError as exc:
        raise Protocol22MaterializationError(
            f"cannot validate materialized directory: {exc}"
        ) from exc
    finally:
        os.close(directory_fd)


def _regular_file_matches(
    parent_fd: int,
    name: str,
    expected: bytes,
    expected_mode: int,
) -> bool:
    flags = os.O_RDONLY | _CLOEXEC | _NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise Protocol22MaterializationError(
            f"cannot open materialized regular file: {exc}"
        ) from exc
    try:
        before = os.fstat(fd)
        _assert_safe_regular(before, "materialized projection entry")
        payload = _read_bounded(fd, len(expected) + 1)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise Protocol22MaterializationError(
                "materialized projection identity changed while reading"
            )
        return (
            stat.S_IMODE(after.st_mode) == expected_mode
            and after.st_size == len(expected)
            and payload == expected
            and content_digest(payload) == content_digest(expected)
        )
    finally:
        os.close(fd)


def _finish_linked_root(parent_fd: int, name: str) -> None:
    temporary = f".{name}.staging"
    try:
        staging_metadata = os.stat(
            temporary,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    target_fd: int | None = None
    staging_fd: int | None = None
    try:
        target_fd = os.open(
            name,
            os.O_RDONLY | _CLOEXEC | _NOFOLLOW,
            dir_fd=parent_fd,
        )
        staging_fd = os.open(
            temporary,
            os.O_RDONLY | _CLOEXEC | _NOFOLLOW,
            dir_fd=parent_fd,
        )
        target_metadata = os.fstat(target_fd)
        reopened_staging = os.fstat(staging_fd)
        if (
            not stat.S_ISREG(staging_metadata.st_mode)
            or not stat.S_ISREG(target_metadata.st_mode)
            or (target_metadata.st_dev, target_metadata.st_ino)
            != (reopened_staging.st_dev, reopened_staging.st_ino)
            or target_metadata.st_nlink != 2
        ):
            raise Protocol22MaterializationError(
                "root staging link is not an exact recoverable commit"
            )
        os.unlink(temporary, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except Protocol22MaterializationError:
        raise
    except OSError as exc:
        raise Protocol22MaterializationError(
            f"cannot finish root staging commit: {exc}"
        ) from exc
    finally:
        if staging_fd is not None:
            os.close(staging_fd)
        if target_fd is not None:
            os.close(target_fd)


def _assert_safe_regular(metadata: os.stat_result, label: str) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise Protocol22MaterializationError(f"{label} is not regular")
    if metadata.st_nlink != 1:
        raise Protocol22MaterializationError(f"{label} is an unsafe hard link")


def _assert_safe_tree(directory_fd: int) -> None:
    for name in os.listdir(directory_fd):
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(metadata.st_mode):
            raise Protocol22MaterializationError(
                "materialized projection contains an unsafe symlink"
            )
        if stat.S_ISREG(metadata.st_mode):
            _assert_safe_regular(metadata, "materialized projection entry")
            continue
        if stat.S_ISDIR(metadata.st_mode):
            child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory_fd)
            try:
                _assert_safe_tree(child_fd)
            finally:
                os.close(child_fd)
            continue
        raise Protocol22MaterializationError(
            "materialized projection contains an unsafe special entry"
        )


def _quarantine_entry(
    context: Protocol22RunContext,
    run_fd: int,
    source_parent_fd: int,
    source_name: str,
    artifact_hash: str,
) -> Path:
    quarantine_fd = _open_or_create_parents(
        run_fd,
        ("quarantine", "materialized"),
    )
    try:
        try:
            source_metadata = os.stat(
                source_name,
                dir_fd=source_parent_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise Protocol22MaterializationError(
                f"cannot reopen altered materialization for quarantine: {exc}"
            ) from exc
        if stat.S_ISLNK(source_metadata.st_mode) or not (
            stat.S_ISREG(source_metadata.st_mode)
            or stat.S_ISDIR(source_metadata.st_mode)
        ):
            raise Protocol22MaterializationError(
                "altered materialization became an unsafe symlink or special entry"
            )
        prefix = f"{_digest_hex(artifact_hash)}-"
        index = 1
        while True:
            destination = f"{prefix}{index:06d}"
            try:
                os.stat(
                    destination,
                    dir_fd=quarantine_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                break
            index += 1
            if index > 999_999:
                raise Protocol22MaterializationError(
                    "materialization quarantine namespace is exhausted"
                )
        try:
            os.rename(
                source_name,
                destination,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=quarantine_fd,
            )
            os.fsync(source_parent_fd)
            os.fsync(quarantine_fd)
            quarantined_metadata = os.stat(
                destination,
                dir_fd=quarantine_fd,
                follow_symlinks=False,
            )
            if (
                quarantined_metadata.st_dev,
                quarantined_metadata.st_ino,
            ) != (source_metadata.st_dev, source_metadata.st_ino):
                raise Protocol22MaterializationError(
                    "quarantined materialization identity changed during move"
                )
        except OSError as exc:
            raise Protocol22MaterializationError(
                f"cannot quarantine altered materialization: {exc}"
            ) from exc
        return context.paths.root / "quarantine" / "materialized" / destination
    finally:
        os.close(quarantine_fd)


def _publish_projection(
    parent_fd: int,
    name: str,
    spec: _ProjectionSpec,
    fault_hook: FaultHook | None,
) -> None:
    if spec.is_directory:
        _publish_directory_projection(parent_fd, name, spec, fault_hook)
    else:
        _publish_regular_noclobber(
            parent_fd,
            name,
            spec.payloads[0][1],
            spec.projection.artifact_hash,
            fault_hook,
        )
    _fault(fault_hook, "materialization_published:" + spec.projection.artifact_hash)


def _publish_directory_projection(
    parent_fd: int,
    name: str,
    spec: _ProjectionSpec,
    fault_hook: FaultHook | None,
) -> None:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError as exc:
        raise Protocol22MaterializationError(
            "materialization target appeared during no-clobber publication"
        ) from exc
    except OSError as exc:
        raise Protocol22MaterializationError(
            f"cannot create materialization directory: {exc}"
        ) from exc
    directory_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    try:
        for child, payload in spec.payloads:
            _write_new_regular(directory_fd, child, payload)
            boundary = (
                "materialization_json_fsynced:"
                if child == "baseline.json"
                else "materialization_markdown_fsynced:"
            )
            _fault(fault_hook, boundary + spec.projection.artifact_hash)
        os.fchmod(directory_fd, 0o700)
        os.fsync(directory_fd)
        os.fsync(parent_fd)
    except Protocol22MaterializationError:
        raise
    except OSError as exc:
        raise Protocol22MaterializationError(
            f"cannot publish materialization directory: {exc}"
        ) from exc
    finally:
        os.close(directory_fd)


def _publish_regular_noclobber(
    parent_fd: int,
    name: str,
    payload: bytes,
    artifact_hash: str,
    fault_hook: FaultHook | None,
) -> None:
    temporary = f".{name}.staging"
    try:
        try:
            os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            _write_new_regular(parent_fd, temporary, payload)
            _fault(fault_hook, "materialization_json_fsynced:" + artifact_hash)
        else:
            if not _regular_file_matches(parent_fd, temporary, payload, 0o400):
                raise Protocol22MaterializationError(
                    "incomplete root staging bytes are altered"
                )
        try:
            os.link(
                temporary,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise Protocol22MaterializationError(
                "materialization target appeared during no-clobber publication"
            ) from exc
        os.fsync(parent_fd)
        _fault(fault_hook, "materialization_root_linked:" + artifact_hash)
        os.unlink(temporary, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except Protocol22MaterializationError:
        raise
    except OSError as exc:
        raise Protocol22MaterializationError(
            f"cannot publish root materialization: {exc}"
        ) from exc


def _write_new_regular(parent_fd: int, name: str, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _CLOEXEC | _NOFOLLOW
    try:
        fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
    except OSError as exc:
        raise Protocol22MaterializationError(
            f"cannot create materialized file {name}: {exc}"
        ) from exc
    try:
        os.fchmod(fd, 0o400)
        _write_all(fd, payload)
        os.fsync(fd)
    except OSError as exc:
        raise Protocol22MaterializationError(
            f"cannot write materialized file {name}: {exc}"
        ) from exc
    finally:
        os.close(fd)


def _open_directory_path_nofollow(path: Path, label: str) -> int:
    absolute = path.absolute()
    if not absolute.is_absolute() or any(
        part in {"", ".", ".."} for part in absolute.parts[1:]
    ):
        raise Protocol22MaterializationError(f"unsafe {label}: {path}")
    current = os.open("/", _DIRECTORY_FLAGS)
    try:
        for part in absolute.parts[1:]:
            next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            os.close(current)
            current = next_fd
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            raise Protocol22MaterializationError(f"{label} is not a directory")
        return current
    except Exception:
        os.close(current)
        raise


def _read_bounded(fd: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit
    while remaining > 0:
        chunk = os.read(fd, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:  # pragma: no cover - defensive kernel contract
            raise OSError("zero-length materialization write")
        view = view[written:]


def _retry_eintr(function, *args):  # type: ignore[no-untyped-def]
    while True:
        try:
            return function(*args)
        except InterruptedError:
            continue


def _digest_hex(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise Protocol22MaterializationError(
            "materialization artifact hash is not lowercase sha256"
        )
    return value[7:]


def _path_component(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise Protocol22MaterializationError(f"unsafe {label}")
    return value


def _fault(fault_hook: FaultHook | None, boundary: str) -> None:
    if fault_hook is not None:
        fault_hook(boundary)


__all__ = (
    "MaterializationReportV1",
    "MaterializedProjectionV1",
    "Protocol22MaterializationError",
    "materialize_accepted_l1",
    "materialize_accepted_l2",
    "materialized_path_for",
    "validate_or_repair_materialization",
)

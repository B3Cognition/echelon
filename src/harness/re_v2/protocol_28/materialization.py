"""Deterministic run-local projections of accepted protocol-2.8 authority."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Callable, ClassVar, Iterator

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_28.artifacts import ExhaustiveEvidenceSliceV1
from harness.re_v2.protocol_28.context import (
    Protocol28ClosureRunContext,
    Protocol28Context,
    Protocol28RunContext,
)
from harness.re_v2.protocol_28.events import replay_protocol_28
from harness.re_v2.protocol_28.graph import (
    L4FindingClosureReceiptV1,
    L4RunRootV1,
    L4SemanticClosureRootV1,
    L4SourceRootV1,
    L4TargetRootV1,
)


class Protocol28MaterializationError(RuntimeError):
    """Raised when an L4 projection cannot be rebuilt safely and exactly."""


@dataclass(frozen=True, slots=True)
class L4MaterializationEntryV1:
    relative_path: str
    content_hash: str
    authority_id: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise Protocol28MaterializationError(
                "L4 materialization path is unsafe"
            )
        for value in (self.content_hash, self.authority_id):
            if not isinstance(value, str) or not value.startswith("sha256:"):
                raise Protocol28MaterializationError(
                    "L4 materialization identity is invalid"
                )

    def to_json_dict(self) -> dict[str, str]:
        return {
            "authority_id": self.authority_id,
            "content_hash": self.content_hash,
            "relative_path": self.relative_path,
        }


@dataclass(frozen=True, slots=True)
class L4MaterializationManifestV1:
    schema_version: int
    run_id: str
    run_mode: str
    root_id: str
    entries: tuple[L4MaterializationEntryV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "run_id",
        "run_mode",
        "root_id",
        "entries",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise Protocol28MaterializationError(
                "L4 materialization schema must be 1"
            )
        entries = tuple(self.entries)
        paths = tuple(item.relative_path for item in entries)
        if paths != tuple(sorted(set(paths))):
            raise Protocol28MaterializationError(
                "L4 materialization entries must be sorted and unique"
            )
        object.__setattr__(self, "entries", entries)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "run_mode": self.run_mode,
            "root_id": self.root_id,
            "entries": [item.to_json_dict() for item in self.entries],
        }


def materialize_l4_closure(
    context: Protocol28Context,
    fault_hook: Callable[[str], None] | None = None,
) -> L4MaterializationManifestV1:
    return _validate_or_materialize(context, fault_hook)


def validate_or_repair_l4_materialization(
    context: Protocol28Context,
    fault_hook: Callable[[str], None] | None = None,
) -> L4MaterializationManifestV1:
    return _validate_or_materialize(context, fault_hook)


def _validate_or_materialize(
    context: Protocol28Context,
    fault_hook: Callable[[str], None] | None,
) -> L4MaterializationManifestV1:
    if not isinstance(context, (Protocol28RunContext, Protocol28ClosureRunContext)):
        raise Protocol28MaterializationError(
            "materialization requires a protocol-2.8 context"
        )
    if fault_hook is not None and not callable(fault_hook):
        raise Protocol28MaterializationError(
            "materialization fault hook must be callable or null"
        )
    state = replay_protocol_28(context.events.replay())
    root_id = state.closure_root_id or state.run_root_id
    if root_id is None:
        raise Protocol28MaterializationError(
            "materialization requires a durable L4 root"
        )
    payloads = _projection_payloads(context, state)
    entries = tuple(
        L4MaterializationEntryV1(path, content_digest(payload), authority_id)
        for path, payload, authority_id in payloads
    )
    manifest = L4MaterializationManifestV1(
        1,
        context.inputs.manifest.run_id,
        context.inputs.manifest.run_mode,
        root_id,
        entries,
    )
    manifest_bytes = canonical_json_bytes(manifest.to_json_dict())
    if context.objects.put_blob(manifest_bytes) != manifest.identity:
        raise Protocol28MaterializationError(
            "materialization manifest identity changed"
        )
    expected = {path: payload for path, payload, _authority in payloads}
    expected["materialization.json"] = manifest_bytes
    with _materialization_lock(context.run_dir):
        root = _open_materialization_directory(context.run_dir)
        _repair_unexpected(context, root, set(expected))
        for relative, payload in sorted(expected.items()):
            if relative == "materialization.json":
                continue
            _publish_exact(context, root, relative, payload)
        if fault_hook is not None:
            fault_hook("before_manifest_publish")
        _publish_exact(context, root, "materialization.json", manifest_bytes)
        _validate_exact_file_set(root, expected)
    context.controller.record_materialization(root_id)
    return manifest


def _projection_payloads(
    context: Protocol28Context,
    state: object,
) -> tuple[tuple[str, bytes, str], ...]:
    values: list[tuple[str, bytes, str]] = []
    if isinstance(context, Protocol28RunContext):
        ledger = context.ledger.replay()
        for relative, value in (
            ("catalogs/l3-target-projections.json", context.inputs.l3_projection_catalog),
            ("catalogs/snapshot-evidence.json", context.inputs.snapshot_evidence_catalog),
            ("catalogs/exhaustive-subjects.json", context.inputs.exhaustive_subject_catalog),
            ("catalogs/exhaustive-policy.json", context.inputs.exhaustive_policy),
            ("plans/exhaustive-plan.json", context.inputs.exhaustive_plan),
        ):
            values.append((relative, _bytes(value), value.identity))
        accepted = tuple(
            sorted(
                ledger.accepted_slices.values(),
                key=lambda item: item.output_artifact_key_id,
            )
        )
        for item in accepted:
            candidate_bytes = context.objects.read_blob(item.candidate_hash)
            candidate = load_canonical_object(
                candidate_bytes, ExhaustiveEvidenceSliceV1.from_json_dict
            )
            suffix = item.output_artifact_key_id.removeprefix("sha256:")
            values.extend(
                (
                    (f"slices/{suffix}.json", candidate_bytes, item.candidate_hash),
                    (
                        f"slices/{suffix}.md",
                        _markdown_bytes(candidate.rendered_markdown),
                        item.candidate_hash,
                    ),
                )
            )
            accepted_bytes = _bytes(item)
            values.append(
                (
                    f"acceptance/{suffix}.json",
                    accepted_bytes,
                    item.identity,
                )
            )
            verification_bytes = context.objects.read_blob(
                item.verifier_result_hash
            )
            values.append(
                (
                    f"verification/{suffix}.json",
                    verification_bytes,
                    item.verifier_result_hash,
                )
            )
        accepted_catalog = canonical_json_bytes(
            {
                "schema_version": 1,
                "accepted_slices": [item.to_json_dict() for item in accepted],
            }
        )
        values.append(
            (
                "coverage/accepted-slices.json",
                accepted_catalog,
                content_digest(accepted_catalog),
            )
        )
        for target in context.inputs.exhaustive_plan.target_plans:
            suffix = target.target_id.removeprefix("sha256:")
            coverage_bytes = _bytes(target.coverage_ledger)
            values.append(
                (
                    f"coverage/{target.source_id}--{target.target_kind}--{suffix}.json",
                    coverage_bytes,
                    target.coverage_ledger.identity,
                )
            )
        for root_id in sorted(state.target_root_ids):
            root = _load(context, root_id, L4TargetRootV1)
            suffix = root.target_id.removeprefix("sha256:")
            path = f"targets/{root.source_id}--{root.target_kind}--{suffix}.json"
            values.append((path, _bytes(root), root.identity))
        for root_id in sorted(state.source_root_ids):
            root = _load(context, root_id, L4SourceRootV1)
            values.append((f"sources/{root.source_id}.json", _bytes(root), root.identity))
        run_root = _load(context, state.run_root_id, L4RunRootV1)
        values.append(("roots/run.json", _bytes(run_root), run_root.identity))
    else:
        for relative, value in (
            ("closure/parent.json", context.inputs.closure_parent_bundle),
            ("closure/request.json", context.inputs.manifest.closure_request),
        ):
            values.append((relative, _bytes(value), value.identity))
        for item in context.inputs.accepted_slices:
            suffix = item.output_artifact_key_id.removeprefix("sha256:")
            values.append(
                (f"slices/{suffix}.accepted.json", _bytes(item), item.identity)
            )
        for root in context.inputs.target_roots:
            suffix = root.target_id.removeprefix("sha256:")
            path = f"targets/{root.source_id}--{root.target_kind}--{suffix}.json"
            values.append((path, _bytes(root), root.identity))
        values.append(
            (
                "roots/run.json",
                _bytes(context.inputs.l4_run_root),
                context.inputs.l4_run_root.identity,
            )
        )
        closure = _load(context, state.closure_root_id, L4SemanticClosureRootV1)
        values.append(("roots/closure.json", _bytes(closure), closure.identity))
        verification_catalog = canonical_json_bytes(
            {
                "schema_version": 1,
                "verification_receipts": [
                    item.to_json_dict()
                    for item in context.inputs.verification_receipts
                ],
            }
        )
        values.append(
            (
                "closure/verification-receipts.json",
                verification_catalog,
                content_digest(verification_catalog),
            )
        )
        receipt_ids = tuple(
            sorted(
                str(event.payload["closure_receipt_id"])
                for event in context.events.replay()
                if event.type == "closure_receipt_recorded"
            )
        )
        for receipt_id in receipt_ids:
            receipt = _load(context, receipt_id, L4FindingClosureReceiptV1)
            suffix = receipt.finding_id.removeprefix("sha256:")
            values.append((f"closures/{suffix}.json", _bytes(receipt), receipt.identity))
    return tuple(sorted(values, key=lambda item: item[0]))


def _load(context: Protocol28Context, object_id: str | None, cls):  # type: ignore[no-untyped-def]
    if object_id is None:
        raise Protocol28MaterializationError("required L4 root is unavailable")
    return load_canonical_object(context.objects.read_blob(object_id), cls.from_json_dict)


def _bytes(value: object) -> bytes:
    return canonical_json_bytes(value.to_json_dict())  # type: ignore[attr-defined]


def _markdown_bytes(value: str) -> bytes:
    return (value.rstrip("\n") + "\n").encode("utf-8")


@contextmanager
def _materialization_lock(run_dir: Path) -> Iterator[None]:
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd = os.open(run_dir / ".l4-materialization.lock", flags, 0o600)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise Protocol28MaterializationError("L4 materialization lock is unsafe")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _open_materialization_directory(run_dir: Path) -> Path:
    """Create the fixed projection path without ever following a symlink."""
    current = Path(run_dir)
    metadata = current.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise Protocol28MaterializationError("L4 run directory is unsafe")
    for name in ("re", "l4"):
        candidate = current / name
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            pass
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise Protocol28MaterializationError("L4 materialization path is unsafe")
        current = candidate
    return current


def _publish_exact(
    context: Protocol28Context,
    root: Path,
    relative: str,
    payload: bytes,
) -> None:
    path = root.joinpath(*PurePosixPath(relative).parts)
    _open_relative_parents(root, PurePosixPath(relative).parts[:-1])
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_nlink == 1
            and path.read_bytes() == payload
        ):
            return
        _quarantine(context, path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.staging")
    if temporary.exists() or temporary.is_symlink():
        _quarantine(context, temporary)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise Protocol28MaterializationError(
                    "L4 materialization write made no progress"
                )
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    directory = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _open_relative_parents(root: Path, parts: tuple[str, ...]) -> None:
    current = root
    for part in parts:
        candidate = current / part
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            pass
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise Protocol28MaterializationError(
                "L4 materialization parent is unsafe"
            )
        current = candidate


def _repair_unexpected(
    context: Protocol28Context,
    root: Path,
    expected: set[str],
) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        relative = path.relative_to(root).as_posix()
        if path.is_dir() and not path.is_symlink():
            if not any(item == relative or item.startswith(relative + "/") for item in expected):
                _quarantine(context, path)
            continue
        if relative not in expected:
            _quarantine(context, path)


def _quarantine(context: Protocol28Context, path: Path) -> None:
    quarantine = _open_quarantine_directory(context.paths.root)
    suffix = content_digest(path.name.encode("utf-8")).removeprefix("sha256:")[:16]
    target = quarantine / f"{suffix}-{path.name}"
    index = 0
    while target.exists() or target.is_symlink():
        index += 1
        target = quarantine / f"{suffix}-{index}-{path.name}"
    os.replace(path, target)


def _open_quarantine_directory(v2_root: Path) -> Path:
    current = v2_root
    metadata = current.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise Protocol28MaterializationError("L4 quarantine root is unsafe")
    for name in ("quarantine", "materialized-l4"):
        candidate = current / name
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            pass
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise Protocol28MaterializationError("L4 quarantine path is unsafe")
        current = candidate
    return current


def _validate_exact_file_set(root: Path, expected: dict[str, bytes]) -> None:
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            continue
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise Protocol28MaterializationError(
                "L4 materialization contains an unsafe entry"
            )
        relative = path.relative_to(root).as_posix()
        actual.add(relative)
        if relative not in expected or path.read_bytes() != expected[relative]:
            raise Protocol28MaterializationError(
                "L4 materialization differs from durable authority"
            )
    if actual != set(expected):
        raise Protocol28MaterializationError(
            "L4 materialization file set is incomplete"
        )


__all__ = (
    "L4MaterializationEntryV1",
    "L4MaterializationManifestV1",
    "Protocol28MaterializationError",
    "materialize_l4_closure",
    "validate_or_repair_l4_materialization",
)

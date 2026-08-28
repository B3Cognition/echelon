"""Disposable run-local projections of accepted protocol-2.7 synthesis."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path, PurePosixPath
import stat
from types import SimpleNamespace
from typing import Callable, Iterator

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.materialization import (
    MaterializedProjectionV1,
    Protocol22MaterializationError,
    _ProjectionSpec,
    _fault,
    _open_directory_path_nofollow,
    _open_or_create_parents,
    _projection_state,
    _publish_projection,
    _quarantine_entry,
    _root_staging_state,
)
from harness.re_v2.protocol_22.schema import load_canonical_object

from .ledger import SynthesisMaterializationReceiptV1
from .model import (
    SynthesisMaterializationEntryV1,
    SynthesisMaterializationManifestV1,
)
from .recovery import Protocol27RunContext
from .runtime import SynthesisCandidateV1


class Protocol27MaterializationError(Protocol22MaterializationError):
    """Raised when synthesis projections cannot be safely rebuilt."""


def canonical_source_overview_bytes(
    context: Protocol27RunContext,
    source_id: str,
) -> bytes:
    """Return the exact child-owned lower-layer overview projection."""
    if not isinstance(context, Protocol27RunContext):
        raise Protocol27MaterializationError(
            "source overview requires Protocol27RunContext"
        )
    matches = tuple(
        item
        for item in context.inputs.source_overview_catalog.projections
        if item.source_id == source_id
    )
    if len(matches) != 1:
        raise Protocol27MaterializationError(
            "source overview has no unique embedded projection"
        )
    projection = matches[0]
    payload = context.object_store.read_blob(projection.object_hash)
    if (
        content_digest(payload) != projection.content_hash
        or context.inputs.source_overview_bytes.get(projection.object_hash) != payload
    ):
        raise Protocol27MaterializationError(
            "embedded source overview differs from projection authority"
        )
    return payload


def materialize_synthesis_closure(
    context: Protocol27RunContext,
    fault_hook: Callable[[str], None] | None = None,
) -> SynthesisMaterializationManifestV1:
    return _validate_or_materialize(context, fault_hook)


def validate_or_repair_synthesis_materialization(
    context: Protocol27RunContext,
    fault_hook: Callable[[str], None] | None = None,
) -> SynthesisMaterializationManifestV1:
    return _validate_or_materialize(context, fault_hook)


def _validate_or_materialize(
    context: Protocol27RunContext,
    fault_hook: Callable[[str], None] | None,
) -> SynthesisMaterializationManifestV1:
    if not isinstance(context, Protocol27RunContext):
        raise Protocol27MaterializationError(
            "materialization requires Protocol27RunContext"
        )
    if fault_hook is not None and not callable(fault_hook):
        raise Protocol27MaterializationError(
            "materialization fault hook must be callable or null"
        )
    ledger = context.ledger.replay()
    root = ledger.synthesis_root
    if root is None or len(ledger.accepted_artifacts) != len(
        context.inputs.graph.required_nodes
    ):
        raise Protocol27MaterializationError(
            "materialization requires exact accepted synthesis closure"
        )
    entries_and_payloads = _materialization_entries(context, ledger)
    manifest = SynthesisMaterializationManifestV1(
        schema_version=1,
        entries=tuple(item[0] for item in entries_and_payloads),
        source_outcomes=root.accepted_source_outcome_ids,
        input_quality=root.input_quality,
    )
    manifest_bytes = canonical_json_bytes(manifest.to_json_dict())
    if context.object_store.put_blob(manifest_bytes) != manifest.identity:
        raise Protocol27MaterializationError("materialization manifest identity changed")
    run_root = context.paths.root.parent
    specs = tuple(
        _projection_spec(run_root, entry, payload)
        for entry, payload in entries_and_payloads
    ) + (
        _manifest_spec(run_root, manifest, manifest_bytes),
    )
    expected_files = {
        PurePosixPath(*spec.relative_parts[2:]).as_posix() for spec in specs
    }
    fake_context = SimpleNamespace(paths=SimpleNamespace(root=run_root))
    with _materialization_lock(run_root) as run_fd:
        published_fd = _open_or_create_parents(run_fd, ("re", "published"))
        try:
            _validate_file_set(published_fd, expected_files, allow_missing=True)
        finally:
            os.close(published_fd)
        for spec in specs:
            parent_fd = _open_or_create_parents(run_fd, spec.relative_parts[:-1])
            try:
                name = spec.relative_parts[-1]
                staging = f".{name}.staging"
                staging_state = _root_staging_state(
                    parent_fd,
                    name,
                    staging,
                    spec.payloads[0][1],
                )
                if staging_state == "altered":
                    _quarantine_entry(
                        fake_context,
                        run_fd,
                        parent_fd,
                        staging,
                        spec.projection.artifact_hash,
                    )
                state = _projection_state(parent_fd, name, spec)
                if state == "exact":
                    continue
                if state == "altered":
                    _quarantine_entry(
                        fake_context,
                        run_fd,
                        parent_fd,
                        name,
                        spec.projection.artifact_hash,
                    )
                    _fault(
                        fault_hook,
                        "materialization_quarantined:"
                        + spec.projection.artifact_hash,
                    )
                _publish_projection(parent_fd, name, spec, fault_hook)
            finally:
                os.close(parent_fd)
        published_fd = _open_or_create_parents(run_fd, ("re", "published"))
        try:
            _validate_file_set(published_fd, expected_files, allow_missing=False)
        finally:
            os.close(published_fd)
        os.fsync(run_fd)
    receipt = SynthesisMaterializationReceiptV1(
        schema_version=1,
        synthesis_root_id=root.identity,
        materialization_manifest_id=manifest.identity,
    )
    before = context.ledger.replay().materialization
    context.ledger.record_materialization(receipt)
    if before is None:
        _fault(fault_hook, "synthesis_materialization_ledger")
    events = context.events.replay()
    existing = tuple(event for event in events if event.type == "synthesis_materialized")
    payload = {
        "materialization_manifest_id": manifest.identity,
        "synthesis_root_id": root.identity,
    }
    if not existing:
        context.events.append(
            "synthesis_materialized",
            payload,
            occurred_at=context.clock(),
        )
        _fault(fault_hook, "synthesis_materialization_event")
    elif len(existing) != 1 or canonical_json_bytes(dict(existing[0].payload)) != canonical_json_bytes(payload):
        raise Protocol27MaterializationError(
            "materialization event differs from exact projection authority"
        )
    return manifest


def _materialization_entries(context: Protocol27RunContext, ledger):  # type: ignore[no-untyped-def]
    values: list[tuple[SynthesisMaterializationEntryV1, bytes]] = []
    for projection in context.inputs.source_overview_catalog.projections:
        payload = canonical_source_overview_bytes(context, projection.source_id)
        values.append(
            (
                SynthesisMaterializationEntryV1(
                    artifact_key_id=projection.source_root_key_id,
                    artifact_hash=projection.object_hash,
                    authority_id=projection.identity,
                    relative_path=f"sources/{projection.source_id}/overview.md",
                    content_hash=content_digest(payload),
                ),
                payload,
            )
        )
    for key_id, acceptance in ledger.accepted_artifacts.items():
        work_item = ledger.accepted_work_items[key_id]
        node = context.inputs.graph.node_for_work_item(work_item)
        if not node.public_path.startswith("re/"):
            raise Protocol27MaterializationError("generated public path is outside re/")
        relative = node.public_path.removeprefix("re/")
        candidate_bytes = context.object_store.read_blob(acceptance.artifact_hash)
        candidate = load_canonical_object(
            candidate_bytes,
            SynthesisCandidateV1.from_json_dict,
        )
        payload = _render_candidate_markdown(candidate)
        values.append(
            (
                SynthesisMaterializationEntryV1(
                    artifact_key_id=key_id,
                    artifact_hash=acceptance.artifact_hash,
                    authority_id=acceptance.identity,
                    relative_path=relative,
                    content_hash=content_digest(payload),
                ),
                payload,
            )
        )
    ordered = tuple(sorted(values, key=lambda item: item[0].relative_path))
    paths = tuple(item.relative_path for item, _payload in ordered)
    if len(paths) != len(set(paths)):
        raise Protocol27MaterializationError("materialization public paths collide")
    return ordered


def _render_candidate_markdown(candidate: SynthesisCandidateV1) -> bytes:
    title = candidate.artifact_kind.replace("-", " ").title()
    lines = [f"# {title}", "", f"Input quality: `{candidate.input_quality}`"]
    if candidate.debt_refs:
        lines.extend(("", "Debt authority:", *[f"- `{item}`" for item in candidate.debt_refs]))
    claims = {item.claim_id: item for item in candidate.claims}
    for section in candidate.sections:
        lines.extend(("", f"## {section.section_id.replace('-', ' ').title()}", ""))
        for claim_id in section.claim_ids:
            claim = claims[claim_id]
            lines.append(claim.statement)
            lines.append("")
            lines.append("Evidence:")
            lines.extend(
                f"- `{item.authority_kind}:{item.authority_id}`"
                + ("" if item.source_id is None else f" (source `{item.source_id}`)")
                for item in claim.evidence
            )
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _projection_spec(
    run_root: Path,
    entry: SynthesisMaterializationEntryV1,
    payload: bytes,
) -> _ProjectionSpec:
    path = run_root / "re" / "published" / entry.relative_path
    projection = MaterializedProjectionV1(
        artifact_kind="source-overview",  # shared regular-file projection primitive
        artifact_hash=entry.content_hash,
        artifact_key_id=entry.artifact_key_id,
        path=path,
    )
    return _ProjectionSpec(
        projection,
        tuple(path.relative_to(run_root).parts),
        ((path.name, payload),),
        directory=False,
    )


def _manifest_spec(
    run_root: Path,
    manifest: SynthesisMaterializationManifestV1,
    payload: bytes,
) -> _ProjectionSpec:
    path = run_root / "re" / "published" / "materialization.json"
    return _ProjectionSpec(
        MaterializedProjectionV1(
            artifact_kind="source-overview",
            artifact_hash=manifest.identity,
            artifact_key_id=manifest.identity,
            path=path,
        ),
        tuple(path.relative_to(run_root).parts),
        ((path.name, payload),),
        directory=False,
    )


def _validate_file_set(
    root_fd: int,
    expected_files: set[str],
    *,
    allow_missing: bool,
) -> None:
    observed_files: set[str] = set()
    observed_directories: set[str] = set()

    def walk(directory_fd: int, prefix: tuple[str, ...]) -> None:
        for name in sorted(os.listdir(directory_fd)):
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            relative = PurePosixPath(*prefix, name).as_posix()
            if stat.S_ISLNK(metadata.st_mode):
                raise Protocol27MaterializationError(
                    "materialization contains an unsafe symlink"
                )
            if stat.S_ISREG(metadata.st_mode):
                if metadata.st_nlink != 1:
                    raise Protocol27MaterializationError(
                        "materialization contains an unsafe hard link"
                    )
                observed_files.add(relative)
                continue
            if not stat.S_ISDIR(metadata.st_mode):
                raise Protocol27MaterializationError(
                    "materialization contains an unsafe special entry"
                )
            observed_directories.add(relative)
            child = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            try:
                walk(child, (*prefix, name))
            finally:
                os.close(child)

    walk(root_fd, ())
    expected_directories = {
        PurePosixPath(*path.parts[:index]).as_posix()
        for value in expected_files
        for path in (PurePosixPath(value),)
        for index in range(1, len(path.parts))
    }
    extras = (observed_files - expected_files) | (
        observed_directories - expected_directories
    )
    if extras:
        raise Protocol27MaterializationError(
            "unexpected materialization entries: " + ", ".join(sorted(extras))
        )
    if not allow_missing and observed_files != expected_files:
        raise Protocol27MaterializationError("materialization file set is incomplete")


@contextmanager
def _materialization_lock(run_root: Path) -> Iterator[int]:
    run_fd = _open_directory_path_nofollow(run_root, "synthesis run root")
    lock_fd: int | None = None
    try:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
        lock_fd = os.open(".synthesis-materialization.lock", flags, 0o600, dir_fd=run_fd)
        metadata = os.fstat(lock_fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise Protocol27MaterializationError(
                "synthesis materialization lock is unsafe"
            )
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield run_fd
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(run_fd)


__all__ = (
    "Protocol27MaterializationError",
    "canonical_source_overview_bytes",
    "materialize_synthesis_closure",
    "validate_or_repair_synthesis_materialization",
)

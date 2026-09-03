"""Recoverable composition of compatibility and immutable v2 publication."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from types import MappingProxyType
from typing import Callable, Mapping

from harness.publication_transaction import (
    PublicationOperation,
    PublicationTransaction,
    apply_publication_transaction,
    rollback_publication_transaction,
    write_publication_journal,
)
from harness.re_lock import RePublishLock
from harness.re_registry import ReRegistryPaths, ensure_re_layout, load_published_index
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.publication import (
    GenerationManifest,
    PublishedV2Index,
    ReV2PublicationConflict,
    current_index_hash,
    load_published_v2_index,
    publish_generation,
)

from .materialization import validate_or_repair_synthesis_materialization
from .model import PublicationDescriptorV1, SynthesisMaterializationManifestV1
from .recovery import Protocol27RunContext


_MARKER = "protocol-27-publication.json"


class Protocol27PublicationError(RuntimeError):
    """Raised when dual publication cannot preserve both authorities."""


@dataclass(frozen=True, slots=True)
class CompatibilityPublicationCandidateV1:
    generation: int
    status: str
    files: Mapping[str, bytes]
    index_bytes: bytes

    def __post_init__(self) -> None:
        if self.generation < 1 or self.status not in {"complete", "partial"}:
            raise Protocol27PublicationError("compatibility candidate metadata is invalid")
        normalized = dict(sorted(self.files.items()))
        if "index.json" in normalized:
            raise Protocol27PublicationError("compatibility files must not contain index.json")
        for relative, payload in normalized.items():
            path = PurePosixPath(relative)
            if (
                path.is_absolute()
                or "." in path.parts
                or ".." in path.parts
                or "\\" in relative
                or not isinstance(payload, bytes)
            ):
                raise Protocol27PublicationError("compatibility candidate path is unsafe")
        object.__setattr__(self, "files", MappingProxyType(normalized))
        if not isinstance(self.index_bytes, bytes):
            raise Protocol27PublicationError("compatibility index must be bytes")

    @property
    def candidate_id(self) -> str:
        return content_digest(
            {
                "files": [
                    [path, content_digest(payload)]
                    for path, payload in self.files.items()
                ],
                "generation": self.generation,
                "index_hash": content_digest(self.index_bytes),
                "schema_version": 1,
                "status": self.status,
            }
        )


@dataclass(frozen=True, slots=True)
class Protocol27PublicationResult:
    status: str
    descriptor: PublicationDescriptorV1 | None = None
    v2_index: PublishedV2Index | None = None

    @classmethod
    def conflict(cls) -> "Protocol27PublicationResult":
        return cls("conflict")


def build_compatibility_candidate(
    context: Protocol27RunContext,
    materialization: SynthesisMaterializationManifestV1,
    generation: int,
) -> CompatibilityPublicationCandidateV1:
    """Build exact legacy registry bytes from authenticated materialization."""
    _require_context(context)
    ledger = context.ledger.replay()
    root = ledger.synthesis_root
    receipt = ledger.materialization
    if (
        root is None
        or receipt is None
        or receipt.materialization_manifest_id != materialization.identity
        or materialization.source_outcomes != root.accepted_source_outcome_ids
    ):
        raise Protocol27PublicationError("compatibility candidate requires materialized root authority")
    published = context.paths.root.parent / "re" / "published"
    files: dict[str, bytes] = {}
    for entry in materialization.entries:
        path = published.joinpath(*PurePosixPath(entry.relative_path).parts)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise Protocol27PublicationError(f"materialized artifact is unavailable: {entry.relative_path}") from exc
        if content_digest(payload) != entry.content_hash:
            raise Protocol27PublicationError(f"materialized artifact changed: {entry.relative_path}")
        files[entry.relative_path] = payload

    source_records: dict[str, dict[str, object]] = {}
    source_rows: list[dict[str, object]] = []
    for source in context.inputs.manifest.accepted_sources:
        prefix = f"sources/{source.source_id}"
        required = ("overview.md", "architecture.md", "contracts.md", "components.md")
        if any(f"{prefix}/{name}" not in files for name in required):
            raise Protocol27PublicationError(
                f"materialization is missing source compatibility files: {source.source_id}"
            )
        manifest_payload = {
            "schema_version": 1,
            "source_id": source.source_id,
            "source_path": source.source_id,
            "source_fingerprint": source.source_root_hash,
            "profile_hash": context.inputs.manifest.synthesis_policy_hash,
            "publication_status": source.outcome,
            "overview": f"re/{prefix}/overview.md",
            "architecture": f"re/{prefix}/architecture.md",
            "contracts": f"re/{prefix}/contracts.md",
            "components": f"re/{prefix}/components.md",
            "specs": [],
            "artifacts": [],
        }
        files[f"{prefix}/manifest.json"] = canonical_json_bytes(manifest_payload)
        source_records[source.source_id] = {
            "path": source.source_id,
            "published_path": f"re/{prefix}",
            "fingerprint": source.source_root_hash,
            "profile_hash": context.inputs.manifest.synthesis_policy_hash,
            "status": source.outcome,
            "manifest": f"re/{prefix}/manifest.json",
        }
        source_rows.append(
            {
                "source_id": source.source_id,
                "fingerprint": source.source_root_hash,
                "profile_hash": context.inputs.manifest.synthesis_policy_hash,
                "status": source.outcome,
                "manifest": f"re/{prefix}/manifest.json",
            }
        )

    workspace_manifest = {
        "schema_version": 1,
        "generation": generation,
        "sources": source_rows,
        "artifacts": [],
    }
    files["workspace/manifest.json"] = canonical_json_bytes(workspace_manifest)
    quality = {
        "schema_version": 1,
        "input_quality": root.input_quality,
        "synthesis_root_id": root.identity,
        "materialization_manifest_id": materialization.identity,
        "accepted_source_outcome_ids": list(root.accepted_source_outcome_ids),
        "debt_manifest_hashes": list(root.debt_manifest_hashes),
        "partial_acceptance_receipt_ids": list(root.partial_acceptance_receipt_ids),
    }
    index = {
        "schema_version": 1,
        "generation": generation,
        "publication_status": root.input_quality,
        "published_at": context.inputs.manifest.created_at,
        "published_from_run": context.inputs.manifest.run_id,
        "quality": {"workspace_synthesis": quality},
        "sources": dict(sorted(source_records.items())),
        "workspace": {
            "manifest": "re/workspace/manifest.json",
            "overview": "re/workspace/overview.md",
            "relationships": "re/workspace/relationships.md",
            "contracts": "re/workspace/contracts.md",
        },
        "warnings": (
            ["workspace synthesis is complete over explicitly accepted partial source inputs"]
            if root.input_quality == "partial"
            else []
        ),
    }
    return CompatibilityPublicationCandidateV1(
        generation=generation,
        status=root.input_quality,
        files=files,
        index_bytes=canonical_json_bytes(index),
    )


def build_publication_descriptor(
    context: Protocol27RunContext,
    materialization: SynthesisMaterializationManifestV1,
    candidate: CompatibilityPublicationCandidateV1,
) -> PublicationDescriptorV1:
    ledger = context.ledger.replay()
    root = ledger.synthesis_root
    if root is None:
        raise Protocol27PublicationError("publication descriptor requires synthesis root")
    return PublicationDescriptorV1(
        schema_version=1,
        run_id=context.inputs.manifest.run_id,
        synthesis_root_id=root.identity,
        input_quality=root.input_quality,
        accepted_source_outcome_ids=root.accepted_source_outcome_ids,
        debt_manifest_hashes=root.debt_manifest_hashes,
        partial_acceptance_receipt_ids=root.partial_acceptance_receipt_ids,
        materialization_manifest_id=materialization.identity,
        compatibility_generation=candidate.generation,
        compatibility_index_hash=content_digest(candidate.index_bytes),
        synthesis_policy_hash=context.inputs.manifest.synthesis_policy_hash,
    )


def prepare_compatibility_transaction(
    registry,
    context: Protocol27RunContext,
    candidate: CompatibilityPublicationCandidateV1,
) -> PublicationTransaction:
    stage_root = registry.staging / context.inputs.manifest.run_id
    journal = stage_root / "rollback-journal.json"
    if journal.is_file():
        raise Protocol27PublicationError("unfinished protocol-2.7 publication exists")
    if stage_root.exists():
        shutil.rmtree(stage_root)
    new_root = stage_root / "new"
    (stage_root / "rollback").mkdir(parents=True)
    new_root.mkdir()
    for relative, payload in candidate.files.items():
        _write_bytes(new_root / relative, payload)
    _write_bytes(new_root / "index.json", candidate.index_bytes)
    source_ids = tuple(sorted(context.inputs.manifest.accepted_sources, key=lambda item: item.source_id))
    operations = tuple(
        PublicationOperation(
            PurePosixPath(f"sources/{source.source_id}"),
            PurePosixPath(f"new/sources/{source.source_id}"),
        )
        for source in source_ids
    ) + (
        PublicationOperation(PurePosixPath("workspace"), PurePosixPath("new/workspace")),
        PublicationOperation(PurePosixPath("index.json"), PurePosixPath("new/index.json")),
    )
    transaction = PublicationTransaction(
        workspace_root=registry.root,
        staging_root=stage_root,
        journal=journal,
        operations=operations,
        expected_generation=candidate.generation,
    )
    write_publication_journal(transaction, "prepared")
    return transaction


def publish_protocol_27_generation(
    context: Protocol27RunContext,
    fault_hook: Callable[[str], None] | None = None,
) -> Protocol27PublicationResult:
    _require_context(context)
    workspace = _workspace_root(context)
    registry = ensure_re_layout(workspace)
    run_id = context.inputs.manifest.run_id
    with RePublishLock.acquire(workspace, run_id, context.paths.root.parent):
        return _publish_under_owned_lock(context, registry, fault_hook)


def _publish_under_owned_lock(
    context: Protocol27RunContext,
    registry,
    fault_hook: Callable[[str], None] | None,
) -> Protocol27PublicationResult:
    workspace = _workspace_root(context)
    materialization = validate_or_repair_synthesis_materialization(context)
    if _compatibility_generation(workspace) != context.inputs.manifest.expected_compatibility_generation:
        return Protocol27PublicationResult.conflict()
    if current_index_hash(workspace) != context.inputs.manifest.expected_v2_index_hash:
        return Protocol27PublicationResult.conflict()
    generation = context.inputs.manifest.expected_compatibility_generation + 1
    candidate = build_compatibility_candidate(context, materialization, generation)
    descriptor = build_publication_descriptor(context, materialization, candidate)
    transaction = prepare_compatibility_transaction(registry, context, candidate)
    _write_marker(transaction, context, candidate, descriptor)
    _fault(fault_hook, "publication_marker_staged")

    def compatibility_hook(point: str) -> None:
        _fault(fault_hook, point)
        if point == "after_replace:index.json":
            _fault(fault_hook, "after_compatibility_index")

    try:
        apply_publication_transaction(transaction, fault_hook=compatibility_hook)
    except Exception:
        # The shared primitive returns through this path only after its guarded
        # rollback succeeded. Remove the now-terminal staging transaction so a
        # caller can retry against the still-valid frozen bases.
        try:
            status = json.loads(transaction.journal.read_text(encoding="utf-8")).get(
                "status"
            )
        except (OSError, json.JSONDecodeError):
            status = None
        if status == "rolled_back":
            shutil.rmtree(transaction.staging_root)
        raise
    write_publication_journal(transaction, "replacing")
    _fault(fault_hook, "compatibility_journal_retained")
    try:
        index = publish_generation(
            workspace,
            context.inputs.manifest.run_id,
            (descriptor.descriptor_id,),
            context.inputs.manifest.synthesis_policy_hash,
            expected_index_hash=context.inputs.manifest.expected_v2_index_hash,
            fault_hook=fault_hook,
        )
    except ReV2PublicationConflict:
        rollback_publication_transaction(transaction)
        shutil.rmtree(transaction.staging_root)
        return Protocol27PublicationResult.conflict()
    _record_publication(context, descriptor, fault_hook)
    _finalize(transaction, fault_hook)
    return Protocol27PublicationResult(
        f"published_{descriptor.input_quality}", descriptor, index
    )


def recover_protocol_27_publication(
    context: Protocol27RunContext,
    fault_hook: Callable[[str], None] | None = None,
    *,
    _release_lock: bool = True,
) -> Protocol27PublicationResult:
    """Complete or roll back the marked second-CAS publication boundary."""
    _require_context(context)
    workspace = _workspace_root(context)
    registry = ReRegistryPaths.for_workspace(workspace)
    if not registry.root.is_dir() or not registry.staging.is_dir():
        raise Protocol27PublicationError("protocol-2.7 publication registry is unavailable")
    stage_root = registry.staging / context.inputs.manifest.run_id
    journal = stage_root / "rollback-journal.json"
    marker_path = stage_root / _MARKER
    if not journal.is_file() or not marker_path.is_file():
        existing = context.ledger.replay().publication
        if existing is None:
            raise Protocol27PublicationError("protocol-2.7 publication marker is missing")
        return _installed_result(context, existing)
    transaction = PublicationTransaction.from_journal(
        workspace_root=registry.root,
        staging_root=stage_root,
        journal=journal,
    )
    materialization = validate_or_repair_synthesis_materialization(context)
    candidate = build_compatibility_candidate(
        context,
        materialization,
        context.inputs.manifest.expected_compatibility_generation + 1,
    )
    descriptor = build_publication_descriptor(context, materialization, candidate)
    _validate_marker(marker_path, context, candidate, descriptor)
    compatibility_matches = (
        registry.index.is_file()
        and content_digest(registry.index.read_bytes()) == descriptor.compatibility_index_hash
    )
    current_v2 = load_published_v2_index(workspace)
    desired_manifest = GenerationManifest.create(
        (descriptor.descriptor_id,), descriptor.synthesis_policy_hash
    )
    v2_matches = bool(
        current_v2 is not None
        and current_v2.generation_id == desired_manifest.generation_id
        and current_v2.run_id == descriptor.run_id
    )
    if compatibility_matches and not v2_matches:
        if current_index_hash(workspace) != context.inputs.manifest.expected_v2_index_hash:
            rollback_publication_transaction(transaction)
            shutil.rmtree(stage_root)
            if _release_lock:
                _release_owned_lock(workspace, context.inputs.manifest.run_id)
            return Protocol27PublicationResult.conflict()
        try:
            current_v2 = publish_generation(
                workspace,
                descriptor.run_id,
                (descriptor.descriptor_id,),
                descriptor.synthesis_policy_hash,
                expected_index_hash=context.inputs.manifest.expected_v2_index_hash,
                fault_hook=fault_hook,
            )
        except ReV2PublicationConflict:
            rollback_publication_transaction(transaction)
            shutil.rmtree(stage_root)
            if _release_lock:
                _release_owned_lock(workspace, context.inputs.manifest.run_id)
            return Protocol27PublicationResult.conflict()
        v2_matches = True
    if compatibility_matches and v2_matches and current_v2 is not None:
        _record_publication(context, descriptor, fault_hook)
        _finalize(transaction, fault_hook)
        if _release_lock:
            _release_owned_lock(workspace, context.inputs.manifest.run_id)
        return Protocol27PublicationResult(
            f"published_{descriptor.input_quality}", descriptor, current_v2
        )
    can_retry = (
        current_index_hash(workspace) == context.inputs.manifest.expected_v2_index_hash
    )
    rollback_publication_transaction(transaction)
    shutil.rmtree(stage_root)
    if can_retry and _compatibility_generation(workspace) == context.inputs.manifest.expected_compatibility_generation:
        result = _publish_under_owned_lock(context, registry, fault_hook)
    else:
        result = Protocol27PublicationResult.conflict()
    if _release_lock:
        _release_owned_lock(workspace, context.inputs.manifest.run_id)
    return result


def _record_publication(
    context: Protocol27RunContext,
    descriptor: PublicationDescriptorV1,
    fault_hook: Callable[[str], None] | None,
) -> None:
    payload = canonical_json_bytes(descriptor.to_json_dict())
    if context.object_store.put_blob(payload) != descriptor.descriptor_id:
        raise Protocol27PublicationError("publication descriptor identity changed")
    before = context.ledger.replay().publication
    context.ledger.record_publication(descriptor)
    if before is None:
        _fault(fault_hook, "publication_receipt")
    event_payload = {
        "materialization_manifest_id": descriptor.materialization_manifest_id,
        "publication_descriptor_id": descriptor.descriptor_id,
        "synthesis_root_id": descriptor.synthesis_root_id,
    }
    matches = [item for item in context.events.replay() if item.type == "synthesis_published"]
    if not matches:
        context.events.append("synthesis_published", event_payload, occurred_at=context.clock())
        _fault(fault_hook, "publication_event")
    elif len(matches) != 1 or dict(matches[0].payload) != event_payload:
        raise Protocol27PublicationError("publication event differs from descriptor")


def _installed_result(
    context: Protocol27RunContext, descriptor: PublicationDescriptorV1
) -> Protocol27PublicationResult:
    workspace = _workspace_root(context)
    index = load_published_v2_index(workspace)
    compatibility = load_published_index(workspace)
    if (
        index is None
        or compatibility is None
        or compatibility.generation != descriptor.compatibility_generation
        or content_digest((workspace / "re/index.json").read_bytes())
        != descriptor.compatibility_index_hash
    ):
        raise Protocol27PublicationError("durable publication receipt has no matching indexes")
    return Protocol27PublicationResult(
        f"published_{descriptor.input_quality}", descriptor, index
    )


def _write_marker(
    transaction: PublicationTransaction,
    context: Protocol27RunContext,
    candidate: CompatibilityPublicationCandidateV1,
    descriptor: PublicationDescriptorV1,
) -> None:
    marker = {
        "schema_version": 1,
        "protocol": "2.7",
        "run_dir": str(context.paths.root.parent),
        "candidate_id": candidate.candidate_id,
        "publication_descriptor_id": descriptor.descriptor_id,
        "compatibility_index_hash": descriptor.compatibility_index_hash,
    }
    _write_bytes(transaction.staging_root / _MARKER, canonical_json_bytes(marker))


def _validate_marker(
    path: Path,
    context: Protocol27RunContext,
    candidate: CompatibilityPublicationCandidateV1,
    descriptor: PublicationDescriptorV1,
) -> None:
    try:
        raw = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise Protocol27PublicationError("protocol-2.7 publication marker is invalid") from exc
    expected = {
        "schema_version": 1,
        "protocol": "2.7",
        "run_dir": str(context.paths.root.parent),
        "candidate_id": candidate.candidate_id,
        "publication_descriptor_id": descriptor.descriptor_id,
        "compatibility_index_hash": descriptor.compatibility_index_hash,
    }
    if raw != expected or path.read_bytes() != canonical_json_bytes(expected):
        raise Protocol27PublicationError("protocol-2.7 publication marker authority mismatch")


def _finalize(
    transaction: PublicationTransaction,
    fault_hook: Callable[[str], None] | None,
) -> None:
    write_publication_journal(transaction, "complete")
    _fault(fault_hook, "publication_journal_finalized")
    shutil.rmtree(transaction.staging_root)
    _fault(fault_hook, "publication_staging_cleaned")


def _compatibility_generation(workspace: Path) -> int:
    index = load_published_index(workspace)
    return 0 if index is None else index.generation


def _workspace_root(context: Protocol27RunContext) -> Path:
    run_dir = context.paths.root.parent
    runs = run_dir.parent
    if runs.name != "runs" or not run_dir.is_relative_to(runs):
        raise Protocol27PublicationError("protocol-2.7 run is outside workspace runs")
    return runs.parent


def _require_context(context: Protocol27RunContext) -> None:
    if not isinstance(context, Protocol27RunContext):
        raise Protocol27PublicationError("publication requires Protocol27RunContext")


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _release_owned_lock(workspace: Path, run_id: str) -> None:
    path = workspace / "re/.locks/publish.lock"
    owner_path = path / "owner.json"
    if not owner_path.is_file():
        return
    try:
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if owner.get("run_id") == run_id:
        shutil.rmtree(path)


def _fault(hook: Callable[[str], None] | None, boundary: str) -> None:
    if hook is not None:
        hook(boundary)


__all__ = (
    "CompatibilityPublicationCandidateV1",
    "Protocol27PublicationError",
    "Protocol27PublicationResult",
    "build_compatibility_candidate",
    "build_publication_descriptor",
    "prepare_compatibility_transaction",
    "publish_protocol_27_generation",
    "recover_protocol_27_publication",
)

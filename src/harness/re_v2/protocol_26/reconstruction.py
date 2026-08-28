"""Reconstruct per-artifact checkpoint authority from stable RE v2 origins."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventRecord, EventStore
from harness.re_v2.ledger import LedgerRecord, ObjectStore
from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
from harness.re_v2.protocol_22.ledger import Protocol22Ledger, Protocol22LedgerView
from harness.re_v2.protocol_22.model import RunManifestV2
from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
from harness.re_v2.protocol_24.model import AdoptedArtifactAuthorityV1, RunManifestV3
from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS
from harness.re_v2.protocol_25.ledger import Protocol25Ledger
from harness.re_v2.protocol_25.model import RunManifestV4
from harness.re_v2.protocol_26.model import (
    CheckpointArtifactDependencyV1,
    CheckpointManifestV1,
    CheckpointRankV1,
    RunManifestV5,
)
from harness.re_v2.protocol_26.selection import RANK_POLICIES
from harness.re_v2.run_store import ReV2Paths, load_run_manifest


@dataclass(frozen=True, slots=True)
class OriginCheckpointRejectionV1:
    origin_run_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class OriginCheckpointResultV1:
    origin_run_id: str
    manifests: tuple[CheckpointManifestV1, ...]
    authority_objects: Mapping[str, Mapping[str, bytes]]
    rejected: tuple[OriginCheckpointRejectionV1, ...]

    def __post_init__(self) -> None:
        frozen = {
            manifest_id: MappingProxyType(dict(sorted(objects.items())))
            for manifest_id, objects in sorted(self.authority_objects.items())
        }
        object.__setattr__(self, "authority_objects", MappingProxyType(frozen))

    @classmethod
    def unstable(cls, origin_run_id: str) -> "OriginCheckpointResultV1":
        return cls(
            origin_run_id=origin_run_id,
            manifests=(),
            authority_objects={},
            rejected=(
                OriginCheckpointRejectionV1(
                    origin_run_id=origin_run_id,
                    reason="checkpoint_origin_unstable",
                ),
            ),
        )

    @classmethod
    def invalid(
        cls, origin_run_id: str, reason: str
    ) -> "OriginCheckpointResultV1":
        return cls(
            origin_run_id=origin_run_id,
            manifests=(),
            authority_objects={},
            rejected=(OriginCheckpointRejectionV1(origin_run_id, reason),),
        )


@dataclass(frozen=True, slots=True)
class _StableOriginV1:
    run_dir: Path
    manifest: RunManifestV2 | RunManifestV3 | RunManifestV4
    manifest_bytes: bytes
    event_bytes: bytes
    ledger_bytes: bytes
    events: tuple[EventRecord, ...]
    history: tuple[LedgerRecord, ...]
    ledger: Protocol22LedgerView
    objects: ObjectStore
    origin_engine_protocol_version: str
    origin_run_schema_version: int


def reconstruct_origin_checkpoints(
    workspace_root: Path,
    run_dir: Path,
    *,
    max_stability_attempts: int = 2,
) -> OriginCheckpointResultV1:
    """Return exact accepted checkpoints from one stable, confined origin run."""
    origin_run_id = Path(run_dir).name
    if max_stability_attempts <= 0:
        raise ValueError("max_stability_attempts must be positive")
    try:
        confined = _confined_origin(workspace_root, run_dir)
        paths = ReV2Paths.for_run(confined)
    except Exception:
        return OriginCheckpointResultV1.invalid(
            origin_run_id, "checkpoint_manifest_invalid"
        )

    try:
        for _attempt in range(max_stability_attempts):
            stable = _stable_chain_pair(paths)
            if stable is not None:
                return _reconstruct_accepted_artifacts(stable)
    except Exception as exc:
        return OriginCheckpointResultV1.invalid(
            origin_run_id, _controlled_reason(exc)
        )
    return OriginCheckpointResultV1.unstable(origin_run_id)


def _stable_chain_pair(paths: ReV2Paths) -> _StableOriginV1 | None:
    before = (
        _safe_regular_read(paths.manifest),
        _safe_optional_regular_read(paths.events),
        _safe_regular_read(paths.ledger),
    )
    active_manifest = load_run_manifest(paths.root.parent)
    event_protocol, ledger_type, manifest = _protocol_facades(
        paths,
        active_manifest,
    )
    if not isinstance(manifest, (RunManifestV2, RunManifestV3, RunManifestV4)):
        raise ValueError("checkpoint origin manifest protocol is unsupported")
    objects = ObjectStore(paths.objects)
    events = EventStore(paths, protocol=event_protocol).replay()
    history, ledger = ledger_type(paths, objects).replay_with_history()
    after = (
        _safe_regular_read(paths.manifest),
        _safe_optional_regular_read(paths.events),
        _safe_regular_read(paths.ledger),
    )
    if before != after:
        return None
    return _StableOriginV1(
        run_dir=paths.root.parent,
        manifest=manifest,
        manifest_bytes=after[0],
        event_bytes=after[1],
        ledger_bytes=after[2],
        events=events,
        history=history,
        ledger=ledger,
        objects=objects,
        origin_engine_protocol_version=active_manifest.engine_protocol_version,
        origin_run_schema_version=active_manifest.schema_version,
    )


def _reconstruct_accepted_artifacts(
    origin: _StableOriginV1,
) -> OriginCheckpointResultV1:
    manifest = origin.manifest
    origin_id = manifest.run_id
    by_artifact_hash: dict[str, list[str]] = {}
    for key_id, receipt in origin.ledger.accepted_artifacts.items():
        by_artifact_hash.setdefault(receipt.artifact_hash, []).append(key_id)
    cyclic_keys = _cyclic_artifact_keys(origin.ledger, by_artifact_hash)

    manifests: list[CheckpointManifestV1] = []
    objects_by_manifest: dict[str, Mapping[str, bytes]] = {}
    rejections: list[OriginCheckpointRejectionV1] = []
    for artifact_key_id, acceptance in sorted(
        origin.ledger.accepted_artifacts.items()
    ):
        try:
            if artifact_key_id in cyclic_keys:
                raise ValueError("accepted artifact dependency cycle")
            certification = origin.ledger.certifications.get(
                acceptance.certification_receipt_id
            )
            work_item = origin.ledger.certification_work_items.get(
                acceptance.certification_receipt_id
            )
            semantic_certifications = getattr(
                origin.ledger, "semantic_certifications", {}
            )
            if certification is None:
                certification = semantic_certifications[
                    acceptance.certification_receipt_id
                ]
                work_item = _semantic_work_item(origin, acceptance)
            if work_item is None:
                raise ValueError("accepted artifact work item is missing")
            ledger_record = origin.ledger.artifact_acceptance_records[
                acceptance.identity
            ]
            event = _acceptance_event(origin.events, acceptance, work_item.work_item_id)
            candidate = _certified_candidate(
                origin.ledger, acceptance.certification_receipt_id
            )
            dependencies, non_artifact = _classify_dependencies(
                work_item.output_key.dependency_hashes,
                artifact_key_id,
                by_artifact_hash,
                origin.objects,
            )
            event_prefix = _canonical_event_prefix(origin.events, event)
            ledger_prefix = _canonical_ledger_prefix(origin.history, ledger_record)
            authority = AdoptedArtifactAuthorityV1(
                schema_version=1,
                artifact_key_id=artifact_key_id,
                artifact_hash=acceptance.artifact_hash,
                dependency_hashes=work_item.output_key.dependency_hashes,
                certification_receipt_id=certification.identity,
                candidate_assessment_id=(
                    None if candidate is None else candidate.identity
                ),
                artifact_acceptance_receipt_id=acceptance.identity,
                source_run_id=origin_id,
                source_ledger_entry_hash=ledger_record.record_hash,
            )
            authority_objects = _authority_objects(
                origin,
                event_prefix,
                ledger_prefix,
                work_item,
                certification,
                candidate,
                acceptance,
                tuple(work_item.output_key.dependency_hashes),
            )
            provisional_rank = CheckpointRankV1(
                schema_version=1,
                policy_id="pending-explicit-rank-policy",
                policy_hash=content_digest("pending-explicit-rank-policy"),
                vector=(1,),
            )
            audit_epoch_id = getattr(certification, "audit_epoch_id", None)
            semantic_authority_ids: tuple[str, ...] = ()
            if acceptance.certification_receipt_id in semantic_certifications:
                semantic_ids = {certification.identity}
                if audit_epoch_id is not None:
                    epochs = getattr(origin.ledger, "audit_epochs", {})
                    if audit_epoch_id not in epochs:
                        raise ValueError(
                            "semantic certification has no exact audit epoch authority"
                        )
                    semantic_ids.add(audit_epoch_id)
                semantic_authority_ids = tuple(sorted(semantic_ids))
            checkpoint = CheckpointManifestV1(
                schema_version=1,
                origin_run_id=origin_id,
                origin_manifest_hash=content_digest(origin.manifest_bytes),
                origin_engine_protocol_version=origin.origin_engine_protocol_version,
                origin_run_schema_version=origin.origin_run_schema_version,
                origin_acceptance_event_hash=event.event_hash,
                origin_event_prefix_hash=content_digest(event_prefix),
                origin_ledger_record_hash=ledger_record.record_hash,
                origin_ledger_prefix_hash=content_digest(ledger_prefix),
                work_item=work_item,
                artifact_key_id=artifact_key_id,
                artifact_hash=acceptance.artifact_hash,
                certification_receipt=certification,
                candidate_assessment=candidate,
                artifact_acceptance_receipt=acceptance,
                adopted_artifact_authority=authority,
                accepted_artifact_dependencies=dependencies,
                non_artifact_dependency_hashes=non_artifact,
                immutable_object_hashes=tuple(sorted(authority_objects)),
                immutable_object_byte_counts={
                    object_hash: len(payload)
                    for object_hash, payload in authority_objects.items()
                },
                audit_epoch_id=audit_epoch_id,
                semantic_authority_ids=semantic_authority_ids,
                rank=provisional_rank,
                rank_policy_hash=provisional_rank.policy_hash,
            )
            rank = RANK_POLICIES.extract(checkpoint)
            checkpoint = replace(
                checkpoint,
                rank=rank,
                rank_policy_hash=rank.policy_hash,
            )
            manifests.append(checkpoint)
            objects_by_manifest[checkpoint.identity] = authority_objects
        except Exception as exc:
            rejections.append(
                OriginCheckpointRejectionV1(origin_id, _controlled_reason(exc))
            )
    manifests.sort(key=lambda item: (item.artifact_key_id, item.identity))
    return OriginCheckpointResultV1(
        origin_run_id=origin_id,
        manifests=tuple(manifests),
        authority_objects=objects_by_manifest,
        rejected=tuple(rejections),
    )


def _protocol_facades(paths: ReV2Paths, manifest: object):  # type: ignore[no-untyped-def]
    if isinstance(manifest, RunManifestV2):
        return PROTOCOL_22_EVENTS, Protocol22Ledger, manifest
    if isinstance(manifest, RunManifestV3):
        return PROTOCOL_24_EVENTS, Protocol22Ledger, manifest
    if isinstance(manifest, RunManifestV4):
        return PROTOCOL_25_EVENTS, Protocol25Ledger, manifest
    if isinstance(manifest, RunManifestV5):
        from harness.re_v2.protocol_26.events import protocol_26_events_for
        from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs

        inputs = load_protocol_26_inputs(paths, manifest)
        layer_manifest = inputs.layer_execution_contract.layer_manifest
        ledger_type = (
            Protocol25Ledger if manifest.target_layer == "L3" else Protocol22Ledger
        )
        return (
            protocol_26_events_for(manifest.target_layer),
            ledger_type,
            layer_manifest,
        )
    raise ValueError("checkpoint origin manifest protocol is unsupported")


def _acceptance_event(events, acceptance, work_item_id):  # type: ignore[no-untyped-def]
    matches: list[EventRecord] = []
    for event in events:
        if event.type == "artifact_accepted":
            if (
                event.payload.get("artifact_acceptance_receipt_id")
                == acceptance.identity
                and event.payload.get("artifact_key_id")
                == acceptance.artifact_key.identity
                and event.payload.get("artifact_hash") == acceptance.artifact_hash
                and event.payload.get("certification_receipt_id")
                == acceptance.certification_receipt_id
                and event.payload.get("work_item_id") == work_item_id
            ):
                matches.append(event)
        elif event.type in {"artifact_adopted", "checkpoint_artifact_adopted"}:
            authority = AdoptedArtifactAuthorityV1.from_json_dict(
                event.payload["adopted_artifact_authority"]
            )
            if (
                authority.artifact_key_id == acceptance.artifact_key.identity
                and authority.artifact_hash == acceptance.artifact_hash
                and authority.certification_receipt_id
                == acceptance.certification_receipt_id
                and authority.artifact_acceptance_receipt_id == acceptance.identity
                and event.payload.get("work_item_id") == work_item_id
            ):
                matches.append(event)
    if len(matches) != 1:
        raise ValueError("accepted artifact has no unique matching acceptance event")
    return matches[0]


def _certified_candidate(ledger, certification_id):  # type: ignore[no-untyped-def]
    matches = tuple(
        item
        for item in ledger.candidate_assessments.values()
        if item.certification_receipt_id == certification_id
        and item.outcome == "certified"
    )
    if len(matches) > 1:
        raise ValueError("accepted artifact has ambiguous candidate assessment")
    return None if not matches else matches[0]


def _semantic_work_item(origin: _StableOriginV1, acceptance):  # type: ignore[no-untyped-def]
    """Rebuild an L3 work item through the existing protocol-2.5 graph builders."""
    from types import SimpleNamespace

    from harness.re_v2.protocol_22.graph import AcceptedArtifactV2
    from harness.re_v2.protocol_24.graph import reconstruct_adopted_parent_closure
    from harness.re_v2.protocol_25.artifacts import (
        AuditCandidateV1,
        SemanticResolutionOverlayV1,
        SourceCompositionAssessmentV1,
        TargetClosureAssessmentV1,
    )
    from harness.re_v2.protocol_25.graph import build_protocol_25_graph
    from harness.re_v2.protocol_25.inputs import load_protocol_25_inputs
    from harness.re_v2.protocol_25.recovery import _semantic_operation_item
    from harness.re_v2.protocol_22.schema import load_canonical_object

    if not isinstance(origin.manifest, RunManifestV4):
        raise ValueError("semantic acceptance requires a schema-4 origin")
    paths = ReV2Paths.for_run(origin.run_dir)
    active_manifest = load_run_manifest(origin.run_dir)
    if isinstance(active_manifest, RunManifestV5):
        from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs

        inputs = load_protocol_26_inputs(paths, active_manifest).layer_inputs
    else:
        inputs = load_protocol_25_inputs(paths, origin.manifest)
    accepted_parent = reconstruct_adopted_parent_closure(
        inputs.parent_authority_bundle.lower_authority_bundle,
        origin.ledger,
    )
    graph = build_protocol_25_graph(
        origin.manifest,
        inputs.graph_inputs,
        accepted_parent,
    )
    prerequisite_template_ids = {
        item.template_id for item in graph.prerequisite_graph.templates
    }
    accepted_prerequisites: dict[str, AcceptedArtifactV2] = {}
    for receipt in origin.ledger.accepted_artifacts.values():
        item = origin.ledger.certification_work_items.get(
            receipt.certification_receipt_id
        )
        if item is not None and item.template_id in prerequisite_template_ids:
            accepted_prerequisites[item.template_id] = AcceptedArtifactV2(
                receipt.artifact_key.identity,
                receipt.artifact_hash,
            )
    materialized = graph.ready_audit_targets(accepted_prerequisites)
    audit_items: dict[str, tuple[object, object]] = {}
    for target, template in zip(materialized, graph.audit_templates, strict=True):
        dependencies = {
            template_id: accepted_prerequisites[template_id]
            for template_id in template.required_template_ids
        }
        item = graph.instantiate_audit_item(template, target, dependencies)
        audit_items[target.audit_target_id] = (target, item)

    kind = acceptance.artifact_key.artifact_kind
    artifact = load_canonical_object(
        origin.objects.read_blob(acceptance.artifact_hash),
        {
            "semantic-audit-findings": AuditCandidateV1.from_json_dict,
            "semantic-resolution-overlay": SemanticResolutionOverlayV1.from_json_dict,
            "target-closure-assessment": TargetClosureAssessmentV1.from_json_dict,
            "source-composition-assessment": SourceCompositionAssessmentV1.from_json_dict,
        }[kind],
    )
    if isinstance(artifact, AuditCandidateV1):
        _target, item = audit_items[artifact.audit_target_id]
        if item.output_key != acceptance.artifact_key:
            raise ValueError("semantic audit work item differs from acceptance")
        return item

    audit_candidates: list[AuditCandidateV1] = []
    for receipt in origin.ledger.accepted_artifacts.values():
        if receipt.artifact_key.artifact_kind == "semantic-audit-findings":
            audit_candidates.append(
                load_canonical_object(
                    origin.objects.read_blob(receipt.artifact_hash),
                    AuditCandidateV1.from_json_dict,
                )
            )
    if isinstance(artifact, SourceCompositionAssessmentV1):
        candidates = tuple(
            item
            for item in audit_candidates
            if item.audit_target.target_kind == "source"
            and item.audit_target.scope.source_id == artifact.source_id
        )
    else:
        candidates = tuple(
            item
            for item in audit_candidates
            if item.audit_target_id == artifact.audit_target_id
        )
    if len(candidates) != 1:
        raise ValueError("semantic operation has no unique audit target authority")
    audit_candidate = candidates[0]
    _target, audit_item = audit_items[audit_candidate.audit_target_id]
    context = SimpleNamespace(semantic_inputs=inputs, semantic_graph=graph)
    item = _semantic_operation_item(
        context,
        audit_item,
        audit_candidate.audit_target,
        kind,
        acceptance.artifact_key.dependency_hashes,
    )
    if item.output_key != acceptance.artifact_key:
        raise ValueError("semantic operation work item differs from acceptance")
    return item


def _classify_dependencies(
    dependency_hashes: tuple[str, ...],
    own_key_id: str,
    by_artifact_hash: Mapping[str, list[str]],
    objects: ObjectStore,
) -> tuple[tuple[CheckpointArtifactDependencyV1, ...], tuple[str, ...]]:
    accepted: list[CheckpointArtifactDependencyV1] = []
    non_artifact: list[str] = []
    for dependency_hash in dependency_hashes:
        matching_keys = by_artifact_hash.get(dependency_hash, [])
        if len(matching_keys) > 1:
            raise ValueError("accepted artifact dependency is ambiguous")
        if matching_keys:
            if matching_keys[0] == own_key_id:
                raise ValueError("accepted artifact dependency cycle")
            accepted.append(
                CheckpointArtifactDependencyV1(
                    schema_version=1,
                    artifact_key_id=matching_keys[0],
                    artifact_hash=dependency_hash,
                )
            )
        else:
            objects.read_blob(dependency_hash)
            non_artifact.append(dependency_hash)
    accepted.sort(key=lambda item: item.identity)
    return tuple(accepted), tuple(sorted(non_artifact))


def _cyclic_artifact_keys(
    ledger: Protocol22LedgerView,
    by_artifact_hash: Mapping[str, list[str]],
) -> frozenset[str]:
    edges: dict[str, tuple[str, ...]] = {}
    for key_id, acceptance in ledger.accepted_artifacts.items():
        edges[key_id] = tuple(
            keys[0]
            for dependency_hash in acceptance.artifact_key.dependency_hashes
            if len(keys := by_artifact_hash.get(dependency_hash, [])) == 1
        )
    visited: set[str] = set()
    active: list[str] = []
    cyclic: set[str] = set()

    def visit(key_id: str) -> None:
        if key_id in active:
            cyclic.update(active[active.index(key_id) :])
            return
        if key_id in visited:
            return
        active.append(key_id)
        for dependency_key in edges.get(key_id, ()):
            visit(dependency_key)
        active.pop()
        visited.add(key_id)

    for key_id in sorted(edges):
        visit(key_id)
    return frozenset(cyclic)


def _authority_objects(
    origin: _StableOriginV1,
    event_prefix: bytes,
    ledger_prefix: bytes,
    work_item,  # type: ignore[no-untyped-def]
    certification,  # type: ignore[no-untyped-def]
    candidate,  # type: ignore[no-untyped-def]
    acceptance,  # type: ignore[no-untyped-def]
    dependency_hashes: tuple[str, ...],
) -> Mapping[str, bytes]:
    payloads = (
        origin.manifest_bytes,
        event_prefix,
        ledger_prefix,
        canonical_json_bytes(work_item.to_json_dict()),
        canonical_json_bytes(certification.to_json_dict()),
        canonical_json_bytes(acceptance.to_json_dict()),
    )
    result = {content_digest(payload): payload for payload in payloads}
    if candidate is not None:
        candidate_bytes = canonical_json_bytes(candidate.to_json_dict())
        result[content_digest(candidate_bytes)] = candidate_bytes
        for object_hash in (
            candidate.execution_capture_hash,
            candidate.normalized_authorial_payload_hash,
        ):
            if object_hash is not None:
                result[object_hash] = origin.objects.read_blob(object_hash)
    audit_epoch_id = getattr(certification, "audit_epoch_id", None)
    if audit_epoch_id is not None:
        result[audit_epoch_id] = origin.objects.read_blob(audit_epoch_id)
    for object_hash in (acceptance.artifact_hash, *dependency_hashes):
        result[object_hash] = origin.objects.read_blob(object_hash)
    return MappingProxyType(dict(sorted(result.items())))


def _canonical_event_prefix(
    history: tuple[EventRecord, ...], terminal: EventRecord
) -> bytes:
    try:
        index = history.index(terminal)
    except ValueError as exc:
        raise ValueError("acceptance event is outside event history") from exc
    return b"".join(
        canonical_json_bytes(item.to_json_dict()) for item in history[: index + 1]
    )


def _canonical_ledger_prefix(
    history: tuple[LedgerRecord, ...], terminal: LedgerRecord
) -> bytes:
    try:
        index = history.index(terminal)
    except ValueError as exc:
        raise ValueError("acceptance record is outside ledger history") from exc
    return b"".join(
        canonical_json_bytes(item.to_json_dict()) for item in history[: index + 1]
    )


def _confined_origin(workspace_root: Path, run_dir: Path) -> Path:
    workspace = Path(workspace_root).resolve()
    runs_root = workspace / "runs"
    candidate = Path(run_dir)
    if candidate.parent != runs_root or not candidate.name.startswith("re-"):
        raise ValueError("origin must be a direct re-* child of workspace runs")
    metadata = os.lstat(candidate)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("origin run must be a real directory")
    resolved = candidate.resolve()
    if resolved.parent != runs_root.resolve():
        raise ValueError("origin escapes workspace runs")
    return resolved


def _safe_regular_read(path: Path) -> bytes:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("checkpoint authority path is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError("checkpoint authority path changed during open")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def _safe_optional_regular_read(path: Path) -> bytes:
    try:
        return _safe_regular_read(path)
    except FileNotFoundError:
        return b""


def _controlled_reason(exc: Exception) -> str:
    message = str(exc).lower()
    if "hash mismatch" in message or "corrupt" in message:
        return "checkpoint_object_hash_mismatch"
    if "object" in message and (
        "missing" in message or "no such file" in message
    ):
        return "checkpoint_object_missing"
    if "cycle" in message:
        return "checkpoint_cycle_detected"
    if "receipt" in message or "certification" in message or "acceptance" in message:
        return "checkpoint_receipt_invalid"
    return "checkpoint_manifest_invalid"


__all__ = (
    "OriginCheckpointRejectionV1",
    "OriginCheckpointResultV1",
    "reconstruct_origin_checkpoints",
)

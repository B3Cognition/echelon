"""Stable, exact checkpoint reuse for protocol-2.7 synthesis artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Callable, ClassVar, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventRecord, EventStore
from harness.re_v2.ledger import LedgerRecord, ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    load_canonical_object,
    safe_id,
)
from harness.re_v2.run_store import ReV2Paths, load_run_manifest

from .events import PROTOCOL_27_EVENTS
from .graph import SynthesisGraph
from .ledger import (
    Protocol27Ledger,
    SynthesisCheckpointAdoptionReceiptV1,
)
from .model import (
    RunManifestV6,
    SynthesisCheckpointDispositionV1,
    SynthesisCheckpointOriginPrefixV1,
    SynthesisCheckpointSelectionEntryV1,
    SynthesisCheckpointSelectionV1,
    SynthesisWorkItemV1,
)
from .runtime import (
    SynthesisArtifactAcceptanceV1,
    SynthesisAssessmentV1,
    SynthesisCertificationV1,
)


class Protocol27CheckpointError(RuntimeError):
    """Raised when checkpoint authority cannot be reconstructed or adopted."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol27CheckpointError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol27CheckpointError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class SynthesisCheckpointManifestV1:
    schema_version: int
    origin_run_id: str
    origin_manifest_hash: str
    origin_acceptance_event_hash: str
    origin_event_prefix_hash: str
    origin_ledger_record_hash: str
    origin_ledger_prefix_hash: str
    work_item: SynthesisWorkItemV1
    candidate_assessment: SynthesisAssessmentV1
    certification: SynthesisCertificationV1
    acceptance: SynthesisArtifactAcceptanceV1
    dependency_artifact_key_ids: tuple[str, ...]
    immutable_object_ids: tuple[str, ...]
    immutable_object_byte_counts: Mapping[str, int]
    certified_rank: tuple[int, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "origin_run_id",
        "origin_manifest_hash",
        "origin_acceptance_event_hash",
        "origin_event_prefix_hash",
        "origin_ledger_record_hash",
        "origin_ledger_prefix_hash",
        "work_item",
        "candidate_assessment",
        "certification",
        "acceptance",
        "dependency_artifact_key_ids",
        "immutable_object_ids",
        "immutable_object_byte_counts",
        "certified_rank",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis checkpoint schema")
        _schema(safe_id, self.origin_run_id, "synthesis checkpoint origin")
        for field in self.FIELDS[2:7]:
            _schema(digest_value, getattr(self, field), f"synthesis checkpoint {field}")
        if not isinstance(self.work_item, SynthesisWorkItemV1):
            raise Protocol27CheckpointError("synthesis checkpoint work item is invalid")
        if not isinstance(self.candidate_assessment, SynthesisAssessmentV1):
            raise Protocol27CheckpointError("synthesis checkpoint assessment is invalid")
        if not isinstance(self.certification, SynthesisCertificationV1):
            raise Protocol27CheckpointError("synthesis checkpoint certification is invalid")
        if not isinstance(self.acceptance, SynthesisArtifactAcceptanceV1):
            raise Protocol27CheckpointError("synthesis checkpoint acceptance is invalid")
        key_id = self.work_item.output_key.artifact_key_id
        if (
            self.candidate_assessment.work_item_id != self.work_item.work_item_id
            or self.certification.work_item_id != self.work_item.work_item_id
            or self.acceptance.work_item_id != self.work_item.work_item_id
            or self.certification.artifact_key_id != key_id
            or self.acceptance.artifact_key != self.work_item.output_key
            or self.certification.artifact_hash != self.acceptance.artifact_hash
            or self.certification.identity != self.acceptance.certification_id
            or self.candidate_assessment.candidate_hash != self.certification.candidate_hash
            or self.candidate_assessment.context_id != self.certification.context_id
        ):
            raise Protocol27CheckpointError(
                "synthesis checkpoint receipt authority is not exactly cross-bound"
            )
        if not isinstance(self.dependency_artifact_key_ids, (list, tuple)):
            raise Protocol27CheckpointError(
                "synthesis checkpoint dependencies must be an array"
            )
        dependencies = tuple(
            sorted(
                _schema(
                    digest_value,
                    item,
                    "synthesis checkpoint dependency artifact key",
                )
                for item in self.dependency_artifact_key_ids
            )
        )
        expected_dependencies = tuple(
            sorted(item.artifact_key_id for item in self.acceptance.artifact_key.artifact_dependencies)
        )
        if dependencies != expected_dependencies or len(dependencies) != len(set(dependencies)):
            raise Protocol27CheckpointError("synthesis checkpoint dependencies are invalid")
        if not isinstance(self.immutable_object_ids, (list, tuple)):
            raise Protocol27CheckpointError(
                "synthesis checkpoint object inventory must be an array"
            )
        objects = tuple(
            sorted(
                _schema(digest_value, item, "synthesis checkpoint object ID")
                for item in self.immutable_object_ids
            )
        )
        if len(objects) != len(set(objects)):
            raise Protocol27CheckpointError("synthesis checkpoint object inventory is invalid")
        if not isinstance(self.immutable_object_byte_counts, Mapping):
            raise Protocol27CheckpointError(
                "synthesis checkpoint object sizes must be a mapping"
            )
        sizes = dict(sorted(self.immutable_object_byte_counts.items()))
        for object_id in sizes:
            _schema(digest_value, object_id, "synthesis checkpoint sized object ID")
        if set(sizes) != set(objects) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in sizes.values()
        ):
            raise Protocol27CheckpointError("synthesis checkpoint object sizes are invalid")
        required = {
            self.origin_manifest_hash,
            self.origin_event_prefix_hash,
            self.origin_ledger_prefix_hash,
            self.work_item.identity,
            self.candidate_assessment.identity,
            self.certification.identity,
            self.acceptance.identity,
            self.acceptance.artifact_hash,
        }
        if not required <= set(objects):
            raise Protocol27CheckpointError("synthesis checkpoint object closure is incomplete")
        rank = tuple(self.certified_rank)
        if not rank or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in rank
        ):
            raise Protocol27CheckpointError("synthesis checkpoint certified rank is invalid")
        object.__setattr__(self, "dependency_artifact_key_ids", dependencies)
        object.__setattr__(self, "immutable_object_ids", objects)
        object.__setattr__(self, "immutable_object_byte_counts", MappingProxyType(sizes))
        object.__setattr__(self, "certified_rank", rank)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    @property
    def artifact_kind(self) -> str:
        return self.acceptance.artifact_key.artifact_kind

    @property
    def artifact_key_id(self) -> str:
        return self.acceptance.artifact_key.artifact_key_id

    @property
    def artifact_hash(self) -> str:
        return self.acceptance.artifact_hash

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "origin_run_id": self.origin_run_id,
            "origin_manifest_hash": self.origin_manifest_hash,
            "origin_acceptance_event_hash": self.origin_acceptance_event_hash,
            "origin_event_prefix_hash": self.origin_event_prefix_hash,
            "origin_ledger_record_hash": self.origin_ledger_record_hash,
            "origin_ledger_prefix_hash": self.origin_ledger_prefix_hash,
            "work_item": self.work_item.to_json_dict(),
            "candidate_assessment": self.candidate_assessment.to_json_dict(),
            "certification": self.certification.to_json_dict(),
            "acceptance": self.acceptance.to_json_dict(),
            "dependency_artifact_key_ids": list(self.dependency_artifact_key_ids),
            "immutable_object_ids": list(self.immutable_object_ids),
            "immutable_object_byte_counts": dict(self.immutable_object_byte_counts),
            "certified_rank": list(self.certified_rank),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisCheckpointManifestV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            origin_run_id=raw["origin_run_id"],
            origin_manifest_hash=raw["origin_manifest_hash"],
            origin_acceptance_event_hash=raw["origin_acceptance_event_hash"],
            origin_event_prefix_hash=raw["origin_event_prefix_hash"],
            origin_ledger_record_hash=raw["origin_ledger_record_hash"],
            origin_ledger_prefix_hash=raw["origin_ledger_prefix_hash"],
            work_item=SynthesisWorkItemV1.from_json_dict(raw["work_item"]),
            candidate_assessment=SynthesisAssessmentV1.from_json_dict(raw["candidate_assessment"]),
            certification=SynthesisCertificationV1.from_json_dict(raw["certification"]),
            acceptance=SynthesisArtifactAcceptanceV1.from_json_dict(raw["acceptance"]),
            dependency_artifact_key_ids=raw["dependency_artifact_key_ids"],
            immutable_object_ids=raw["immutable_object_ids"],
            immutable_object_byte_counts=raw["immutable_object_byte_counts"],
            certified_rank=raw["certified_rank"],
        )


@dataclass(frozen=True, slots=True)
class SynthesisCheckpointRejectionV1:
    origin_run_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class SynthesisCheckpointInventoryV1:
    by_origin: Mapping[str, tuple[SynthesisCheckpointManifestV1, ...]]
    authority_objects: Mapping[str, Mapping[str, bytes]]
    rejections: tuple[SynthesisCheckpointRejectionV1, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.by_origin, Mapping) or not isinstance(
            self.authority_objects, Mapping
        ):
            raise Protocol27CheckpointError("checkpoint inventory must be mappings")
        for origin, values in self.by_origin.items():
            _schema(safe_id, origin, "checkpoint inventory origin")
            if not isinstance(values, (list, tuple)) or any(
                not isinstance(item, SynthesisCheckpointManifestV1) for item in values
            ):
                raise Protocol27CheckpointError(
                    "checkpoint inventory manifests are invalid"
                )
        origins = {
            origin: tuple(sorted(values, key=lambda item: item.identity))
            for origin, values in sorted(self.by_origin.items())
        }
        if any(
            manifest.origin_run_id != origin
            for origin, values in origins.items()
            for manifest in values
        ):
            raise Protocol27CheckpointError("checkpoint inventory origin mismatch")
        objects: dict[str, Mapping[str, bytes]] = {}
        for manifest_id, values in sorted(self.authority_objects.items()):
            _schema(digest_value, manifest_id, "checkpoint inventory manifest ID")
            if not isinstance(values, Mapping):
                raise Protocol27CheckpointError(
                    "checkpoint inventory authority objects are invalid"
                )
            objects[manifest_id] = MappingProxyType(dict(sorted(values.items())))
        manifests = {item.identity for values in origins.values() for item in values}
        if set(objects) != manifests:
            raise Protocol27CheckpointError("checkpoint inventory object closure mismatch")
        for manifest_id, values in objects.items():
            if any(content_digest(payload) != object_id for object_id, payload in values.items()):
                raise Protocol27CheckpointError(
                    f"checkpoint inventory contains corrupt object: {manifest_id}"
                )
            if manifest_id not in values:
                raise Protocol27CheckpointError("checkpoint inventory omits manifest bytes")
        object.__setattr__(self, "by_origin", MappingProxyType(origins))
        object.__setattr__(self, "authority_objects", MappingProxyType(objects))
        object.__setattr__(self, "rejections", tuple(self.rejections))

    @property
    def manifests(self) -> tuple[SynthesisCheckpointManifestV1, ...]:
        return tuple(item for values in self.by_origin.values() for item in values)

    @classmethod
    def empty(cls) -> "SynthesisCheckpointInventoryV1":
        return cls({}, {})

    def only_origin(self, origin_run_id: str) -> "SynthesisCheckpointInventoryV1":
        values = self.by_origin.get(origin_run_id, ())
        return SynthesisCheckpointInventoryV1(
            {origin_run_id: values} if values else {},
            {item.identity: self.authority_objects[item.identity] for item in values},
        )


@dataclass(frozen=True, slots=True)
class SynthesisCheckpointAdoptionReportV1:
    adoption_receipt_ids: tuple[str, ...]
    work_item_ids: tuple[str, ...]
    artifact_key_ids: tuple[str, ...]
    object_ids: tuple[str, ...]


def reconstruct_synthesis_checkpoints(
    workspace_root: Path,
    *,
    max_stability_attempts: int = 2,
) -> SynthesisCheckpointInventoryV1:
    """Scan stable schema-6 siblings; malformed origins become controlled rejections."""
    if max_stability_attempts <= 0:
        raise ValueError("max_stability_attempts must be positive")
    workspace = Path(workspace_root).resolve()
    runs = workspace / "runs"
    if not runs.is_dir() or runs.is_symlink():
        return SynthesisCheckpointInventoryV1.empty()
    by_origin: dict[str, tuple[SynthesisCheckpointManifestV1, ...]] = {}
    objects: dict[str, Mapping[str, bytes]] = {}
    rejections: list[SynthesisCheckpointRejectionV1] = []
    try:
        candidates = tuple(sorted(runs.iterdir(), key=lambda path: path.name))
    except OSError as exc:
        raise Protocol27CheckpointError(f"cannot enumerate synthesis origins: {exc}") from exc
    for run_dir in candidates:
        if not run_dir.name.startswith("re-"):
            continue
        try:
            result = _reconstruct_origin(workspace, run_dir, max_stability_attempts)
        except Exception as exc:
            rejections.append(
                SynthesisCheckpointRejectionV1(run_dir.name, _controlled_reason(exc))
            )
            continue
        if result is None:
            rejections.append(
                SynthesisCheckpointRejectionV1(run_dir.name, "checkpoint_origin_unstable")
            )
            continue
        manifests, origin_objects = result
        if manifests:
            by_origin[run_dir.name] = manifests
            objects.update(origin_objects)
    return SynthesisCheckpointInventoryV1(by_origin, objects, tuple(rejections))


def _reconstruct_origin(
    workspace: Path,
    run_dir: Path,
    max_stability_attempts: int,
) -> tuple[
    tuple[SynthesisCheckpointManifestV1, ...],
    Mapping[str, Mapping[str, bytes]],
] | None:
    confined = _confined_origin(workspace, run_dir)
    paths = ReV2Paths.for_run(confined)
    for _attempt in range(max_stability_attempts):
        before = (
            _safe_regular_read(paths.manifest),
            _safe_optional_regular_read(paths.events),
            _safe_optional_regular_read(paths.ledger),
        )
        manifest = load_run_manifest(confined)
        if not isinstance(manifest, RunManifestV6):
            return ((), {})
        from .inputs import load_protocol_27_inputs

        inputs = load_protocol_27_inputs(confined)
        events = EventStore(paths, protocol=PROTOCOL_27_EVENTS).replay()
        history, ledger = Protocol27Ledger(inputs).replay_with_history()
        after = (
            _safe_regular_read(paths.manifest),
            _safe_optional_regular_read(paths.events),
            _safe_optional_regular_read(paths.ledger),
        )
        if before != after:
            continue
        store = ObjectStore(paths.objects)
        manifests: list[SynthesisCheckpointManifestV1] = []
        objects_by_manifest: dict[str, Mapping[str, bytes]] = {}
        for key_id, acceptance in sorted(ledger.accepted_artifacts.items()):
            work_item = ledger.accepted_work_items[key_id]
            assessment = ledger.candidate_assessments[work_item.work_item_id]
            certification = ledger.certifications[key_id]
            acceptance_record = ledger.records[("synthesis_artifact_acceptance_v1", key_id)]
            acceptance_event = _acceptance_event(events, acceptance)
            event_prefix = _canonical_event_prefix(events, acceptance_event)
            ledger_prefix = _canonical_ledger_prefix(history, acceptance_record)
            authority = _checkpoint_authority_objects(
                before[0], event_prefix, ledger_prefix, store,
                work_item, assessment, certification, acceptance,
            )
            checkpoint = SynthesisCheckpointManifestV1(
                schema_version=1,
                origin_run_id=manifest.run_id,
                origin_manifest_hash=content_digest(before[0]),
                origin_acceptance_event_hash=acceptance_event.event_hash,
                origin_event_prefix_hash=content_digest(event_prefix),
                origin_ledger_record_hash=acceptance_record.record_hash,
                origin_ledger_prefix_hash=content_digest(ledger_prefix),
                work_item=work_item,
                candidate_assessment=assessment,
                certification=certification,
                acceptance=acceptance,
                dependency_artifact_key_ids=tuple(
                    sorted(item.artifact_key_id for item in acceptance.artifact_key.artifact_dependencies)
                ),
                immutable_object_ids=tuple(sorted(authority)),
                immutable_object_byte_counts={key: len(value) for key, value in authority.items()},
                certified_rank=(1,),
            )
            manifest_bytes = canonical_json_bytes(checkpoint.to_json_dict())
            complete = dict(authority)
            complete[checkpoint.identity] = manifest_bytes
            manifests.append(checkpoint)
            objects_by_manifest[checkpoint.identity] = MappingProxyType(dict(sorted(complete.items())))
        return tuple(sorted(manifests, key=lambda item: item.identity)), objects_by_manifest
    return None


def select_synthesis_checkpoints(
    graph: SynthesisGraph,
    direct_parent: SynthesisCheckpointInventoryV1,
    inventory: SynthesisCheckpointInventoryV1,
) -> SynthesisCheckpointSelectionV1:
    """Select the largest exact dependency closure with direct-parent precedence."""
    if not isinstance(graph, SynthesisGraph):
        raise Protocol27CheckpointError("checkpoint selection requires a synthesis graph")
    if not isinstance(direct_parent, SynthesisCheckpointInventoryV1) or not isinstance(
        inventory, SynthesisCheckpointInventoryV1
    ):
        raise Protocol27CheckpointError("checkpoint selection requires typed inventories")
    parent_ids = {item.identity for item in direct_parent.manifests}
    candidates = {
        item.identity: item for item in (*inventory.manifests, *direct_parent.manifests)
    }

    def solve(
        accepted: Mapping[str, str],
        blocked: frozenset[str],
    ) -> tuple[SynthesisCheckpointManifestV1, ...]:
        ready = tuple(
            item
            for item in graph.ready_work_items(accepted)
            if graph.node_for_work_item(item).node_id not in blocked
        )
        if not ready:
            return ()
        item = ready[0]
        node = graph.node_for_work_item(item)
        exact = [value for value in candidates.values() if value.work_item == item]
        parents = [value for value in exact if value.identity in parent_ids]
        choices = parents or exact
        if not choices:
            return solve(accepted, blocked | {node.node_id})
        ordered = sorted(
            choices,
            key=lambda value: (
                tuple(-rank for rank in value.certified_rank),
                value.artifact_hash,
                value.origin_run_id,
                value.identity,
            ),
        )
        branches: list[tuple[SynthesisCheckpointManifestV1, ...]] = []
        for choice in ordered:
            next_accepted = dict(accepted)
            next_accepted[node.node_id] = choice.artifact_hash
            branches.append((choice, *solve(next_accepted, blocked)))
        return min(
            branches,
            key=lambda values: (
                -len(values),
                tuple(0 if value.identity in parent_ids else 1 for value in values),
                tuple(tuple(-rank for rank in value.certified_rank) for value in values),
                tuple(value.artifact_hash for value in values),
            ),
        )

    selected = solve({}, frozenset())
    selected_ids = {item.identity for item in selected}
    entries: list[SynthesisCheckpointSelectionEntryV1] = []
    copied: dict[str, bytes] = {}
    prefixes: dict[str, SynthesisCheckpointOriginPrefixV1] = {}
    for candidate in selected:
        source_inventory = (
            direct_parent if candidate.identity in parent_ids else inventory
        )
        candidate_objects = source_inventory.authority_objects[candidate.identity]
        for object_id, payload in candidate_objects.items():
            existing = copied.get(object_id)
            if existing is not None and existing != payload:
                raise Protocol27CheckpointError("selected checkpoint object conflict")
            copied[object_id] = payload
        prefix = SynthesisCheckpointOriginPrefixV1(
            1,
            candidate.origin_run_id,
            candidate.origin_manifest_hash,
            candidate.origin_event_prefix_hash,
            candidate.origin_ledger_prefix_hash,
        )
        prefixes[prefix.identity] = prefix
        entries.append(
            SynthesisCheckpointSelectionEntryV1(
                schema_version=1,
                source_kind=(
                    "direct_parent"
                    if candidate.identity in parent_ids
                    else "workspace_checkpoint"
                ),
                checkpoint_manifest_id=candidate.identity,
                origin_run_id=candidate.origin_run_id,
                work_item_id=candidate.work_item.work_item_id,
                artifact_key_id=candidate.artifact_key_id,
                artifact_kind=candidate.artifact_kind,
                artifact_hash=candidate.artifact_hash,
                dependency_artifact_key_ids=tuple(
                    sorted(
                        dependency.artifact_key_id
                        for dependency in candidate.acceptance.artifact_key.artifact_dependencies
                        if dependency.artifact_key_id
                        not in {
                            item.artifact_key_id
                            for item in graph.node_for_work_item(
                                candidate.work_item
                            ).fixed_artifact_dependencies
                        }
                    )
                ),
                copied_object_ids=tuple(sorted(candidate_objects)),
                certified_rank=candidate.certified_rank,
                selection_reason=(
                    "direct-parent-precedence"
                    if candidate.identity in parent_ids
                    else "certified-rank-artifact-hash"
                ),
            )
        )
    dispositions = tuple(
        SynthesisCheckpointDispositionV1(
            1,
            candidate.identity,
            candidate.origin_run_id,
            candidate.work_item.work_item_id,
            candidate.artifact_kind,
            "not_selected",
            "lower-ranked-or-dependency-pruned",
        )
        for candidate in sorted(candidates.values(), key=lambda item: item.identity)
        if candidate.identity not in selected_ids
    )
    selection = SynthesisCheckpointSelectionV1(
        1,
        graph.graph_id,
        tuple(entries),
        dispositions,
        tuple(sorted(copied)),
        tuple(prefixes.values()),
        copied,
    )
    return selection


def stage_synthesis_checkpoint_selection(
    run_dir: Path,
    selection: SynthesisCheckpointSelectionV1,
) -> Mapping[str, bytes]:
    """Validate frozen selection bytes; optionally verify them in an existing store."""
    copied = getattr(selection, "_copied_objects", None)
    if not isinstance(copied, Mapping) or set(copied) != set(selection.copied_object_ids):
        raise Protocol27CheckpointError("checkpoint selection has no staged object closure")
    validated: dict[str, bytes] = {}
    for object_id, payload in copied.items():
        if not isinstance(payload, bytes) or content_digest(payload) != object_id:
            raise Protocol27CheckpointError("checkpoint selection contains corrupt bytes")
        validated[object_id] = payload
    path = Path(run_dir)
    if (path / "v2" / "objects").is_dir():
        store = ObjectStore(path / "v2" / "objects")
        for object_id, payload in validated.items():
            if store.put_blob(payload) != object_id:
                raise Protocol27CheckpointError("checkpoint staged object identity changed")
    return MappingProxyType(dict(sorted(validated.items())))


def adopt_synthesis_checkpoints(
    context: object,
) -> SynthesisCheckpointAdoptionReportV1:
    """Import the child's frozen checkpoint receipts and events before dispatch."""
    from .inputs import ValidatedProtocol27Inputs

    inputs = getattr(context, "inputs", context)
    if not isinstance(inputs, ValidatedProtocol27Inputs):
        raise Protocol27CheckpointError("checkpoint adoption requires validated inputs")
    ledger = getattr(context, "ledger", Protocol27Ledger(inputs))
    event_store = getattr(
        context,
        "event_store",
        EventStore(inputs.paths, protocol=PROTOCOL_27_EVENTS),
    )
    clock: Callable[[], str] = getattr(context, "clock", lambda: inputs.manifest.created_at)
    try:
        history = event_store.replay()
        if not history or not any(item.type == "work_planned" for item in history):
            raise Protocol27CheckpointError(
                "checkpoint adoption requires run creation and frozen work planning"
            )
        selected_work = {
            entry.work_item_id for entry in inputs.checkpoint_selection.entries
        }
        if any(
            item.type == "dispatch_started"
            and item.payload.get("work_item_id") in selected_work
            for item in history
        ):
            raise Protocol27CheckpointError(
                "checkpoint adoption must precede every selected synthesis dispatch"
            )
        # Preflight the complete frozen closure before the first receipt append.
        # This makes post-freeze corruption a terminal all-or-nothing conflict.
        for object_id in inputs.checkpoint_selection.copied_object_ids:
            payload = inputs.checkpoint_objects.get(object_id)
            if payload is None or content_digest(payload) != object_id:
                raise Protocol27CheckpointError(
                    "post-freeze checkpoint object is missing or corrupt"
                )
            if ledger.object_store.put_blob(payload) != object_id:
                raise Protocol27CheckpointError(
                    "post-freeze checkpoint copy changed identity"
                )
        adopted: list[SynthesisCheckpointAdoptionReceiptV1] = []
        for entry in inputs.checkpoint_selection.entries:
            manifest = load_canonical_object(
                inputs.checkpoint_objects[entry.checkpoint_manifest_id],
                SynthesisCheckpointManifestV1.from_json_dict,
            )
            if (
                manifest.work_item.work_item_id != entry.work_item_id
                or manifest.artifact_key_id != entry.artifact_key_id
                or manifest.artifact_hash != entry.artifact_hash
                or set(manifest.immutable_object_ids)
                != set(entry.copied_object_ids) - {entry.checkpoint_manifest_id}
            ):
                raise Protocol27CheckpointError("post-freeze checkpoint selection conflict")
            expected_prefix = SynthesisCheckpointOriginPrefixV1(
                1,
                manifest.origin_run_id,
                manifest.origin_manifest_hash,
                manifest.origin_event_prefix_hash,
                manifest.origin_ledger_prefix_hash,
            )
            if expected_prefix not in inputs.checkpoint_selection.origin_prefixes:
                raise Protocol27CheckpointError(
                    "post-freeze checkpoint origin prefix conflict"
                )
            ledger.record_candidate_assessment(manifest.candidate_assessment)
            ledger.record_synthesis_certification(manifest.certification)
            ledger.record_synthesis_acceptance(manifest.acceptance)
            adoption = SynthesisCheckpointAdoptionReceiptV1(
                1,
                manifest.origin_run_id,
                manifest.work_item.work_item_id,
                manifest.artifact_key_id,
                manifest.artifact_hash,
                manifest.certification.identity,
                manifest.acceptance.identity,
            )
            ledger.record_checkpoint_adoption(adoption)
            checkpoint_payload = {
                "acceptance_receipt_id": manifest.acceptance.identity,
                "adoption_receipt_id": adoption.identity,
                "artifact_hash": manifest.artifact_hash,
                "artifact_key_id": manifest.artifact_key_id,
                "certification_id": manifest.certification.identity,
                "work_item_id": manifest.work_item.work_item_id,
            }
            replay = event_store.replay()
            checkpoint_events = tuple(
                item
                for item in replay
                if item.type == "checkpoint_adopted"
                and item.payload.get("work_item_id") == manifest.work_item.work_item_id
            )
            if not checkpoint_events:
                event_store.append(
                    "checkpoint_adopted",
                    checkpoint_payload,
                    occurred_at=clock(),
                )
            elif len(checkpoint_events) != 1 or any(
                checkpoint_events[0].payload.get(key) != value
                for key, value in checkpoint_payload.items()
            ):
                raise Protocol27CheckpointError(
                    "post-freeze checkpoint adoption event conflicts with selection"
                )
            acceptance_payload = {
                "acceptance_receipt_id": manifest.acceptance.identity,
                "adopted": True,
                "artifact_hash": manifest.artifact_hash,
                "artifact_key_id": manifest.artifact_key_id,
                "certification_id": manifest.certification.identity,
                "generated_dependency_key_ids": tuple(
                    entry.dependency_artifact_key_ids
                ),
                "work_item_id": manifest.work_item.work_item_id,
            }
            replay = event_store.replay()
            acceptance_events = tuple(
                item
                for item in replay
                if item.type == "synthesis_artifact_accepted"
                and item.payload.get("work_item_id") == manifest.work_item.work_item_id
            )
            if not acceptance_events:
                event_store.append(
                    "synthesis_artifact_accepted",
                    acceptance_payload,
                    occurred_at=clock(),
                )
            elif len(acceptance_events) != 1 or any(
                acceptance_events[0].payload.get(key) != value
                for key, value in acceptance_payload.items()
            ):
                raise Protocol27CheckpointError(
                    "post-freeze checkpoint acceptance event conflicts with selection"
                )
            adopted.append(adoption)
        return SynthesisCheckpointAdoptionReportV1(
            tuple(item.identity for item in adopted),
            tuple(item.work_item_id for item in adopted),
            tuple(item.artifact_key_id for item in adopted),
            inputs.checkpoint_selection.copied_object_ids,
        )
    except Protocol27CheckpointError:
        raise
    except (KeyError, OSError, ReV2LedgerError, ValueError) as exc:
        raise Protocol27CheckpointError(
            f"post-freeze checkpoint authority cannot be adopted: {exc}"
        ) from exc


def _checkpoint_authority_objects(
    manifest_bytes: bytes,
    event_prefix: bytes,
    ledger_prefix: bytes,
    store: ObjectStore,
    work_item: SynthesisWorkItemV1,
    assessment: SynthesisAssessmentV1,
    certification: SynthesisCertificationV1,
    acceptance: SynthesisArtifactAcceptanceV1,
) -> Mapping[str, bytes]:
    payloads = (
        manifest_bytes,
        event_prefix,
        ledger_prefix,
        canonical_json_bytes(work_item.to_json_dict()),
        canonical_json_bytes(assessment.to_json_dict()),
        canonical_json_bytes(certification.to_json_dict()),
        canonical_json_bytes(acceptance.to_json_dict()),
    )
    result = {content_digest(payload): payload for payload in payloads}
    object_ids = {
        acceptance.artifact_hash,
        *(item.artifact_hash for item in acceptance.artifact_key.artifact_dependencies),
        *acceptance.artifact_key.non_artifact_dependency_hashes,
        *acceptance.artifact_key.debt_manifest_hashes,
    }
    for object_id in object_ids:
        result[object_id] = store.read_blob(object_id)
    return MappingProxyType(dict(sorted(result.items())))


def _acceptance_event(
    events: tuple[EventRecord, ...],
    acceptance: SynthesisArtifactAcceptanceV1,
) -> EventRecord:
    matches = tuple(
        event
        for event in events
        if event.type == "synthesis_artifact_accepted"
        and event.payload.get("acceptance_receipt_id") == acceptance.identity
        and event.payload.get("artifact_key_id") == acceptance.artifact_key.artifact_key_id
        and event.payload.get("artifact_hash") == acceptance.artifact_hash
        and event.payload.get("certification_id") == acceptance.certification_id
        and event.payload.get("work_item_id") == acceptance.work_item_id
    )
    if len(matches) != 1:
        raise Protocol27CheckpointError(
            "accepted synthesis artifact has no unique acceptance event"
        )
    return matches[0]


def _canonical_event_prefix(
    history: tuple[EventRecord, ...], terminal: EventRecord
) -> bytes:
    index = history.index(terminal)
    return b"".join(
        canonical_json_bytes(item.to_json_dict()) for item in history[: index + 1]
    )


def _canonical_ledger_prefix(
    history: tuple[LedgerRecord, ...], terminal: LedgerRecord
) -> bytes:
    index = history.index(terminal)
    return b"".join(
        canonical_json_bytes(item.to_json_dict()) for item in history[: index + 1]
    )


def _confined_origin(workspace_root: Path, run_dir: Path) -> Path:
    runs = workspace_root / "runs"
    if run_dir.parent != runs or not run_dir.name.startswith("re-"):
        raise Protocol27CheckpointError("checkpoint origin is outside workspace runs")
    metadata = os.lstat(run_dir)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise Protocol27CheckpointError("checkpoint origin is not a real directory")
    resolved = run_dir.resolve()
    if resolved.parent != runs.resolve():
        raise Protocol27CheckpointError("checkpoint origin escapes workspace runs")
    return resolved


def _safe_regular_read(path: Path) -> bytes:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise Protocol27CheckpointError("checkpoint authority is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise Protocol27CheckpointError("checkpoint authority changed during open")
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
    if "missing" in message or "no such file" in message:
        return "checkpoint_object_missing"
    if "cycle" in message:
        return "checkpoint_cycle_detected"
    if "receipt" in message or "certification" in message or "acceptance" in message:
        return "checkpoint_receipt_invalid"
    return "checkpoint_manifest_invalid"


__all__ = (
    "Protocol27CheckpointError",
    "SynthesisCheckpointAdoptionReportV1",
    "SynthesisCheckpointInventoryV1",
    "SynthesisCheckpointManifestV1",
    "SynthesisCheckpointRejectionV1",
    "adopt_synthesis_checkpoints",
    "reconstruct_synthesis_checkpoints",
    "select_synthesis_checkpoints",
    "stage_synthesis_checkpoint_selection",
)

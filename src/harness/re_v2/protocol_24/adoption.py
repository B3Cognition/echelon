"""Validation and self-contained adoption of completed RE v2 parents."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventRecord, EventStore, ReV2EventError
from harness.re_v2.ledger import (
    LedgerRecord,
    ObjectStore,
    ReV2LedgerError,
)
from harness.re_v2.run_store import (
    ReV2Paths,
    ReV2RunStoreError,
    load_run_manifest,
)
from harness.re_v2.snapshot import (
    CapturedSnapshot,
    ReV2SnapshotError,
    load_snapshot_manifest,
    validate_source_snapshot,
)
from harness.re_v2.workspace_snapshot import (
    ReV2WorkspaceSourceError,
    plan_clean_workspace_sources,
)
from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    Protocol22Graph,
    build_protocol_22_graph,
    plan_next_v22,
)
from harness.re_v2.protocol_22.inputs import (
    ValidatedProtocol22Inputs,
    load_protocol_22_inputs,
)
from harness.re_v2.protocol_22.ledger import (
    Protocol22Ledger,
    Protocol22LedgerView,
)
from harness.re_v2.protocol_22.model import RunManifestV2, WorkTemplateV2
from harness.re_v2.protocol_26.adoption import (
    FrozenAcceptancePackageV1,
    Protocol26AdoptionError,
    import_typed_acceptance,
)

from .model import (
    AdoptedArtifactAuthorityV1,
    ParentAuthorityBundleV1,
    RunManifestV3,
)
from .events import PROTOCOL_24_EVENTS
from .graph import (
    Protocol24Graph,
    build_protocol_24_graph,
    reconstruct_adopted_parent_closure,
)
from .inputs import ValidatedProtocol24Inputs, load_protocol_24_inputs


class Protocol24AdoptionError(RuntimeError):
    """Raised when parent authority cannot be safely adopted."""


@dataclass(frozen=True, slots=True)
class ValidatedParentV1:
    run_dir: Path
    paths: ReV2Paths
    manifest: RunManifestV2 | RunManifestV3
    inputs: ValidatedProtocol22Inputs | ValidatedProtocol24Inputs
    graph: Protocol22Graph | Protocol24Graph
    events: tuple[EventRecord, ...]
    ledger: Protocol22LedgerView
    ledger_history: tuple[LedgerRecord, ...]
    manifest_bytes: bytes
    event_chain_bytes: bytes
    ledger_chain_bytes: bytes
    accepted_parent: Mapping[
        str,
        tuple[WorkTemplateV2, AcceptedArtifactV2],
    ]
    ancestor_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "accepted_parent",
            MappingProxyType(dict(sorted(self.accepted_parent.items()))),
        )
        object.__setattr__(
            self,
            "ancestor_objects",
            MappingProxyType(dict(sorted(self.ancestor_objects.items()))),
        )


@dataclass(frozen=True, slots=True)
class AdoptionReportV1:
    artifact_count: int
    certification_count: int
    candidate_assessment_count: int
    artifact_key_ids: tuple[str, ...]
    receipt_ids: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "artifact_count": self.artifact_count,
            "certification_count": self.certification_count,
            "candidate_assessment_count": self.candidate_assessment_count,
            "artifact_key_ids": list(self.artifact_key_ids),
            "receipt_ids": list(self.receipt_ids),
        }


class _UnlimitedBudget:
    def item_attempt_available(self, _work_item: object) -> bool:
        return True

    def run_budget_available(self, _work_item: object) -> bool:
        return True


def validate_parent_for_deepening(
    parent_run: Path,
    workspace: Path,
) -> ValidatedParentV1:
    """Authenticate a completed schema-2/3 parent and its current clean sources."""
    run_dir, workspace_root = _validated_run_path(parent_run, workspace)
    try:
        paths = ReV2Paths.for_run(run_dir)
        manifest = load_run_manifest(run_dir)
        from harness.re_v2.protocol_26.model import RunManifestV5

        if isinstance(manifest, RunManifestV5):
            return _validate_schema5_parent(
                run_dir,
                workspace_root,
                paths,
                manifest,
            )
        if isinstance(manifest, RunManifestV3):
            return _validate_schema3_parent(
                run_dir,
                workspace_root,
                paths,
                manifest,
            )
        if not isinstance(manifest, RunManifestV2):
            raise Protocol24AdoptionError(
                "deepening requires a completed schema-2 or schema-3 parent"
            )
        manifest_bytes = _stable_read(paths.manifest, "parent manifest")
        if manifest_bytes != canonical_json_bytes(manifest.to_json_dict()):
            raise Protocol24AdoptionError("parent manifest changed during validation")
        inputs = load_protocol_22_inputs(paths, manifest)
        graph = build_protocol_22_graph(manifest, inputs)

        event_before = _stable_optional_read(paths.events, "parent event chain")
        events = EventStore(paths, protocol=PROTOCOL_22_EVENTS).replay()
        event_after = _stable_optional_read(paths.events, "parent event chain")
        if event_before != event_after:
            raise Protocol24AdoptionError(
                "parent event chain changed during validation"
            )
        _validate_terminal_events(events, manifest)

        objects = ObjectStore(paths.objects)
        ledger_before = _stable_read(paths.ledger, "parent ledger chain")
        ledger_history, ledger = Protocol22Ledger(
            paths,
            objects,
        ).replay_with_history()
        ledger_after = _stable_read(paths.ledger, "parent ledger chain")
        if ledger_before != ledger_after:
            raise Protocol24AdoptionError(
                "parent ledger chain changed during validation"
            )
        accepted_parent = _validate_complete_authority(graph, ledger, events)
        _validate_workspace_sources(workspace_root, manifest)
        return ValidatedParentV1(
            run_dir=run_dir,
            paths=paths,
            manifest=manifest,
            inputs=inputs,
            graph=graph,
            events=events,
            ledger=ledger,
            ledger_history=ledger_history,
            manifest_bytes=manifest_bytes,
            event_chain_bytes=event_after,
            ledger_chain_bytes=ledger_after,
            accepted_parent=accepted_parent,
            ancestor_objects={},
        )
    except Protocol24AdoptionError:
        raise
    except (
        OSError,
        ReV2RunStoreError,
        ReV2EventError,
        ReV2LedgerError,
        ReV2SnapshotError,
    ) as exc:
        raise Protocol24AdoptionError(
            f"cannot validate parent authority: {exc}"
        ) from exc


def _validate_schema5_parent(
    run_dir: Path,
    workspace_root: Path,
    paths: ReV2Paths,
    manifest: object,
) -> ValidatedParentV1:
    """Authenticate a completed self-contained protocol-2.6 L1/L2 parent."""
    from harness.re_v2.protocol_22.graph import build_protocol_22_graph
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5

    if not isinstance(manifest, RunManifestV5) or manifest.target_layer not in {
        "L1",
        "L2",
    }:
        raise Protocol24AdoptionError(
            "deepening requires a completed protocol-2.6 L1 or L2 parent"
        )
    manifest_bytes = _stable_read(paths.manifest, "parent manifest")
    if manifest_bytes != canonical_json_bytes(manifest.to_json_dict()):
        raise Protocol24AdoptionError("parent manifest changed during validation")
    outer_inputs = load_protocol_26_inputs(paths, manifest)
    layer_manifest = outer_inputs.layer_execution_contract.layer_manifest
    inputs = outer_inputs.layer_inputs
    if isinstance(layer_manifest, RunManifestV3):
        ancestor_objects = _validate_schema3_lineage(paths, layer_manifest, inputs)
    elif isinstance(layer_manifest, RunManifestV2):
        ancestor_objects = MappingProxyType({})
    else:
        raise Protocol24AdoptionError(
            "protocol-2.6 parent layer contract is not eligible for deepening"
        )

    event_before = _stable_optional_read(paths.events, "parent event chain")
    events = EventStore(
        paths,
        protocol=protocol_26_events_for(manifest.target_layer),
    ).replay()
    event_after = _stable_optional_read(paths.events, "parent event chain")
    if event_before != event_after:
        raise Protocol24AdoptionError("parent event chain changed during validation")
    _validate_terminal_events(events, manifest)

    objects = ObjectStore(paths.objects)
    ledger_before = _stable_read(paths.ledger, "parent ledger chain")
    ledger_history, ledger = Protocol22Ledger(paths, objects).replay_with_history()
    ledger_after = _stable_read(paths.ledger, "parent ledger chain")
    if ledger_before != ledger_after:
        raise Protocol24AdoptionError("parent ledger chain changed during validation")

    if isinstance(layer_manifest, RunManifestV3):
        adopted = reconstruct_adopted_parent_closure(
            inputs.parent_authority_bundle,
            ledger,
        )
        graph = build_protocol_24_graph(layer_manifest, inputs, adopted)
        current = _validate_complete_authority(graph, ledger, events)
        accepted_parent = dict(adopted)
        accepted_parent.update(current)
    else:
        graph = build_protocol_22_graph(layer_manifest, inputs)
        accepted_parent = dict(_validate_complete_authority(graph, ledger, events))
    if set(ledger.accepted_artifacts) != {
        artifact.artifact_key_id for _template, artifact in accepted_parent.values()
    }:
        raise Protocol24AdoptionError(
            "protocol-2.6 parent accepted closure does not cover its ledger"
        )
    _validate_workspace_sources(workspace_root, manifest)
    return ValidatedParentV1(
        run_dir=run_dir,
        paths=paths,
        manifest=manifest,
        inputs=inputs,
        graph=graph,
        events=events,
        ledger=ledger,
        ledger_history=ledger_history,
        manifest_bytes=manifest_bytes,
        event_chain_bytes=event_after,
        ledger_chain_bytes=ledger_after,
        accepted_parent=accepted_parent,
        ancestor_objects=ancestor_objects,
    )


def _validate_schema3_parent(
    run_dir: Path,
    workspace_root: Path,
    paths: ReV2Paths,
    manifest: RunManifestV3,
) -> ValidatedParentV1:
    manifest_bytes = _stable_read(paths.manifest, "parent manifest")
    if manifest_bytes != canonical_json_bytes(manifest.to_json_dict()):
        raise Protocol24AdoptionError("parent manifest changed during validation")
    inputs = load_protocol_24_inputs(paths, manifest)
    ancestor_objects = _validate_schema3_lineage(paths, manifest, inputs)

    event_before = _stable_optional_read(paths.events, "parent event chain")
    events = EventStore(paths, protocol=PROTOCOL_24_EVENTS).replay()
    event_after = _stable_optional_read(paths.events, "parent event chain")
    if event_before != event_after:
        raise Protocol24AdoptionError("parent event chain changed during validation")
    _validate_terminal_events(events, manifest)

    objects = ObjectStore(paths.objects)
    ledger_before = _stable_read(paths.ledger, "parent ledger chain")
    ledger_history, ledger = Protocol22Ledger(
        paths,
        objects,
    ).replay_with_history()
    ledger_after = _stable_read(paths.ledger, "parent ledger chain")
    if ledger_before != ledger_after:
        raise Protocol24AdoptionError("parent ledger chain changed during validation")
    adopted = reconstruct_adopted_parent_closure(
        inputs.parent_authority_bundle,
        ledger,
    )
    graph = build_protocol_24_graph(manifest, inputs, adopted)
    current = _validate_complete_authority(graph, ledger, events)
    accepted_parent = dict(adopted)
    accepted_parent.update(current)
    accepted_keys = {
        item.artifact_key_id for _template, item in accepted_parent.values()
    }
    if accepted_keys != set(ledger.accepted_artifacts):
        raise Protocol24AdoptionError(
            "schema-3 parent accepted closure does not cover its complete ledger"
        )
    _validate_workspace_sources(workspace_root, manifest)
    return ValidatedParentV1(
        run_dir=run_dir,
        paths=paths,
        manifest=manifest,
        inputs=inputs,
        graph=graph,
        events=events,
        ledger=ledger,
        ledger_history=ledger_history,
        manifest_bytes=manifest_bytes,
        event_chain_bytes=event_after,
        ledger_chain_bytes=ledger_after,
        accepted_parent=accepted_parent,
        ancestor_objects=ancestor_objects,
    )


def build_parent_authority_bundle(
    parent: ValidatedParentV1,
) -> tuple[ParentAuthorityBundleV1, Mapping[str, bytes]]:
    """Build immutable parent provenance without rewriting nested receipts."""
    if not isinstance(parent, ValidatedParentV1):
        raise Protocol24AdoptionError(
            "parent authority bundle requires ValidatedParentV1"
        )
    artifacts: list[AdoptedArtifactAuthorityV1] = []
    for artifact_key_id, acceptance in sorted(parent.ledger.accepted_artifacts.items()):
        certification = parent.ledger.certifications.get(
            acceptance.certification_receipt_id
        )
        if certification is None:
            raise Protocol24AdoptionError(
                "accepted parent artifact has no certification receipt"
            )
        candidate_matches = tuple(
            candidate
            for candidate in parent.ledger.candidate_assessments.values()
            if candidate.certification_receipt_id == certification.identity
            and candidate.outcome == "certified"
        )
        if len(candidate_matches) > 1:
            raise Protocol24AdoptionError(
                "accepted parent artifact has ambiguous candidate authority"
            )
        record = parent.ledger.artifact_acceptance_records.get(acceptance.identity)
        if record is None:
            raise Protocol24AdoptionError(
                "accepted parent artifact has no ledger record"
            )
        artifacts.append(
            AdoptedArtifactAuthorityV1(
                schema_version=1,
                artifact_key_id=artifact_key_id,
                artifact_hash=acceptance.artifact_hash,
                dependency_hashes=acceptance.artifact_key.dependency_hashes,
                certification_receipt_id=certification.identity,
                candidate_assessment_id=(
                    candidate_matches[0].identity if candidate_matches else None
                ),
                artifact_acceptance_receipt_id=acceptance.identity,
                source_run_id=parent.manifest.run_id,
                source_ledger_entry_hash=record.record_hash,
            )
        )
    if not artifacts:
        raise Protocol24AdoptionError("completed parent has no accepted artifacts")

    manifest_hash = content_digest(parent.manifest_bytes)
    event_chain_hash = content_digest(parent.event_chain_bytes)
    ledger_chain_hash = content_digest(parent.ledger_chain_bytes)
    bundle = ParentAuthorityBundleV1(
        schema_version=1,
        direct_parent_run_id=parent.manifest.run_id,
        source_manifest_hash=manifest_hash,
        source_event_chain_hash=event_chain_hash,
        source_terminal_event_hash=parent.events[-1].event_hash,
        source_ledger_chain_hash=ledger_chain_hash,
        lineage_root_run_id=(
            parent.manifest.parent_lineage.lineage_root_run_id
            if isinstance(parent.manifest, RunManifestV3)
            else parent.manifest.run_id
        ),
        ancestor_bundle_hashes=tuple(sorted(parent.ancestor_objects)),
        artifacts=tuple(artifacts),
    )
    objects = {
        manifest_hash: parent.manifest_bytes,
        event_chain_hash: parent.event_chain_bytes,
        ledger_chain_hash: parent.ledger_chain_bytes,
        **parent.ancestor_objects,
    }
    return bundle, MappingProxyType(dict(sorted(objects.items())))


def import_parent_acceptance_closure(
    parent: ValidatedParentV1,
    child_objects: ObjectStore,
    child_ledger: Protocol22Ledger,
) -> AdoptionReportV1:
    """Copy required blobs and append existing typed receipts idempotently."""
    if not isinstance(parent, ValidatedParentV1):
        raise Protocol24AdoptionError("adoption requires ValidatedParentV1")
    if not isinstance(child_objects, ObjectStore) or not isinstance(
        child_ledger, Protocol22Ledger
    ):
        raise Protocol24AdoptionError(
            "adoption requires the existing object-store and typed-ledger facades"
        )
    source_objects = ObjectStore(parent.paths.objects)
    receipt_ids: set[str] = set()
    candidates = 0
    try:
        for artifact_key_id, acceptance in sorted(
            parent.ledger.accepted_artifacts.items()
        ):
            certification = parent.ledger.certifications[
                acceptance.certification_receipt_id
            ]
            work_item = parent.ledger.certification_work_items[certification.identity]
            matches = tuple(
                candidate
                for candidate in parent.ledger.candidate_assessments.values()
                if candidate.certification_receipt_id == certification.identity
                and candidate.outcome == "certified"
            )
            if len(matches) > 1:
                raise Protocol24AdoptionError(
                    f"ambiguous candidate authority for {artifact_key_id}"
                )
            candidate = None if not matches else matches[0]
            object_ids = {acceptance.artifact_hash}
            if candidate is not None:
                object_ids.add(candidate.execution_capture_hash)
                if candidate.normalized_authorial_payload_hash is not None:
                    object_ids.add(candidate.normalized_authorial_payload_hash)
            package = FrozenAcceptancePackageV1(
                work_item=work_item,
                certification=certification,
                candidate_assessment=candidate,
                acceptance=acceptance,
                required_objects={
                    object_hash: source_objects.read_blob(object_hash)
                    for object_hash in sorted(object_ids)
                },
            )
            imported = import_typed_acceptance(
                package,
                child_objects,
                child_ledger,
            )
            receipt_ids.update(imported.receipt_ids)
            candidates += candidate is not None
        replayed = child_ledger.replay()
    except (KeyError, ReV2LedgerError, Protocol26AdoptionError) as exc:
        raise Protocol24AdoptionError(f"cannot import parent authority: {exc}") from exc
    if any(
        replayed.accepted_artifacts.get(key) != receipt
        for key, receipt in parent.ledger.accepted_artifacts.items()
    ):
        raise Protocol24AdoptionError(
            "imported ledger does not equal the parent acceptance authority"
        )
    keys = tuple(sorted(parent.ledger.accepted_artifacts))
    return AdoptionReportV1(
        artifact_count=len(keys),
        certification_count=len(
            {
                receipt.certification_receipt_id
                for receipt in parent.ledger.accepted_artifacts.values()
            }
        ),
        candidate_assessment_count=candidates,
        artifact_key_ids=keys,
        receipt_ids=tuple(sorted(receipt_ids)),
    )


def _validated_run_path(parent_run: Path, workspace: Path) -> tuple[Path, Path]:
    workspace_root = Path(workspace)
    if workspace_root.is_symlink() or not workspace_root.is_dir():
        raise Protocol24AdoptionError("workspace must be a real directory")
    workspace_root = workspace_root.resolve()
    runs = workspace_root / "runs"
    if runs.is_symlink() or not runs.is_dir():
        raise Protocol24AdoptionError("workspace runs directory is missing or unsafe")
    candidate = Path(parent_run)
    if candidate.is_symlink() or not candidate.is_dir():
        raise Protocol24AdoptionError(
            "parent run must be a real directory, not a symlink"
        )
    resolved = candidate.resolve()
    if resolved.parent != runs.resolve() or candidate.absolute() != resolved:
        raise Protocol24AdoptionError(
            "parent run must be a direct child beneath the workspace runs directory"
        )
    return resolved, workspace_root


def _validate_terminal_events(
    events: tuple[EventRecord, ...],
    manifest: RunManifestV2 | RunManifestV3,
) -> None:
    if not events or events[0].type != "run_created":
        raise Protocol24AdoptionError(
            "parent is not completed: no authenticated run creation"
        )
    if events[0].payload.get("run_manifest_id") != manifest.identity:
        raise Protocol24AdoptionError("parent run_created does not match its manifest")
    terminal = tuple(
        event for event in events if event.type in {"run_completed", "run_failed"}
    )
    if (
        len(terminal) != 1
        or terminal[0] is not events[-1]
        or terminal[0].type != "run_completed"
    ):
        raise Protocol24AdoptionError(
            "parent must have exactly one authenticated completed terminal state"
        )


def _validate_complete_authority(
    graph: Protocol22Graph | Protocol24Graph,
    ledger: Protocol22LedgerView,
    events: tuple[EventRecord, ...],
) -> Mapping[str, tuple[WorkTemplateV2, AcceptedArtifactV2]]:
    if ledger.work_item_failures or ledger.executor_failures:
        raise Protocol24AdoptionError(
            "completed parent contains terminal failure receipts"
        )
    decision = plan_next_v22(graph, ledger, _UnlimitedBudget())
    if decision.ready or any(
        explanation.action != "reuse" for explanation in decision.explanations.values()
    ):
        raise Protocol24AdoptionError(
            "parent completion is partial or does not cover its exact graph"
        )
    acceptance_events: dict[str, EventRecord] = {}
    for event in events:
        if event.type == "artifact_accepted":
            acceptance_events[str(event.payload["artifact_key_id"])] = event
        elif event.type in {"artifact_adopted", "checkpoint_artifact_adopted"}:
            authority = AdoptedArtifactAuthorityV1.from_json_dict(
                event.payload["adopted_artifact_authority"]
            )
            acceptance_events[authority.artifact_key_id] = event
    if set(acceptance_events) != set(ledger.accepted_artifacts):
        raise Protocol24AdoptionError(
            "parent events and accepted ledger artifacts disagree"
        )
    closure: dict[str, tuple[WorkTemplateV2, AcceptedArtifactV2]] = {}
    for template in graph.templates:
        explanation = decision.explanations[template.template_id]
        if explanation.work_item_id is None:
            raise Protocol24AdoptionError("accepted parent work identity is missing")
        work_item = next(
            (
                item
                for item in ledger.certification_work_items.values()
                if item.work_item_id == explanation.work_item_id
            ),
            None,
        )
        if work_item is None or work_item.template_id != template.template_id:
            raise Protocol24AdoptionError(
                "accepted parent template/work identity is inconsistent"
            )
        artifact = ledger.artifact_for_key(work_item.output_key.identity)
        if artifact is None:
            raise Protocol24AdoptionError("accepted parent artifact is missing")
        event = acceptance_events[artifact.artifact_key_id]
        acceptance = ledger.accepted_artifacts[artifact.artifact_key_id]
        if event.type in {"artifact_adopted", "checkpoint_artifact_adopted"}:
            authority = AdoptedArtifactAuthorityV1.from_json_dict(
                event.payload["adopted_artifact_authority"]
            )
            event_matches = (
                authority.artifact_hash == artifact.artifact_hash
                and authority.certification_receipt_id
                == acceptance.certification_receipt_id
                and event.payload.get("work_item_id") == work_item.work_item_id
            )
        else:
            event_matches = (
                event.payload.get("artifact_hash") == artifact.artifact_hash
                and event.payload.get("certification_receipt_id")
                == acceptance.certification_receipt_id
                and event.payload.get("work_item_id") == work_item.work_item_id
            )
        if not event_matches:
            raise Protocol24AdoptionError(
                "parent artifact event does not match ledger authority"
            )
        closure[template.template_id] = (template, artifact)
    return MappingProxyType(dict(sorted(closure.items())))


def _validate_workspace_sources(
    workspace: Path,
    manifest: RunManifestV2 | RunManifestV3,
) -> None:
    configured = os.environ.get("ECHELON_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".echelon"
    bundle = (base / "re-v2" / "snapshots" / manifest.source_snapshot_id).resolve(
        strict=False
    )
    snapshot = CapturedSnapshot(
        snapshot_id=manifest.source_snapshot_id,
        kind=manifest.source_snapshot_kind,
        read_root=bundle / "source",
        manifest_path=bundle / "manifest.json",
    )
    validate_source_snapshot(snapshot)
    snapshot_manifest = load_snapshot_manifest(snapshot)
    components = snapshot_manifest.components
    if components is None:
        raise Protocol24AdoptionError("parent snapshot has no workspace components")
    declarations = tuple(
        SimpleNamespace(
            id=component.source_id,
            path=component.workspace_path,
            git_role=component.git_role,
        )
        for component in components
    )
    try:
        plan = plan_clean_workspace_sources(workspace, declarations)
    except ReV2WorkspaceSourceError as exc:
        raise Protocol24AdoptionError(
            f"sources must be clean before deepening: {exc}\n"
            "Commit, stash (including untracked files), or revert the source changes, then retry."
        ) from exc
    expected = {
        component.source_id: (
            component.workspace_path,
            component.repository_path,
            component.commit,
        )
        for component in components
    }
    actual = {
        proof.source_id: (
            proof.workspace_path,
            proof.repository_path,
            proof.commit,
        )
        for proof in plan.sources
    }
    if actual != expected:
        raise Protocol24AdoptionError(
            "source commits do not match the parent snapshot; restore the exact parent commits before deepening"
        )


def _validate_schema3_lineage(
    paths: ReV2Paths,
    manifest: RunManifestV3,
    inputs: ValidatedProtocol24Inputs | None = None,
) -> Mapping[str, bytes]:
    objects = ObjectStore(paths.objects)
    active: set[str] = set()
    retained: dict[str, bytes] = {}

    def visit_payload(
        object_hash: str,
        payload: bytes,
        *,
        require_bundle: bool,
    ) -> None:
        if object_hash in active:
            raise Protocol24AdoptionError("schema-3 parent lineage contains a cycle")
        active.add(object_hash)
        retained[object_hash] = payload
        try:
            try:
                value = json.loads(payload)
            except Exception:
                if require_bundle:
                    raise Protocol24AdoptionError(
                        "schema-3 parent authority bundle is invalid"
                    )
                return
            if not isinstance(value, dict) or set(value) != set(
                ParentAuthorityBundleV1.FIELDS
            ):
                if require_bundle:
                    raise Protocol24AdoptionError(
                        "schema-3 parent authority bundle is invalid"
                    )
                return
            try:
                bundle = ParentAuthorityBundleV1.from_json_dict(value)
            except Exception as exc:
                raise Protocol24AdoptionError(
                    "schema-3 parent authority bundle is invalid"
                ) from exc
            if inputs is not None:
                for chain_hash in (
                    bundle.source_manifest_hash,
                    bundle.source_event_chain_hash,
                    bundle.source_ledger_chain_hash,
                ):
                    retained[chain_hash] = objects.read_blob(chain_hash)
            for ancestor in bundle.ancestor_bundle_hashes:
                visit(ancestor, require_bundle=False)
        finally:
            active.remove(object_hash)

    def visit(object_hash: str, *, require_bundle: bool) -> None:
        visit_payload(
            object_hash,
            objects.read_blob(object_hash),
            require_bundle=require_bundle,
        )

    if inputs is None:
        visit(manifest.parent_authority_bundle.object_hash, require_bundle=True)
        return MappingProxyType(dict(sorted(retained.items())))
    root = inputs.parent_authority_bundle
    root_payload = canonical_json_bytes(root.to_json_dict())
    if content_digest(root_payload) != manifest.parent_authority_bundle.object_hash:
        raise Protocol24AdoptionError(
            "schema-3 parent authority bundle differs from its manifest"
        )
    visit_payload(root.identity, root_payload, require_bundle=True)
    return MappingProxyType(dict(sorted(retained.items())))


def _stable_read(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise Protocol24AdoptionError(f"{label} is missing or unsafe")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    chunks: list[bytes] = []
    try:
        fd = os.open(path, flags)
        try:
            before = os.fstat(fd)
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise Protocol24AdoptionError(f"cannot read {label}: {exc}") from exc
    payload = b"".join(chunks)
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if identity(before) != identity(after) or len(payload) != before.st_size:
        raise Protocol24AdoptionError(f"{label} changed while being read")
    return payload


def _stable_optional_read(path: Path, label: str) -> bytes:
    if not path.exists() and not path.is_symlink():
        return b""
    return _stable_read(path, label)


__all__ = (
    "AdoptionReportV1",
    "Protocol24AdoptionError",
    "ValidatedParentV1",
    "build_parent_authority_bundle",
    "import_parent_acceptance_closure",
    "validate_parent_for_deepening",
)

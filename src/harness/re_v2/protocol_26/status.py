"""Truthful status decoration for self-contained protocol-2.6 checkpoints."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_22.model import WorkItemV2
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_22.status import _read_events_without_creating_lock
from harness.re_v2.protocol_25.ledger import Protocol25Ledger
from harness.re_v2.run_store import ReV2Paths, load_run_manifest

from .events import protocol_26_events_for
from .inputs import ValidatedProtocol26Inputs, load_protocol_26_inputs
from .model import RunManifestV5


class Protocol26StatusError(RuntimeError):
    """Raised when frozen checkpoint status authority is inconsistent."""


@dataclass(frozen=True, slots=True)
class CheckpointStatusV1:
    document: Mapping[str, object]

    @classmethod
    def from_authority(
        cls,
        inputs: ValidatedProtocol26Inputs,
        events: tuple[object, ...],
        accepted_count: int,
    ) -> "CheckpointStatusV1":
        selection = inputs.checkpoint_selection
        checkpoint_events = tuple(
            event for event in events if event.type == "checkpoint_artifact_adopted"
        )
        adopted_work_ids = {
            str(event.payload["work_item_id"]) for event in checkpoint_events
        }
        selected = tuple(
            item
            for item in selection.selected
            if item.source_kind == "workspace_checkpoint"
        )
        direct = tuple(
            item for item in selection.selected if item.source_kind == "direct_parent"
        )
        work_items = {
            item.expected_work_item_id: load_canonical_object(
                inputs.authority_objects[item.expected_work_item_id],
                WorkItemV2.from_json_dict,
            )
            for item in selected
        }
        grouped: Counter[tuple[str, str | None, str, str]] = Counter()
        avoided_tokens = 0
        avoided_active_ms = 0
        for work_id in sorted(adopted_work_ids):
            work = work_items.get(work_id)
            if work is None:
                raise Protocol26StatusError(
                    "checkpoint event has no frozen selected work authority"
                )
            grouped[
                (
                    work.output_key.scope.source_id,
                    work.output_key.scope.domain_key,
                    work.output_key.layer,
                    work.output_key.artifact_kind,
                )
            ] += 1
            executor = inputs.layer_inputs.executor_contract.entry_for(
                work.producer_family
            )
            avoided_active_ms += executor.limits.max_active_ms_per_dispatch
            if executor.execution_mode in {"api", "cli"}:
                avoided_tokens += executor.limits.max_billable_tokens_per_dispatch
        rejected = selection.rejected
        quarantined = selection.quarantined
        alternatives = selection.alternatives
        generated_count = max(
            0,
            accepted_count - len(adopted_work_ids) - len(direct),
        )
        reasons = Counter(
            item.reason for item in (*alternatives, *rejected, *quarantined)
        )
        document: dict[str, object] = {
            "cache_generation_id": selection.cache_generation_id,
            "reconstruction_state": "frozen_self_contained",
            "discovered_count": len(selected) + len(alternatives) + len(rejected) + len(quarantined),
            "compatible_count": len(selected) + len(alternatives),
            "selected_count": len(selected),
            "adopted_count": len(adopted_work_ids),
            "direct_parent_count": len(direct),
            "generated_count": generated_count,
            "rejected_count": len(rejected),
            "quarantined_count": len(quarantined),
            "copied_byte_count": selection.copied_byte_count,
            "origin_run_ids": sorted({item.origin_run_id for item in selected}),
            "checkpoint_manifest_ids": sorted(
                item.checkpoint_manifest_id
                for item in selected
                if item.checkpoint_manifest_id is not None
            ),
            "precedence": "direct_parent_then_workspace_checkpoint_then_generation",
            "reason_counts": dict(sorted(reasons.items())),
            "groups": [
                {
                    "source_id": key[0],
                    "domain_key": key[1],
                    "layer": key[2],
                    "artifact_kind": key[3],
                    "adopted_count": count,
                }
                for key, count in sorted(grouped.items())
            ],
            "avoided_dispatch_count": len(adopted_work_ids),
            "avoided_token_reservation": avoided_tokens,
            "avoided_active_ms_reservation": avoided_active_ms,
            "zero_dispatch_reuse": accepted_count > 0 and generated_count == 0,
        }
        return cls(document)


def protocol_26_status_document(
    run_dir: Path,
    *,
    context: object | None = None,
) -> dict[str, object]:
    """Render schema-5 status solely from the child run's frozen authority."""
    run_path = Path(run_dir)
    manifest = load_run_manifest(run_path)
    if not isinstance(manifest, RunManifestV5):
        raise Protocol26StatusError("protocol-2.6 status requires schema 5")
    paths = ReV2Paths.for_run(run_path)
    inputs = load_protocol_26_inputs(paths, manifest)
    if manifest.target_layer == "L1":
        from harness.re_v2.protocol_22.status import protocol_22_status_document

        base = protocol_22_status_document(run_path, context=context)
    elif manifest.target_layer == "L2":
        from harness.re_v2.protocol_24.status import protocol_24_status_document

        base = protocol_24_status_document(run_path, context=context)
    else:
        from harness.re_v2.protocol_25.status import protocol_25_status_document

        base = protocol_25_status_document(run_path, context=context)
    events = _read_events_without_creating_lock(
        EventStore(paths, protocol=protocol_26_events_for(manifest.target_layer))
    )
    objects = context.object_store if context is not None else ObjectStore(paths.objects)
    ledger = (
        Protocol25Ledger(paths, objects)
        if manifest.target_layer == "L3"
        else Protocol22Ledger(paths, objects)
    ).replay()
    checkpoint = CheckpointStatusV1.from_authority(
        inputs,
        events,
        len(ledger.accepted_artifacts),
    ).document
    decorated = dict(base)
    decorated["engine_protocol_version"] = "2.6"
    decorated["schema_version"] = 5
    decorated["target_layer"] = manifest.target_layer
    decorated["checkpoints"] = dict(checkpoint)
    decorated["banner"] = (
        f"{base['banner']} — adopted {checkpoint['adopted_count']} checkpoints, "
        f"generated {checkpoint['generated_count']}"
    )
    return decorated


def render_protocol_26_status(
    run_dir: Path,
    *,
    as_json: bool = False,
    context: object | None = None,
) -> str:
    import json

    document = protocol_26_status_document(run_dir, context=context)
    if as_json:
        return json.dumps(document, indent=2, sort_keys=True) + "\n"
    target_layer = str(document["target_layer"])
    if target_layer == "L1":
        from harness.re_v2.protocol_22.status import _render_human
    elif target_layer == "L2":
        from harness.re_v2.protocol_24.status import _render_human
    else:
        from harness.re_v2.protocol_25.status import _render_human

    base = _render_human(document).rstrip("\n")
    checkpoints = document["checkpoints"]
    return "\n".join(
        (
            base,
            (
                "checkpoints: "
                f"selected={checkpoints['selected_count']} "
                f"adopted={checkpoints['adopted_count']} "
                f"generated={checkpoints['generated_count']} "
                f"rejected={checkpoints['rejected_count']} "
                f"quarantined={checkpoints['quarantined_count']}"
            ),
            (
                "avoided reservation: "
                f"dispatches={checkpoints['avoided_dispatch_count']} "
                f"tokens={checkpoints['avoided_token_reservation']} "
                f"active_ms={checkpoints['avoided_active_ms_reservation']}"
            ),
            "",
        )
    )


__all__ = (
    "CheckpointStatusV1",
    "Protocol26StatusError",
    "protocol_26_status_document",
    "render_protocol_26_status",
)

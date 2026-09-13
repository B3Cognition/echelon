"""Deterministic, provider-free publication of protocol-2.8 closure successors."""

from __future__ import annotations

import json
from pathlib import Path

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_28.authority import (
    L4ClosureParentBundleV1,
    ParentAuthorityBundleV3,
    ValidatedL3ParentV1,
)
from harness.re_v2.protocol_28.context import (
    Protocol28ClosureRunContext,
    initialize_protocol_28_run,
    load_protocol_28_run_context,
)
from harness.re_v2.protocol_28.events import replay_protocol_28
from harness.re_v2.protocol_28.graph import (
    ExhaustiveVerificationReceiptV1,
    L4RunRootV1,
    L4TargetRootV1,
    build_l4_finding_closure_receipts,
    build_l4_semantic_closure,
)
from harness.re_v2.protocol_28.inputs import (
    Protocol28ClosureInputs,
    publish_protocol_28_run,
    stage_closure_inputs,
)
from harness.re_v2.protocol_28.model import L4ClosureRunManifestV7
from harness.re_v2.protocol_28.model import (
    L4ClosureLineageV1,
    L4ClosureRequestV1,
)
from harness.re_v2.run_store import load_run_manifest


class Protocol28ClosureError(RuntimeError):
    """Raised when immutable L3/L4 authority cannot close deterministically."""


_CLOSURE_POLICY_BYTES = canonical_json_bytes(
    {
        "finding_assignment": "exactly-one-primary",
        "provider_calls": 0,
        "schema_version": 1,
        "verifier_requirement": "independent-pass",
    }
)


def prepare_l4_closure_inputs(
    blocked_l3: ValidatedL3ParentV1,
    complete_l4_run: Path,
    *,
    run_id: str,
    created_at: str,
    closure_policy_bytes: bytes = _CLOSURE_POLICY_BYTES,
) -> Protocol28ClosureInputs:
    """Assemble a self-contained zero-call successor from exact durable L4 bytes."""
    context = load_protocol_28_run_context(Path(complete_l4_run))
    from harness.re_v2.protocol_28.context import Protocol28RunContext

    if not isinstance(context, Protocol28RunContext):
        raise Protocol28ClosureError("closure parent must be an exhaustive L4 run")
    if blocked_l3.terminal_state != "blocked" or blocked_l3.blocker_classes != (
        "requires_deeper_evidence",
    ):
        raise Protocol28ClosureError(
            "closure successor requires a deeper-evidence-only L3 parent"
        )
    parent = context.inputs.parent_authority_bundle
    expected_findings = tuple(
        sorted(
            finding_id
            for target in blocked_l3.targets
            for finding_id in target.unresolved_finding_ids
        )
    )
    if (
        parent.l3_run_id != blocked_l3.run_id
        or parent.l3_manifest_hash != blocked_l3.manifest_hash
        or parent.l3_terminal_event_hash != blocked_l3.terminal_event_hash
        or parent.frozen_epoch_id != blocked_l3.frozen_epoch_id
        or parent.unresolved_deeper_finding_ids != expected_findings
    ):
        raise Protocol28ClosureError(
            "exhaustive L4 run does not bind the blocked L3 authority"
        )
    state = replay_protocol_28(context.events.replay())
    if state.run_root_id is None:
        raise Protocol28ClosureError("exhaustive L4 run has no complete run root")
    run_root = load_canonical_object(
        context.objects.read_blob(state.run_root_id), L4RunRootV1.from_json_dict
    )
    target_roots = tuple(
        sorted(
            (
                load_canonical_object(
                    context.objects.read_blob(root_id),
                    L4TargetRootV1.from_json_dict,
                )
                for root_id in run_root.target_root_ids
            ),
            key=lambda item: item.sort_key,
        )
    )
    ledger = context.ledger.replay()
    accepted = tuple(
        sorted(ledger.accepted_slices.values(), key=lambda item: item.identity)
    )
    verification_receipts = tuple(
        ExhaustiveVerificationReceiptV1(
            1,
            item.identity,
            item.plan_entry_id,
            item.verifier_result_hash,
            item.verifier_execution_capture_hash,
            item.addressed_finding_ids,
            "PASS",
        )
        for item in accepted
    )
    # This call is the integrity gate; no successor is staged if finding,
    # accepted-slice, or independent-verifier closure differs.
    build_l4_semantic_closure(parent, run_root, accepted, verification_receipts)

    l4_manifest_bytes = canonical_json_bytes(context.inputs.manifest.to_json_dict())
    l4_manifest_hash = content_digest(l4_manifest_bytes)
    events = context.events.replay()
    if not events:
        raise Protocol28ClosureError("exhaustive L4 run has no completion event")
    l4_terminal_bytes = canonical_json_bytes(events[-1].identity_dict())
    l4_terminal_hash = events[-1].event_hash
    if content_digest(l4_terminal_bytes) != l4_terminal_hash:
        raise Protocol28ClosureError("L4 completion event identity is invalid")
    closure_policy_id = content_digest(closure_policy_bytes)
    request = L4ClosureRequestV1(
        1,
        blocked_l3.manifest_hash,
        blocked_l3.terminal_event_hash,
        blocked_l3.frozen_epoch_id,
        expected_findings,
        run_root.identity,
        tuple(sorted(item.identity for item in target_roots)),
        tuple(sorted(item.identity for item in verification_receipts)),
        closure_policy_id,
        run_root.source_snapshot_id,
        run_root.partition_manifest_id,
        run_root.selection_id,
    )
    lineage = L4ClosureLineageV1(
        1,
        blocked_l3.run_id,
        blocked_l3.manifest_hash,
        blocked_l3.terminal_event_hash,
        context.inputs.manifest.run_id,
        l4_manifest_hash,
        l4_terminal_hash,
    )
    typed_objects = {
        parent.identity: canonical_json_bytes(parent.to_json_dict()),
        run_root.identity: canonical_json_bytes(run_root.to_json_dict()),
        **{
            item.identity: canonical_json_bytes(item.to_json_dict())
            for item in (*target_roots, *accepted, *verification_receipts)
        },
    }
    opaque_ids = {
        parent.identity,
        run_root.identity,
        blocked_l3.manifest_hash,
        blocked_l3.terminal_event_hash,
        blocked_l3.frozen_epoch_id,
        l4_manifest_hash,
        l4_terminal_hash,
        *parent.selected_projection_ids,
        *expected_findings,
        *(item.identity for item in target_roots),
        *(item.identity for item in accepted),
        *(item.identity for item in verification_receipts),
    }
    authority_objects: dict[str, bytes] = {
        **typed_objects,
        blocked_l3.manifest_hash: context.objects.read_blob(blocked_l3.manifest_hash),
        blocked_l3.terminal_event_hash: context.objects.read_blob(
            blocked_l3.terminal_event_hash
        ),
        blocked_l3.frozen_epoch_id: context.objects.read_blob(
            blocked_l3.frozen_epoch_id
        ),
        l4_manifest_hash: l4_manifest_bytes,
        l4_terminal_hash: l4_terminal_bytes,
    }
    for object_id in sorted(opaque_ids - set(authority_objects)):
        authority_objects[object_id] = context.objects.read_blob(object_id)
    closure_parent = L4ClosureParentBundleV1(
        1,
        run_root.selection_id,
        run_root.source_snapshot_id,
        run_root.partition_manifest_id,
        blocked_l3.run_id,
        blocked_l3.manifest_hash,
        blocked_l3.terminal_event_hash,
        blocked_l3.frozen_epoch_id,
        context.inputs.manifest.run_id,
        l4_manifest_hash,
        l4_terminal_hash,
        run_root.identity,
        "complete",
        parent.selected_projection_ids,
        tuple(sorted(item.identity for item in accepted)),
        tuple(sorted(item.identity for item in verification_receipts)),
        tuple(sorted(item.identity for item in target_roots)),
        tuple(sorted(opaque_ids)),
    )
    manifest = L4ClosureRunManifestV7(
        7,
        "re-v2",
        "2.8",
        "l4-closure-successor",
        ("l4-evidence-closure",),
        "L4",
        run_id,
        created_at,
        run_root.source_snapshot_id,
        "workspace-git-composite",
        run_root.partition_manifest_id,
        context.inputs.manifest.selection,
        lineage,
        closure_parent.identity,
        request,
        run_root.identity,
        closure_policy_id,
    )
    return Protocol28ClosureInputs(
        manifest,
        closure_parent,
        run_root,
        target_roots,
        accepted,
        verification_receipts,
        closure_policy_bytes,
        {object_id: authority_objects[object_id] for object_id in sorted(opaque_ids)},
    )


def find_exact_l4_closure_successor(
    workspace_root: Path,
    request_id: str,
) -> Path | None:
    """Return the unique closure successor for an exact closure request."""
    runs = Path(workspace_root).resolve() / "runs"
    if not runs.is_dir() or runs.is_symlink():
        return None
    matches: list[Path] = []
    for candidate in sorted(runs.iterdir(), key=lambda item: item.name):
        if candidate.name.startswith(".") or candidate.is_symlink():
            continue
        manifest_path = candidate / "v2" / "run.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        try:
            raw = json.loads(manifest_path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or (
            raw.get("schema_version"),
            raw.get("engine_protocol_version"),
            raw.get("run_mode"),
        ) != (7, "2.8", "l4-closure-successor"):
            continue
        try:
            manifest = load_run_manifest(candidate)
        except Exception as exc:
            raise Protocol28ClosureError(
                f"invalid protocol-2.8 closure manifest: {candidate.name}"
            ) from exc
        if (
            isinstance(manifest, L4ClosureRunManifestV7)
            and manifest.closure_request.request_id == request_id
        ):
            matches.append(candidate)
    if len(matches) > 1:
        raise Protocol28ClosureError(
            "multiple protocol-2.8 closure successors share one request identity"
        )
    return matches[0] if matches else None


def create_or_reuse_l4_closure_successor(
    workspace_root: Path,
    inputs: Protocol28ClosureInputs,
) -> Path:
    """Publish and complete one exact closure successor with zero provider calls."""
    if not isinstance(inputs, Protocol28ClosureInputs):
        raise Protocol28ClosureError(
            "closure successor requires validated immutable inputs"
        )
    root = Path(workspace_root).resolve()
    request_id = inputs.manifest.closure_request.request_id
    existing = find_exact_l4_closure_successor(root, request_id)
    if existing is None:
        runs = root / "runs"
        final = runs / inputs.manifest.run_id
        stage = runs / f".{inputs.manifest.run_id}.stage"
        if stage.exists() or stage.is_symlink():
            raise Protocol28ClosureError(
                f"private protocol-2.8 closure stage already exists: {stage.name}"
            )
        stage_closure_inputs(stage, inputs)
        publish_protocol_28_run(stage, final, inputs.manifest)
        existing = final
    complete_l4_closure_successor(existing)
    return existing


def complete_l4_closure_successor(run_dir: Path) -> str:
    """Recover and finish deterministic closure authority without an executor seam."""
    from harness.re_v2.protocol_28.materialization import (
        validate_or_repair_l4_materialization,
    )

    context = load_protocol_28_run_context(Path(run_dir))
    if not isinstance(context, Protocol28ClosureRunContext):
        raise Protocol28ClosureError(
            "closure completion requires l4-closure-successor mode"
        )
    initialize_protocol_28_run(context)
    state = replay_protocol_28(context.events.replay())
    if state.terminal:
        if state.closure_root_id is None:
            raise Protocol28ClosureError("completed closure has no closure root")
        validate_or_repair_l4_materialization(context)
        return state.closure_root_id

    parent_id = context.inputs.l4_run_root.parent_authority_bundle_id
    try:
        parent = load_canonical_object(
            context.objects.read_blob(parent_id),
            ParentAuthorityBundleV3.from_json_dict,
        )
    except Exception as exc:
        context.controller.block_run(
            "closure_integrity", "closure_parent_authority_unavailable"
        )
        raise Protocol28ClosureError(
            "closure parent authority is unavailable or invalid"
        ) from exc

    try:
        receipts = build_l4_finding_closure_receipts(
            parent,
            context.inputs.l4_run_root,
            context.inputs.accepted_slices,
            context.inputs.verification_receipts,
        )
        closure_root = build_l4_semantic_closure(
            parent,
            context.inputs.l4_run_root,
            context.inputs.accepted_slices,
            context.inputs.verification_receipts,
        )
    except Exception as exc:
        reason = getattr(exc, "reason_code", "closure_authority_mismatch")
        context.controller.block_run("closure_integrity", str(reason))
        raise Protocol28ClosureError(str(exc)) from exc

    for receipt in receipts:
        context.controller.record_closure_receipt(receipt)
    context.controller.record_closure_root(
        closure_root, context.inputs.manifest.run_manifest_id
    )
    validate_or_repair_l4_materialization(context)
    context.controller.complete_run(
        context.inputs.l4_run_root.identity, closure_required=True
    )
    return closure_root.identity


__all__ = (
    "Protocol28ClosureError",
    "complete_l4_closure_successor",
    "create_or_reuse_l4_closure_successor",
    "find_exact_l4_closure_successor",
    "prepare_l4_closure_inputs",
)

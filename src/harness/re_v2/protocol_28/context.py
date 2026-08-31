"""Authenticated runtime contexts for published protocol-2.8 runs."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeAlias

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_28.budget import L4ResourceStore
from harness.re_v2.protocol_28.controller import Protocol28Controller
from harness.re_v2.protocol_28.events import PROTOCOL_28_EVENTS
from harness.re_v2.protocol_28.inputs import (
    ValidatedProtocol28ClosureInputs,
    ValidatedProtocol28Inputs,
    load_protocol_28_inputs,
)
from harness.re_v2.protocol_28.ledger import Protocol28Ledger
from harness.re_v2.protocol_28.artifacts import ExhaustiveEvidenceSliceV1
from harness.re_v2.protocol_28.planning import (
    ExhaustiveTargetPlanV1,
    SlicePlanEntryV1,
    SliceSpecV1,
)
from harness.re_v2.run_store import ReV2Paths


class Protocol28ContextError(RuntimeError):
    """Raised when a protocol-2.8 runtime context cannot be authenticated."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class Protocol28RunContext:
    paths: ReV2Paths
    inputs: ValidatedProtocol28Inputs
    objects: ObjectStore
    events: EventStore
    ledger: Protocol28Ledger
    resources: L4ResourceStore
    controller: Protocol28Controller

    @property
    def run_dir(self) -> Path:
        return self.paths.root.parent


@dataclass(frozen=True, slots=True)
class Protocol28ClosureRunContext:
    paths: ReV2Paths
    inputs: ValidatedProtocol28ClosureInputs
    objects: ObjectStore
    events: EventStore
    ledger: Protocol28Ledger
    controller: Protocol28Controller

    @property
    def run_dir(self) -> Path:
        return self.paths.root.parent


Protocol28Context: TypeAlias = Protocol28RunContext | Protocol28ClosureRunContext


def build_protocol_28_slice_context(
    context: Protocol28RunContext,
    target_plan: ExhaustiveTargetPlanV1,
    plan_entry: SlicePlanEntryV1,
    slice_spec: SliceSpecV1,
    *,
    role: str,
    candidate: ExhaustiveEvidenceSliceV1 | None = None,
    repair_diagnostic_ids: tuple[str, ...] = (),
    producer_attempt_number: int = 1,
    verifier_attempt_number: int | None = None,
) -> bytes:
    """Build one role-local context solely from the published child store."""
    if not isinstance(context, Protocol28RunContext):
        raise Protocol28ContextError("slice context requires an exhaustive run")
    if role not in {"producer", "verifier"}:
        raise Protocol28ContextError("slice context role must be producer or verifier")
    if (
        not isinstance(target_plan, ExhaustiveTargetPlanV1)
        or not isinstance(plan_entry, SlicePlanEntryV1)
        or not isinstance(slice_spec, SliceSpecV1)
        or plan_entry not in target_plan.entries
        or slice_spec.plan_entry_id != plan_entry.identity
    ):
        raise Protocol28ContextError("slice context does not match the frozen plan")
    if role == "producer" and candidate is not None:
        raise Protocol28ContextError("producer context cannot contain a candidate")
    if role == "verifier" and not isinstance(candidate, ExhaustiveEvidenceSliceV1):
        raise Protocol28ContextError("verifier context requires an immutable candidate")
    if (
        not isinstance(producer_attempt_number, int)
        or isinstance(producer_attempt_number, bool)
        or not 1 <= producer_attempt_number <= 3
    ):
        raise Protocol28ContextError("producer attempt number must be in [1, 3]")
    if role == "producer" and verifier_attempt_number is not None:
        raise Protocol28ContextError("producer context cannot claim a verifier attempt")
    if role == "verifier" and verifier_attempt_number is None:
        verifier_attempt_number = 1
    if role == "verifier" and verifier_attempt_number not in {1, 2}:
        raise Protocol28ContextError("verifier attempt number must be 1 or 2")

    inputs = context.inputs
    l3 = next(
        (
            item
            for item in inputs.l3_projection_catalog.projections
            if item.identity == plan_entry.target_l3_projection_id
        ),
        None,
    )
    evidence_projection = next(
        (
            item
            for item in inputs.snapshot_evidence_catalog.projections
            if item.identity == plan_entry.target_evidence_projection_id
        ),
        None,
    )
    if l3 is None or evidence_projection is None:
        raise Protocol28ContextError("slice target authority is unavailable")
    subject_ids = {
        *plan_entry.primary_subject_ids,
        *plan_entry.supporting_subject_ids,
    }
    evidence_ids = {
        *plan_entry.primary_snapshot_evidence_ids,
        *plan_entry.supporting_snapshot_evidence_ids,
    }
    evidence_catalog = inputs.snapshot_evidence_catalog
    evidence_objects = tuple(
        sorted(
            (
                item
                for item in (
                    *evidence_catalog.shards,
                    *evidence_catalog.empty_receipts,
                    *evidence_catalog.nontext_dispositions,
                )
                if item.identity in evidence_ids
            ),
            key=lambda item: item.identity,
        )
    )
    if {item.identity for item in evidence_objects} != evidence_ids:
        raise Protocol28ContextError("slice evidence authority is incomplete")
    subjects = tuple(
        item
        for item in inputs.exhaustive_subject_catalog.subjects
        if item.identity in subject_ids
    )
    if {item.identity for item in subjects} != subject_ids:
        raise Protocol28ContextError("slice subject authority is incomplete")
    lower_objects: list[dict[str, str]] = []
    for object_id in plan_entry.required_lower_authority_ids:
        payload = inputs.authority_objects.get(object_id)
        if payload is None:
            raise Protocol28ContextError(
                f"slice lower authority is unavailable: {object_id}"
            )
        lower_objects.append(
            {
                "object_id": object_id,
                "bytes_base64": base64.b64encode(payload).decode("ascii"),
            }
        )
    payload: dict[str, object] = {
        "schema_version": 1,
        "role": role,
        "slice_spec": slice_spec.to_json_dict(),
        "plan_entry": plan_entry.to_json_dict(),
        "target_plan_id": target_plan.identity,
        "target_l3_projection": l3.to_json_dict(),
        "target_evidence_projection": evidence_projection.to_json_dict(),
        "subjects": [item.to_json_dict() for item in subjects],
        "snapshot_evidence": [item.to_json_dict() for item in evidence_objects],
        "lower_authority_objects": lower_objects,
        "repair_diagnostic_ids": list(sorted(set(repair_diagnostic_ids))),
        "producer_attempt_number": producer_attempt_number,
        "verifier_attempt_number": verifier_attempt_number,
        "candidate_id": None if candidate is None else candidate.identity,
        "candidate": None if candidate is None else candidate.to_json_dict(),
    }
    encoded = canonical_json_bytes(payload)
    maximum = inputs.exhaustive_policy.max_context_bytes
    if role == "verifier":
        maximum += inputs.exhaustive_policy.max_candidate_output_bytes
    if len(encoded) > maximum:
        raise Protocol28ContextError(
            f"{role} slice context exceeds frozen byte bound"
        )
    return encoded


def load_protocol_28_run_context(
    run_dir: Path,
    *,
    clock: Callable[[], str] | None = None,
    fault: Callable[[str], None] | None = None,
) -> Protocol28Context:
    """Load only child-owned protocol-2.8 authority; never reopen live sources."""
    run_path = Path(run_dir)
    inputs = load_protocol_28_inputs(run_path)
    paths = ReV2Paths.for_run(run_path)
    objects = ObjectStore(paths.objects)
    events = EventStore(paths, protocol=PROTOCOL_28_EVENTS)
    ledger = Protocol28Ledger(paths.ledger, objects)
    controller = Protocol28Controller(
        events,
        objects,
        paths.projection,
        clock=clock or _now,
        fault=fault,
    )
    if isinstance(inputs, ValidatedProtocol28Inputs):
        resources = L4ResourceStore(
            paths.root / "resources.jsonl", inputs.manifest.budget_policy
        )
        return Protocol28RunContext(
            paths, inputs, objects, events, ledger, resources, controller
        )
    return Protocol28ClosureRunContext(
        paths, inputs, objects, events, ledger, controller
    )


def initialize_protocol_28_run(context: Protocol28Context) -> None:
    """Publish the exact initial event prefix once after manifest publication."""
    manifest = context.inputs.manifest
    controller = context.controller
    controller.append_once(
        "l4_run_created", {"run_manifest_id": manifest.run_manifest_id}
    )
    if isinstance(context, Protocol28ClosureRunContext):
        return
    inputs = context.inputs
    planned = tuple(
        sorted(
            entry.identity
            for target in inputs.exhaustive_plan.target_plans
            for entry in target.entries
        )
    )
    controller.append_once(
        "l4_inputs_staged",
        {
            "coverage_proof_id": inputs.snapshot_evidence_catalog.identity,
            "exhaustive_plan_id": inputs.exhaustive_plan.identity,
            "parent_authority_bundle_id": inputs.parent_authority_bundle.identity,
            "snapshot_evidence_catalog_id": inputs.snapshot_evidence_catalog.identity,
            "target_projection_catalog_id": inputs.l3_projection_catalog.identity,
        },
    )
    controller.append_once(
        "l4_activated",
        {
            "activation_id": content_digest(
                {
                    "exhaustive_plan_id": inputs.exhaustive_plan.identity,
                    "run_manifest_id": manifest.run_manifest_id,
                }
            ),
            "planned_entry_ids": list(planned),
        },
    )


__all__ = (
    "Protocol28ClosureRunContext",
    "Protocol28Context",
    "Protocol28ContextError",
    "Protocol28RunContext",
    "build_protocol_28_slice_context",
    "initialize_protocol_28_run",
    "load_protocol_28_run_context",
)

"""Read-only truthful status for protocol-2.5 semantic audit and closure."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.budget import evaluate_budget_v22
from harness.re_v2.protocol_22.graph import plan_next_v2
from harness.re_v2.protocol_22.status import (
    _budget_document,
    _open_dispatch_ids,
    _read_events_without_creating_lock,
    _read_ledger_without_creating_lock,
    _utc_now,
)
from harness.re_v2.protocol_24.graph import reconstruct_adopted_parent_closure
from harness.re_v2.run_store import ReV2Paths, load_run_manifest

from .artifacts import AuditCandidateV1
from .budget import evaluate_semantic_budget
from .controller import Protocol25ControllerStateV1
from .events import PROTOCOL_25_EVENTS, Protocol25ReplayState
from .graph import Protocol25Graph, build_protocol_25_graph
from .inputs import ValidatedProtocol25Inputs, load_protocol_25_inputs
from .ledger import Protocol25Ledger, Protocol25LedgerView
from .model import RunManifestV4
from .recovery import (
    Protocol25RunContext,
    _accepted_prerequisites,
    _source_cycle_states,
    _target_states,
    recover_protocol_25_run,
)
from harness.re_v2.protocol_22.schema import load_canonical_object


_BANNERS = {
    "complete": "L3 SELECTED SCOPE COMPLETE",
    "paused": "L3 PAUSED - CONTINUABLE",
    "blocked_incomplete": "L3 BLOCKED - AUDIT EPOCH INCOMPLETE",
    "blocked_plateau": "L3 BLOCKED - FROZEN FINDINGS UNRESOLVED",
    "next_epoch_required": "L3 EPOCH CLOSED - NEXT AUDIT EPOCH REQUIRED",
    "in_progress": "L3 SELECTED SCOPE IN PROGRESS",
}


class Protocol25StatusError(RuntimeError):
    """Raised when schema-4 status authority cannot be replayed exactly."""


@dataclass(frozen=True, slots=True)
class _StatusAuthority:
    manifest: RunManifestV4
    inputs: ValidatedProtocol25Inputs
    graph: Protocol25Graph
    events: tuple[object, ...]
    ledger: Protocol25LedgerView
    objects: ObjectStore
    state: Protocol25ControllerStateV1


def render_protocol_25_status(
    run_dir: Path,
    *,
    as_json: bool = False,
    context: Protocol25RunContext | None = None,
) -> str:
    document = protocol_25_status_document(run_dir, context=context)
    if as_json:
        return json.dumps(document, indent=2, sort_keys=True) + "\n"
    return _render_human(document)


def protocol_25_status_document(
    run_dir: Path,
    *,
    context: Protocol25RunContext | None = None,
) -> dict[str, object]:
    run_path = Path(run_dir)
    try:
        authority = _authority(run_path, context)
        return _document(authority)
    except Protocol25StatusError:
        raise
    except Exception as exc:
        raise Protocol25StatusError(
            f"cannot replay protocol-2.5 status for {run_path.name}: {exc}"
        ) from exc


def _authority(
    run_path: Path,
    context: Protocol25RunContext | None,
) -> _StatusAuthority:
    if context is not None:
        if not isinstance(context, Protocol25RunContext):
            raise Protocol25StatusError("status context must be Protocol25RunContext")
        if context.paths.root.parent != run_path:
            raise Protocol25StatusError("status context differs from requested run")
        recovered = recover_protocol_25_run(context)
        return _StatusAuthority(
            context.semantic_graph.manifest,
            context.semantic_inputs,
            context.semantic_graph,
            recovered.events,
            recovered.ledger,
            context.object_store,
            recovered.controller_state,
        )

    manifest = load_run_manifest(run_path)
    if not isinstance(manifest, RunManifestV4):
        raise Protocol25StatusError(
            f"RE run is not schema-4 protocol 2.5: {run_path.name}"
        )
    paths = ReV2Paths.for_run(run_path)
    inputs = load_protocol_25_inputs(paths, manifest)
    objects = ObjectStore(paths.objects)
    ledger = _read_ledger_without_creating_lock(Protocol25Ledger(paths, objects))
    if not isinstance(ledger, Protocol25LedgerView):
        raise Protocol25StatusError("schema-4 status requires protocol-2.5 ledger")
    events = _read_events_without_creating_lock(
        EventStore(paths, protocol=PROTOCOL_25_EVENTS)
    )
    adopted = reconstruct_adopted_parent_closure(
        inputs.parent_authority_bundle.lower_authority_bundle,
        ledger,
    )
    graph = build_protocol_25_graph(manifest, inputs.graph_inputs, adopted)
    replay = Protocol25ReplayState()
    for event in events:
        replay.consume(event)
    facade = SimpleNamespace(semantic_graph=graph, object_store=objects)
    accepted = _accepted_prerequisites(facade, ledger)
    plan = plan_next_v2(graph.prerequisite_graph, ledger, _AvailableBudget())
    actions = {item.action for item in plan.explanations.values()}
    prerequisites_complete = not plan.ready and actions <= {"reuse"}
    prerequisites_failed = not plan.ready and bool(
        actions & {"failed", "blocked_executor", "blocked_dependency", "blocked_attempts"}
    )
    targets = (
        _target_states(facade, ledger, replay, accepted)
        if prerequisites_complete
        else ()
    )
    terminal = None
    if replay.shared.shared.terminal:
        if replay.shared.shared.last_type == "run_completed":
            terminal = (
                "next_epoch_required"
                if "next_epoch_required" in replay.l3_source_root_states.values()
                else "complete"
            )
        else:
            terminal = "blocked_plateau" if replay.plateau_targets else "blocked_incomplete"
    state = Protocol25ControllerStateV1(
        prerequisites_complete=prerequisites_complete,
        prerequisites_failed=prerequisites_failed,
        paused_resource=replay.shared.shared.paused,
        audit_epoch_id=replay.audit_epoch_id,
        targets=targets,
        source_cycles=_source_cycle_states(replay, targets),
        rooted_source_ids=tuple(sorted(ledger.l3_source_roots)),
        deferred_observation_ids=tuple(
            sorted(
                {
                    observation.observation_id
                    for item in ledger.target_closure_assessments.values()
                    for observation in item.deferred_observations
                }
                | {
                    observation.observation_id
                    for item in ledger.source_composition_assessments.values()
                    for observation in item.deferred_observations
                }
            )
        ),
        terminal_state=terminal,  # type: ignore[arg-type]
    )
    return _StatusAuthority(manifest, inputs, graph, events, ledger, objects, state)


class _AvailableBudget:
    @staticmethod
    def item_attempt_available(_item: object) -> bool:
        return True


def _document(authority: _StatusAuthority) -> dict[str, object]:
    manifest = authority.manifest
    state = authority.state
    events = authority.events
    ledger = authority.ledger
    replay = Protocol25ReplayState()
    for event in events:
        replay.consume(event)  # type: ignore[arg-type]
    if state.paused_resource:
        status = "paused"
    elif state.terminal_state is not None:
        status = state.terminal_state
    else:
        status = "in_progress"
    run_budget = evaluate_budget_v22(
        manifest.initial_budget_policy,
        events,  # type: ignore[arg-type]
        _open_dispatch_ids(events),  # type: ignore[arg-type]
        _utc_now(),
        event_protocol=PROTOCOL_25_EVENTS,
    )
    semantic_budget = evaluate_semantic_budget(
        manifest.semantic_closure_policy,
        events,  # type: ignore[arg-type]
    )
    candidate_by_target = dict(replay.audit_candidates)
    targets = []
    finding_classes: dict[str, str] = {}
    for target in state.targets:
        candidate_hash = candidate_by_target.get(target.audit_target_id)
        if candidate_hash is not None:
            candidate = load_canonical_object(
                authority.objects.read_blob(candidate_hash),
                AuditCandidateV1.from_json_dict,
            )
            finding_classes.update(
                (item.finding_key_id, item.finding_key.finding_class)
                for item in candidate.findings
            )
        targets.append(
            {
                "audit_state": target.audit_state,
                "audit_target_id": target.audit_target_id,
                "closed_findings": len(target.frozen_finding_ids)
                - len(target.unresolved_finding_ids),
                "frozen_findings": len(target.frozen_finding_ids),
                "no_reduction_rounds": target.no_reduction_rounds,
                "semantic_round": target.semantic_round,
                "source_id": target.source_id,
                "stage": target.stage,
                "unresolved_finding_ids": list(target.unresolved_finding_ids),
            }
        )
    frozen = {item for target in state.targets for item in target.frozen_finding_ids}
    unresolved = {item for target in state.targets for item in target.unresolved_finding_ids}
    closed = frozen - unresolved
    adopted_work_ids = {
        str(event.payload["work_item_id"])
        for event in events  # type: ignore[union-attr]
        if event.type == "artifact_adopted"
    }
    accepted_lower = tuple(
        item
        for item in ledger.accepted_artifacts.values()
        if item.certification_receipt_id in ledger.certifications
    )
    semantic_accepted = tuple(
        item
        for item in ledger.accepted_artifacts.values()
        if item.certification_receipt_id in ledger.semantic_certifications
    )
    generated_l2 = sum(
        ledger.certification_work_items[item.certification_receipt_id].output_key.layer
        == "L2"
        and ledger.certification_work_items[item.certification_receipt_id].work_item_id
        not in adopted_work_ids
        for item in accepted_lower
    )
    unresolved_targets = sum(item.audit_state != "accepted" for item in state.targets)
    source_roots = [
        {
            "deferred_observation_ids": list(item.deferred_observation_ids),
            "l3_source_root_id": item.identity,
            "source_id": item.source_id,
            "state": item.state,
            "unresolved_finding_ids": list(item.unresolved_finding_ids),
        }
        for item in sorted(ledger.l3_source_roots.values(), key=lambda value: value.source_id)
    ]
    calls: dict[str, int] = {}
    operation_by_event = {
        "semantic_resolution_started": "semantic-resolution",
        "closure_recheck_started": "closure-recheck",
        "source_composition_guard_started": "source-composition-guard",
    }
    for event in events:  # type: ignore[assignment]
        operation = operation_by_event.get(event.type)
        if operation is not None:
            calls[operation] = calls.get(operation, 0) + 1
    return {
        "artifact_counts": {
            "adopted": len(adopted_work_ids),
            "generated_l2": generated_l2,
            "generated_l3": len(semantic_accepted),
            "retained_audit_candidates": len(candidate_by_target),
        },
        "banner": _BANNERS[status],
        "budget": {
            "run_wide": _budget_document(run_budget),
            "semantic": {
                "active_ms": _semantic_resource(
                    semantic_budget.charged_active_ms,
                    semantic_budget.active_ms_limit,
                ),
                "exhausted_dimensions": list(semantic_budget.exhausted_dimensions),
                "tokens": _semantic_resource(
                    semantic_budget.charged_tokens,
                    semantic_budget.token_limit,
                ),
            },
        },
        "completion_scope": "selected L3 scope only",
        "continuable": status == "paused",
        "engine": manifest.engine,
        "engine_protocol_version": manifest.engine_protocol_version,
        "lineage": manifest.parent_lineage.to_json_dict(),
        "next_action": _next_action(status, manifest.run_id),
        "not_run": {
            "exhaustive_re_l4": "not run",
            "workspace_synthesis": "not run",
        },
        "partition_manifest_id": manifest.partition_manifest_id,
        "run_id": manifest.run_id,
        "run_mode": manifest.run_mode,
        "selection": {
            **manifest.selection.to_json_dict(),
            "selected_domains": len(authority.graph.selected_domain_keys),
            "selected_sources": len(authority.graph.selected_source_ids),
            "target_layer": "L3",
            "unaudited_unselected_domains": len(
                authority.graph.not_requested_domain_keys
            ),
        },
        "semantic": {
            "closed_findings": len(closed),
            "deferred_observations": len(state.deferred_observation_ids),
            "finding_classes": dict(sorted(finding_classes.items())),
            "frozen_findings": len(frozen),
            "unresolved_audit_targets": unresolved_targets,
            "unresolved_findings": len(unresolved),
        },
        "semantic_request_id": manifest.semantic_request_id,
        "source_roots": source_roots,
        "source_snapshot_id": manifest.source_snapshot_id,
        "status": status,
        "targets": targets,
        "telemetry": {
            "calls_by_operation": dict(sorted(calls.items())),
            "semantic_trusted_observed_active_ms": (
                semantic_budget.trusted_observed_active_ms
            ),
            "semantic_trusted_observed_tokens": (
                semantic_budget.trusted_observed_tokens
            ),
            # Every exact semantic request is resolved to this immutable child
            # before controller/provider execution, regardless of how the child
            # was originally created. Successor adoption is a separate fact.
            "zero_call_reuse": True,
            "successor_adoption": manifest.run_mode != "new-audit-epoch",
        },
    }


def _semantic_resource(used: int, authorized: int | None) -> dict[str, int | None]:
    return {
        "authorized": authorized,
        "remaining": None if authorized is None else max(0, authorized - used),
        "used": used,
    }


def _next_action(status: str, run_id: str) -> str:
    if status == "complete":
        return "none — selected L3 scope is complete"
    if status == "paused":
        return "increase resource authorization, then run `echelon re continue`"
    if status == "next_epoch_required":
        return (
            f"run `echelon re deepen --to L3 --from-run {run_id} "
            "--new-audit-epoch --all`"
        )
    if status in {"blocked_incomplete", "blocked_plateau"}:
        return (
            "run `echelon re resume \"<guidance>\"`; identical guidance reuses "
            "the existing successor with zero provider calls"
        )
    return "run `echelon re continue`"


def _render_human(document: Mapping[str, object]) -> str:
    selection = document["selection"]
    semantic = document["semantic"]
    budget = document["budget"]
    lines = [
        "RE V2 — PROTOCOL 2.5",
        f"run: {document['run_id']}",
        f"mode: {document['run_mode']}",
        f"status: {document['status']}",
        (
            "selected L3 scope: "
            f"{selection['selected_sources']} source(s), "
            f"{selection['selected_domains']} domain(s)"
        ),
        f"frozen findings: {semantic['frozen_findings']}",
        f"closed findings: {semantic['closed_findings']}",
        f"unresolved findings: {semantic['unresolved_findings']}",
        f"deferred observations: {semantic['deferred_observations']}",
        (
            "run-wide tokens: "
            f"charged={budget['run_wide']['tokens']['charged']} "
            f"authorized={budget['run_wide']['tokens']['authorized']}"
        ),
        (
            "semantic tokens: "
            f"used={budget['semantic']['tokens']['used']} "
            f"authorized={budget['semantic']['tokens']['authorized']}"
        ),
        "workspace synthesis: not run",
        "exhaustive RE L4: not run",
        f"completion scope: {document['completion_scope']}",
        f"next action: {document['next_action']}",
        "=" * 72,
        str(document["banner"]),
    ]
    return "\n".join(lines) + "\n"


__all__ = (
    "Protocol25StatusError",
    "protocol_25_status_document",
    "render_protocol_25_status",
)

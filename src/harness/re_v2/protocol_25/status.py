"""Read-only truthful status for protocol-2.5 semantic audit and closure."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

from harness.re_v2.events import EventProtocol, EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.budget import evaluate_budget_v22
from harness.re_v2.protocol_22.graph import plan_next_v2
from harness.re_v2.protocol_22.model import ExecutionCaptureV1
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
from .preflight import AuditContextPreflightFailureV1
from .recovery import (
    Protocol25RunContext,
    _accepted_prerequisites,
    _source_cycle_states,
    _target_states,
    _replay_protocol_25_events,
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
    replay: Protocol25ReplayState
    event_protocol: EventProtocol


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
            _replay_protocol_25_events(context, recovered.events),
            context.event_store.protocol,
        )

    active_manifest = load_run_manifest(run_path)
    paths = ReV2Paths.for_run(run_path)
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5

    if isinstance(active_manifest, RunManifestV5):
        if active_manifest.target_layer != "L3":
            raise Protocol25StatusError(
                f"RE run is not protocol-2.6 L3: {run_path.name}"
            )
        outer_inputs = load_protocol_26_inputs(paths, active_manifest)
        manifest = outer_inputs.layer_execution_contract.layer_manifest
        inputs = outer_inputs.layer_inputs
        event_protocol = protocol_26_events_for("L3")
    else:
        manifest = active_manifest
        inputs = load_protocol_25_inputs(paths, manifest)
        event_protocol = PROTOCOL_25_EVENTS
    if not isinstance(manifest, RunManifestV4):
        raise Protocol25StatusError(
            f"RE run is not schema-4 protocol 2.5: {run_path.name}"
        )
    objects = ObjectStore(paths.objects)
    ledger = _read_ledger_without_creating_lock(Protocol25Ledger(paths, objects))
    if not isinstance(ledger, Protocol25LedgerView):
        raise Protocol25StatusError("schema-4 status requires protocol-2.5 ledger")
    events = _read_events_without_creating_lock(
        EventStore(paths, protocol=event_protocol)
    )
    adopted = reconstruct_adopted_parent_closure(
        inputs.parent_authority_bundle.lower_authority_bundle,
        ledger,
    )
    graph = build_protocol_25_graph(manifest, inputs.graph_inputs, adopted)
    replay = event_protocol.new_state()
    for event in events:
        replay.consume(event)
    if not isinstance(replay, Protocol25ReplayState):
        replay = getattr(replay, "delegate", None)
    if not isinstance(replay, Protocol25ReplayState):
        raise Protocol25StatusError("L3 status replay has no protocol-2.5 delegate")
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
    return _StatusAuthority(
        manifest,
        inputs,
        graph,
        events,
        ledger,
        objects,
        state,
        replay,
        event_protocol,
    )


class _AvailableBudget:
    @staticmethod
    def item_attempt_available(_item: object) -> bool:
        return True


def _document(authority: _StatusAuthority) -> dict[str, object]:
    manifest = authority.manifest
    state = authority.state
    events = authority.events
    ledger = authority.ledger
    replay = authority.replay
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
        event_protocol=authority.event_protocol,
    )
    semantic_budget = evaluate_semantic_budget(
        manifest.semantic_closure_policy,
        events,  # type: ignore[arg-type]
        event_protocol=authority.event_protocol,
    )
    authorization_required = (
        _authorization_required(authority, run_budget, semantic_budget)
        if status == "paused"
        else {}
    )
    authorization_recommended = _authorization_recommended(
        authority,
        run_budget,
        semantic_budget,
        authorization_required,
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
        if event.type in {"artifact_adopted", "checkpoint_artifact_adopted"}
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
    cli_provider_ids = {
        entry.provider_id
        for entry in authority.inputs.executor_contract.entries
        if entry.execution_mode == "cli" and entry.provider_id is not None
    }
    required_provider = (
        next(iter(cli_provider_ids)) if len(cli_provider_ids) == 1 else None
    )
    last_provider_failure = _latest_provider_failure(
        events,
        authority.objects,
        required_provider=required_provider,
    )
    preflight = _preflight_document(authority)
    projection_failure = (
        None
        if replay.semantic_context_projection_failure is None
        else dict(replay.semantic_context_projection_failure)
    )
    banner = (
        "L3 BLOCKED - AUDIT CONTEXT PREFLIGHT FAILED"
        if preflight["state"] == "failed"
        else "L3 BLOCKED - SOURCE COMPOSITION CONTEXT FAILED"
        if projection_failure is not None
        else _BANNERS[status]
    )
    return {
        "artifact_counts": {
            "adopted": len(adopted_work_ids),
            "generated_l2": generated_l2,
            "generated_l3": len(semantic_accepted),
            "retained_audit_candidates": len(candidate_by_target),
        },
        "banner": banner,
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
        "context_projection_failure": projection_failure,
        "continuable": status == "paused",
        "engine": manifest.engine,
        "engine_protocol_version": manifest.engine_protocol_version,
        "layer_protocol_version": manifest.engine_protocol_version,
        "lineage": manifest.parent_lineage.to_json_dict(),
        "last_provider_failure": last_provider_failure,
        "authorization_required": authorization_required,
        "authorization_recommended": authorization_recommended,
        "next_action": _next_action(
            status,
            manifest,
            authorization_recommended,
            preflight_failed=preflight["state"] == "failed",
            projection_failed=projection_failure is not None,
        ),
        "not_run": {
            "exhaustive_re_l4": "not run",
            "workspace_synthesis": "not run",
        },
        "partition_manifest_id": manifest.partition_manifest_id,
        "preflight": preflight,
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
            "provider_dispatches_avoided_by_preflight": (
                max(
                    0,
                    len(authority.graph.audit_target_plans)
                    - len(replay.audit_candidates),
                )
                if preflight["state"] == "failed"
                else 0
            ),
        },
    }


def _preflight_document(authority: _StatusAuthority) -> dict[str, object]:
    replay = authority.replay
    selected = len(authority.graph.audit_target_plans)
    target_ids = _preflight_target_ids(authority)
    if replay.audit_context_preflight_failure_id is not None:
        failure = authority.ledger.audit_context_preflight_failures.get(
            replay.audit_context_preflight_failure_id
        )
        if failure is None:
            raise Protocol25StatusError("preflight event has no failure receipt")
        try:
            checked = target_ids.index(failure.audit_target_id) + 1
        except ValueError as exc:
            raise Protocol25StatusError(
                "preflight failure target is absent from the frozen graph"
            ) from exc
        return _failed_preflight_document(failure, checked, selected)
    if authority.ledger.audit_context_preflight_failures:
        if len(authority.ledger.audit_context_preflight_failures) != 1:
            raise Protocol25StatusError("run has multiple preflight failure receipts")
        failure = next(
            iter(authority.ledger.audit_context_preflight_failures.values())
        )
        try:
            checked = target_ids.index(failure.audit_target_id) + 1
        except ValueError as exc:
            raise Protocol25StatusError(
                "preflight failure target is absent from the frozen graph"
            ) from exc
        return _failed_preflight_document(failure, checked, selected)
    if replay.audit_context_preflight_entries:
        entries = replay.audit_context_preflight_entries
        return {
            "state": "passed",
            "checked_target_count": len(entries),
            "selected_target_count": selected,
            "max_measured_canonical_json_bytes": max(
                item.canonical_json_bytes for item in entries
            ),
            "max_canonical_json_bytes": authority.inputs.artifact_policy.entry_for(
                "L3", "semantic-audit-findings"
            ).max_context_bundle_bytes,
            "provider_dispatch_count": 0,
            "failure": None,
        }
    return {
        "state": "not_run",
        "checked_target_count": 0,
        "selected_target_count": selected,
        "max_measured_canonical_json_bytes": None,
        "max_canonical_json_bytes": authority.inputs.artifact_policy.entry_for(
            "L3", "semantic-audit-findings"
        ).max_context_bundle_bytes,
        "provider_dispatch_count": 0,
        "failure": None,
    }


def _preflight_target_ids(authority: _StatusAuthority) -> tuple[str, ...]:
    facade = SimpleNamespace(
        semantic_graph=authority.graph,
        object_store=authority.objects,
    )
    accepted = _accepted_prerequisites(facade, authority.ledger)
    return tuple(
        item.audit_target_id
        for item in authority.graph.ready_audit_targets(accepted)
    )


def _failed_preflight_document(
    failure: AuditContextPreflightFailureV1,
    checked: int,
    selected: int,
) -> dict[str, object]:
    return {
        "state": "failed",
        "checked_target_count": checked,
        "selected_target_count": selected,
        "max_measured_canonical_json_bytes": (
            failure.measured_canonical_json_bytes
        ),
        "max_canonical_json_bytes": failure.max_canonical_json_bytes,
        "provider_dispatch_count": failure.provider_dispatch_count,
        "failure": {
            "audit_target_id": failure.audit_target_id,
            "scope_kind": failure.scope_kind,
            "source_id": failure.source_id,
            "domain_key": failure.domain_key,
            "reason_code": failure.reason_code,
        },
    }


def _latest_provider_failure(
    events: tuple[object, ...],
    objects: ObjectStore,
    *,
    required_provider: str | None = None,
) -> dict[str, object] | None:
    """Describe the latest failed CLI capture without persisting provider stderr."""
    for event in reversed(events):
        if getattr(event, "type", None) != "dispatch_observed":
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, Mapping):
            continue
        capture_hash = payload.get("execution_capture_hash")
        if not isinstance(capture_hash, str):
            continue
        capture = load_canonical_object(
            objects.read_blob(capture_hash),
            ExecutionCaptureV1.from_json_dict,
        )
        failed = (
            capture.execution_mode == "cli"
            and (
                capture.result_kind == "provider_failure"
                or capture.timed_out
                or capture.exit_code not in {None, 0}
            )
        )
        if capture.execution_mode == "cli" and not failed:
            return None
        if not failed:
            continue
        reason = (
            "timed_out"
            if capture.timed_out
            else "nonzero_exit"
            if capture.exit_code not in {None, 0}
            else "provider_failure"
        )
        return {
            "dispatch_id": capture.dispatch_id,
            "exit_code": capture.exit_code,
            "provider": capture.provider_name,
            "provider_contract_mismatch": bool(
                required_provider is not None
                and capture.provider_name != required_provider
            ),
            "reason": reason,
            "required_provider": required_provider,
            "timed_out": capture.timed_out,
            "work_item_id": capture.work_item_id,
        }
    return None


def _semantic_resource(used: int, authorized: int | None) -> dict[str, int | None]:
    return {
        "authorized": authorized,
        "remaining": None if authorized is None else max(0, authorized - used),
        "used": used,
    }


def _authorization_required(
    authority: _StatusAuthority,
    run_budget: object,
    semantic_budget: object,
) -> dict[str, dict[str, int]]:
    catalog = authority.inputs.executor_contract
    entries = (
        catalog.semantic_entries
        if authority.state.prerequisites_complete
        else catalog.inherited_catalog.entries
    )
    if not entries:
        return {}
    reservation_tokens = max(
        entry.limits.max_billable_tokens_per_dispatch for entry in entries
    )
    reservation_active_ms = max(
        entry.limits.max_active_ms_per_dispatch for entry in entries
    )

    def required(pool: object) -> dict[str, int]:
        result: dict[str, int] = {}
        dimensions = (
            (
                "tokens",
                int(getattr(pool, "charged_tokens")),
                getattr(pool, "token_limit"),
                reservation_tokens,
            ),
            (
                "active_ms",
                int(getattr(pool, "charged_active_ms")),
                getattr(pool, "active_ms_limit"),
                reservation_active_ms,
            ),
        )
        for name, charged, authorized, reservation in dimensions:
            minimum = charged + reservation
            if authorized is not None and minimum > int(authorized):
                result[name] = minimum
        return result

    result: dict[str, dict[str, int]] = {}
    run_required = required(run_budget)
    if run_required:
        result["run_wide"] = run_required
    if authority.state.prerequisites_complete:
        semantic_required = required(semantic_budget)
        if semantic_required:
            result["semantic"] = semantic_required
    return result


def _authorization_recommended(
    authority: _StatusAuthority,
    run_budget: object,
    semantic_budget: object,
    required: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, int]]:
    """Add one full dispatch window so a continuation is not a one-call ratchet."""
    if not required:
        return {}
    catalog = authority.inputs.executor_contract
    entries = (
        catalog.semantic_entries
        if authority.state.prerequisites_complete
        else catalog.inherited_catalog.entries
    )
    reservations = {
        "tokens": max(
            entry.limits.max_billable_tokens_per_dispatch for entry in entries
        ),
        "active_ms": max(
            entry.limits.max_active_ms_per_dispatch for entry in entries
        ),
    }
    pools = {"run_wide": run_budget, "semantic": semantic_budget}
    result: dict[str, dict[str, int]] = {}
    for pool_name, dimensions in required.items():
        pool = pools[pool_name]
        recommended: dict[str, int] = {}
        for dimension, minimum in dimensions.items():
            if dimension == "tokens":
                authorized = getattr(pool, "token_limit")
            else:
                authorized = getattr(pool, "active_ms_limit")
            if authorized is None:
                continue
            recommended[dimension] = max(
                int(minimum),
                int(authorized) + reservations[dimension],
            )
        if recommended:
            result[pool_name] = recommended
    return result


def _minutes(active_ms: int) -> int:
    return (active_ms + 59_999) // 60_000


def _next_action(
    status: str,
    manifest: RunManifestV4,
    authorization_required: Mapping[str, Mapping[str, int]],
    *,
    preflight_failed: bool = False,
    projection_failed: bool = False,
) -> str:
    run_id = manifest.run_id
    if preflight_failed or projection_failed:
        return f"run `{_fresh_l3_command(manifest)}`"
    if status == "complete":
        return "none — selected L3 scope is complete"
    if status == "paused":
        flags: list[str] = []
        run_wide = authorization_required.get("run_wide", {})
        semantic = authorization_required.get("semantic", {})
        if "tokens" in run_wide:
            flags.extend(("--re-token-limit", str(run_wide["tokens"])))
        if "active_ms" in run_wide:
            flags.extend(
                (
                    "--re-time-limit-minutes",
                    str(_minutes(run_wide["active_ms"])),
                )
            )
        if "tokens" in semantic:
            flags.extend(
                ("--re-semantic-token-limit", str(semantic["tokens"]))
            )
        if "active_ms" in semantic:
            flags.extend(
                (
                    "--re-semantic-time-limit-minutes",
                    str(_minutes(semantic["active_ms"])),
                )
            )
        suffix = " " + " ".join(flags) if flags else ""
        return f"run `echelon re continue {run_id}{suffix}`"
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


def _fresh_l3_command(manifest: RunManifestV4) -> str:
    command = ["echelon re deepen", "--to L3"]
    if manifest.selection.all_sources:
        command.append("--all")
    else:
        command.extend(
            f"--source {source_id}" for source_id in manifest.selection.source_ids
        )
        command.extend(
            f"--domain {domain_key}" for domain_key in manifest.selection.domain_keys
        )
    command.append(f"--from-run {manifest.parent_lineage.direct_parent_run_id}")
    return " ".join(command)


def _render_human(document: Mapping[str, object]) -> str:
    selection = document["selection"]
    semantic = document["semantic"]
    budget = document["budget"]
    lines = [
        f"RE V2 — PROTOCOL {document['engine_protocol_version']}",
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
    ]
    preflight = document.get("preflight")
    if isinstance(preflight, Mapping) and preflight.get("state") != "not_run":
        lines.append(
            "preflight: "
            f"{preflight['state']} after {preflight['checked_target_count']}/"
            f"{preflight['selected_target_count']} target(s)"
        )
        measured = preflight.get("max_measured_canonical_json_bytes")
        ceiling = preflight.get("max_canonical_json_bytes")
        if isinstance(measured, int) and isinstance(ceiling, int):
            relation = "exceeds" if measured > ceiling else "within"
            lines.append(
                f"preflight context: {measured} bytes {relation} {ceiling}"
            )
        lines.append(
            "provider calls made by preflight: "
            f"{preflight.get('provider_dispatch_count', 0)}"
        )
    projection_failure = document.get("context_projection_failure")
    if isinstance(projection_failure, Mapping):
        measured = projection_failure.get("measured_canonical_json_bytes")
        ceiling = projection_failure.get("max_canonical_json_bytes")
        lines.append(
            "source composition context: "
            f"{measured if isinstance(measured, int) else 'unmeasured'} bytes; "
            f"limit {ceiling}"
        )
        lines.append("provider calls made after projection failure: 0")
    provider_failure = document.get("last_provider_failure")
    if isinstance(provider_failure, Mapping):
        provider = provider_failure.get("provider", "unknown")
        if provider_failure.get("timed_out") is True:
            summary = f"{provider} CLI timed out"
        else:
            summary = (
                f"{provider} CLI exited with code "
                f"{provider_failure.get('exit_code', 'unknown')}"
            )
        required_provider = provider_failure.get("required_provider")
        mismatch = provider_failure.get("provider_contract_mismatch") is True
        if mismatch and isinstance(required_provider, str):
            lines.append(
                f"last provider failure: {summary}; frozen run provider is "
                f"{required_provider}"
            )
            lines.append(
                f"action required: configure/authenticate {required_provider} "
                "before retrying"
            )
        else:
            lines.append(f"last provider failure: {summary}")
            lines.append(
                "action required: resolve provider authentication/connectivity "
                "before retrying"
            )
    authorization = document.get("authorization_required")
    if isinstance(authorization, Mapping) and authorization:
        descriptions = []
        labels = {"run_wide": "run", "semantic": "semantic"}
        for pool_name in ("run_wide", "semantic"):
            required = authorization.get(pool_name)
            if not isinstance(required, Mapping):
                continue
            current_pool = budget[pool_name]
            if "tokens" in required:
                descriptions.append(
                    f"{labels[pool_name]} tokens={required['tokens']} "
                    f"(currently {current_pool['tokens']['authorized']})"
                )
            if "active_ms" in required:
                descriptions.append(
                    f"{labels[pool_name]} active time="
                    f"{_minutes(required['active_ms'])} min "
                    f"(currently "
                    f"{_minutes(current_pool['active_ms']['authorized'])})"
                )
        lines.append(
            "authorization required (absolute totals): " + "; ".join(descriptions)
        )
    recommended = document.get("authorization_recommended")
    if isinstance(recommended, Mapping) and recommended:
        descriptions = []
        labels = {"run_wide": "run", "semantic": "semantic"}
        for pool_name in ("run_wide", "semantic"):
            values = recommended.get(pool_name)
            if not isinstance(values, Mapping):
                continue
            if "tokens" in values:
                descriptions.append(
                    f"{labels[pool_name]} tokens={values['tokens']}"
                )
            if "active_ms" in values:
                descriptions.append(
                    f"{labels[pool_name]} active time="
                    f"{_minutes(values['active_ms'])} min"
                )
        lines.append(
            "recommended continuation ceiling: " + "; ".join(descriptions)
        )
    lines.extend(
        (
            f"next action: {document['next_action']}",
            "=" * 72,
            str(document["banner"]),
        )
    )
    return "\n".join(lines) + "\n"


__all__ = (
    "Protocol25StatusError",
    "protocol_25_status_document",
    "render_protocol_25_status",
)

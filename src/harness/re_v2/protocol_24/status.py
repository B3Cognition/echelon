"""Read-only selected-scope status for RE v2 protocol 2.4."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Mapping

from harness.re_v2.events import EventRecord, EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.run_store import ReV2Paths, load_run_manifest
from harness.re_v2.protocol_22.budget import evaluate_budget_v22
from harness.re_v2.protocol_22.graph import plan_next_v2
from harness.re_v2.protocol_22.ledger import Protocol22Ledger, Protocol22LedgerView
from harness.re_v2.protocol_22.materialization import materialized_path_for
from harness.re_v2.protocol_22.recovery import (
    Protocol22RunContext,
    installed_authority_mismatches,
)
from harness.re_v2.protocol_22.status import (
    Protocol22StatusError,
    _baseline_documents,
    _budget_document,
    _context_estimates,
    _failure_documents,
    _materialization_document,
    _mismatch_documents,
    _next_work_document,
    _open_dispatch_ids,
    _plan_documents,
    _read_events_without_creating_lock,
    _read_ledger_without_creating_lock,
    _root_projection_status,
    _run_status,
    _telemetry_document,
    _utc_now,
)

from .events import PROTOCOL_24_EVENTS
from .graph import (
    Protocol24Graph,
    build_protocol_24_graph,
    reconstruct_adopted_parent_closure,
)
from .inputs import ValidatedProtocol24Inputs, load_protocol_24_inputs
from .model import RunManifestV3


_BANNERS = {
    "complete": "L2 SELECTED SCOPE COMPLETE",
    "paused": "L2 PAUSED - CONTINUABLE",
    "blocked": "L2 BLOCKED - REQUESTED OUTPUTS INCOMPLETE",
    "in_progress": "L2 SELECTED SCOPE IN PROGRESS",
    "pinned_authority_unavailable": "L2 BLOCKED - PINNED AUTHORITY UNAVAILABLE",
}
_NOT_RUN = {
    "exhaustive_re": "not run",
    "semantic_audit": "not run",
    "workspace_synthesis": "not run",
}


class Protocol24StatusError(Protocol22StatusError):
    """Raised when protocol-2.4 status authority cannot be replayed safely."""


def render_protocol_24_status(
    run_dir: Path,
    *,
    as_json: bool = False,
    context: Protocol22RunContext | None = None,
) -> str:
    """Render authoritative protocol-2.4 status without changing the run."""
    document = protocol_24_status_document(run_dir, context=context)
    if as_json:
        return json.dumps(document, indent=2, sort_keys=True) + "\n"
    return _render_human(document)


def protocol_24_status_document(
    run_dir: Path,
    *,
    context: Protocol22RunContext | None = None,
) -> dict[str, object]:
    """Replay manifest, adoption, ledger, graph, budget, and projections."""
    run_path = Path(run_dir)
    try:
        manifest = load_run_manifest(run_path)
        if not isinstance(manifest, RunManifestV3):
            raise Protocol24StatusError(
                f"RE run is not schema-3 protocol 2.4: {run_path.name}"
            )
        paths = ReV2Paths.for_run(run_path)
        inputs = load_protocol_24_inputs(paths, manifest)
        objects = context.object_store if context is not None else ObjectStore(paths.objects)
        ledger_store = (
            context.ledger if context is not None else Protocol22Ledger(paths, objects)
        )
        ledger = _read_ledger_without_creating_lock(ledger_store)
        parent = reconstruct_adopted_parent_closure(
            inputs.parent_authority_bundle,
            ledger,
        )
        graph = build_protocol_24_graph(manifest, inputs, parent)
        mismatches = _validate_context(context, paths, inputs, graph)
        events = _read_events_without_creating_lock(
            EventStore(paths, protocol=PROTOCOL_24_EVENTS)
        )
        raw_status = _run_status(events)
        status = "blocked" if raw_status == "failed" else raw_status
        if mismatches and raw_status not in {"complete", "failed"}:
            status = "pinned_authority_unavailable"
        budget = evaluate_budget_v22(
            manifest.initial_budget_policy,
            events,
            _open_dispatch_ids(events),
            context.clock() if context is not None else _utc_now(),
            event_protocol=PROTOCOL_24_EVENTS,
        )
        plan = plan_next_v2(graph, ledger, budget)
        return _status_document(
            manifest,
            paths,
            inputs,
            graph,
            events,
            ledger,
            budget,
            plan,
            objects,
            status,
            mismatches,
            context,
        )
    except Protocol24StatusError:
        raise
    except Exception as exc:
        raise Protocol24StatusError(
            f"cannot replay protocol-2.4 status for {run_path.name}: {exc}"
        ) from exc


def _validate_context(
    context: Protocol22RunContext | None,
    paths: ReV2Paths,
    inputs: ValidatedProtocol24Inputs,
    graph: Protocol24Graph,
) -> tuple[object, ...]:
    if context is None:
        return ()
    if not isinstance(context, Protocol22RunContext):
        raise Protocol24StatusError("status context must be Protocol22RunContext")
    if context.paths != paths or context.inputs != inputs or context.graph != graph:
        raise Protocol24StatusError(
            "status context differs from immutable run authority"
        )
    return installed_authority_mismatches(inputs, context.installed_authorities)


def _status_document(
    manifest: RunManifestV3,
    paths: ReV2Paths,
    inputs: ValidatedProtocol24Inputs,
    graph: Protocol24Graph,
    events: tuple[EventRecord, ...],
    ledger: Protocol22LedgerView,
    budget: object,
    plan: object,
    objects: ObjectStore,
    status: str,
    mismatches: tuple[object, ...],
    context: Protocol22RunContext | None,
) -> dict[str, object]:
    templates = tuple(graph.templates)
    plan_items = _plan_documents(templates, plan)
    plan_by_template = {str(item["template_id"]): item for item in plan_items}
    l2_templates = tuple(item for item in templates if item.layer == "L2")
    accepted_l2 = sum(
        plan_by_template[item.template_id]["action"] == "reuse"
        for item in l2_templates
    )
    required_output_items = [
        plan_by_template[template_id]
        for template_id in graph.required_output_template_ids
    ]
    accepted_outputs = sum(item["action"] == "reuse" for item in required_output_items)
    if status == "complete" and accepted_outputs != len(required_output_items):
        raise Protocol24StatusError(
            "run_completed does not cover every requested L2 output"
        )

    adopted_work_ids = {
        str(event.payload["work_item_id"])
        for event in events
        if event.type == "artifact_adopted"
    }
    accepted_work = {
        receipt.certification_receipt_id: ledger.certification_work_items[
            receipt.certification_receipt_id
        ]
        for receipt in ledger.accepted_artifacts.values()
    }
    generated_l2 = sum(
        work.output_key.layer == "L2" and work.work_item_id not in adopted_work_ids
        for work in accepted_work.values()
    )
    adopted_by_layer: dict[str, int] = {}
    for work in ledger.certification_work_items.values():
        if work.work_item_id in adopted_work_ids:
            adopted_by_layer[work.output_key.layer] = (
                adopted_by_layer.get(work.output_key.layer, 0) + 1
            )
    selected_l2_reuse = sum(
        item["action"] == "reuse" and item["work_item_id"] in adopted_work_ids
        for item in plan_items
        if _template_layer(templates, str(item["template_id"])) == "L2"
    )
    baselines = _l2_baselines(ledger)
    baseline_by_domain = {
        (str(item["source_id"]), str(item["domain_key"])): item
        for item in baselines
        if item["artifact_kind"] == "domain-baseline"
        and item["verdict"] == "accepted"
    }
    source_roots = _source_root_documents(paths, inputs, ledger)
    domains = _domain_documents(inputs, graph, plan_by_template, baseline_by_domain)
    sources = _source_documents(inputs, graph, domains, source_roots)
    plan_counts = {
        action: sum(item["action"] == action for item in plan_items)
        for action in (
            "reuse",
            "generate",
            "failed",
            "blocked_executor",
            "blocked_dependency",
            "blocked_attempts",
            "blocked_budget",
            "blocked_authority",
        )
    }
    return {
        "artifact_counts": {
            "adopted": len(adopted_work_ids),
            "adopted_by_layer": dict(sorted(adopted_by_layer.items())),
            "generated_l2": generated_l2,
            "selected_l2": {"accepted": accepted_l2, "required": len(l2_templates)},
            "requested_outputs": {
                "accepted": accepted_outputs,
                "required": len(required_output_items),
            },
            "zero_dispatch_l2_reuse": selected_l2_reuse,
        },
        "authority": {
            "status": "drift_warning" if mismatches else "available" if context else "not_checked",
            "mismatches": _mismatch_documents(mismatches),
        },
        "banner": _BANNERS[status],
        "baselines": baselines,
        "budget": _budget_document(budget),
        "completion_scope": "selected L2 scope only",
        "context_estimates": _l2_context_estimates(ledger, objects),
        "continuable": status == "paused",
        "domains": domains,
        "engine": manifest.engine,
        "engine_protocol_version": manifest.engine_protocol_version,
        "failures": _failure_documents(ledger, plan_items),
        "lineage": manifest.parent_lineage.to_json_dict(),
        "materialization": _materialization_document(paths),
        "next_action": _next_action(status),
        "next_work": (
            _next_work_document(
                context,
                plan,
                budget,
                events,
                ledger,
                objects,
                inputs.executor_contract,
            )
            if status == "in_progress"
            else None
        ),
        "not_run": dict(_NOT_RUN),
        "partition_manifest_id": manifest.partition_manifest_id,
        "plan": plan_items,
        "plan_counts": plan_counts,
        "requested_goals": list(manifest.requested_goals),
        "run_id": manifest.run_id,
        "selection": {
            **manifest.selection.to_json_dict(),
            "selected_domains": len(graph.selected_domain_keys),
            "selected_sources": len(graph.selected_source_ids),
            "target_layer": manifest.target_layer,
        },
        "semantic_request_id": manifest.semantic_request_id,
        "source_roots": source_roots,
        "source_snapshot_id": manifest.source_snapshot_id,
        "sources": sources,
        "status": status,
        "telemetry": {
            **_telemetry_document(events, budget, objects, paths),
            "adoption_validation_duration_ms": _adoption_duration_ms(events),
            "adopted_artifact_bytes": sum(
                len(objects.read_blob(item.artifact_hash))
                for item in inputs.parent_authority_bundle.artifacts
            ),
            "adopted_artifacts": len(adopted_work_ids),
            "generated_l2_artifacts": generated_l2,
            "dispatches_by_attempt_kind": _dispatches_by_attempt_kind(events),
            "zero_dispatch_l2_reuse": selected_l2_reuse,
        },
    }


def _template_layer(templates: tuple[object, ...], template_id: str) -> str:
    return next(item.layer for item in templates if item.template_id == template_id)


def _l2_baselines(ledger: Protocol22LedgerView) -> list[dict[str, object]]:
    l2_work_ids = {
        item.work_item_id
        for item in ledger.certification_work_items.values()
        if item.output_key.layer == "L2"
    }
    return [
        item
        for item in _baseline_documents(ledger)
        if item["work_item_id"] in l2_work_ids
    ]


def _l2_context_estimates(
    ledger: Protocol22LedgerView,
    objects: ObjectStore,
) -> list[dict[str, object]]:
    l2_work_ids = {
        item.work_item_id
        for item in ledger.certification_work_items.values()
        if item.output_key.layer == "L2"
    }
    return [
        item
        for item in _context_estimates(ledger, objects)
        if item["work_item_id"] in l2_work_ids
    ]


def _domain_documents(
    inputs: ValidatedProtocol24Inputs,
    graph: Protocol24Graph,
    plan_by_template: Mapping[str, Mapping[str, object]],
    baselines: Mapping[tuple[str, str], Mapping[str, object]],
) -> list[dict[str, object]]:
    selected = set(graph.selected_domain_keys)
    documents: list[dict[str, object]] = []
    for source in inputs.workspace_partition.sources:
        for domain in source.domains:
            selected_template = next(
                (
                    item
                    for item in graph.templates
                    if item.layer == "L2"
                    and item.artifact_kind == "domain-baseline"
                    and item.scope.source_id == source.source_id
                    and item.scope.domain_key == domain.domain_key
                ),
                None,
            )
            is_selected = domain.domain_key in selected
            action = (
                plan_by_template[selected_template.template_id]["action"]
                if selected_template is not None
                else None
            )
            baseline = baselines.get((source.source_id, domain.domain_key))
            documents.append(
                {
                    "coverage": None if baseline is None else baseline["coverage"],
                    "domain_key": domain.domain_key,
                    "presentation_domain_id": domain.presentation_domain_id,
                    "selected": is_selected,
                    "source_id": source.source_id,
                    "state": (
                        "not_requested"
                        if not is_selected
                        else "complete"
                        if action == "reuse"
                        else "incomplete"
                    ),
                }
            )
    return documents


def _source_documents(
    inputs: ValidatedProtocol24Inputs,
    graph: Protocol24Graph,
    domains: list[dict[str, object]],
    roots: list[dict[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    selected_sources = set(graph.selected_source_ids)
    for source in inputs.workspace_partition.sources:
        scoped = [item for item in domains if item["source_id"] == source.source_id]
        root = next(
            (item for item in roots if item["source_id"] == source.source_id),
            None,
        )
        result.append(
            {
                "domains": {
                    "complete": sum(item["state"] == "complete" for item in scoped),
                    "intentionally_unselected": sum(
                        item["state"] == "not_requested" for item in scoped
                    ),
                    "selected": sum(bool(item["selected"]) for item in scoped),
                    "total": len(scoped),
                },
                "selected": source.source_id in selected_sources,
                "selection_relative_root": (
                    "not_requested" if source.source_id not in selected_sources
                    else "complete" if root is not None else "incomplete"
                ),
                "source_id": source.source_id,
            }
        )
    return result


def _source_root_documents(
    paths: ReV2Paths,
    inputs: ValidatedProtocol24Inputs,
    ledger: Protocol22LedgerView,
) -> list[dict[str, object]]:
    roots: list[dict[str, object]] = []
    for receipt in ledger.accepted_artifacts.values():
        key = receipt.artifact_key
        if key.layer != "L2" or key.artifact_kind != "source-baseline-root":
            continue
        path = materialized_path_for(
            paths,
            inputs.workspace_partition,
            key,
            receipt.artifact_hash,
        )
        roots.append(
            {
                "artifact_hash": receipt.artifact_hash,
                "artifact_key_id": key.identity,
                "materialized_path": str(path),
                "projection_status": _root_projection_status(path, receipt.artifact_hash),
                "source_id": key.scope.source_id,
            }
        )
    return sorted(roots, key=lambda item: str(item["source_id"]))


def _next_action(status: str) -> str:
    if status == "complete":
        return "none — selected L2 scope is complete"
    if status == "paused":
        return (
            "increase the child run resource authorization, then run "
            "`echelon re continue`"
        )
    if status == "blocked":
        return "start a new L2 child after addressing the terminal work-item failures"
    if status == "pinned_authority_unavailable":
        return "restore the pinned runtime authority before continuing"
    return "run `echelon re continue`"


def _adoption_duration_ms(events: tuple[EventRecord, ...]) -> int:
    created = next((item for item in events if item.type == "run_created"), None)
    adopted = [item for item in events if item.type == "artifact_adopted"]
    if created is None or not adopted:
        return 0
    start = datetime.fromisoformat(created.occurred_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(adopted[-1].occurred_at.replace("Z", "+00:00"))
    return max(0, int((end - start).total_seconds() * 1000))


def _dispatches_by_attempt_kind(
    events: tuple[EventRecord, ...],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        if event.type != "dispatch_started":
            continue
        kind = str(event.payload["attempt_kind"])
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def _render_human(document: Mapping[str, object]) -> str:
    selection = document["selection"]
    counts = document["artifact_counts"]
    budget = document["budget"]
    lines = [
        "RE V2 — PROTOCOL 2.4",
        f"run: {document['run_id']}",
        f"protocol: {document['engine_protocol_version']}",
        f"status: {document['status']}",
        (
            "selected L2 scope: "
            f"{selection['selected_sources']} source(s), "
            f"{selection['selected_domains']} domain(s)"
        ),
        (
            "selected L2 artifacts: "
            f"{counts['selected_l2']['accepted']}/"
            f"{counts['selected_l2']['required']} accepted"
        ),
        f"adopted artifacts: {counts['adopted']}",
        f"generated L2 artifacts: {counts['generated_l2']}",
    ]
    for dimension in ("tokens", "active_ms"):
        value = budget[dimension]
        lines.append(
            f"{dimension}: charged={value['charged']} "
            f"authorized={value['authorized']} "
            f"trusted_observed={value['trusted_observed']}"
        )
    for source in document["sources"]:
        domain_counts = source["domains"]
        lines.append(
            f"source {source['source_id']}: "
            f"{domain_counts['complete']}/{domain_counts['selected']} selected domains complete; "
            f"{domain_counts['intentionally_unselected']} intentionally unselected"
        )
    for failure in document["failures"]["work_items"]:
        lines.append(
            f"failed work: {failure['work_item_id']} "
            f"{failure['failure_class']}/{failure['reason_code']}"
        )
    lines.extend(
        (
            "semantic audit: not run",
            "workspace synthesis: not run",
            "exhaustive RE: not run",
            f"completion scope: {document['completion_scope']}",
            f"next action: {document['next_action']}",
            "=" * 72,
            str(document["banner"]),
        )
    )
    return "\n".join(lines) + "\n"


__all__ = (
    "Protocol24StatusError",
    "protocol_24_status_document",
    "render_protocol_24_status",
)

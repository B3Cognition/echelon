"""Read-only status and terminal banners for protocol 2.2."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.events import EventRecord, EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.run_store import ReV2Paths, load_run_manifest

from .artifacts import ContextBundleV1
from .baseline import CompactCertificationAssessmentV2
from .budget import BudgetDecisionV2, evaluate_budget_v22
from .events import PROTOCOL_22_EVENTS
from .execution import (
    InProcessDispatchReservationV1,
    dispatch_id_for,
    preview_dispatch_reservation,
)
from .executors import ExecutorContractCatalogV1, ExecutorContractEntryV1
from .graph import PlanDecisionV2, build_protocol_22_graph, plan_next_v22
from .inputs import load_protocol_22_inputs
from .ledger import Protocol22Ledger, Protocol22LedgerView
from .materialization import materialized_path_for
from .model import ExecutionCaptureV1, RunManifestV2, WorkItemV2
from .provider import (
    DispatchReservationV1,
    calculate_bounded_dispatch_reservation,
    render_provider_request_envelope,
)
from .recovery import (
    Protocol22RunContext,
    installed_authority_mismatches,
    resolve_execution_dependencies,
)
from .schema import load_canonical_object


_BANNERS = {
    "complete": "L1 COMPACT BASELINE COMPLETE",
    "paused": "L1 COMPACT BASELINE PAUSED — BUDGET AUTHORIZATION REQUIRED",
    "pinned_authority_unavailable": (
        "L1 COMPACT BASELINE UNAVAILABLE — PINNED AUTHORITY REQUIRED"
    ),
    "failed": "L1 COMPACT BASELINE INCOMPLETE — TERMINAL WORK-ITEM FAILURES",
    "in_progress": "L1 COMPACT BASELINE IN PROGRESS",
}
_NOT_RUN = {
    "exhaustive_re": "not run",
    "selective_deepening": "not run",
    "semantic_audit": "not run",
    "workspace_synthesis": "not run",
}


class Protocol22StatusError(RuntimeError):
    """Raised when protocol-2.2 status authority cannot be replayed safely."""


def render_protocol_22_status(
    run_dir: Path,
    *,
    as_json: bool = False,
    context: Protocol22RunContext | None = None,
) -> str:
    """Render one protocol-2.2 status view without repairing or dispatching."""
    document = protocol_22_status_document(run_dir, context=context)
    if as_json:
        return json.dumps(document, indent=2, sort_keys=True) + "\n"
    return _render_human(document)


def protocol_22_status_document(
    run_dir: Path,
    *,
    context: Protocol22RunContext | None = None,
) -> dict[str, object]:
    """Build JSON-safe status exclusively from immutable and durable authority."""
    run_path = Path(run_dir)
    try:
        manifest = load_run_manifest(run_path)
        if not isinstance(manifest, RunManifestV2) or (
            manifest.engine_protocol_version != "2.2"
        ):
            raise Protocol22StatusError(f"RE run is not protocol 2.2: {run_path.name}")
        paths = ReV2Paths.for_run(run_path)
        inputs = load_protocol_22_inputs(paths, manifest)
        graph = build_protocol_22_graph(manifest, inputs)
        if context is not None:
            if not isinstance(context, Protocol22RunContext):
                raise Protocol22StatusError(
                    "status context must be Protocol22RunContext"
                )
            if (
                context.paths != paths
                or context.inputs != inputs
                or context.graph != graph
            ):
                raise Protocol22StatusError(
                    "status context differs from immutable run authority"
                )
            mismatches = installed_authority_mismatches(
                inputs,
                context.installed_authorities,
            )
        else:
            mismatches = ()

        event_store = EventStore(paths, protocol=PROTOCOL_22_EVENTS)
        events = _read_events_without_creating_lock(event_store)
        terminal = _terminal_event(events)
        if mismatches and terminal is None:
            return _unavailable_document(manifest, mismatches)

        objects = (
            context.object_store if context is not None else ObjectStore(paths.objects)
        )
        ledger_store = (
            context.ledger if context is not None else Protocol22Ledger(paths, objects)
        )
        ledger = _read_ledger_without_creating_lock(ledger_store)
        open_dispatches = _open_dispatch_ids(events)
        now = context.clock() if context is not None else _utc_now()
        budget = evaluate_budget_v22(
            manifest.initial_budget_policy,
            events,
            open_dispatches,
            now,
        )
        plan = plan_next_v22(graph, ledger, budget)
        status = _run_status(events)
        authority = {
            "status": (
                "drift_warning"
                if mismatches
                else "available"
                if context is not None
                else "not_checked"
            ),
            "mismatches": _mismatch_documents(mismatches),
        }
        return _status_document(
            manifest,
            paths,
            inputs.workspace_partition,
            graph,
            events,
            ledger,
            budget,
            plan,
            objects,
            status,
            authority,
            context,
            inputs.executor_contract,
        )
    except Protocol22StatusError:
        raise
    except Exception as exc:
        raise Protocol22StatusError(
            f"cannot replay protocol-2.2 status for {run_path.name}: {exc}"
        ) from exc


def _status_document(
    manifest: RunManifestV2,
    paths: ReV2Paths,
    partition: object,
    graph: object,
    events: tuple[EventRecord, ...],
    ledger: Protocol22LedgerView,
    budget: BudgetDecisionV2,
    plan: PlanDecisionV2,
    objects: ObjectStore,
    status: str,
    authority: Mapping[str, object],
    context: Protocol22RunContext | None,
    executor_catalog: ExecutorContractCatalogV1,
) -> dict[str, object]:
    templates = tuple(graph.templates)
    accepted_template_ids = {
        ledger.certification_work_items[receipt.certification_receipt_id].template_id
        for receipt in ledger.accepted_artifacts.values()
    }
    by_kind: dict[str, dict[str, int]] = {}
    for template in templates:
        counts = by_kind.setdefault(
            template.artifact_kind,
            {"accepted": 0, "required": 0},
        )
        counts["required"] += 1
        counts["accepted"] += template.template_id in accepted_template_ids
    plan_items = _plan_documents(templates, plan)
    plan_actions = {str(item["action"]) for item in plan_items}
    if status == "complete" and plan_actions != {"reuse"}:
        raise Protocol22StatusError(
            "run_completed does not match the accepted graph authority"
        )
    if status == "failed" and (
        plan.ready
        or not plan_actions.intersection(
            {"failed", "blocked_executor", "blocked_dependency", "blocked_attempts"}
        )
    ):
        raise Protocol22StatusError(
            "run_failed does not match a terminal graph fixed point"
        )
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
    next_work = _next_work_document(
        context,
        plan,
        budget,
        events,
        ledger,
        objects,
        executor_catalog,
    )
    roots = _source_root_documents(paths, partition, ledger)
    return {
        "artifact_counts": {
            "by_kind": dict(sorted(by_kind.items())),
            "total": {
                "accepted": len(accepted_template_ids),
                "required": len(templates),
            },
        },
        "authority": dict(authority),
        "banner": _BANNERS[status],
        "baselines": _baseline_documents(ledger),
        "budget": _budget_document(budget),
        "context_estimates": _context_estimates(ledger, objects),
        "continuable": status == "paused",
        "domains": _domain_documents(
            partition,
            templates,
            accepted_template_ids,
        ),
        "engine": manifest.engine,
        "engine_protocol_version": manifest.engine_protocol_version,
        "failures": _failure_documents(ledger, plan_items),
        "materialization": _materialization_document(paths),
        "next_work": next_work,
        "not_run": dict(_NOT_RUN),
        "partition_manifest_id": manifest.partition_manifest_id,
        "plan": plan_items,
        "plan_counts": plan_counts,
        "requested_goals": list(manifest.requested_goals),
        "run_id": manifest.run_id,
        "source_roots": roots,
        "source_snapshot_id": manifest.source_snapshot_id,
        "source_snapshot_kind": manifest.source_snapshot_kind,
        "sources": _source_documents(
            partition,
            templates,
            accepted_template_ids,
        ),
        "status": status,
        "telemetry": _telemetry_document(events, budget, objects, paths),
        "accepted_siblings": [item for item in plan_items if item["action"] == "reuse"],
    }


def _unavailable_document(
    manifest: RunManifestV2, mismatches: tuple[object, ...]
) -> dict[str, object]:
    return {
        "authority": {
            "status": "pinned_authority_unavailable",
            "mismatches": _mismatch_documents(mismatches),
        },
        "banner": _BANNERS["pinned_authority_unavailable"],
        "continuable": False,
        "engine": manifest.engine,
        "engine_protocol_version": manifest.engine_protocol_version,
        "not_run": dict(_NOT_RUN),
        "partition_manifest_id": manifest.partition_manifest_id,
        "requested_goals": list(manifest.requested_goals),
        "run_id": manifest.run_id,
        "source_snapshot_id": manifest.source_snapshot_id,
        "status": "pinned_authority_unavailable",
    }


def _mismatch_documents(mismatches: tuple[object, ...]) -> list[dict[str, object]]:
    return [
        {
            "authority_id": item.authority_id,
            "authority_kind": item.authority_kind,
            "expected_digest": item.expected_digest,
            "installed_digest": item.installed_digest,
        }
        for item in mismatches
    ]


def _plan_documents(
    templates: tuple[object, ...], plan: PlanDecisionV2
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for template in templates:
        explanation = plan.explanations[template.template_id]
        result.append(
            {
                "action": explanation.action,
                "artifact_kind": template.artifact_kind,
                "domain_key": template.scope.domain_key,
                "reason_code": explanation.reason_code,
                "receipt_id": explanation.receipt_id,
                "source_id": template.scope.source_id,
                "template_id": template.template_id,
                "work_item_id": explanation.work_item_id,
            }
        )
    return result


def _source_documents(
    partition: object,
    templates: tuple[object, ...],
    accepted_template_ids: set[str],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for source in partition.sources:
        scoped = tuple(
            template
            for template in templates
            if template.scope.source_id == source.source_id
        )
        domains = tuple(
            template
            for template in scoped
            if template.artifact_kind == "domain-baseline"
        )
        roots = tuple(
            template
            for template in scoped
            if template.artifact_kind == "source-baseline-root"
        )
        result.append(
            {
                "artifacts": {
                    "accepted": sum(
                        item.template_id in accepted_template_ids for item in scoped
                    ),
                    "required": len(scoped),
                },
                "domains": {
                    "accepted": sum(
                        item.template_id in accepted_template_ids for item in domains
                    ),
                    "required": len(domains),
                },
                "source_id": source.source_id,
                "source_roots": {
                    "accepted": sum(
                        item.template_id in accepted_template_ids for item in roots
                    ),
                    "required": len(roots),
                },
            }
        )
    return result


def _domain_documents(
    partition: object,
    templates: tuple[object, ...],
    accepted_template_ids: set[str],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for source in partition.sources:
        for domain in source.domains:
            scoped = tuple(
                template
                for template in templates
                if template.scope.source_id == source.source_id
                and template.scope.domain_key == domain.domain_key
            )
            result.append(
                {
                    "accepted": sum(
                        item.template_id in accepted_template_ids for item in scoped
                    ),
                    "domain_key": domain.domain_key,
                    "presentation_domain_id": domain.presentation_domain_id,
                    "required": len(scoped),
                    "source_id": source.source_id,
                }
            )
    return result


def _source_root_documents(
    paths: ReV2Paths,
    partition: object,
    ledger: Protocol22LedgerView,
) -> list[dict[str, object]]:
    roots: list[dict[str, object]] = []
    for receipt in ledger.accepted_artifacts.values():
        if receipt.artifact_key.artifact_kind != "source-baseline-root":
            continue
        path = materialized_path_for(
            paths,
            partition,
            receipt.artifact_key,
            receipt.artifact_hash,
        )
        roots.append(
            {
                "artifact_hash": receipt.artifact_hash,
                "artifact_key_id": receipt.artifact_key.identity,
                "materialized_path": str(path),
                "projection_status": _root_projection_status(
                    path,
                    receipt.artifact_hash,
                ),
                "source_id": receipt.artifact_key.scope.source_id,
            }
        )
    return sorted(roots, key=lambda item: str(item["source_id"]))


def _baseline_documents(ledger: Protocol22LedgerView) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for receipt in ledger.certifications.values():
        assessment = receipt.assessment
        if not isinstance(assessment, CompactCertificationAssessmentV2):
            continue
        key = receipt.certification_key.artifact_key
        result.append(
            {
                "artifact_hash": receipt.certification_key.artifact_hash,
                "artifact_kind": key.artifact_kind,
                "certification_receipt_id": receipt.identity,
                "coverage": assessment.coverage.to_json_dict(),
                "depth_debt": assessment.depth_debt.to_json_dict(),
                "domain_key": key.scope.domain_key,
                "minimum_utility": assessment.minimum_utility.to_json_dict(),
                "required_surfaces": [
                    item.to_json_dict() for item in assessment.required_surfaces
                ],
                "semantic_status": assessment.semantic_status,
                "source_id": key.scope.source_id,
                "verdict": receipt.verdict,
                "work_item_id": ledger.certification_work_items[
                    receipt.identity
                ].work_item_id,
            }
        )
    return sorted(
        result,
        key=lambda item: (
            str(item["source_id"]),
            str(item["domain_key"] or ""),
            str(item["artifact_kind"]),
        ),
    )


def _context_estimates(
    ledger: Protocol22LedgerView,
    objects: ObjectStore,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for receipt in ledger.accepted_artifacts.values():
        if receipt.artifact_key.artifact_kind not in {
            "domain-context-bundle",
            "source-overview-context-bundle",
        }:
            continue
        payload = objects.read_blob(receipt.artifact_hash)
        bundle = load_canonical_object(payload, ContextBundleV1.from_json_dict)
        work_item = ledger.certification_work_items[receipt.certification_receipt_id]
        result.append(
            {
                "artifact_hash": receipt.artifact_hash,
                "artifact_kind": receipt.artifact_key.artifact_kind,
                "canonical_bytes": len(payload),
                "conservative_input_tokens": len(payload),
                "domain_key": bundle.scope.domain_key,
                "source_id": bundle.scope.source_id,
                "target_artifact_kind": bundle.target_artifact_kind,
                "work_item_id": work_item.work_item_id,
            }
        )
    return sorted(
        result,
        key=lambda item: (
            str(item["source_id"]),
            str(item["domain_key"] or ""),
        ),
    )


def _failure_documents(
    ledger: Protocol22LedgerView,
    plan_items: list[dict[str, object]],
) -> dict[str, object]:
    scope_by_work = {
        item["work_item_id"]: item
        for item in plan_items
        if item["work_item_id"] is not None
    }
    work_items = []
    for receipt in ledger.work_item_failures.values():
        scope = scope_by_work.get(receipt.work_item_id, {})
        work_items.append(
            {
                "artifact_kind": scope.get("artifact_kind"),
                "diagnostics": list(receipt.normalized_diagnostics),
                "domain_key": scope.get("domain_key"),
                "failure_class": receipt.failure_class,
                "reason_code": receipt.reason_code,
                "receipt_id": receipt.identity,
                "source_id": scope.get("source_id"),
                "work_item_id": receipt.work_item_id,
            }
        )
    executors = [
        {
            "diagnostics": list(receipt.normalized_diagnostics),
            "executor_contract_hash": receipt.executor_contract_hash,
            "reason_code": receipt.reason_code,
            "receipt_id": receipt.identity,
            "trigger_work_item_id": receipt.trigger_work_item_id,
        }
        for receipt in ledger.executor_failures.values()
    ]
    blocked = [
        item
        for item in plan_items
        if item["action"]
        in {"blocked_executor", "blocked_dependency", "blocked_attempts"}
    ]
    return {
        "blocked": blocked,
        "executors": sorted(
            executors,
            key=lambda item: str(item["executor_contract_hash"]),
        ),
        "work_items": sorted(
            work_items,
            key=lambda item: str(item["work_item_id"]),
        ),
    }


def _budget_document(budget: BudgetDecisionV2) -> dict[str, object]:
    return {
        "active_ms": _resource_document(
            budget.charged_active_ms,
            budget.active_ms_limit,
            budget.open_active_ms_reservations,
            budget.trusted_observed_active_ms,
            budget.unknown_active_dispatches,
        ),
        "attempts": {
            "artifact_contract_retries": dict(budget.artifact_contract_retries),
            "generation": dict(budget.generation_attempts),
            "provider": dict(budget.provider_attempts),
            "result_contract_retries": dict(budget.result_contract_retries),
            "semantic_rounds": dict(budget.semantic_rounds),
            "shared_retries": dict(budget.shared_retries),
        },
        "attempt_limits": {
            "artifact_contract_retries_per_item": budget.artifact_contract_retry_limit,
            "generation_per_item": budget.generation_attempt_limit,
            "provider_per_item": budget.provider_attempt_limit,
            "result_contract_retries_per_item": budget.result_contract_retry_limit,
            "semantic_rounds_per_item": budget.semantic_round_limit,
            "shared_retries_per_item": budget.shared_retry_limit,
        },
        "exhausted_dimensions": list(budget.exhausted_dimensions),
        "reservation_breaches": list(budget.reservation_breaches),
        "tokens": _resource_document(
            budget.charged_tokens,
            budget.token_limit,
            budget.open_token_reservations,
            budget.trusted_observed_tokens,
            budget.unknown_token_dispatches,
        ),
    }


def _resource_document(
    charged: int,
    authorized: int | None,
    open_reservation: int,
    trusted_observed: int,
    unknown_dispatches: int,
) -> dict[str, object]:
    return {
        "authorized": authorized,
        "charged": charged,
        "open_reservation": open_reservation,
        "remaining": None if authorized is None else max(0, authorized - charged),
        "trusted_observed": trusted_observed,
        "unknown_dispatches": unknown_dispatches,
    }


def _next_work_document(
    context: Protocol22RunContext | None,
    plan: PlanDecisionV2,
    budget: BudgetDecisionV2,
    events: tuple[EventRecord, ...],
    ledger: Protocol22LedgerView,
    objects: ObjectStore,
    executor_catalog: ExecutorContractCatalogV1,
) -> dict[str, object] | None:
    if not plan.ready:
        return None
    item = plan.ready[0]
    result: dict[str, object] = {
        "artifact_kind": item.output_key.artifact_kind,
        "domain_key": item.output_key.scope.domain_key,
        "reservation": None,
        "source_id": item.output_key.scope.source_id,
        "work_item_id": item.work_item_id,
    }
    attempt_kind = _attempt_kind(item, budget)
    if context is None:
        dispatch_id, reservation = _preview_from_pinned_run(
            item,
            attempt_kind,
            events,
            ledger,
            objects,
            executor_catalog,
        )
    else:
        dependencies = resolve_execution_dependencies(context, item, attempt_kind)
        preview = preview_dispatch_reservation(item, attempt_kind, dependencies)
        dispatch_id = preview.dispatch_id
        reservation = preview.reservation
    result["attempt_kind"] = attempt_kind
    result["dispatch_id"] = dispatch_id
    result["reservation"] = {
        "active_ms": reservation.active_ms,
        "billable_tokens": reservation.billable_tokens,
    }
    initial_input_tokens = getattr(reservation, "initial_input_tokens", None)
    if initial_input_tokens is not None:
        result["reservation"]["initial_input_tokens"] = initial_input_tokens
    return result


class _PinnedConservativeTokenizer:
    def __init__(self, executor: ExecutorContractEntryV1) -> None:
        authority = executor.request_tokenizer
        if authority is None:
            raise Protocol22StatusError(
                "provider executor has no pinned tokenizer authority"
            )
        self.tokenizer_id = authority.tokenizer_id
        self.tokenizer_version = authority.tokenizer_version
        self.implementation_digest = authority.implementation_digest

    def count_tokens(self, payload: bytes) -> None:
        del payload
        return None


def _preview_from_pinned_run(
    item: WorkItemV2,
    attempt_kind: str,
    events: tuple[EventRecord, ...],
    ledger: Protocol22LedgerView,
    objects: ObjectStore,
    executor_catalog: ExecutorContractCatalogV1,
) -> tuple[str, DispatchReservationV1 | InProcessDispatchReservationV1]:
    executor = executor_catalog.entry_for(item.producer_family)
    if executor.executor_contract_hash != item.executor_contract_hash:
        raise Protocol22StatusError(
            "next work item differs from its pinned executor authority"
        )
    dispatch_id = dispatch_id_for(item, attempt_kind)
    if executor.execution_mode == "in_process":
        if attempt_kind != "initial_generation":
            raise Protocol22StatusError(
                "deterministic next work cannot be a retry attempt"
            )

        return dispatch_id, InProcessDispatchReservationV1(
            billable_tokens=0,
            active_ms=executor.limits.max_active_ms_per_dispatch,
        )
    if executor.execution_mode != "api":
        raise Protocol22StatusError("next work uses an unsupported execution mode")
    if len(item.required_artifact_hashes) != 1:
        raise Protocol22StatusError(
            "provider next work does not have one context-bundle dependency"
        )
    renderer = executor.request_renderer
    if renderer is None:
        raise Protocol22StatusError("provider next work has no renderer authority")
    schema_hash = next(
        (
            reference.schema_hash
            for reference in renderer.response_schemas
            if reference.artifact_kind == item.output_key.artifact_kind
        ),
        None,
    )
    if schema_hash is None:
        raise Protocol22StatusError(
            "provider next work has no response-schema authority"
        )
    diagnostics = _pinned_retry_diagnostics(
        item,
        attempt_kind,
        events,
        ledger,
    )
    schema_bytes = objects.read_blob(schema_hash)
    envelope = render_provider_request_envelope(
        item,
        dispatch_id,
        objects.read_blob(renderer.agent_contract_hash),
        objects.read_blob(item.required_artifact_hashes[0]),
        executor,
        schema_hash,
        diagnostics,
    )
    reservation = calculate_bounded_dispatch_reservation(
        envelope,
        schema_bytes,
        executor,
        _PinnedConservativeTokenizer(executor),
    )
    return dispatch_id, reservation


def _pinned_retry_diagnostics(
    item: WorkItemV2,
    attempt_kind: str,
    events: tuple[EventRecord, ...],
    ledger: Protocol22LedgerView,
) -> tuple[str, ...]:
    if attempt_kind == "initial_generation":
        return ()
    if attempt_kind == "result_contract_retry":
        abandoned = any(
            event.type == "dispatch_abandoned"
            and event.payload["work_item_id"] == item.work_item_id
            for event in events
        )
        return (
            "execution_outcome_indeterminate" if abandoned else "result_unrecoverable",
        )
    if attempt_kind != "artifact_contract_retry":
        raise Protocol22StatusError("next work has an unsupported retry kind")
    rejected = next(
        (
            event
            for event in reversed(events)
            if event.type == "candidate_rejected"
            and event.payload["work_item_id"] == item.work_item_id
        ),
        None,
    )
    if rejected is None:
        raise Protocol22StatusError(
            "artifact retry has no preceding candidate rejection"
        )
    assessment = ledger.candidate_assessments.get(
        str(rejected.payload["candidate_assessment_id"])
    )
    if assessment is None or not assessment.normalized_diagnostics:
        raise Protocol22StatusError(
            "artifact retry has no exact normalized diagnostics"
        )
    return tuple(assessment.normalized_diagnostics)


def _attempt_kind(item: WorkItemV2, budget: BudgetDecisionV2) -> str:
    if budget.generation_attempts.get(item.work_item_id, 0) == 0:
        return "initial_generation"
    retry = budget.retry_eligibility.get(item.work_item_id)
    if retry not in {"result_contract_retry", "artifact_contract_retry"}:
        raise Protocol22StatusError("next retry has no exact eligibility")
    return retry


def _telemetry_document(
    events: tuple[EventRecord, ...],
    budget: BudgetDecisionV2,
    objects: ObjectStore,
    paths: ReV2Paths,
) -> dict[str, object]:
    complete = 0
    terminal_tail = 0
    captures: set[str] = set()
    for event in events:
        if event.type != "dispatch_observed":
            continue
        capture_hash = str(event.payload["execution_capture_hash"])
        if capture_hash in captures:
            continue
        captures.add(capture_hash)
        capture = load_canonical_object(
            objects.read_blob(capture_hash),
            ExecutionCaptureV1.from_json_dict,
        )
        if capture.stdout_capture == "complete":
            complete += 1
        else:
            terminal_tail += 1
    return {
        "abandoned_dispatches": sum(
            event.type == "dispatch_abandoned" for event in events
        ),
        "candidate_persisted": sum(
            event.type == "candidate_persisted" for event in events
        ),
        "capture_complete": complete,
        "capture_terminal_tail": terminal_tail,
        "completed_staging_commits": _safe_entry_count(
            paths.root / "captures" / "committed"
        ),
        "incomplete_staging": _safe_entry_count(paths.root / "captures" / ".staging"),
        "result_contract_reconstructed": sum(
            event.type == "result_contract_reconstructed" for event in events
        ),
        "trusted_observed_active_ms": budget.trusted_observed_active_ms,
        "trusted_observed_tokens": budget.trusted_observed_tokens,
        "unknown_active_dispatches": budget.unknown_active_dispatches,
        "unknown_token_dispatches": budget.unknown_token_dispatches,
    }


def _materialization_document(paths: ReV2Paths) -> dict[str, object]:
    root = paths.root / "quarantine" / "materialized"
    if not root.exists() and not root.is_symlink():
        entries: list[str] = []
    else:
        root_fd = _open_directory_path_nofollow(root, "materialization quarantine")
        try:
            names = sorted(os.listdir(root_fd))
            for name in names:
                metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode) or not (
                    stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)
                ):
                    raise Protocol22StatusError(
                        "unsafe entry in materialization quarantine"
                    )
            entries = [str(root / name) for name in names]
        finally:
            os.close(root_fd)
    return {"quarantine_paths": entries, "quarantined_count": len(entries)}


def _safe_entry_count(path: Path) -> int:
    if not path.exists() and not path.is_symlink():
        return 0
    directory_fd = _open_directory_path_nofollow(path, "telemetry directory")
    try:
        names = [name for name in os.listdir(directory_fd) if not name.startswith(".")]
        for name in names:
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise Protocol22StatusError(f"unsafe telemetry entry in {path}: {name}")
        return len(names)
    finally:
        os.close(directory_fd)


def _root_projection_status(path: Path, artifact_hash: str) -> str:
    try:
        parent_fd = _open_directory_path_nofollow(
            path.parent,
            "source-root materialization parent",
        )
        try:
            metadata = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                return "unsafe_or_altered"
            fd = os.open(
                path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            try:
                payload = b""
                while True:
                    chunk = os.read(fd, 64 * 1024)
                    if not chunk:
                        break
                    payload += chunk
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)
        return (
            "present"
            if content_digest(payload) == artifact_hash
            else "unsafe_or_altered"
        )
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unsafe_or_altered"


def _open_directory_path_nofollow(path: Path, label: str) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    absolute = path.absolute()
    current = os.open("/", flags)
    try:
        for part in absolute.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = next_fd
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            raise Protocol22StatusError(f"{label} is not a directory")
        return current
    except Exception:
        os.close(current)
        raise


def _read_events_without_creating_lock(store: EventStore) -> tuple[EventRecord, ...]:
    if not store.path.exists():
        return ()
    if not store.lock_path.exists():
        raise Protocol22StatusError(
            "event history exists without its durable lock authority"
        )
    return store.replay()


def _read_ledger_without_creating_lock(
    store: Protocol22Ledger,
) -> Protocol22LedgerView:
    if not store.path.exists() and not store.path.is_symlink():
        if store.lock_path.is_symlink():
            raise Protocol22StatusError("ledger lock is an unsafe symlink")
        if store.lock_path.exists():
            return store.replay()
        empty: Mapping[str, object] = MappingProxyType({})
        return Protocol22LedgerView(
            certifications=empty,
            certification_work_items=empty,
            candidate_assessments=empty,
            accepted_artifacts=empty,
            work_item_failures=empty,
            executor_failures=empty,
            certification_records=empty,
            candidate_assessment_records=empty,
            artifact_acceptance_records=empty,
            work_item_failure_records=empty,
            executor_failure_records=empty,
        )
    if not store.lock_path.exists() or store.lock_path.is_symlink():
        raise Protocol22StatusError(
            "ledger history exists without its durable lock authority"
        )
    return store.replay()


def _terminal_event(events: tuple[EventRecord, ...]) -> EventRecord | None:
    return next(
        (
            event
            for event in reversed(events)
            if event.type in {"run_completed", "run_failed"}
        ),
        None,
    )


def _run_status(events: tuple[EventRecord, ...]) -> str:
    terminal = _terminal_event(events)
    if terminal is not None:
        return "complete" if terminal.type == "run_completed" else "failed"
    paused = max(
        (event.seq for event in events if event.type == "run_paused"),
        default=0,
    )
    resumed = max(
        (event.seq for event in events if event.type == "run_resumed"),
        default=0,
    )
    return "paused" if paused > resumed else "in_progress"


def _open_dispatch_ids(events: tuple[EventRecord, ...]) -> frozenset[str]:
    started = {
        str(event.payload["dispatch_id"])
        for event in events
        if event.type == "dispatch_started"
    }
    closed = {
        str(event.payload["dispatch_id"])
        for event in events
        if event.type in {"dispatch_observed", "dispatch_abandoned"}
    }
    return frozenset(started - closed)


def _render_human(document: Mapping[str, object]) -> str:
    lines = [
        f"run: {document['run_id']}",
        f"protocol: {document['engine_protocol_version']}",
        f"status: {document['status']}",
    ]
    counts = document.get("artifact_counts")
    if isinstance(counts, Mapping) and isinstance(counts.get("total"), Mapping):
        total = counts["total"]
        lines.append(f"artifacts: {total['accepted']}/{total['required']} accepted")
    budget = document.get("budget")
    if isinstance(budget, Mapping):
        for dimension in ("tokens", "active_ms"):
            value = budget.get(dimension)
            if isinstance(value, Mapping):
                lines.append(
                    f"{dimension}: charged={value['charged']} "
                    f"authorized={value['authorized']} "
                    f"open_reservation={value['open_reservation']}"
                )
    next_work = document.get("next_work")
    if isinstance(next_work, Mapping):
        lines.append(
            "next work: "
            f"{next_work['work_item_id']} "
            f"({next_work['source_id']}/{next_work['artifact_kind']})"
        )
        reservation = next_work.get("reservation")
        if isinstance(reservation, Mapping):
            lines.append(
                "next reservation: "
                f"tokens={reservation['billable_tokens']} "
                f"active_ms={reservation['active_ms']}"
            )
    failures = document.get("failures")
    if isinstance(failures, Mapping):
        for failure in failures.get("work_items", []):
            lines.append(
                "failed work: "
                f"{failure['work_item_id']} {failure['failure_class']}/"
                f"{failure['reason_code']} receipt={failure['receipt_id']}"
            )
        for failure in failures.get("executors", []):
            lines.append(
                "failed executor: "
                f"{failure['executor_contract_hash']} {failure['reason_code']} "
                f"receipt={failure['receipt_id']}"
            )
    roots = document.get("source_roots")
    if isinstance(roots, list):
        for root in roots:
            lines.append(
                f"source root {root['source_id']}: {root['artifact_hash']} "
                f"at {root['materialized_path']} ({root['projection_status']})"
            )
    authority = document.get("authority")
    if isinstance(authority, Mapping):
        for mismatch in authority.get("mismatches", []):
            lines.append(
                "pinned authority mismatch: "
                f"{mismatch['authority_kind']}:{mismatch['authority_id']} "
                f"expected={mismatch['expected_digest']} "
                f"installed={mismatch['installed_digest'] or 'missing'}"
            )
    lines.extend(
        (
            "semantic audit: not run",
            "workspace synthesis: not run",
            "selective deepening: not run",
            "exhaustive RE: not run",
            "completion scope: compact L1 baseline only",
            "=" * 72,
            str(document["banner"]),
        )
    )
    return "\n".join(lines) + "\n"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


__all__ = (
    "Protocol22StatusError",
    "protocol_22_status_document",
    "render_protocol_22_status",
)

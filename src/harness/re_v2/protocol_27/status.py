"""Authenticated protocol-2.7 status documents and terminal banners."""

from __future__ import annotations

import json
from pathlib import Path

from harness.re_registry import load_published_index
from harness.re_v2.protocol_22.cli_provider import (
    calculate_shared_cli_dispatch_reservation,
)
from harness.re_v2.publication import current_index_hash, load_published_v2_index

from .budget import evaluate_synthesis_budget
from .controller import plan_next_synthesis, reconstruct_synthesis_controller_state
from .execution import build_synthesis_provider_dependencies
from .recovery import load_protocol_27_run_context


class Protocol27StatusError(RuntimeError):
    """Raised when protocol-2.7 authority cannot be rendered exactly."""


def protocol_27_status_document(run_dir: Path) -> dict[str, object]:
    try:
        context = load_protocol_27_run_context(Path(run_dir))
        manifest = context.inputs.manifest
        events = context.events.replay()
        ledger = context.ledger.replay()
        budget = evaluate_synthesis_budget(manifest, events, ledger)
        state = reconstruct_synthesis_controller_state(
            context.inputs, ledger, events, budget
        )
        action = plan_next_synthesis(state)
        next_reservation: dict[str, object] | None = None
        insufficient_dimensions: list[str] = []
        if action.kind == "dispatch" and action.work_item is not None:
            dependencies = build_synthesis_provider_dependencies(
                context.inputs,
                action.work_item,
                action.retry_diagnostics,
            )
            reservation = calculate_shared_cli_dispatch_reservation(
                dependencies.agent_bytes,
                dependencies.context_bytes,
                dependencies.response_schema_bytes,
                dependencies.executor,
                dependencies.retry_diagnostics,
            )
            token_remaining = (
                None
                if budget.token_limit is None
                else max(0, budget.token_limit - budget.charged_tokens)
            )
            active_remaining = (
                None
                if budget.active_ms_limit is None
                else max(0, budget.active_ms_limit - budget.charged_active_ms)
            )
            if token_remaining is not None and reservation.billable_tokens > token_remaining:
                insufficient_dimensions.append("tokens")
            if active_remaining is not None and reservation.active_ms > active_remaining:
                insufficient_dimensions.append("active_ms")
            next_reservation = {
                "work_item_id": action.work_item.work_item_id,
                "artifact_kind": action.work_item.output_key.artifact_kind,
                "billable_tokens": reservation.billable_tokens,
                "active_ms": reservation.active_ms,
                "remaining_tokens": token_remaining,
                "remaining_active_ms": active_remaining,
                "fits": not insufficient_dimensions,
            }
        workspace = context.paths.root.parent.parent.parent
        current_compatibility = load_published_index(workspace)
        current_v2 = load_published_v2_index(workspace)
        complete_sources = tuple(
            item.source_id
            for item in manifest.accepted_sources
            if item.outcome == "complete"
        )
        partial_sources = tuple(
            item.source_id
            for item in manifest.accepted_sources
            if item.outcome == "partial"
        )
        accepted_key_ids = set(ledger.accepted_artifacts)
        artifact_rows: list[dict[str, object]] = []
        for node in context.inputs.graph.required_nodes:
            matches = [
                (key_id, work_item)
                for key_id, work_item in ledger.accepted_work_items.items()
                if context.inputs.graph.node_for_work_item(work_item).node_id
                == node.node_id
            ]
            key_id = matches[0][0] if matches else None
            work_id = matches[0][1].work_item_id if matches else None
            adoption = (
                None if work_id is None else ledger.checkpoint_adoptions.get(work_id)
            )
            artifact_rows.append(
                {
                    "artifact_kind": node.artifact_kind,
                    "artifact_key_id": key_id,
                    "node_id": node.node_id,
                    "scope": node.scope.kind,
                    "source_id": node.scope.source_id,
                    "workspace_domain_id": node.scope.workspace_domain_id,
                    "origin_run_id": (
                        None if adoption is None else adoption.origin_run_id
                    ),
                    "status": (
                        "adopted"
                        if adoption is not None
                        else "generated"
                        if key_id in accepted_key_ids
                        else "unresolved"
                    ),
                    "attempts": (
                        0
                        if work_id is None
                        else budget.provider_attempts_by_work_item.get(work_id, 0)
                    ),
                }
            )
        synthesis_complete = bool(
            ledger.synthesis_root is not None
            and len(ledger.accepted_artifacts)
            == len(context.inputs.graph.required_nodes)
        )
        compatibility_matches = bool(
            ledger.publication is not None
            and current_compatibility is not None
            and current_compatibility.published_from_run == manifest.run_id
            and current_compatibility.generation
            == ledger.publication.compatibility_generation
            and current_compatibility.synthesis_quality is not None
            and current_compatibility.synthesis_quality.synthesis_root_id
            == ledger.publication.synthesis_root_id
        )
        v2_matches = bool(
            ledger.publication is not None
            and current_v2 is not None
            and current_v2.run_id == manifest.run_id
        )
        if compatibility_matches and v2_matches:
            publication_status = f"published_{manifest.input_quality}"
        elif ledger.publication is not None:
            publication_status = "conflict"
        elif not synthesis_complete:
            publication_status = "not_attempted"
        elif (
            current_index_hash(workspace) != manifest.expected_v2_index_hash
            or (current_compatibility.generation if current_compatibility else 0)
            != manifest.expected_compatibility_generation
        ):
            publication_status = "conflict"
        else:
            publication_status = "not_attempted"
        accepted_work_item_ids = {
            item.work_item_id for item in ledger.accepted_work_items.values()
        }
        failures = [
            {
                "failure_class": str(event.payload["failure_class"]),
                "reason_code": str(event.payload["reason_code"]),
                "work_item_id": str(event.payload["work_item_id"]),
                "resolved": str(event.payload["work_item_id"])
                in accepted_work_item_ids,
            }
            for event in events
            if event.type == "work_item_failed"
        ]
        unresolved_failed_work_items = {
            str(item["work_item_id"])
            for item in failures
            if item["resolved"] is False
        }
        next_action = _next_action(
            manifest.run_id,
            partial_sources,
            synthesis_complete,
            publication_status,
            action.kind,
        )
        return {
            "schema_version": manifest.schema_version,
            "engine": manifest.engine,
            "engine_protocol_version": manifest.engine_protocol_version,
            "run_id": manifest.run_id,
            "parent_run_id": manifest.parent_run_id,
            "parent_manifest_hash": manifest.parent_manifest_hash,
            "request_id": manifest.request_id,
            "source_snapshot_id": manifest.source_snapshot_id,
            "partition_manifest_id": manifest.partition_manifest_id,
            "sources": {
                "complete": list(complete_sources),
                "partial": list(partial_sources),
                "outcomes": [item.to_json_dict() for item in manifest.accepted_sources],
            },
            "debt_manifest_hashes": list(
                ledger.synthesis_root.debt_manifest_hashes
                if ledger.synthesis_root is not None
                else sorted(
                    item.debt_manifest_hash
                    for item in manifest.accepted_sources
                    if item.debt_manifest_hash is not None
                )
            ),
            "partial_acceptance_receipt_ids": list(
                item.receipt_id for item in manifest.partial_acceptances
            ),
            "artifacts": artifact_rows,
            "artifact_counts": {
                "required": len(context.inputs.graph.required_nodes),
                "generated": sum(row["status"] == "generated" for row in artifact_rows),
                "adopted": sum(row["status"] == "adopted" for row in artifact_rows),
                "failed": len(unresolved_failed_work_items),
                "failed_attempts": len(failures),
                "unresolved": sum(row["status"] == "unresolved" for row in artifact_rows),
            },
            "failures": failures,
            "checkpoint_dispositions": [
                item.to_json_dict()
                for item in context.inputs.checkpoint_selection.dispositions
            ],
            "resources": {
                "known_tokens": budget.known_tokens,
                "known_active_ms": budget.known_active_ms,
                "charged_tokens": budget.charged_tokens,
                "charged_active_ms": budget.charged_active_ms,
                "unknown_token_dispatches": budget.unknown_token_dispatches,
                "unknown_active_dispatches": budget.unknown_active_dispatches,
                "open_token_reservations": budget.open_token_reservations,
                "open_active_ms_reservations": budget.open_active_ms_reservations,
                "provider_attempts": budget.provider_attempts,
                "result_contract_retries": sum(budget.result_contract_retries.values()),
                "artifact_contract_retries": sum(budget.artifact_contract_retries.values()),
                "token_limit": budget.token_limit,
                "active_ms_limit": budget.active_ms_limit,
                "exhausted_dimensions": list(budget.exhausted_dimensions),
                "insufficient_remaining_dimensions": insufficient_dimensions,
                "next_reservation": next_reservation,
            },
            "avoided_provider_calls": len(ledger.checkpoint_adoptions),
            "avoided_reservations": len(ledger.checkpoint_adoptions),
            "synthesis_status": "complete" if synthesis_complete else "incomplete",
            "input_quality": manifest.input_quality,
            "publication_status": publication_status,
            "full_quality_claim": (
                "available"
                if synthesis_complete
                and manifest.input_quality == "complete"
                and publication_status == "published_complete"
                else "unavailable"
            ),
            "synthesis_root_id": (
                None if ledger.synthesis_root is None else ledger.synthesis_root.identity
            ),
            "materialization_manifest_id": (
                None
                if ledger.materialization is None
                else ledger.materialization.materialization_manifest_id
            ),
            "publication_descriptor_id": (
                None if ledger.publication is None else ledger.publication.descriptor_id
            ),
            "compatibility_generation": (
                None if current_compatibility is None else current_compatibility.generation
            ),
            "v2_generation_id": None if current_v2 is None else current_v2.generation_id,
            "next_action": next_action,
            "stop_reason": (
                "synthesis-reservation-exceeds-remaining-budget"
                if insufficient_dimensions
                else action.reason
            ),
        }
    except Protocol27StatusError:
        raise
    except Exception as exc:
        raise Protocol27StatusError(
            f"cannot replay protocol-2.7 status for {Path(run_dir).name}: {exc}"
        ) from exc


def render_protocol_27_status(run_dir: Path, *, as_json: bool = False) -> str:
    document = protocol_27_status_document(run_dir)
    if as_json:
        return json.dumps(document, indent=2, sort_keys=True) + "\n"
    synthesis = str(document["synthesis_status"])
    quality = str(document["input_quality"])
    publication = str(document["publication_status"])
    if synthesis != "complete":
        title = "RE WORKSPACE SYNTHESIS — INCOMPLETE"
    elif publication == "conflict":
        title = "RE WORKSPACE SYNTHESIS — COMPLETE, PUBLICATION CONFLICT"
    elif quality == "partial":
        title = "RE WORKSPACE SYNTHESIS — COMPLETE OVER ACCEPTED PARTIAL INPUTS"
    else:
        title = "RE WORKSPACE SYNTHESIS — COMPLETE"
    counts = document["artifact_counts"]
    assert isinstance(counts, dict)
    sources = document["sources"]
    assert isinstance(sources, dict)
    unresolved = [
        str(item["artifact_kind"])
        for item in document["artifacts"]  # type: ignore[union-attr]
        if item["status"] == "unresolved"
    ]
    lines = [
        "=" * len(title),
        title,
        "=" * len(title),
        f"run: {document['run_id']}",
        f"synthesis: {synthesis}",
        f"input quality: {quality}",
        f"publication: {publication}",
        f"sources: {len(sources['complete'])} complete, {len(sources['partial'])} partial",
        f"artifacts: {counts['generated']} generated, {counts['adopted']} adopted, {counts['unresolved']} unresolved",
    ]
    if sources["partial"]:
        lines.append("retained source debt: " + ", ".join(sources["partial"]))
    if unresolved:
        lines.append("unresolved: " + ", ".join(unresolved))
    if document["stop_reason"] is not None:
        lines.append(f"stopped because: {document['stop_reason']}")
    lines.append(f"next action: {document['next_action']}")
    return "\n".join(lines) + "\n"


def _next_action(
    run_id: str,
    partial_sources: tuple[str, ...],
    synthesis_complete: bool,
    publication_status: str,
    planner_action: str,
) -> str:
    if synthesis_complete and publication_status.startswith("published_"):
        return "none; synthesis and publication are complete"
    if not synthesis_complete:
        return f"echelon re continue {run_id}"
    if publication_status == "conflict":
        flags = " ".join(
            f"--accept-partial {source_id}" for source_id in partial_sources
        )
        return (
            f"echelon re synthesize --from-run {run_id}"
            + (f" {flags}" if flags else "")
        )
    if planner_action == "publish":
        return f"echelon re continue {run_id}"
    return f"echelon re continue {run_id}"


__all__ = (
    "Protocol27StatusError",
    "protocol_27_status_document",
    "render_protocol_27_status",
)

"""Manifest-first status and prominent terminal banners for protocol 2.8."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_28.context import (
    Protocol28RunContext,
    load_protocol_28_run_context,
)
from harness.re_v2.protocol_28.events import replay_protocol_28
from harness.re_v2.protocol_28.orchestration import (
    load_orchestration,
    recover_orchestration,
)


class Protocol28StatusError(RuntimeError):
    """Raised when protocol-2.8 operator state cannot be authenticated."""


def protocol_28_status_document(
    run_dir: Path,
    intent: object | None = None,
) -> dict[str, object]:
    try:
        context = load_protocol_28_run_context(Path(run_dir))
        manifest = context.inputs.manifest
        events = context.events.replay()
        state = replay_protocol_28(events)
        orchestration = _orchestration_document(context.run_dir, intent)
        blocker = (
            next(
                (
                    {
                        "kind": str(event.payload["blocker_kind"]),
                        "reason_code": str(event.payload["reason_code"]),
                    }
                    for event in reversed(events)
                    if event.type == "run_blocked"
                ),
                None,
            )
            if state.blocker_kind is not None
            else None
        )
        details = (
            _exhaustive_document(context, state, events)
            if isinstance(context, Protocol28RunContext)
            else _closure_document(context, state, events)
        )
        if (
            isinstance(context, Protocol28RunContext)
            and context.inputs.parent_authority_bundle.unresolved_deeper_finding_ids
            and isinstance(orchestration, Mapping)
            and orchestration.get("state") == "complete"
        ):
            details["l3_finding_closure"] = "complete via linked L4 successor"
            details["l4_closure_root"] = orchestration.get(
                "closure_root_id", "not recorded"
            )
        banner = _banner(context, state, orchestration)
        return {
            "run_id": manifest.run_id,
            "engine": manifest.engine,
            "engine_protocol_version": manifest.engine_protocol_version,
            "run_mode": manifest.run_mode,
            "status": state.lifecycle_state,
            "source_snapshot_id": manifest.source_snapshot_id,
            "partition_manifest_id": manifest.partition_manifest_id,
            "selection": {
                "scope": (
                    "all-scope"
                    if manifest.selection.all_sources
                    else "selected-scope"
                ),
                "all_sources": manifest.selection.all_sources,
                "source_ids": list(manifest.selection.source_ids),
                "domain_keys": list(manifest.selection.domain_keys),
            },
            "orchestration": orchestration,
            "blocker": blocker,
            "reason_code": _banner_reason_code(banner),
            **details,
            "post_l4": {"synthesis": "not run", "publication": "not run"},
            "next_action": _next_action(context, state, blocker, orchestration),
            "banner": banner,
        }
    except Protocol28StatusError:
        raise
    except Exception as exc:
        raise Protocol28StatusError(
            f"cannot replay protocol-2.8 status for {Path(run_dir).name}: {exc}"
        ) from exc


def render_protocol_28_status(
    run_dir: Path,
    intent: object | None = None,
    *,
    as_json: bool = False,
) -> str:
    document = protocol_28_status_document(run_dir, intent)
    if as_json:
        return json.dumps(document, indent=2, sort_keys=True) + "\n"
    selection = document["selection"]
    slices = document["slice_counts"]
    resources = document["resources"]
    lines = [
        "RE V2 — PROTOCOL 2.8",
        f"run: {document['run_id']}",
        "protocol: 2.8",
        f"mode: {document['run_mode']}",
        f"status: {document['status']}",
        f"completion scope: {selection['scope']}",
        f"selected sources: {document['selected_counts']['sources']}",
        f"selected domains: {document['selected_counts']['domains']}",
        f"planned slices: {slices['planned']}",
        (
            "slices: adopted={adopted} generated={generated} "
            "verified={verified} repaired={repaired} accepted={accepted} "
            "failed={failed} pending={pending}"
        ).format(**slices),
        (
            "resources: charged_tokens={charged_tokens} "
            "authorized_tokens={token_limit} "
            "trusted_tokens={trusted_observed_tokens} "
            "charged_active_ms={charged_active_ms} "
            "authorized_active_ms={active_ms_limit} "
            "trusted_active_ms={trusted_observed_active_ms}"
        ).format(**resources),
        (
            "dispatches: producer={producer} verifier={verifier} "
            "avoided={avoided_dispatches}"
        ).format(**document["dispatch_counts"]),
        f"historical rejected attempts: {document['historical_rejected_attempts']}",
        f"inherited L3 finding closure: {document['l3_finding_closure']}",
        f"L4 closure root: {document['l4_closure_root']}",
        "workspace synthesis: not run",
        "workspace publication: not run",
    ]
    orchestration = document.get("orchestration")
    if isinstance(orchestration, Mapping):
        lines.extend(
            (
                f"orchestration intent: {orchestration['request_id']}",
                f"orchestration state: {orchestration['state']}",
                (
                    "orchestration chain: input={input_run_id} L3={l3_run_id} "
                    "L4={l4_run_id} closure={closure_run_id}"
                ).format(**orchestration),
            )
        )
    for row in document["targets"]:
        lines.append(
            (
                "target {source_id}/{target_kind}/{target_id}: "
                "{accepted}/{planned} accepted"
            ).format(**row)
        )
    lines.extend(
        (
            f"next action: {document['next_action']}",
            "=" * 82,
            str(document["banner"]),
        )
    )
    return "\n".join(lines) + "\n"


def protocol_28_orchestration_status_document(
    intent: object,
) -> dict[str, object]:
    """Render an intent before an L4 child exists without inventing run state."""
    supplied_paths = getattr(intent, "paths", None)
    path = supplied_paths.root if supplied_paths is not None else Path(intent)
    loaded = load_orchestration(Path(path))
    projection = recover_orchestration(loaded.paths.root)
    banner, reason_code, next_action = _orchestration_terminal_state(
        projection,
        loaded.request,
    )
    return {
        "request_id": loaded.request.request_id,
        "state": projection.state,
        "input_run_id": loaded.request.input_run_id,
        "l3_run_id": projection.l3_run_id,
        "l4_run_id": projection.l4_run_id,
        "closure_run_id": projection.closure_run_id,
        "blocked_stage": projection.blocked_stage,
        "reason_code": reason_code,
        "next_action": next_action,
        "banner": banner,
    }


def render_protocol_28_orchestration_status(
    intent: object,
    *,
    as_json: bool = False,
) -> str:
    document = protocol_28_orchestration_status_document(intent)
    if as_json:
        return json.dumps(document, indent=2, sort_keys=True) + "\n"
    return (
        "RE V2 — L4 ORCHESTRATION\n"
        f"request: {document['request_id']}\n"
        f"state: {document['state']}\n"
        f"input run: {document['input_run_id']}\n"
        f"L3 run: {document['l3_run_id'] or 'pending'}\n"
        f"L4 run: {document['l4_run_id'] or 'pending'}\n"
        f"closure run: {document['closure_run_id'] or 'not required/pending'}\n"
        f"reason: {document['reason_code']}\n"
        f"next action: {document['next_action']}\n"
        + "=" * 82
        + "\n"
        + str(document["banner"])
        + "\n"
    )


def _exhaustive_document(context, state, events):  # type: ignore[no-untyped-def]
    ledger = context.ledger.replay()
    plan = context.inputs.exhaustive_plan
    entries = tuple(
        entry for target in plan.target_plans for entry in target.entries
    )
    accepted_entry_ids = {
        item.plan_entry_id for item in ledger.accepted_slices.values()
    }
    adopted_output_ids = {
        str(event.payload["output_artifact_key_id"])
        for event in events
        if event.type == "checkpoint_adopted"
    }
    repaired_output_ids = {
        str(event.payload["output_artifact_key_id"])
        for event in events
        if event.type == "repair_packet_recorded"
    }
    accepted_output_ids = set(ledger.accepted_slices)
    targets = []
    for target in plan.target_plans:
        planned_ids = {entry.identity for entry in target.entries}
        targets.append(
            {
                "source_id": target.source_id,
                "target_kind": target.target_kind,
                "target_id": target.target_id,
                "planned": len(planned_ids),
                "accepted": len(planned_ids & accepted_entry_ids),
            }
        )
    decision = context.resources.decision
    accepted = len(ledger.accepted_slices)
    planned = len(entries)
    failures = len(state.failed_output_ids)
    unresolved = context.inputs.parent_authority_bundle.unresolved_deeper_finding_ids
    return {
        "selected_counts": {
            "sources": len({target.source_id for target in plan.target_plans}),
            "domains": sum(
                target.target_kind == "domain" for target in plan.target_plans
            ),
        },
        "slice_counts": {
            "planned": planned,
            "adopted": len(accepted_output_ids & adopted_output_ids),
            "generated": len(accepted_output_ids - adopted_output_ids),
            "verified": len(ledger.verification_receipts),
            "repaired": len(repaired_output_ids),
            "accepted": accepted,
            "failed": failures,
            "pending": max(0, planned - accepted - failures),
        },
        "targets": targets,
        "dispatch_counts": {
            "producer": decision.generated_dispatches_by_role.get("producer", 0),
            "verifier": decision.generated_dispatches_by_role.get("verifier", 0),
            "avoided_dispatches": sum(
                decision.avoided_dispatches_by_role.values()
            ),
        },
        "resources": {
            "charged_tokens": decision.charged_tokens,
            "token_limit": decision.token_limit,
            "trusted_observed_tokens": decision.trusted_observed_tokens,
            "charged_active_ms": decision.charged_active_ms,
            "active_ms_limit": decision.active_ms_limit,
            "trusted_observed_active_ms": decision.trusted_observed_active_ms,
            "avoided_tokens": decision.avoided_tokens,
            "avoided_active_ms": decision.avoided_active_ms,
        },
        "historical_rejected_attempts": sum(
            event.type in {"candidate_rejected", "verification_rejected"}
            for event in events
        ),
        "l3_finding_closure": "required" if unresolved else "not required",
        "l4_closure_root": state.closure_root_id or "not recorded",
    }


def _closure_document(context, state, events):  # type: ignore[no-untyped-def]
    del events
    roots = context.inputs.target_roots
    count = len(context.inputs.accepted_slices)
    return {
        "selected_counts": {
            "sources": len({root.source_id for root in roots}),
            "domains": sum(root.target_kind == "domain" for root in roots),
        },
        "slice_counts": {
            "planned": count,
            "adopted": count,
            "generated": 0,
            "verified": len(context.inputs.verification_receipts),
            "repaired": 0,
            "accepted": count,
            "failed": 0,
            "pending": 0,
        },
        "targets": [
            {
                "source_id": root.source_id,
                "target_kind": root.target_kind,
                "target_id": root.target_id,
                "planned": len(root.plan_entry_ids),
                "accepted": len(root.accepted_slice_ids),
            }
            for root in roots
        ],
        "dispatch_counts": {
            "producer": 0,
            "verifier": 0,
            "avoided_dispatches": 0,
        },
        "resources": {
            "charged_tokens": 0,
            "token_limit": None,
            "trusted_observed_tokens": 0,
            "charged_active_ms": 0,
            "active_ms_limit": None,
            "trusted_observed_active_ms": 0,
            "avoided_tokens": 0,
            "avoided_active_ms": 0,
        },
        "historical_rejected_attempts": 0,
        "l3_finding_closure": "complete" if state.closure_root_id else "required",
        "l4_closure_root": state.closure_root_id or "not recorded",
    }


def _orchestration_document(run_dir: Path, supplied: object | None):
    if supplied is not None:
        supplied_paths = getattr(supplied, "paths", None)
        candidate = (
            supplied_paths.root
            if supplied_paths is not None
            else Path(supplied)
        )
        paths = (Path(candidate),)
    else:
        namespace = run_dir.parent / ".re-v2-orchestrations"
        paths = (
            tuple(
                path
                for path in sorted(namespace.iterdir())
                if path.is_dir() and not path.is_symlink()
            )
            if namespace.is_dir() and not namespace.is_symlink()
            else ()
        )
    matches = []
    for path in paths:
        intent = load_orchestration(path)
        projection = recover_orchestration(path)
        if run_dir.name not in {
            intent.request.input_run_id,
            projection.l3_run_id,
            projection.l4_run_id,
            projection.closure_run_id,
        }:
            continue
        manifest_hash = content_digest(
            canonical_json_bytes(
                load_protocol_28_run_context(run_dir).inputs.manifest.to_json_dict()
            )
        )
        expected_hash = (
            intent.request.input_manifest_hash
            if run_dir.name == intent.request.input_run_id
            else projection.l3_manifest_hash
            if run_dir.name == projection.l3_run_id
            else projection.l4_manifest_hash
            if run_dir.name == projection.l4_run_id
            else projection.closure_manifest_hash
        )
        if expected_hash != manifest_hash:
            raise Protocol28StatusError(
                "orchestration child manifest binding is invalid"
            )
        matches.append((intent, projection))
    if len(matches) > 1:
        raise Protocol28StatusError("multiple orchestration intents name this run")
    if not matches:
        if supplied is not None:
            raise Protocol28StatusError(
                "supplied orchestration intent does not name this run"
            )
        return None
    intent, projection = matches[0]
    closure_root_id = "not recorded"
    if projection.closure_run_id is not None:
        closure_dir = run_dir.parent / projection.closure_run_id
        closure_context = load_protocol_28_run_context(closure_dir)
        closure_manifest_hash = content_digest(
            canonical_json_bytes(closure_context.inputs.manifest.to_json_dict())
        )
        if closure_manifest_hash != projection.closure_manifest_hash:
            raise Protocol28StatusError(
                "orchestration closure manifest binding is invalid"
            )
        closure_state = replay_protocol_28(closure_context.events.replay())
        closure_root_id = closure_state.closure_root_id or "not recorded"
    return {
        "request_id": intent.request.request_id,
        "state": projection.state,
        "input_run_id": intent.request.input_run_id,
        "l3_run_id": projection.l3_run_id or "pending",
        "l4_run_id": projection.l4_run_id or "pending",
        "closure_run_id": projection.closure_run_id or "not required/pending",
        "blocked_stage": projection.blocked_stage,
        "blocked_reason_code": projection.blocked_reason_code,
        "closure_root_id": closure_root_id,
    }


def _banner(context, state, orchestration):  # type: ignore[no-untyped-def]
    if state.blocker_kind == "closure_integrity":
        return "L4 EVIDENCE COMPLETE — CLOSURE INTEGRITY BLOCKED"
    if state.run_root_id is None:
        return "L4 BLOCKED — REQUESTED EVIDENCE INCOMPLETE"
    if isinstance(context, Protocol28RunContext):
        requires_closure = bool(
            context.inputs.parent_authority_bundle.unresolved_deeper_finding_ids
        )
        closure_complete = (
            isinstance(orchestration, Mapping)
            and orchestration.get("state") == "complete"
        )
        if requires_closure and not closure_complete:
            return "L4 EVIDENCE COMPLETE — CLOSURE INTEGRITY BLOCKED"
        scope = context.inputs.exhaustive_plan.completion_scope
        completion_authorized = state.terminal or (
            requires_closure and closure_complete
        )
    else:
        if state.closure_root_id is None:
            return "L4 EVIDENCE COMPLETE — CLOSURE INTEGRITY BLOCKED"
        scope = context.inputs.l4_run_root.completion_scope
        completion_authorized = state.terminal
    if not completion_authorized:
        return "L4 BLOCKED — REQUESTED EVIDENCE INCOMPLETE"
    if scope == "all-scope":
        return "L4 ALL-SCOPE EVIDENCE COMPLETE — SYNTHESIS REQUIRED"
    return "L4 SELECTED SCOPE COMPLETE"


def _next_action(context, state, blocker, orchestration):  # type: ignore[no-untyped-def]
    del blocker
    if state.blocker_kind == "resource":
        return (
            "raise the required ceiling with "
            f"`echelon re continue {context.run_dir.name}`"
        )
    if state.blocker_kind == "closure_integrity":
        return "repair or reconstruct the deterministic closure authority"
    if state.failed_output_ids:
        return (
            "address the terminal slice failures and start a new L4 child; "
            "this immutable run cannot continue"
        )
    if state.run_root_id is None:
        return (
            "continue exact unresolved L4 work with "
            f"`echelon re continue {context.run_dir.name}`"
        )
    if (
        isinstance(context, Protocol28RunContext)
        and context.inputs.parent_authority_bundle.unresolved_deeper_finding_ids
        and not (
            isinstance(orchestration, Mapping)
            and orchestration.get("state") == "complete"
        )
    ):
        return "complete or reconstruct the linked protocol-2.8 closure successor"
    linked_closure_complete = (
        isinstance(orchestration, Mapping)
        and orchestration.get("state") == "complete"
    )
    if not state.terminal and not linked_closure_complete:
        return (
            "validate or rebuild run-local L4 materialization with "
            f"`echelon re continue {context.run_dir.name}`"
        )
    if (
        context.inputs.manifest.selection.all_sources
        or getattr(
            getattr(context.inputs, "l4_run_root", None),
            "completion_scope",
            None,
        )
        == "all-scope"
    ):
        return "run protocol-2.9 workspace synthesis when available"
    if isinstance(orchestration, Mapping):
        input_run_id = orchestration.get("input_run_id")
        if isinstance(input_run_id, str):
            return (
                "`echelon re deepen --to L4 --all --from-run "
                f"{input_run_id}`"
            )
    return (
        "deepen remaining intentionally unselected scope or run "
        "protocol-2.9 synthesis"
    )


def _deepen_command(request):  # type: ignore[no-untyped-def]
    command = [
        "echelon re deepen",
        "--to L4",
        f"--from-run {request.input_run_id}",
    ]
    if request.selection.all_sources:
        command.append("--all")
    else:
        command.extend(f"--source {value}" for value in request.selection.source_ids)
        command.extend(f"--domain {value}" for value in request.selection.domain_keys)
    return " ".join(command)


def _orchestration_terminal_state(
    projection,
    request,
):  # type: ignore[no-untyped-def]
    reason = projection.blocked_reason_code or "none"
    if projection.state == "awaiting_l3":
        if projection.blocked_reason_code == "l3_prerequisite_resource_blocked":
            return (
                "L4 PENDING — L3 PREREQUISITE RESOURCE BLOCKED",
                reason,
                "first run the copy-paste L3 continuation command above; "
                f"after L3 completes, then rerun `{_deepen_command(request)}`",
            )
        if projection.blocked_reason_code is not None:
            return (
                "L4 NOT STARTED — L3 PREREQUISITE INELIGIBLE",
                reason,
                "resolve the named L3 eligibility blocker before retrying L4",
            )
        return (
            "L4 PENDING — L3 PREREQUISITE RESOURCE BLOCKED",
            "l3_prerequisite_pending",
            "first run the copy-paste L3 continuation command above; "
            f"after L3 completes, then rerun `{_deepen_command(request)}`",
        )
    if projection.state == "awaiting_l4" and projection.l4_run_id is None:
        return (
            "L4 NOT STARTED — PRE-ACTIVATION BLOCKED",
            reason,
            "repair the pre-activation authority or raise the minimum reservation",
        )
    if projection.state == "awaiting_closure":
        return (
            "L4 EVIDENCE COMPLETE — CLOSURE INTEGRITY BLOCKED",
            reason if reason != "none" else "closure_successor_pending",
            "complete or reconstruct the linked protocol-2.8 closure successor",
        )
    if projection.state == "awaiting_l4":
        return (
            "L4 BLOCKED — REQUESTED EVIDENCE INCOMPLETE",
            reason,
            f"continue L4 run {projection.l4_run_id}",
        )
    return (
        "L4 ORCHESTRATION COMPLETE",
        reason,
        "inspect the final linked protocol-2.8 run status",
    )


def _banner_reason_code(banner: str) -> str:
    return {
        "L4 SELECTED SCOPE COMPLETE": "selected_scope_complete",
        "L4 ALL-SCOPE EVIDENCE COMPLETE — SYNTHESIS REQUIRED": (
            "all_scope_synthesis_required"
        ),
        "L4 EVIDENCE COMPLETE — CLOSURE INTEGRITY BLOCKED": (
            "closure_integrity_blocked"
        ),
        "L4 BLOCKED — REQUESTED EVIDENCE INCOMPLETE": (
            "requested_evidence_incomplete"
        ),
    }[banner]


__all__ = (
    "Protocol28StatusError",
    "protocol_28_orchestration_status_document",
    "protocol_28_status_document",
    "render_protocol_28_orchestration_status",
    "render_protocol_28_status",
)

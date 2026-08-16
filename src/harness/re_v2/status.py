"""Authoritative operator status rendering for pinned RE v2 runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Mapping

from .budget import BudgetDecision, evaluate_budget
from .events import EventRecord, EventStore
from .ledger import Ledger, LedgerView, ObjectStore
from .planner import PlanDecision, ReV2PlanError, build_initial_inventory_graph, plan_next
from .projection import rebuild_projection
from .publication import load_published_v2_index
from .run_store import ReV2Paths, ReV2RunStoreError, detect_re_engine, load_run_manifest


class ReV2StatusError(RuntimeError):
    """Raised when authoritative v2 facts cannot be rendered safely."""


def render_v2_status(run_dir: Path, *, as_json: bool = False) -> str:
    """Replay manifest, events, and ledger and render one semantic status view."""
    run_path = Path(run_dir)
    try:
        if detect_re_engine(run_path) != "v2":
            raise ReV2StatusError(f"RE run is not pinned to v2: {run_path.name}")
        manifest = load_run_manifest(run_path)
        paths = ReV2Paths.for_run(run_path)
        graph = build_initial_inventory_graph(
            manifest.source_snapshot_id,
            manifest.partition_manifest_id,
        )
        supported_verifiers = {
            template.verifier_id: template.verifier_version
            for template in graph.templates
        }
        objects = ObjectStore(paths.objects)
        ledger_store = Ledger(paths, objects, supported_verifiers)
        ledger = ledger_store.replay()
        events = EventStore(paths).replay()
        projection = rebuild_projection(paths, ledger)
        budget = evaluate_budget(
            manifest.initial_budget_policy,
            events,
            now=_canonical_utc_now(),
        )
        plan = _plan(graph, manifest.requested_goals, ledger, budget)
        status = _status_document(
            run_path,
            manifest=manifest,
            events=events,
            ledger=ledger,
            projection=projection,
            budget=budget,
            plan=plan,
            graph=graph,
        )
    except ReV2StatusError:
        raise
    except Exception as exc:
        raise ReV2StatusError(f"cannot replay RE v2 status for {run_path.name}: {exc}") from exc
    if as_json:
        return json.dumps(status, indent=2, sort_keys=True) + "\n"
    return _render_human(status)


def _plan(
    graph: object,
    requested_goals: tuple[str, ...],
    ledger: LedgerView,
    budget: BudgetDecision,
) -> PlanDecision | None:
    try:
        return plan_next(  # type: ignore[arg-type]
            graph,
            ledger,
            budget,
            requested_goals=requested_goals,
        )
    except ReV2PlanError:
        return None


def _status_document(
    run_dir: Path,
    *,
    manifest: object,
    events: tuple[EventRecord, ...],
    ledger: LedgerView,
    projection: Mapping[str, object],
    budget: BudgetDecision,
    plan: PlanDecision | None,
    graph: object,
) -> dict[str, object]:
    raw_state = str(projection["state"])
    status = (
        raw_state
        if raw_state in {"paused", "complete", "finalized_partial", "failed"}
        else "active"
    )
    reason_code, reason = _reason(events, status)
    next_action = _next_action(status, reason_code, reason)
    publication = load_published_v2_index(run_dir.resolve().parent.parent)
    explanations = tuple(plan.explanations.values()) if plan is not None else ()
    accepted = tuple(ledger.accepted_artifacts.values())
    certifications = tuple(ledger.certifications.values())
    templates = tuple(getattr(graph, "templates", ()))
    layers: dict[str, dict[str, object]] = {}
    artifact_policies = getattr(manifest, "artifact_policy_versions")
    for layer in sorted(artifact_policies):
        accepted_count = sum(
            receipt.artifact_key.layer == layer for receipt in accepted
        )
        required_count = sum(template.layer == layer for template in templates)
        layer_status = (
            "complete"
            if required_count > 0 and accepted_count >= required_count
            else "partial"
            if accepted_count
            else "pending"
        )
        layers[layer] = {
            "accepted_artifacts": accepted_count,
            "status": layer_status,
        }

    current_work_item_id = projection.get("current_work_item_id")
    next_work_item_id = (
        plan.ready[0].work_item_id if plan is not None and plan.ready else None
    )
    return {
        "artifact_counts": {
            "adopted": 0,
            "certified": sum(
                receipt.verdict == "accepted" for receipt in certifications
            ),
            "generated": len(accepted),
            "rejected": sum(
                receipt.verdict == "rejected" for receipt in certifications
            ),
            "reused": sum(item.action == "reuse" for item in explanations),
        },
        "audit": "not registered",
        "budgets": _budget_document(budget),
        "continuable": status == "paused",
        "current_work_item_id": current_work_item_id,
        "engine": getattr(manifest, "engine"),
        "engine_protocol_version": getattr(manifest, "engine_protocol_version"),
        "layers": layers,
        "next_action": next_action,
        "next_work_item_id": next_work_item_id,
        "partition_manifest_id": getattr(manifest, "partition_manifest_id"),
        "plan_counts": {
            "blocked_budget": sum(item.action == "blocked_budget" for item in explanations),
            "blocked_dependency": sum(
                item.action == "blocked_dependency" for item in explanations
            ),
            "generate": sum(item.action == "generate" for item in explanations),
            "reject": sum(
                item.action == "reject_incompatible" for item in explanations
            ),
            "reuse": sum(item.action == "reuse" for item in explanations),
        },
        "publication_generation_id": (
            publication.generation_id if publication is not None else None
        ),
        "reason": reason,
        "reason_code": reason_code,
        "requested_goals": list(getattr(manifest, "requested_goals")),
        "run_id": getattr(manifest, "run_id"),
        "source_snapshot_id": getattr(manifest, "source_snapshot_id"),
        "status": status,
        "synthesis": "not registered",
        "token_coverage": {
            "complete": budget.token_coverage_complete,
            "known_tokens": budget.known_tokens,
            "unknown_dispatches": budget.unknown_token_dispatches,
        },
    }


def _budget_document(budget: BudgetDecision) -> dict[str, object]:
    return {
        "active_ms": _resource_budget(budget.active_ms, budget.active_ms_limit),
        "generation_attempts": _attempt_budget(
            budget.generation_attempts, budget.generation_attempt_limit
        ),
        "provider_attempts": _attempt_budget(
            budget.provider_attempts, budget.provider_attempt_limit
        ),
        "result_contract_retries": _attempt_budget(
            budget.result_contract_retries, budget.result_contract_retry_limit
        ),
        "semantic_rounds": _attempt_budget(
            budget.semantic_rounds, budget.semantic_round_limit
        ),
        "tokens": _resource_budget(budget.known_tokens, budget.token_limit),
    }


def _resource_budget(used: int, authorized: int | None) -> dict[str, int | None]:
    return {
        "authorized": authorized,
        "remaining": None if authorized is None else max(0, authorized - used),
        "used": used,
    }


def _attempt_budget(
    used_by_work_item: Mapping[str, int], authorized: int
) -> dict[str, object]:
    highest = max(used_by_work_item.values(), default=0)
    return {
        "authorized": authorized,
        "remaining": max(0, authorized - highest),
        "used": sum(used_by_work_item.values()),
        "used_by_work_item": dict(sorted(used_by_work_item.items())),
    }


def _reason(
    events: tuple[EventRecord, ...], status: str
) -> tuple[str | None, str | None]:
    paused: EventRecord | None = None
    terminal: EventRecord | None = None
    for event in events:
        if event.type == "run_paused":
            paused = event
        elif event.type == "run_resumed":
            paused = None
        elif event.type in {"run_completed", "run_finalized_partial", "run_failed"}:
            terminal = event
    if status == "paused" and paused is not None:
        return str(paused.payload["reason_code"]), str(paused.payload["reason"])
    if terminal is not None:
        return terminal.type, str(terminal.payload["reason"])
    return None, None


def _next_action(
    status: str, reason_code: str | None, reason: str | None
) -> str | None:
    if status == "active":
        return "echelon re continue"
    if status != "paused":
        return None
    combined = f"{reason_code or ''} {reason or ''}".lower()
    if "token" in combined:
        return "echelon re continue --re-token-limit <new-total>"
    if "active_ms" in combined or "time" in combined:
        return "echelon re continue --re-time-limit-minutes <new-total>"
    return "resolve the recorded pause reason, then run echelon re continue"


def _render_human(status: Mapping[str, object]) -> str:
    banner_status = str(status["status"]).replace("_", " ").upper()
    budgets = status["budgets"]
    assert isinstance(budgets, Mapping)
    token = budgets["tokens"]
    active = budgets["active_ms"]
    assert isinstance(token, Mapping) and isinstance(active, Mapping)
    lines = [
        f"RE V2 — {banner_status}",
        f"run: {status['run_id']}",
        f"engine: {status['engine']}",
        f"protocol: {status['engine_protocol_version']}",
        f"source snapshot: {status['source_snapshot_id']}",
        f"partition manifest: {status['partition_manifest_id']}",
        "goals: " + (", ".join(status["requested_goals"]) or "none"),  # type: ignore[arg-type]
        "layers: " + _layers_text(status["layers"]),
        f"current work: {status['current_work_item_id'] or 'none'}",
        f"next work: {status['next_work_item_id'] or 'none'}",
        (
            "token coverage: "
            f"{status['token_coverage']['known_tokens']} known; "  # type: ignore[index]
            f"{status['token_coverage']['unknown_dispatches']} unknown; "  # type: ignore[index]
            f"complete={str(status['token_coverage']['complete']).lower()}"  # type: ignore[index]
        ),
        "budgets:",
        f"  token_limit: {_used_authorized(token)}",
        f"  active_ms_limit: {_used_authorized(active)}",
    ]
    for key in (
        "provider_attempts",
        "generation_attempts",
        "semantic_rounds",
        "result_contract_retries",
    ):
        value = budgets[key]
        assert isinstance(value, Mapping)
        lines.append(f"  {key}: {_used_authorized(value)}")
    artifact_counts = status["artifact_counts"]
    plan_counts = status["plan_counts"]
    assert isinstance(artifact_counts, Mapping) and isinstance(plan_counts, Mapping)
    lines.extend(
        [
            "plan: "
            f"reuse={plan_counts['reuse']} generate={plan_counts['generate']} "
            f"reject={plan_counts['reject']}",
            "artifacts: "
            f"reused={artifact_counts['reused']} adopted={artifact_counts['adopted']} "
            f"generated={artifact_counts['generated']} "
            f"certified={artifact_counts['certified']} rejected={artifact_counts['rejected']}",
            f"audit: {status['audit']}",
            f"synthesis: {status['synthesis']}",
            f"publication generation: {status['publication_generation_id'] or 'none'}",
            f"status: {status['status']}",
            f"reason code: {status['reason_code'] or 'none'}",
            f"reason: {status['reason'] or 'none'}",
        ]
    )
    if status["next_action"] is not None:
        lines.append(f"next action: {status['next_action']}")
    return "\n".join(lines) + "\n"


def _layers_text(value: object) -> str:
    if not isinstance(value, Mapping) or not value:
        return "none"
    return ", ".join(
        f"{layer}={details['status']} ({details['accepted_artifacts']} accepted)"
        for layer, details in value.items()
        if isinstance(details, Mapping)
    )


def _used_authorized(value: Mapping[str, object]) -> str:
    authorized = value["authorized"]
    return f"{value['used']} / {authorized if authorized is not None else 'unlimited'}"


def _canonical_utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


__all__ = ("ReV2StatusError", "render_v2_status")

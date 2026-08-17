"""Authoritative operator status rendering for pinned RE v2 runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Mapping

from .canonical import content_digest
from .budget import BudgetDecision, evaluate_budget
from .events import EventRecord, EventStore
from .ledger import Ledger, LedgerView, ObjectStore
from .planner import PlanDecision, WorkGraph, build_initial_inventory_graph, plan_next
from .projection import rebuild_projection
from . import publication as publication_store
from .publication import GenerationManifest
from .run_store import ReV2Paths, ReV2RunStoreError, detect_re_engine, load_run_manifest


class ReV2StatusError(RuntimeError):
    """Raised when authoritative v2 facts cannot be rendered safely."""


_SUPPORTED_PROVIDER_CONTRACT = {
    "provider": "deterministic-inventory",
    "provider_protocol_version": "re-v2-l0-v1",
    "result_contract_id": "deterministic-inventory-v1",
}
_SUPPORTED_ARTIFACT_POLICIES = {"L0": "egr-164-v1"}


def validate_supported_v2_manifest(manifest: object, graph: WorkGraph) -> None:
    """Refuse immutable pins this EGR-164 binary cannot execute exactly."""
    requested_goals = tuple(getattr(manifest, "requested_goals", ()))
    if requested_goals != graph.requested_goals:
        raise ReV2StatusError(
            "unsupported pinned requested goals "
            f"{requested_goals!r}; supported goals are {graph.requested_goals!r}"
        )
    artifact_policies = dict(getattr(manifest, "artifact_policy_versions", {}))
    if artifact_policies != _SUPPORTED_ARTIFACT_POLICIES:
        raise ReV2StatusError(
            "unsupported pinned artifact policies "
            f"{artifact_policies!r}; supported policies are "
            f"{_SUPPORTED_ARTIFACT_POLICIES!r}"
        )
    provider_contract = dict(getattr(manifest, "provider_contract", {}))
    if provider_contract != _SUPPORTED_PROVIDER_CONTRACT:
        raise ReV2StatusError(
            "unsupported pinned RE v2 provider contract "
            f"{provider_contract!r}; supported contract is "
            f"{_SUPPORTED_PROVIDER_CONTRACT!r}"
        )


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
        validate_supported_v2_manifest(manifest, graph)
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
    graph: WorkGraph,
    requested_goals: tuple[str, ...],
    ledger: LedgerView,
    budget: BudgetDecision,
) -> PlanDecision:
    return plan_next(
        graph,
        ledger,
        budget,
        requested_goals=requested_goals,
    )


def _status_document(
    run_dir: Path,
    *,
    manifest: object,
    events: tuple[EventRecord, ...],
    ledger: LedgerView,
    projection: Mapping[str, object],
    budget: BudgetDecision,
    plan: PlanDecision,
    graph: WorkGraph,
) -> dict[str, object]:
    raw_state = str(projection["state"])
    status = (
        raw_state
        if raw_state in {"paused", "complete", "finalized_partial", "failed"}
        else "active"
    )
    reason_code, reason = _reason(events, status)
    next_action = _next_action(status, reason_code, reason)
    explanations = tuple(plan.explanations.values())
    accepted = tuple(ledger.accepted_artifacts.values())
    publication_generation_id = _matching_publication_generation_id(
        run_dir.resolve().parent.parent,
        run_id=str(getattr(manifest, "run_id")),
        accepted_root_hashes=tuple(
            sorted({receipt.artifact_hash for receipt in accepted})
        ),
        events=events,
    )
    certifications = tuple(ledger.certifications.values())
    templates = graph.templates
    layers: dict[str, dict[str, object]] = {}
    artifact_policies = getattr(manifest, "artifact_policy_versions")
    for layer in sorted(artifact_policies):
        layer_templates = tuple(
            template for template in templates if template.layer == layer
        )
        accepted_count = sum(
            plan.explanations[template.template_id].action == "reuse"
            and plan.explanations[template.template_id].reason_code
            == "accepted_exact_artifact"
            for template in layer_templates
        )
        required_count = len(layer_templates)
        layer_status = (
            "complete"
            if required_count > 0 and accepted_count >= required_count
            else "partial"
            if accepted_count
            else "pending"
        )
        layers[layer] = {
            "accepted_artifacts": accepted_count,
            "required_artifacts": required_count,
            "status": layer_status,
        }

    current_work_item_id = projection.get("current_work_item_id")
    next_work_item_id = (
        plan.ready[0].work_item_id if plan.ready else None
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
        "publication_generation_id": publication_generation_id,
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


def _matching_publication_generation_id(
    workspace_root: Path,
    *,
    run_id: str,
    accepted_root_hashes: tuple[str, ...],
    events: tuple[EventRecord, ...],
) -> str | None:
    """Attribute the current exact-root generation only to its proven run."""
    with publication_store._pinned_layout(workspace_root, create=False) as layout:
        if layout.v2_fd is None:
            return None
        with publication_store._publication_lock(layout):
            index = publication_store._load_index(layout)
            if index is None or index.run_id != run_id:
                return None
            if layout.generations_fd is None:
                raise publication_store.ReV2PublicationError(
                    f"generation manifest is missing for {index.generation_id}"
                )
            flags = (
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0)
            )
            generation_fd = publication_store._open_at(
                layout.generations_fd, index.generation_id, flags
            )
            try:
                publication_store._require_entry_matches_fd(
                    layout.generations_fd,
                    index.generation_id,
                    generation_fd,
                    f"generation {index.generation_id}",
                )
                payload, _ = publication_store._read_regular_at(
                    generation_fd,
                    "manifest.json",
                    "generation manifest",
                    expected_mode=0o400,
                    require_single_link=True,
                )
                publication_store._require_entry_matches_fd(
                    layout.generations_fd,
                    index.generation_id,
                    generation_fd,
                    f"generation {index.generation_id}",
                )
            finally:
                os.close(generation_fd)

    generation = GenerationManifest.from_bytes(payload)
    if (
        generation.generation_id != index.generation_id
        or content_digest(payload) != index.generation_manifest_hash
    ):
        raise publication_store.ReV2PublicationError(
            f"generation collision at {index.generation_id}"
        )
    if generation.accepted_root_hashes != accepted_root_hashes:
        return None
    expected_policy = _applicable_synthesis_policy(events, accepted_root_hashes)
    if (
        expected_policy is not None
        and generation.synthesis_policy_hash != expected_policy
    ):
        return None
    return generation.generation_id


def _applicable_synthesis_policy(
    events: tuple[EventRecord, ...], accepted_root_hashes: tuple[str, ...]
) -> str | None:
    policy: str | None = None
    for event in events:
        if (
            event.type == "synthesis_accepted"
            and tuple(event.payload["input_root_hashes"]) == accepted_root_hashes
        ):
            policy = str(event.payload["synthesis_policy_hash"])
    return policy


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
    return {
        "aggregate_used": sum(used_by_work_item.values()),
        "authorized_per_work_item": authorized,
        "by_work_item": {
            work_item_id: {
                "authorized": authorized,
                "remaining": max(0, authorized - used),
                "used": used,
            }
            for work_item_id, used in sorted(used_by_work_item.items())
        },
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
        lines.append(f"  {key}: {_attempts_text(value)}")
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
        f"{layer}={details['status']} "
        f"({details['accepted_artifacts']}/{details['required_artifacts']} accepted)"
        for layer, details in value.items()
        if isinstance(details, Mapping)
    )


def _used_authorized(value: Mapping[str, object]) -> str:
    authorized = value["authorized"]
    return f"{value['used']} / {authorized if authorized is not None else 'unlimited'}"


def _attempts_text(value: Mapping[str, object]) -> str:
    by_work_item = value["by_work_item"]
    assert isinstance(by_work_item, Mapping)
    item_text = ", ".join(
        (
            f"{work_item_id}={details['used']}/{details['authorized']} "
            f"({details['remaining']} remaining)"
        )
        for work_item_id, details in by_work_item.items()
        if isinstance(details, Mapping)
    ) or "none"
    return (
        f"aggregate used={value['aggregate_used']}; authorized per work item="
        f"{value['authorized_per_work_item']}; work items={item_text}"
    )


def _canonical_utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


__all__ = (
    "ReV2StatusError",
    "render_v2_status",
    "validate_supported_v2_manifest",
)

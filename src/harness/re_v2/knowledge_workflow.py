"""Thin composed lifecycle for reviewed analysis and workspace publication.

The workflow owns no provider implementation and no durable scheduler state. It
derives progress from the existing protocol-2.8 and protocol-2.7 authorities, so
repeating the same request resumes the exact incomplete boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Literal

from harness.re_registry import load_published_index
from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.knowledge_refresh import (
    KnowledgeRefreshPlanV1,
    merge_refresh_synthesis_parent,
)
from harness.re_v2.protocol_27.authority import resolve_synthesis_parent
from harness.re_v2.protocol_27.lifecycle import (
    execute_protocol_27_parent,
    execute_protocol_27_request,
)
from harness.re_v2.protocol_27.model import SynthesisBudgetPolicyV1
from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
from harness.re_v2.protocol_28.context import load_protocol_28_run_context
from harness.re_v2.protocol_28.model import KnowledgeAccountTransferV1
from harness.re_v2.protocol_28.status import protocol_28_status_document
from harness.re_v2.reviewed_synthesis_parent import resolve_reviewed_synthesis_parent


KnowledgeWorkflowState = Literal[
    "analyzing",
    "synthesizing",
    "publishing",
    "complete",
    "complete-with-limitations",
    "needs-attention",
]


class KnowledgeWorkflowError(RuntimeError):
    """Raised when a composed knowledge request is malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class KnowledgeWorkflowResultV1:
    analysis_run_id: str
    state: KnowledgeWorkflowState
    synthesis_run_id: str | None
    publication_generation: int | None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeRefreshResultV1:
    plan_id: str
    analysis_run_id: str | None
    state: KnowledgeWorkflowState
    synthesis_run_id: str | None
    publication_generation: int | None
    reason_code: str | None
    receipt_path: str


def _remaining_synthesis_budget(
    context: object,
    *,
    token_limit: int | None,
    active_ms_limit: int | None,
) -> tuple[int | None, int | None]:
    """Return the unspent aggregate allowance after reviewed analysis."""
    resources = getattr(context, "resources", None)
    records = tuple(getattr(resources, "records", ()))
    if not records or not isinstance(records[0], KnowledgeAccountTransferV1):
        return token_limit, active_ms_limit
    decision = resources.decision
    remaining_tokens = (
        None
        if decision.token_limit is None
        else max(
            0,
            decision.token_limit
            - decision.charged_tokens
            - decision.open_token_reservations,
        )
    )
    remaining_active_ms = (
        None
        if decision.active_ms_limit is None
        else max(
            0,
            decision.active_ms_limit
            - decision.charged_active_ms
            - decision.open_active_ms_reservations,
        )
    )
    return remaining_tokens, remaining_active_ms


def run_knowledge_workflow(
    workspace_root: Path,
    analysis_run_id: str,
    provider_factory: Callable[[], object],
    *,
    token_limit: int | None,
    active_ms_limit: int | None,
    fault_hook: Callable[[str], None] | None = None,
) -> KnowledgeWorkflowResultV1:
    """Resume reviewed analysis, then synthesize and publish its exact result."""

    root = Path(workspace_root).resolve()
    run_dir = _run_directory(root, analysis_run_id)
    if not callable(provider_factory):
        raise KnowledgeWorkflowError("knowledge workflow requires a provider factory")
    for name, value in (("token_limit", token_limit), ("active_ms_limit", active_ms_limit)):
        if value is not None and (type(value) is not int or value <= 0):
            raise KnowledgeWorkflowError(f"{name} must be a positive integer")

    provider: object | None = None

    def shared_provider() -> object:
        nonlocal provider
        if provider is None:
            provider = provider_factory()
        return provider

    def analysis_backend() -> object:
        candidate = shared_provider()
        if callable(getattr(candidate, "execute", None)):
            return candidate
        from harness.re_v2.protocol_28.cli_provider import SquadCliProtocol28Backend

        return SquadCliProtocol28Backend(shared_provider)  # type: ignore[arg-type]

    analysis = run_protocol_28_exhaustive(run_dir, analysis_backend)  # type: ignore[arg-type]
    if analysis.state not in {"complete", "complete-with-limitations"}:
        return KnowledgeWorkflowResultV1(
            analysis_run_id,
            "needs-attention",
            None,
            None,
            analysis.reason_code,
        )
    _fault(fault_hook, "after_analysis")

    synthesis_tokens, synthesis_active_ms = _remaining_synthesis_budget(
        load_protocol_28_run_context(run_dir),
        token_limit=token_limit,
        active_ms_limit=active_ms_limit,
    )
    if synthesis_tokens == 0 or synthesis_active_ms == 0:
        return KnowledgeWorkflowResultV1(
            analysis_run_id,
            "needs-attention",
            None,
            None,
            "aggregate-budget-exhausted-before-synthesis",
        )

    parent = resolve_reviewed_synthesis_parent(root, analysis_run_id)
    partial_sources = tuple(
        item.source_id for item in parent.accepted_sources if item.outcome == "partial"
    )
    synthesis = execute_protocol_27_request(
        root,
        SimpleNamespace(
            from_run=analysis_run_id,
            accepted_partial_sources=partial_sources,
            token_limit=synthesis_tokens,
            active_ms_limit=synthesis_active_ms,
        ),
        shared_provider,  # type: ignore[arg-type]
        fault_hook=fault_hook,
    )
    if synthesis.terminal_kind != "complete":
        status = protocol_28_status_document(run_dir)
        post_l4 = status["post_l4"]
        return KnowledgeWorkflowResultV1(
            analysis_run_id,
            "needs-attention",
            post_l4.get("run_id"),
            None,
            synthesis.terminal_kind,
        )
    _fault(fault_hook, "after_publication")

    index = load_published_index(root)
    status = protocol_28_status_document(run_dir)
    post_l4 = status["post_l4"]
    if (
        index is None
        or post_l4.get("synthesis") != "complete"
        or post_l4.get("publication")
        != f"published_{index.publication_status}"
        or post_l4.get("run_id") != index.published_from_run
    ):
        raise KnowledgeWorkflowError(
            "completed synthesis is not the authenticated current publication"
        )
    return KnowledgeWorkflowResultV1(
        analysis_run_id,
        (
            "complete-with-limitations"
            if index.publication_status == "partial"
            else "complete"
        ),
        index.published_from_run,
        index.generation,
        None,
    )


def run_knowledge_refresh(
    workspace_root: Path,
    plan: KnowledgeRefreshPlanV1,
    analysis_run_id: str | None,
    provider_factory: Callable[[], object],
    *,
    token_limit: int | None,
    active_ms_limit: int | None,
    fault_hook: Callable[[str], None] | None = None,
) -> KnowledgeRefreshResultV1:
    """Resume one planned refresh and atomically publish its merged generation."""

    root = Path(workspace_root).resolve()
    if not isinstance(plan, KnowledgeRefreshPlanV1):
        raise KnowledgeWorkflowError("knowledge refresh requires an immutable plan")
    for name, value in (("token_limit", token_limit), ("active_ms_limit", active_ms_limit)):
        if value is not None and (type(value) is not int or value <= 0):
            raise KnowledgeWorkflowError(f"{name} must be a positive integer")

    current = load_published_index(root)
    if current is None or current.generation != plan.publication_generation:
        return _refresh_result(
            root,
            plan,
            analysis_run_id,
            "needs-attention",
            None,
            current.generation if current is not None else None,
            "publication-conflict-retry-refresh",
        )
    if plan.needs_attention:
        return _refresh_result(
            root,
            plan,
            analysis_run_id,
            "needs-attention",
            None,
            current.generation,
            plan.reason_code,
        )
    if plan.no_op:
        return _refresh_result(
            root,
            plan,
            None,
            "complete",
            current.published_from_run,
            current.generation,
            "already-current",
        )
    if not plan.reanalyze_source_ids:
        raise KnowledgeWorkflowError("executable refresh has no source analysis work")
    if analysis_run_id is None:
        raise KnowledgeWorkflowError("changed refresh requires an analysis run")
    run_dir = _run_directory(root, analysis_run_id)
    if not callable(provider_factory):
        raise KnowledgeWorkflowError("knowledge refresh requires a provider factory")

    provider: object | None = None

    def shared_provider() -> object:
        nonlocal provider
        if provider is None:
            provider = provider_factory()
        return provider

    def analysis_backend() -> object:
        candidate = shared_provider()
        if callable(getattr(candidate, "execute", None)):
            return candidate
        from harness.re_v2.protocol_28.cli_provider import SquadCliProtocol28Backend

        return SquadCliProtocol28Backend(shared_provider)  # type: ignore[arg-type]

    analysis = run_protocol_28_exhaustive(run_dir, analysis_backend)  # type: ignore[arg-type]
    if analysis.state not in {"complete", "complete-with-limitations"}:
        return _refresh_result(
            root,
            plan,
            analysis_run_id,
            "needs-attention",
            None,
            current.generation,
            analysis.reason_code,
        )
    _fault(fault_hook, "after_refresh_analysis")

    synthesis_tokens, synthesis_active_ms = _remaining_synthesis_budget(
        load_protocol_28_run_context(run_dir),
        token_limit=token_limit,
        active_ms_limit=active_ms_limit,
    )
    if synthesis_tokens == 0 or synthesis_active_ms == 0:
        return _refresh_result(
            root,
            plan,
            analysis_run_id,
            "needs-attention",
            None,
            current.generation,
            "aggregate-budget-exhausted-before-synthesis",
        )

    latest = load_published_index(root)
    if latest is None or latest.generation != plan.publication_generation:
        return _refresh_result(
            root,
            plan,
            analysis_run_id,
            "needs-attention",
            None,
            latest.generation if latest is not None else None,
            "publication-conflict-retry-refresh",
        )
    fresh_parent = resolve_reviewed_synthesis_parent(root, analysis_run_id)
    prior_parent = resolve_synthesis_parent(
        root,
        latest.published_from_run,
        tuple(
            source_id
            for source_id, source in sorted(latest.sources.items())
            if source.status == "partial"
        ),
    )
    merged = merge_refresh_synthesis_parent(
        plan=plan,
        fresh_parent=fresh_parent,
        published_parent=prior_parent,
        published=latest,
    )
    synthesis = execute_protocol_27_parent(
        root,
        merged,
        SynthesisBudgetPolicyV1(
            schema_version=1,
            token_limit=synthesis_tokens,
            active_ms_limit=synthesis_active_ms,
            provider_attempt_limit=2,
            generation_attempt_limit=2,
            result_contract_retry_limit=1,
            artifact_contract_retry_limit=1,
        ),
        shared_provider,  # type: ignore[arg-type]
        fault_hook=fault_hook,
    )
    published = load_published_index(root)
    if synthesis.terminal_kind != "complete":
        return _refresh_result(
            root,
            plan,
            analysis_run_id,
            "needs-attention",
            None,
            published.generation if published is not None else current.generation,
            synthesis.terminal_kind,
        )
    if (
        published is None
        or published.generation != current.generation + 1
        or published.published_from_run == current.published_from_run
    ):
        raise KnowledgeWorkflowError(
            "completed refresh is not the authenticated next publication generation"
        )
    _fault(fault_hook, "after_refresh_publication")
    return _refresh_result(
        root,
        plan,
        analysis_run_id,
        (
            "complete-with-limitations"
            if published.publication_status == "partial"
            else "complete"
        ),
        published.published_from_run,
        published.generation,
        None,
    )


def _refresh_result(
    root: Path,
    plan: KnowledgeRefreshPlanV1,
    analysis_run_id: str | None,
    state: KnowledgeWorkflowState,
    synthesis_run_id: str | None,
    generation: int | None,
    reason_code: str | None,
) -> KnowledgeRefreshResultV1:
    relative = Path("runs") / f"re-refresh-{plan.identity.removeprefix('sha256:')[:20]}" / "result.json"
    path = root / relative
    payload = canonical_json_bytes(
        {
            "schema_version": 1,
            "plan_id": plan.identity,
            "analysis_run_id": analysis_run_id,
            "state": state,
            "synthesis_run_id": synthesis_run_id,
            "publication_generation": generation,
            "reason_code": reason_code,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return KnowledgeRefreshResultV1(
        plan.identity,
        analysis_run_id,
        state,
        synthesis_run_id,
        generation,
        reason_code,
        relative.as_posix(),
    )


def _fault(hook: Callable[[str], None] | None, point: str) -> None:
    if hook is not None:
        hook(point)


def _run_directory(workspace_root: Path, run_id: str) -> Path:
    if (
        type(run_id) is not str
        or not run_id
        or run_id in {".", ".."}
        or any(
            character
            not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in run_id
        )
    ):
        raise KnowledgeWorkflowError(f"unsafe analysis run ID: {run_id!r}")
    runs = workspace_root / "runs"
    run_dir = runs / run_id
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise KnowledgeWorkflowError(f"analysis run does not exist: {run_id}")
    try:
        if run_dir.resolve().parent != runs.resolve():
            raise KnowledgeWorkflowError("analysis run escaped the workspace run root")
    except OSError as exc:
        raise KnowledgeWorkflowError(f"cannot resolve analysis run: {run_id}") from exc
    return run_dir


__all__ = (
    "KnowledgeRefreshResultV1",
    "KnowledgeWorkflowError",
    "KnowledgeWorkflowResultV1",
    "run_knowledge_refresh",
    "run_knowledge_workflow",
)

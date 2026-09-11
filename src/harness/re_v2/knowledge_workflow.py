"""Thin composed lifecycle for reviewed analysis and workspace publication.

The workflow owns no provider implementation and no durable scheduler state. It
derives progress from the existing protocol-2.8 and protocol-2.7 authorities, so
repeating the same request resumes the exact incomplete boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Literal

from harness.re_registry import load_published_index
from harness.re_v2.protocol_27.lifecycle import execute_protocol_27_request
from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
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

    parent = resolve_reviewed_synthesis_parent(root, analysis_run_id)
    partial_sources = tuple(
        item.source_id for item in parent.accepted_sources if item.outcome == "partial"
    )
    synthesis = execute_protocol_27_request(
        root,
        SimpleNamespace(
            from_run=analysis_run_id,
            accepted_partial_sources=partial_sources,
            token_limit=token_limit,
            active_ms_limit=active_ms_limit,
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
    "KnowledgeWorkflowError",
    "KnowledgeWorkflowResultV1",
    "run_knowledge_workflow",
)

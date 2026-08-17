"""Explicit partial finalization for stopped reverse-engineering runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.publication_transaction import write_json_atomic
from harness.re_budget import evaluate_re_budget
from harness.re_controller import ReExtractionController
from harness.re_lifecycle import ReLifecycleError, resolve_current_re_run
from harness.re_publication import validate_re_run


class ReFinalizationError(RuntimeError):
    """Raised when a run cannot safely transition to terminal partial state."""


@dataclass(frozen=True)
class ReFinalizationResult:
    run_id: str
    status: str
    debt_manifest: Path
    blocked_reason: str
    semantic_failure_count: int
    partial_sources: tuple[str, ...]
    workspace_synthesis_incomplete: bool


@dataclass(frozen=True)
class ReWorkspaceSynthesisResult:
    run_id: str
    completed: bool
    token_usage: int
    publication_pending: bool


def mark_re_run_published(run_dir: Path, *, status: str, generation: int) -> None:
    """Synchronize run-local lifecycle state after canonical publication succeeds."""
    if status not in {"complete", "partial"} or generation < 1:
        raise ReFinalizationError("invalid RE publication result")
    outer_path = run_dir / "state.json"
    inner_path = run_dir / "re" / "state.json"
    outer = _read_object(outer_path)
    inner = _read_object(inner_path)
    outer.update(
        {
            "status": "done",
            "golddigger_status": status,
            "publication_pending": False,
            "publication_complete": True,
            "generation": generation,
        }
    )
    inner.update(
        {
            "status": "done",
            "publication_status": status,
            "publication_generation": generation,
        }
    )
    write_json_atomic(inner_path, inner)
    write_json_atomic(outer_path, outer)


def finalize_partial_re_run(
    workspace_root: Path,
    *,
    run_id: str | None = None,
) -> ReFinalizationResult:
    """Validate and explicitly accept the remaining debt of a blocked RE run."""
    root = workspace_root.resolve()
    run_dir = _resolve_run(root, run_id)
    outer_path = run_dir / "state.json"
    inner_path = run_dir / "re" / "state.json"
    outer = _read_object(outer_path)
    inner = _read_object(inner_path)

    if (
        outer.get("status") == "done"
        and outer.get("golddigger_status") == "partial"
        and inner.get("status") == "done"
        and inner.get("publication_status") == "partial"
    ):
        return _result_from_manifest(run_dir, outer)
    if outer.get("run_kind") != "re" or outer.get("run_id") != run_dir.name:
        raise ReFinalizationError(f"invalid RE lifecycle state: {outer_path}")
    if outer.get("status") != "blocked":
        raise ReFinalizationError(
            f"RE run {run_dir.name} is {outer.get('status')!r}, not blocked"
        )
    if inner.get("status") not in {"blocked", "in_progress"}:
        raise ReFinalizationError(
            f"RE controller is {inner.get('status')!r}, not stopped"
        )
    decision = outer.get("blocked_decision")
    if isinstance(decision, dict) and decision.get("status") == "pending":
        raise ReFinalizationError(
            "RE run is waiting for a human decision; use echelon re resume"
        )
    blocked_reason = str(
        outer.get("blocked_reason") or inner.get("blocked_reason") or ""
    ).strip()
    if not blocked_reason:
        raise ReFinalizationError("blocked RE run has no recorded blocked reason")

    source_quality_debt = _source_quality_debt(inner)
    semantic_failure_sources, semantic_failure_count = _semantic_debt(run_dir)
    workspace_incomplete = inner.get("re_workspace_synthesis_complete") is not True
    finalized_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "status": "partial",
        "finalized_at": finalized_at,
        "finalized_from": {
            "outer_status": str(outer.get("status") or ""),
            "inner_status": str(inner.get("status") or ""),
            "blocked_reason": blocked_reason,
            "phase": str(inner.get("phase") or outer.get("phase") or ""),
        },
        "debt": {
            "controller_incomplete": True,
            "workspace_synthesis_incomplete": workspace_incomplete,
            "source_quality_debt": list(source_quality_debt),
            "semantic_failure_sources": {
                source_id: list(domains)
                for source_id, domains in semantic_failure_sources.items()
            },
        },
    }
    manifest_path = run_dir / "re" / "quality" / "partial-finalization.json"
    write_json_atomic(manifest_path, manifest)

    try:
        validate_re_run(
            root,
            run_dir,
            allow_partial=True,
            status_override="partial",
        )
    except Exception as exc:
        raise ReFinalizationError(
            "RE output is not structurally publishable even as partial: " + str(exc)
        ) from exc

    finalization_summary = {
        "status": "partial",
        "finalized_at": finalized_at,
        "blocked_reason": blocked_reason,
        "debt_manifest": str(manifest_path),
        "workspace_synthesis_incomplete": workspace_incomplete,
        "source_quality_debt": list(source_quality_debt),
        "semantic_failure_count": semantic_failure_count,
        "semantic_failure_sources": sorted(semantic_failure_sources),
    }
    inner.update(
        {
            "status": "done",
            "publication_status": "partial",
            "re_partial_finalization": finalization_summary,
        }
    )
    inner.pop("blocked_reason", None)
    inner.pop("blocked_detail", None)
    write_json_atomic(inner_path, inner)

    outer.update(
        {
            "status": "done",
            "golddigger_status": "partial",
            "finalized_partial": True,
            "extraction_complete": True,
            "publication_pending": True,
            "publication_complete": False,
            "re_partial_finalization": finalization_summary,
        }
    )
    outer.pop("blocked_reason", None)
    outer.pop("blocked_detail", None)
    write_json_atomic(outer_path, outer)
    return ReFinalizationResult(
        run_id=run_dir.name,
        status="partial",
        debt_manifest=manifest_path,
        blocked_reason=blocked_reason,
        semantic_failure_count=semantic_failure_count,
        partial_sources=tuple(
            sorted(set(source_quality_debt) | set(semantic_failure_sources))
        ),
        workspace_synthesis_incomplete=workspace_incomplete,
    )


def synthesize_partial_re_run(
    workspace_root: Path,
    *,
    provider: object,
    extension_root: Path,
    run_id: str | None = None,
    prosaic_subagents_dir: Path | None = None,
    hard_token_limit: int | None = None,
    hard_active_minutes: int | None = None,
) -> ReWorkspaceSynthesisResult:
    """Regenerate workspace synthesis from explicitly accepted partial sources only."""
    root = workspace_root.resolve()
    run_dir = _resolve_run(root, run_id)
    outer_path = run_dir / "state.json"
    inner_path = run_dir / "re" / "state.json"
    manifest_path = run_dir / "re" / "quality" / "partial-finalization.json"
    outer = _read_object(outer_path)
    inner = _read_object(inner_path)
    manifest = _read_object(manifest_path)

    if (
        outer.get("run_kind") != "re"
        or outer.get("run_id") != run_dir.name
        or outer.get("status") != "done"
        or outer.get("golddigger_status") != "partial"
        or outer.get("finalized_partial") is not True
        or inner.get("status") != "done"
        or inner.get("publication_status") != "partial"
    ):
        raise ReFinalizationError(
            f"RE run {run_dir.name} is not a terminal explicitly finalized partial run"
        )
    debt = manifest.get("debt")
    if not isinstance(debt, dict):
        raise ReFinalizationError(
            f"invalid partial finalization manifest: {manifest_path}"
        )
    if inner.get("re_workspace_synthesis_complete") is True:
        return ReWorkspaceSynthesisResult(
            run_id=run_dir.name,
            completed=True,
            token_usage=_nonnegative_int(inner.get("re_token_usage")),
            publication_pending=bool(outer.get("publication_pending")),
        )

    source_states = inner.get("re_source_states")
    if not isinstance(source_states, dict) or not source_states:
        raise ReFinalizationError("partial RE run has no finalized source results")
    unfinished = sorted(
        str(source_id)
        for source_id, source_state in source_states.items()
        if not isinstance(source_state, dict)
        or source_state.get("status") not in {"passed", "partial_quality_debt"}
    )
    if unfinished:
        raise ReFinalizationError(
            "workspace synthesis requires terminal source results; unfinished: "
            + ", ".join(unfinished)
        )

    _raise_synthesis_budget(
        outer,
        inner,
        hard_token_limit=hard_token_limit,
        hard_active_minutes=hard_active_minutes,
    )
    budget = evaluate_re_budget(inner, minimum_dispatch_tokens=100_000)
    if not budget.allowed:
        option = (
            "--re-token-limit"
            if budget.reason == "re_token_budget_exhausted"
            else "--re-time-limit-minutes"
        )
        raise ReFinalizationError(
            f"{budget.reason}; rerun with {option} above the current limit"
        )

    inner.update(
        {
            "status": "in_progress",
            "phase": "re-extract-2-specify",
            "re_workspace_synthesis_complete": False,
            "re_specification_targets": [{"kind": "workspace-synthesis"}],
            "re_workspace_synthesis_repair_attempts": 0,
            "last_dispatch": {
                "phase_id": "re-extract-2-specify",
                "agent": "specifier",
                "post_dispatch_complete": True,
                "dispatched_at": None,
            },
        }
    )
    for key in ("blocked_reason", "blocked_detail", "re_agent_result_detail"):
        inner.pop(key, None)
    outer.update({"status": "running", "extraction_complete": False})
    write_json_atomic(inner_path, inner)
    write_json_atomic(outer_path, outer)

    controller = ReExtractionController(
        provider=provider,
        project_root=root,
        run_dir=run_dir,
        extension_root=extension_root,
        prosaic_subagents_dir=prosaic_subagents_dir,
        stop_after_workspace_synthesis=True,
    )
    outcome = controller.run()
    inner = _read_object(inner_path)
    outer = _read_object(outer_path)
    if not outcome.completed or inner.get("re_workspace_synthesis_complete") is not True:
        inner.update({"status": "done", "publication_status": "partial"})
        outer.update(
            {
                "status": "done",
                "golddigger_status": "partial",
                "extraction_complete": True,
            }
        )
        write_json_atomic(inner_path, inner)
        write_json_atomic(outer_path, outer)
        reason = outcome.blocked_reason or "re_workspace_synthesis_incomplete"
        detail = str(outcome.blocked_detail or "").strip()
        raise ReFinalizationError(f"{reason}{': ' + detail if detail else ''}")

    synthesized_at = datetime.now(timezone.utc).isoformat()
    debt["workspace_synthesis_incomplete"] = False
    manifest["workspace_synthesized_at"] = synthesized_at
    summary = outer.get("re_partial_finalization")
    summary = dict(summary) if isinstance(summary, dict) else {}
    summary.update(
        {
            "workspace_synthesis_incomplete": False,
            "workspace_synthesized_at": synthesized_at,
        }
    )
    inner.update(
        {
            "status": "done",
            "publication_status": "partial",
            "re_partial_finalization": summary,
        }
    )
    inner.pop("blocked_reason", None)
    inner.pop("blocked_detail", None)
    outer.update(
        {
            "status": "done",
            "golddigger_status": "partial",
            "finalized_partial": True,
            "extraction_complete": True,
            "publication_pending": True,
            "publication_complete": False,
            "token_usage": _nonnegative_int(inner.get("re_token_usage")),
            "re_partial_finalization": summary,
        }
    )
    write_json_atomic(manifest_path, manifest)
    write_json_atomic(inner_path, inner)
    write_json_atomic(outer_path, outer)
    try:
        validate_re_run(
            root,
            run_dir,
            allow_partial=True,
            status_override="partial",
            allow_same_run_republish=True,
        )
    except Exception as exc:
        raise ReFinalizationError(
            "workspace synthesis completed but partial publication validation failed: "
            + str(exc)
        ) from exc
    return ReWorkspaceSynthesisResult(
        run_id=run_dir.name,
        completed=True,
        token_usage=_nonnegative_int(inner.get("re_token_usage")),
        publication_pending=True,
    )


def _raise_synthesis_budget(
    outer: dict[str, Any],
    inner: dict[str, Any],
    *,
    hard_token_limit: int | None,
    hard_active_minutes: int | None,
) -> None:
    profile = inner.get("re_execution_profile")
    if not isinstance(profile, dict):
        raise ReFinalizationError("partial RE run has no execution profile")
    updated = dict(profile)
    changes: dict[str, dict[str, int | None]] = {}
    for field, value, option in (
        ("hard_token_limit", hard_token_limit, "--re-token-limit"),
        ("hard_active_minutes", hard_active_minutes, "--re-time-limit-minutes"),
    ):
        if value is None:
            continue
        if isinstance(value, bool) or value < 1:
            raise ReFinalizationError(f"{option} requires a positive integer")
        previous = updated.get(field)
        if isinstance(previous, (int, float)) and not isinstance(previous, bool):
            if int(previous) >= value:
                raise ReFinalizationError(
                    f"{option} must be greater than the active run's current {field}"
                )
            prior_value: int | None = int(previous)
        else:
            prior_value = None
        updated[field] = value
        changes[field] = {"previous": prior_value, "updated": value}
    inner["re_execution_profile"] = updated
    outer["re_execution_profile"] = updated
    if changes:
        history = outer.get("re_execution_budget_overrides")
        history = list(history) if isinstance(history, list) else []
        history.append(changes)
        outer["re_execution_budget_overrides"] = history
        inner["re_execution_budget_overrides"] = list(history)


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _resolve_run(root: Path, run_id: str | None) -> Path:
    if run_id is None:
        try:
            current = resolve_current_re_run(root)
        except ReLifecycleError as exc:
            raise ReFinalizationError(str(exc)) from exc
        if current is None:
            raise ReFinalizationError("no active RE run")
        return current
    if not run_id.startswith("re-") or any(
        value in run_id for value in ("/", "\\", "..")
    ):
        raise ReFinalizationError(f"unsafe RE run id: {run_id!r}")
    run_dir = root / "runs" / run_id
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ReFinalizationError(f"RE run does not exist: {run_id}")
    resolved = run_dir.resolve()
    if not resolved.is_relative_to((root / "runs").resolve()):
        raise ReFinalizationError(f"RE run escapes workspace: {run_id}")
    return resolved


def _source_quality_debt(inner: dict[str, Any]) -> tuple[str, ...]:
    states = inner.get("re_source_states")
    if not isinstance(states, dict):
        return ()
    return tuple(
        sorted(
            source_id
            for source_id, state in states.items()
            if isinstance(source_id, str)
            and isinstance(state, dict)
            and state.get("status") == "partial_quality_debt"
        )
    )


def _semantic_debt(run_dir: Path) -> tuple[dict[str, tuple[str, ...]], int]:
    review_path = run_dir / "re" / "quality" / "semantic-quality-review.json"
    if not review_path.is_file():
        return {}, 0
    review = _read_object(review_path)
    failures = review.get("failures")
    if not isinstance(failures, list):
        return {}, 0
    by_source: dict[str, set[str]] = {}
    count = 0
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        source_id = failure.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            continue
        domain_id = failure.get("domain_id")
        by_source.setdefault(source_id, set()).add(
            domain_id if isinstance(domain_id, str) and domain_id else "(source)"
        )
        count += 1
    return (
        {
            source_id: tuple(sorted(domains))
            for source_id, domains in sorted(by_source.items())
        },
        count,
    )


def _result_from_manifest(run_dir: Path, outer: dict[str, Any]) -> ReFinalizationResult:
    manifest_path = run_dir / "re" / "quality" / "partial-finalization.json"
    manifest = _read_object(manifest_path)
    debt = manifest.get("debt")
    if not isinstance(debt, dict):
        raise ReFinalizationError(f"invalid partial finalization manifest: {manifest_path}")
    semantic = debt.get("semantic_failure_sources")
    semantic = semantic if isinstance(semantic, dict) else {}
    source_debt = debt.get("source_quality_debt")
    source_debt = source_debt if isinstance(source_debt, list) else []
    summary = outer.get("re_partial_finalization")
    summary = summary if isinstance(summary, dict) else {}
    return ReFinalizationResult(
        run_id=run_dir.name,
        status="partial",
        debt_manifest=manifest_path,
        blocked_reason=str(summary.get("blocked_reason") or ""),
        semantic_failure_count=int(summary.get("semantic_failure_count") or 0),
        partial_sources=tuple(sorted(set(source_debt) | set(semantic))),
        workspace_synthesis_incomplete=bool(
            debt.get("workspace_synthesis_incomplete")
        ),
    )


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReFinalizationError(f"cannot read RE state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReFinalizationError(f"RE state must be an object: {path}")
    return value

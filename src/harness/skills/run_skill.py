"""Run skill orchestration entry point.

Per T043: wires RunIntent parsing -> StrategyCoordinator -> terminal output.
Acquires lock, runs GC, launches coordinator, prints results.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import logging
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Mapping

from harness.config import load_config
from harness.coordinator import StrategyCoordinator
from harness.gc import run_gc
from harness.harness_run_history import append_run, summarize_history
from harness.delivery_results import DeliveryRunOutcome, LandingOutcome
from harness.paths import make_build_id, current_build_marker, runs_dir
from harness.run_intent import parse_intent
from harness.spec_frontmatter import find_spec_dir, read_targets

logger = logging.getLogger(__name__)

_CHECKPOINT_REASONS = {"build_incomplete", "publish_failed", "checkpoint_outer_cap"}
_RECOVERABLE_BASELINE_REASONS = {
    "outer_cap",
    "checkpoint_outer_cap",
    "task_progress_incomplete",
    "publish_failed",
}


class RunContextError(ValueError):
    """The delivery caller supplied an invalid orchestration context."""


@dataclass
class _DeliverySummaryScope:
    intent: Any
    harness_root: Path
    workspace_root: Path
    spec_dir: Path | None
    config: Any
    summary_command: str
    emitted: bool = False


_ACTIVE_DELIVERY_SUMMARY: ContextVar[_DeliverySummaryScope | None] = ContextVar(
    "echelon_delivery_summary_scope",
    default=None,
)


def print_run_context_error(spec_id: str, error: RunContextError) -> None:
    """Render an invalid explicit orchestration context at adapter boundaries."""
    from echelon.ui import banner

    banner(
        "HARNESS — INVALID ORCHESTRATION CONTEXT",
        [
            ("spec", spec_id),
            ("problem", str(error)),
            (
                "next step",
                "run delivery from the workspace that owns specs/, or repair "
                "the supplied orchestration root",
            ),
        ],
        file=sys.stderr,
    )


def _resolve_run_roots(
    base_dir: str | Path,
    orchestration_root: str | Path | None,
) -> tuple[Path, Path]:
    harness_root = Path(base_dir).resolve()
    workspace_root = (
        Path(orchestration_root).resolve()
        if orchestration_root is not None
        else harness_root
    )
    if orchestration_root is not None and not workspace_root.is_dir():
        raise RunContextError(
            f"orchestration root is not a directory: {workspace_root}"
        )
    return harness_root, workspace_root


def _fresh_delivery_baselines(harness_root: Path, intent: Any) -> dict[str, str]:
    """Return checkpoint commits a new delivery budget may safely retain.

    A normal fresh delivery intentionally restarts from the target default branch.
    The exception is a previous blocked run for the same spec whose last durable
    checkpoint represents unfinished delivery work.  This decision is made before
    the current-build marker is advanced, so the new build cannot accidentally
    erase the only recoverable candidate branch.
    """
    if getattr(intent, "reset", False) or getattr(intent, "resume", False):
        return {}
    marker = current_build_marker(harness_root, intent.spec_id)
    try:
        marked_build_id = marker.read_text(encoding="utf-8").strip()
    except OSError:
        marked_build_id = ""

    # A cancelled or failed fresh attempt can advance the marker without ever
    # writing a durable checkpoint.  Search the remaining build directories as
    # well, newest first, so that bookkeeping failure cannot strand an older
    # recoverable candidate.
    build_ids = [marked_build_id] if marked_build_id else []
    build_ids.extend(
        path.name
        for path in sorted(runs_dir(harness_root).glob("build-*"), reverse=True)
        if path.is_dir() and path.name != marked_build_id
    )

    baselines: dict[str, str] = {}
    for strategy_id in intent.strategies:
        for prior_build_id in build_ids:
            state_path = runs_dir(harness_root) / prior_build_id / "state" / f"{strategy_id}.json"
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                state.get("status") != "blocked"
                or state.get("termination_reason") not in _RECOVERABLE_BASELINE_REASONS
            ):
                continue
            checkpoints = state.get("checkpoint_commits")
            if not isinstance(checkpoints, list):
                continue
            for checkpoint in reversed(checkpoints):
                if not isinstance(checkpoint, dict):
                    continue
                commit = checkpoint.get("commit")
                if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit):
                    baselines[strategy_id] = commit
                    break
            if strategy_id in baselines:
                break
    return baselines


def _count_tasks(spec_id: str, base_dir: str) -> int:
    """Return count of canonical task rows in tasks.md, or 0 if absent."""
    try:
        from harness.task_validation import count_tasks_for_spec
        return count_tasks_for_spec(spec_id, Path(base_dir))
    except FileNotFoundError:
        return 0


def _fulfillment_gap_recommendation(spec_dir: Path | None) -> str:
    """Read the first deterministic remediation from a verified gaps artifact."""
    if spec_dir is None:
        return ""
    gaps_path = spec_dir / "fulfillment-gaps.md"
    try:
        text = gaps_path.read_text(encoding="utf-8")
    except OSError:
        return ""

    match = re.search(
        r"(?ms)^-\s+\*\*Remediation[^:]*:\*\*\s*(.+?)(?=^\s*$|^##\s|\Z)",
        text,
    )
    if match is None:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _has_fulfillment_gap_failure(result: Any) -> bool:
    verify_result = getattr(result, "final_verify", None)
    return any(
        getattr(failure, "id", "") == "fulfillment-gaps"
        for failure in (getattr(verify_result, "failures", None) or [])
    )


def _should_print_suggested_answers(reason: object, result: Any) -> bool:
    if _has_fulfillment_gap_failure(result):
        return True
    return str(reason or "") == "blocker_escalation"


def _is_provider_limited_summary_row(info: dict[str, Any], result: Any = None) -> bool:
    reason = (
        getattr(result, "termination_reason", None)
        if result is not None
        else info.get("termination_reason")
    )
    return (
        not info.get("converged", False)
        and str(reason or "") == "provider_session_limit"
        and str(info.get("build_status") or "") == "provider_session_limit"
    )


def _json_section(text: str, heading: str) -> dict[str, Any]:
    marker = f"## {heading}"
    start = text.find(marker)
    if start == -1:
        return {}
    fence_start = text.find("```json", start)
    if fence_start == -1:
        return {}
    fence_start += len("```json")
    fence_end = text.find("```", fence_start)
    if fence_end == -1:
        return {}
    try:
        payload = json.loads(text[fence_start:fence_end].strip())
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _suggested_answer_lines(escalation_file: object, spec_id: str) -> list[str]:
    path_text = str(escalation_file or "").strip()
    if not path_text:
        return []
    try:
        text = Path(path_text).read_text(encoding="utf-8")
    except OSError:
        return []
    metadata = _json_section(text, "Decision Metadata")
    suggestions = metadata.get("suggested_answers")
    if not isinstance(suggestions, list):
        return []

    lines = ["suggested answers:"]
    for raw in suggestions:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        answer = str(raw.get("answer") or "").strip()
        consequence = str(raw.get("consequence") or "").strip()
        if not label or not answer:
            continue
        marker = " (recommended)" if bool(raw.get("recommended")) else ""
        safe_answer = answer.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f"- {label}{marker}: echelon delivery resume {spec_id} \"{safe_answer}\"")
        if consequence:
            lines.append(f"  {consequence}")
    return lines if len(lines) > 1 else []


def _verified_ledger_line(info: dict[str, Any]) -> str:
    refresh = info.get("fulfillment_refresh")
    if not isinstance(refresh, dict):
        return ""
    ledger = refresh.get("verified_ledger")
    if not isinstance(ledger, dict):
        return ""
    return (
        "verified ledger: "
        f"reused {int(ledger.get('reused') or 0)}, "
        f"rechecked {int(ledger.get('rechecked') or 0)}, "
        f"invalidated {int(ledger.get('invalidated') or 0)}, "
        f"unresolved {int(ledger.get('unresolved') or 0)}"
    )


def _delivery_provider_limit_message(
    result_map: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> str:
    messages: list[str] = []
    for sid, info in comparison.get("strategies", {}).items():
        result = result_map.get(sid)
        if _is_provider_limited_summary_row(info, result):
            message = str(info.get("provider_limit_message") or "").strip()
            messages.append(message or f"Strategy {sid} reached its provider limit")
    if not messages:
        return ""
    if len(messages) == 1:
        return messages[0]
    return f"{len(messages)} strategies reached provider limits; first: {messages[0]}"


def _delivery_summary_facts(
    result_map: Mapping[str, Any],
    comparison: Mapping[str, Any],
):
    from harness.run_summary import (
        SummaryFact,
        SummaryFactCategory,
        SummaryFactImportance,
    )

    strategies = comparison.get("strategies", {})
    summary = comparison.get("summary", {})
    n_converged = int(summary.get("converged", 0) or 0)
    n_provider_limited = sum(
        1
        for sid, info in strategies.items()
        if _is_provider_limited_summary_row(info, result_map.get(sid))
    )
    n_checkpointed = sum(
        1
        for sid, info in strategies.items()
        if not info.get("converged", False)
        and not _is_provider_limited_summary_row(info, result_map.get(sid))
        and (
            getattr(result_map.get(sid), "termination_reason", None)
            or info.get("termination_reason")
        )
        in _CHECKPOINT_REASONS
    )
    n_failed = max(
        0,
        int(summary.get("failed", 0) or 0) - n_checkpointed - n_provider_limited,
    )
    outcome_parts = [f"{n_converged} converged", f"{n_failed} failed"]
    if n_checkpointed:
        outcome_parts.append(f"{n_checkpointed} checkpointed")
    if n_provider_limited:
        outcome_parts.append(f"{n_provider_limited} provider-limited")
    outcome = ", ".join(outcome_parts[:-1])
    if len(outcome_parts) > 1:
        outcome += f", and {outcome_parts[-1]}"
    else:
        outcome = outcome_parts[0]
    facts = [
        SummaryFact(
            SummaryFactCategory.OUTCOME,
            SummaryFactImportance.HIGH,
            f"Delivery finished with {outcome} strategies.",
            0,
        )
    ]
    for sid, info in strategies.items():
        result = result_map.get(sid)
        converged = bool(info.get("converged", False))
        reason = (
            getattr(result, "termination_reason", None)
            if result is not None
            else info.get("termination_reason")
        )
        provider_limited = _is_provider_limited_summary_row(info, result)
        if converged:
            facts.append(
                SummaryFact(
                    SummaryFactCategory.WORK,
                    SummaryFactImportance.HIGH,
                    f"Strategy {sid} converged successfully.",
                    len(facts),
                )
            )
        elif provider_limited or reason in _CHECKPOINT_REASONS:
            facts.append(
                SummaryFact(
                    SummaryFactCategory.HANDOFF,
                    SummaryFactImportance.HIGH,
                    f"Prepared strategy {sid} for durable continuation.",
                    len(facts),
                )
            )
        else:
            facts.append(
                SummaryFact(
                    SummaryFactCategory.BLOCKER,
                    SummaryFactImportance.CRITICAL,
                    f"Strategy {sid} stopped before convergence.",
                    len(facts),
                )
            )
        verification = getattr(result, "final_verify", None)
        if verification is not None:
            verdict = "passed" if verification.passed else "failed"
            facts.append(
                SummaryFact(
                    SummaryFactCategory.VERIFICATION,
                    SummaryFactImportance.HIGH,
                    f"Strategy {sid} verification {verdict}.",
                    len(facts),
                )
            )
    return tuple(facts)


def _print_delivery_summary(
    intent: Any,
    result_map: Dict[str, Any],
    comparison: Dict[str, Any],
    workspace_root: Path,
    spec_dir: Path | None,
    config: Any = None,
    landing: LandingOutcome | None = None,
    summary_command: str = "echelon delivery run",
) -> None:
    """Print a structured delivery summary to stderr."""
    from echelon.ui import banner as _banner

    scope = _ACTIVE_DELIVERY_SUMMARY.get()
    if scope is not None:
        if scope.emitted:
            return

    task_count = _count_tasks(intent.spec_id, str(workspace_root))
    task_note = f"  ({task_count} tasks)" if task_count else ""
    target_repo = getattr(config, "target_repo", None) if config is not None else None
    fulfillment_recommendation = _fulfillment_gap_recommendation(spec_dir)

    fields: list[tuple[str, str]] = [("spec", f"{intent.spec_id}{task_note}")]
    if target_repo:
        fields.append(("target", target_repo))
    fields.append(("strategies", f"{', '.join(intent.strategies)}  |  mode: {intent.mode}"))

    for sid, info in comparison.get("strategies", {}).items():
        result = result_map.get(sid)
        converged = info.get("converged", False)
        reason = getattr(result, "termination_reason", None) if result is not None else info.get("termination_reason")
        build_status = str(info.get("build_status") or "")
        provider_limited = _is_provider_limited_summary_row(info, result)
        checkpointed = (not converged) and reason in _CHECKPOINT_REASONS and not provider_limited
        if converged:
            status_icon = "✓"
            status_str = "CONVERGED"
        elif provider_limited:
            status_icon = "◐"
            status_str = "PROVIDER SESSION LIMIT"
        elif checkpointed:
            status_icon = "◐"
            status_str = "CHECKPOINTED"
        else:
            status_icon = "✗"
            status_str = info.get("status", "FAILED").upper()
        outer = info.get("outer_iterations", 0)
        inner = info.get("inner_iterations", 0)
        branch = info.get("branch") or f"harness/{intent.spec_id}/{sid}/iter-{max(outer - 1, 0)}"
        pr_url = info.get("pr_url")

        lines = [
            f"{status_icon} {status_str}",
            f"branch: {branch}",
            f"PR: {pr_url}" if pr_url else "PR: not created (gh/glab unavailable or pr_host unset)",
            f"iterations: {outer} outer, {inner} inner retries",
        ]
        if result is not None:
            if reason and reason != "converged":
                if provider_limited:
                    lines.append("stopped: provider session limit")
                    provider_message = str(info.get("provider_limit_message") or "")
                    provider_reset = str(info.get("provider_reset_hint") or "")
                    salvage_commit = str(info.get("salvage_commit") or "")
                    salvage_branch = str(info.get("salvage_branch") or "")
                    salvage_verified = str(info.get("salvage_verified") or "")
                    if provider_message:
                        lines.append(f"provider: {provider_message}")
                    if provider_reset:
                        lines.append(f"reset: {provider_reset}")
                    if salvage_commit:
                        lines.append(f"salvage commit: {salvage_commit[:12]}")
                    if salvage_branch:
                        lines.append(f"salvage branch: {salvage_branch}")
                    if salvage_verified:
                        lines.append(f"salvage verified: {salvage_verified}")
                    lines.append(f"continue: echelon delivery continue {intent.spec_id}")
                elif checkpointed:
                    if reason == "checkpoint_outer_cap":
                        lines.append("stopped: checkpoint continuation needed")
                    else:
                        lines.append("stopped: checkpoint recovery needed")
                    lines.append(f"continue: echelon delivery continue {intent.spec_id}")
                else:
                    lines.append(f"stopped: {reason}")
                    if reason == "outer_cap":
                        lines.append(
                            f"next: echelon delivery run {intent.spec_id}  "
                            "# continue with a fresh outer-loop budget"
                        )
            fv = getattr(result, "final_verify", None)
            if fv is not None:
                duration = f"  ({fv.duration_s:.1f}s)" if fv.duration_s else ""
                deferred = (
                    reason == "checkpoint_outer_cap"
                    and not fv.passed
                    and any(
                        getattr(failure, "id", "") == "fulfillment-refresh-deferred"
                        for failure in (fv.failures or [])
                    )
                )
                if deferred:
                    lines.append(f"verify: deferred{duration}")
                else:
                    v_icon = "✓" if fv.passed else "✗"
                    lines.append(f"verify: {v_icon} {'passed' if fv.passed else 'FAILED'}{duration}")
                for failure in (fv.failures or []):
                    if deferred:
                        lines.append(
                            f"        deferred [{failure.category.value}] {failure.error}"
                        )
                    else:
                        lines.append(
                            f"        ✗ [{failure.category.value}] {failure.error}"
                        )
            else:
                lines.append("verify: skipped (no sandbox / project type undetected)")
            if fulfillment_recommendation and _has_fulfillment_gap_failure(result):
                lines.append(f"recommended action: {fulfillment_recommendation}")
            verified_ledger = _verified_ledger_line(info)
            if verified_ledger:
                lines.append(verified_ledger)
            if _should_print_suggested_answers(reason, result):
                lines.extend(
                    _suggested_answer_lines(info.get("escalation_file"), intent.spec_id)
                )

        fields.append((sid, "\n".join(lines)))

    summary = comparison.get("summary", {})
    n_converged = summary.get("converged", 0)
    n_checkpointed = sum(
        1
        for sid, info in comparison.get("strategies", {}).items()
        if not info.get("converged", False)
        and info.get("build_status") != "provider_session_limit"
        and (
            getattr(result_map.get(sid), "termination_reason", None)
            or info.get("termination_reason")
        )
        in _CHECKPOINT_REASONS
    )
    n_provider_limited = sum(
        1
        for sid, info in comparison.get("strategies", {}).items()
        if _is_provider_limited_summary_row(info, result_map.get(sid))
    )
    raw_failed = summary.get("failed", 0)
    n_failed = max(0, raw_failed - n_checkpointed - n_provider_limited)
    total_tokens = summary.get("total_tokens", 0)
    result_str = f"{n_converged} converged, {n_failed} failed"
    if n_checkpointed:
        result_str += f", {n_checkpointed} checkpointed"
    if n_provider_limited:
        result_str += f", {n_provider_limited} provider-limited"
    if total_tokens:
        result_str += f"  ·  {total_tokens:,} tokens"
    fields.append(("delivery", result_str))
    provider_limit_message = _delivery_provider_limit_message(result_map, comparison)
    if provider_limit_message:
        fields.append(("provider limit", provider_limit_message))
    next_step = ""
    if n_checkpointed or n_provider_limited:
        next_step = f"echelon delivery continue {intent.spec_id}"
    elif n_failed:
        next_step = f"echelon delivery run {intent.spec_id}"
    elif n_converged and (landing is None or landing.status != "landed"):
        next_step = f"echelon delivery land {intent.spec_id}"
    if landing is not None:
        landing_text = landing.status
        if landing.reason:
            landing_text += f" ({landing.reason})"
        fields.append(("landing", landing_text))

    if not os.environ.get("ECHELON_SUPPRESS_RUN_SUMMARY"):
        from harness.run_summary import RunSummaryContext, summarize_run_for_cli

        worked_on = summarize_run_for_cli(
            RunSummaryContext(
                project_root=workspace_root,
                command=summary_command,
                task=str(
                    getattr(intent, "task_description", "")
                    or f"Deliver spec {intent.spec_id}"
                ),
                status=(
                    "done"
                    if n_converged
                    and not (n_failed or n_checkpointed or n_provider_limited)
                    else "blocked"
                ),
                facts=_delivery_summary_facts(result_map, comparison),
                next_step=next_step,
                provider_limit_message=provider_limit_message,
            )
        )
        fields.append(("worked on", worked_on))
        if next_step:
            fields.append(("next", next_step))

    _banner("DELIVERY SUMMARY", fields, file=sys.stderr)
    if scope is not None:
        scope.emitted = True


def _print_delivery_exception_summary(
    intent: Any,
    harness_root: Path,
    workspace_root: Path,
    spec_dir: Path | None,
    *,
    config: Any,
    summary_command: str,
) -> None:
    """Render the durable command handoff without masking its exception."""

    def durable_counter(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    result_map: dict[str, object] = {}
    strategies: dict[str, dict[str, object]] = {}
    durable_states: dict[str, dict[str, object]] = {}
    try:
        build_id = current_build_marker(
            harness_root,
            str(intent.spec_id),
        ).read_text(encoding="utf-8").strip()
        state_dir = runs_dir(harness_root) / build_id / "state"
        for state_path in sorted(state_dir.glob("*.json")):
            value = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                durable_states[state_path.stem] = value
    except (OSError, ValueError, json.JSONDecodeError):
        durable_states = {}
    strategy_ids = tuple(
        dict.fromkeys(
            (
                *tuple(str(value) for value in getattr(intent, "strategies", ()) or ()),
                *tuple(durable_states),
            )
            or ("default",)
        )
    )
    for strategy in strategy_ids:
        state = durable_states.get(strategy, {})
        reason = str(
            state.get("termination_reason")
            or state.get("blocked_reason")
            or "coordinator_exception"
        )
        result = SimpleNamespace(
            status=str(state.get("status") or "blocked"),
            termination_reason=reason,
            outer_iterations=durable_counter(state.get("outer_iteration")),
            inner_iterations=durable_counter(state.get("inner_iteration")),
            pr_url=state.get("pr_url"),
            final_verify=None,
        )
        result_map[strategy] = result
        strategies[strategy] = {
            "status": str(state.get("status") or "blocked"),
            "termination_reason": reason,
            "build_status": str(state.get("build_status") or "failed"),
            "outer_iterations": result.outer_iterations,
            "inner_iterations": result.inner_iterations,
            "converged": False,
            "branch": state.get("branch"),
            "pr_url": state.get("pr_url"),
            "provider_limit_message": state.get("provider_limit_message"),
            "provider_reset_hint": state.get("provider_reset_hint"),
            "completed_task_ids": state.get("completed_task_ids") or [],
        }
    _print_delivery_summary(
        intent,
        result_map,
        {
            "strategies": strategies,
            "summary": {
                "converged": 0,
                "failed": len(strategies),
                "total_tokens": 0,
            },
        },
        workspace_root,
        spec_dir,
        config,
        LandingOutcome("not_requested"),
        summary_command,
    )


@contextmanager
def _delivery_summary_session(scope: _DeliverySummaryScope):
    active = _ACTIVE_DELIVERY_SUMMARY.get()
    if active is not None:
        yield active
        return
    token = _ACTIVE_DELIVERY_SUMMARY.set(scope)
    try:
        yield scope
    finally:
        try:
            if not scope.emitted:
                _print_delivery_exception_summary(
                    scope.intent,
                    scope.harness_root,
                    scope.workspace_root,
                    scope.spec_dir,
                    config=scope.config,
                    summary_command=scope.summary_command,
                )
        except BaseException:
            pass
        finally:
            _ACTIVE_DELIVERY_SUMMARY.reset(token)


def _print_harness_history_summary(
    *,
    spec_dir: Path | None,
    title: str,
) -> None:
    if spec_dir is None:
        return
    summary = summarize_history(spec_dir)
    recent = summary.get("recent", [])
    if not recent:
        return

    fields: list[tuple[str, str]] = []
    for row in recent:
        if not isinstance(row, dict):
            continue
        build_id = str(row.get("build_id") or "?")
        short_build = build_id.replace("build-", "")
        strategy = str(row.get("strategy_id") or "?")
        status = str(row.get("status") or "?")
        reason = str(row.get("termination_reason") or "?")
        tokens = int(row.get("tokens_used") or 0)
        fields.append(
            (
                f"{short_build}/{strategy}",
                f"{status}  |  {reason}  |  {tokens:,} tokens",
            )
        )
    if not fields:
        return

    subtitle = f"{summary['count']} runs tracked · {summary['total_tokens']:,} tokens total"
    from echelon.ui import banner as _banner
    _banner(title, fields, subtitle=subtitle, file=sys.stderr)


def _append_harness_history(
    *,
    spec_dir: Path | None,
    spec_id: str,
    build_id: str,
    mode: str,
    result_map: Dict[str, Any],
    comparison: Dict[str, Any],
    coordinator: StrategyCoordinator,
) -> None:
    if spec_dir is None:
        return
    for sid, result in result_map.items():
        info = comparison.get("strategies", {}).get(sid, {})
        state = coordinator.status().get("strategies", {}).get(sid, {})
        append_run(
            spec_dir,
            spec_id=spec_id,
            build_id=build_id,
            mode=mode,
            strategy_id=sid,
            result=result,
            pr_url=info.get("pr_url") or getattr(result, "pr_url", None),
            started_at=state.get("started_at"),
        )


def _execute_delivery_run(
    *,
    intent: Any,
    provider: Any,
    gitops: Any,
    harness_root: Path,
    workspace_root: Path,
    spec_dir: Path | None,
    config: Any,
    resume_build_id: str | None,
    summary_command: str,
) -> DeliveryRunOutcome:
    """Execute one already-identified delivery command inside its summary scope."""

    fresh_branch_bases = (
        {} if resume_build_id is not None else _fresh_delivery_baselines(harness_root, intent)
    )
    build_id = resume_build_id or make_build_id()
    rd = runs_dir(harness_root)
    rd.mkdir(parents=True, exist_ok=True)
    current_build_marker(harness_root, intent.spec_id).write_text(build_id)
    logger.info("Build ID: %s", build_id)

    coordinator = StrategyCoordinator(
        provider=provider,
        gitops=gitops,
        config=config,
        base_dir=harness_root,
        build_id=build_id,
        orchestration_root=workspace_root,
        fresh_branch_bases=fresh_branch_bases,
    )
    if fresh_branch_bases:
        logger.info(
            "Starting new delivery budget from checkpointed candidate(s): %s",
            ", ".join(f"{strategy}={commit[:12]}" for strategy, commit in fresh_branch_bases.items()),
        )
    try:
        run_gc(config, base_dir=str(harness_root))
    except Exception as exc:
        logger.warning("GC failed (continuing): %s", exc)

    _print_harness_history_summary(spec_dir=spec_dir, title="HARNESS HISTORY")
    results = coordinator.start(intent)
    result_map = dict(zip(intent.strategies, results))
    comparison = coordinator.compare_results(result_map)
    _append_harness_history(
        spec_dir=spec_dir,
        spec_id=intent.spec_id,
        build_id=build_id,
        mode=intent.mode,
        result_map=result_map,
        comparison=comparison,
        coordinator=coordinator,
    )
    _print_harness_history_summary(spec_dir=spec_dir, title="HARNESS HISTORY")

    landing = LandingOutcome("not_requested")
    converged = comparison.get("summary", {}).get("converged", 0) > 0
    if intent.auto_merge and converged:
        targets = read_targets(spec_dir) if spec_dir is not None else []
        if len(targets) > 1:
            logger.warning(
                "auto-land skipped for spec %s: aggregate multi-target landing is "
                "unsupported (%d targets)",
                intent.spec_id,
                len(targets),
            )
            landing = LandingOutcome("skipped", "multi_target")
        else:
            from harness.land import land

            try:
                landed = land(
                    intent.spec_id,
                    project_dir=workspace_root,
                    gitops=gitops,
                    harness_root=harness_root,
                )
                if landed:
                    print("  Auto-landed successfully!", file=sys.stderr)
                    landing = LandingOutcome("landed")
                else:
                    logger.warning(
                        "auto-land: land() returned False for spec %s",
                        intent.spec_id,
                    )
                    landing = LandingOutcome("blocked", "land_returned_false")
            except Exception as exc:
                logger.warning(
                    "auto-land: land() raised for spec %s: %s",
                    intent.spec_id,
                    exc,
                )
                landing = LandingOutcome("blocked", "land_exception")

    _print_delivery_summary(
        intent,
        result_map,
        comparison,
        workspace_root,
        spec_dir,
        config,
        landing,
        summary_command,
    )
    return DeliveryRunOutcome(results=tuple(results), landing=landing)


def run(
    user_message: str,
    provider: Any,
    gitops: Any,
    base_dir: str = ".",
    config: Any = None,
    resume_build_id: str | None = None,
    orchestration_root: str | Path | None = None,
    summary_command: str = "echelon delivery run",
) -> DeliveryRunOutcome:
    """Execute an Echelon delivery run.

    Args:
        user_message: Natural-language run request.
        provider: SandboxProvider instance.
        gitops: GitOpsManager instance.
        base_dir: Base directory for harness state.
        resume_build_id: Existing build id to continue, when resuming.
        orchestration_root: Workspace that owns canonical specs and history.
    """
    harness_root, workspace_root = _resolve_run_roots(base_dir, orchestration_root)

    # 1. Parse intent
    intent = parse_intent(user_message)
    logger.info("Parsed run intent: spec=%s, mode=%s, strategies=%s",
                intent.spec_id, intent.mode, intent.strategies)

    spec_dir = find_spec_dir(intent.spec_id, workspace_root)
    if orchestration_root is not None and spec_dir is None:
        raise RunContextError(
            f"spec directory for {intent.spec_id} was not found from "
            f"orchestration root {workspace_root}"
        )

    scope = _DeliverySummaryScope(
        intent=intent,
        harness_root=harness_root,
        workspace_root=workspace_root,
        spec_dir=spec_dir,
        config=config,
        summary_command=summary_command,
    )
    with _delivery_summary_session(scope):
        # Load config only after the valid run identity is inside emit-once scope.
        config = config or load_config()
        scope.config = config
        return _execute_delivery_run(
            intent=intent,
            provider=provider,
            gitops=gitops,
            harness_root=harness_root,
            workspace_root=workspace_root,
            spec_dir=spec_dir,
            config=config,
            resume_build_id=resume_build_id,
            summary_command=summary_command,
        )

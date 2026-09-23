"""Run skill orchestration entry point.

Wires RunIntent parsing to the single DeliveryController and terminal output.
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
from typing import Any, Mapping

from harness.config import load_config
from harness.delivery_controller import DeliveryController
from harness.gc import run_gc
from harness.harness_run_history import append_run, summarize_history
from harness.delivery_results import DeliveryResult, DeliveryRunOutcome, LandingOutcome
from harness.paths import make_build_id, current_build_marker, runs_dir
from harness.run_intent import parse_intent
from harness.spec_frontmatter import find_spec_dir, read_targets
from harness.state import state_lock_owner_is_alive

logger = logging.getLogger(__name__)

_CHECKPOINT_REASONS = {"build_incomplete", "publish_failed", "checkpoint_outer_cap"}
_RECOVERABLE_BASELINE_REASONS = {
    "build_blocked",
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


def _fresh_delivery_baseline(
    harness_root: Path,
    intent: Any,
    gitops: Any | None = None,
) -> str | None:
    """Return checkpoint commits a new delivery budget may safely retain.

    A normal fresh delivery intentionally restarts from the target default branch.
    The exception is a prior stopped run for the same spec whose last durable
    checkpoint represents unfinished delivery work.  A state left ``running`` by
    an ungraceful process exit is recoverable only after its lock owner is dead;
    a live owner prevents a competing delivery.  This decision is made before the
    current-build marker is advanced, so the new build cannot accidentally erase
    the only recoverable candidate branch.
    """
    if getattr(intent, "reset", False) or getattr(intent, "resume", False):
        return None
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

    for prior_build_id in build_ids:
        state_path = runs_dir(harness_root) / prior_build_id / "state" / "default.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(state, dict) or state.get("spec_id") != intent.spec_id:
            continue
        status = str(state.get("status") or "")
        if status == "running" and state_lock_owner_is_alive(state_path):
            raise RunContextError(
                f"delivery is already active for {intent.spec_id} in {prior_build_id}"
            )
        recoverable = (
            status in {"interrupted", "running"}
            or (
                status == "blocked"
                and state.get("termination_reason")
                in _RECOVERABLE_BASELINE_REASONS
            )
        )
        if not recoverable:
            continue
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(checkpoints, list):
            continue
        for checkpoint in reversed(checkpoints):
            if not isinstance(checkpoint, dict):
                continue
            commit = checkpoint.get("commit")
            if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit):
                if _checkpoint_is_landed(gitops, commit):
                    logger.info(
                        "Latest checkpoint %s is already contained in the target "
                        "default branch; starting fresh",
                        commit[:12],
                    )
                    # A newer durable checkpoint supersedes every older run.
                    # Once it has landed, an old abandoned candidate must not
                    # be revived merely because its state still says running.
                    return None
                return commit
    return None


def _fresh_delivery_completed_tasks(
    harness_root: Path,
    intent: Any,
    baseline: str | None,
    gitops: Any | None = None,
    *,
    spec_dir: Path | None = None,
) -> tuple[str, ...]:
    """Recover Python-checkpointed task progress on the retained lineage.

    Provider task results are intentionally insufficient: a process can exit
    after writing its status marker but before Ralph commits the corresponding
    checkpoint.  Only task IDs recorded on checkpoint commits that are
    ancestors of the selected baseline are inherited by a fresh budget.
    """
    if baseline is None or gitops is None:
        return ()
    from harness.task_progress import checkpoint_input_hash

    current_input_hash = checkpoint_input_hash(spec_dir)
    if current_input_hash is None:
        return ()
    ancestry = getattr(gitops, "commit_is_ancestor", None)
    if not callable(ancestry):
        return ()

    recovered: set[str] = set()
    for state_path in sorted(runs_dir(harness_root).glob("build-*/state/default.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(state.get("spec_id") or "") != str(intent.spec_id):
            continue
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(checkpoints, list):
            continue
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, dict):
                continue
            if checkpoint.get("checkpoint_input_hash") != current_input_hash:
                continue
            commit = checkpoint.get("commit")
            task_ids = checkpoint.get("task_ids")
            if (
                not isinstance(commit, str)
                or not re.fullmatch(r"[0-9a-f]{40}", commit)
                or not isinstance(task_ids, list)
            ):
                continue
            try:
                retained = ancestry(commit, baseline) is True
            except Exception:
                retained = False
            if not retained:
                continue
            recovered.update(
                task_id.strip()
                for task_id in task_ids
                if isinstance(task_id, str)
                and re.fullmatch(r"T-\d+", task_id.strip())
            )
    return tuple(sorted(recovered))


def _checkpoint_is_landed(gitops: Any | None, commit: str) -> bool:
    """Return whether a prior delivery checkpoint is already on target main."""
    if gitops is None:
        return False
    checker = getattr(gitops, "commit_is_ancestor_of_default", None)
    if not callable(checker):
        return False
    try:
        return checker(commit) is True
    except Exception as error:  # pragma: no cover - defensive: stale recovery must remain available
        logger.warning("Could not inspect stale checkpoint %s: %s", commit[:12], error)
        return False


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


def _delivery_summary_facts(
    result: DeliveryResult,
    state: Mapping[str, object],
) -> dict[str, object]:
    return {
        "status": result.status,
        "termination_reason": result.termination_reason,
        "outer_iterations": result.outer_iterations,
        "inner_iterations": result.inner_iterations,
        "tokens_used": result.tokens_used,
        "build_status": state.get("build_status"),
        "provider_limit_message": state.get("provider_limit_message"),
        "completed_task_ids": state.get("completed_task_ids") or [],
    }


def _delivery_run_summary_facts(
    result: DeliveryResult,
    state: Mapping[str, object],
):
    from harness.run_summary import (
        SummaryFact,
        SummaryFactCategory,
        SummaryFactImportance,
    )

    converged = result.status == "converged"
    provider_limited = _is_provider_limited_summary_row(dict(state), result)
    checkpointed = not converged and not provider_limited and (
        result.termination_reason in _CHECKPOINT_REASONS
    )
    outcome = (
        "converged"
        if converged
        else "provider-limited"
        if provider_limited
        else "checkpointed"
        if checkpointed
        else "failed"
    )
    facts = [
        SummaryFact(
            SummaryFactCategory.OUTCOME,
            SummaryFactImportance.HIGH,
            f"Delivery finished {outcome}.",
            0,
        )
    ]
    if converged:
        category = SummaryFactCategory.WORK
        importance = SummaryFactImportance.HIGH
        text = "Delivery converged successfully."
    elif provider_limited or checkpointed:
        category = SummaryFactCategory.HANDOFF
        importance = SummaryFactImportance.HIGH
        text = "Prepared delivery for durable continuation."
    else:
        category = SummaryFactCategory.BLOCKER
        importance = SummaryFactImportance.CRITICAL
        text = "Delivery stopped before convergence."
    facts.append(SummaryFact(category, importance, text, len(facts)))
    verification = result.final_verify
    if verification is not None:
        verdict = "passed" if verification.passed else "failed"
        facts.append(
            SummaryFact(
                SummaryFactCategory.VERIFICATION,
                SummaryFactImportance.HIGH,
                f"Delivery verification {verdict}.",
                len(facts),
            )
        )
    return tuple(facts)


def _print_delivery_summary(
    intent: Any,
    result: DeliveryResult,
    state: Mapping[str, object],
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
    fields.append(("mode", str(intent.mode)))

    info = dict(state)
    converged = result.status == "converged"
    reason = result.termination_reason
    provider_limited = _is_provider_limited_summary_row(info, result)
    checkpointed = not converged and reason in _CHECKPOINT_REASONS and not provider_limited
    if converged:
        status_icon, status_str = "✓", "CONVERGED"
    elif provider_limited:
        status_icon, status_str = "◐", "PROVIDER SESSION LIMIT"
    elif checkpointed:
        status_icon, status_str = "◐", "CHECKPOINTED"
    else:
        status_icon, status_str = "✗", result.status.upper()
    outer = result.outer_iterations
    inner = result.inner_iterations
    branch = result.branch or state.get("branch") or f"harness/{intent.spec_id}/iter-{max(outer - 1, 0)}"
    pr_url = state.get("pr_url") or result.pr_url
    lines = [
        f"{status_icon} {status_str}",
        f"branch: {branch}",
        f"PR: {pr_url}" if pr_url else "PR: not created (gh/glab unavailable or pr_host unset)",
        f"iterations: {outer} outer, {inner} inner retries",
    ]
    convergence = state.get("convergence_lease")
    if isinstance(convergence, Mapping):
        from harness.convergence import DEFAULT_STALL_PATIENCE

        meaningful = int(convergence.get("meaningful_attempts") or 0)
        ceiling = int(state.get("max_outer") or intent.max_outer)
        stalled = int(convergence.get("stalled_attempts") or 0)
        infrastructure = int(convergence.get("infrastructure_attempts") or 0)
        lines.extend(
            [
                f"meaningful attempts: {meaningful}/{ceiling}",
                f"stall patience: {stalled}/{DEFAULT_STALL_PATIENCE}",
                f"excluded infrastructure attempts: {infrastructure}",
            ]
        )
        outcome = str(convergence.get("last_outcome") or "").strip()
        outcome_reason = str(convergence.get("last_reason") or "").strip()
        if outcome:
            lines.append(
                "convergence: "
                + (f"{outcome}: {outcome_reason}" if outcome_reason else outcome)
            )
        best_checkpoint = str(convergence.get("best_checkpoint_commit") or "").strip()
        if best_checkpoint:
            lines.append(f"best checkpoint: {best_checkpoint[:12]}")
    if reason and reason != "converged":
        if provider_limited:
            lines.append("stopped: provider session limit")
            for key, label in (
                ("provider_limit_message", "provider"),
                ("provider_reset_hint", "reset"),
                ("salvage_branch", "salvage branch"),
                ("salvage_verified", "salvage verified"),
            ):
                value = str(state.get(key) or "").strip()
                if value:
                    lines.append(f"{label}: {value}")
            salvage_commit = str(state.get("salvage_commit") or "").strip()
            if salvage_commit:
                lines.append(f"salvage commit: {salvage_commit[:12]}")
            lines.append(f"continue: echelon delivery continue {intent.spec_id}")
        elif checkpointed:
            stopped = (
                "checkpoint continuation needed"
                if reason == "checkpoint_outer_cap"
                else "checkpoint recovery needed"
            )
            lines.append(f"stopped: {stopped}")
            lines.append(f"continue: echelon delivery continue {intent.spec_id}")
        else:
            lines.append(f"stopped: {reason}")
            if reason == "outer_cap":
                lines.append(
                    f"next: echelon delivery run {intent.spec_id}  "
                    "# continue with a fresh outer-loop budget"
                )
        if reason == "publish_failed":
            failure = state.get("publication_failure")
            if isinstance(failure, Mapping):
                stage = str(failure.get("stage") or "publication")
                error = str(failure.get("error") or "unknown error")
                lines.append(f"publish failure: {stage}: {error}")
    fv = result.final_verify
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
            prefix = "deferred" if deferred else "✗"
            lines.append(f"        {prefix} [{failure.category.value}] {failure.error}")
    else:
        lines.append("verify: skipped (no sandbox / project type undetected)")
    if fulfillment_recommendation and _has_fulfillment_gap_failure(result):
        lines.append(f"recommended action: {fulfillment_recommendation}")
    verified_ledger = _verified_ledger_line(info)
    if verified_ledger:
        lines.append(verified_ledger)
    if _should_print_suggested_answers(reason, result):
        lines.extend(_suggested_answer_lines(state.get("escalation_file"), intent.spec_id))
    fields.append(("delivery", "\n".join(lines)))

    outcome = (
        "converged"
        if converged
        else "provider-limited"
        if provider_limited
        else "checkpointed"
        if checkpointed
        else "failed"
    )
    if result.tokens_used:
        outcome += f"  ·  {result.tokens_used:,} tokens"
    fields.append(("outcome", outcome))
    provider_limit_message = (
        str(state.get("provider_limit_message") or "").strip()
        if provider_limited
        else ""
    )
    if provider_limited and not provider_limit_message:
        provider_limit_message = "Delivery reached its provider limit"
    if provider_limit_message:
        fields.append(("provider limit", provider_limit_message))
    next_step = ""
    if checkpointed or provider_limited:
        next_step = f"echelon delivery continue {intent.spec_id}"
    elif not converged:
        next_step = f"echelon delivery run {intent.spec_id}"
    elif landing is None or landing.status != "landed":
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
                    if converged
                    else "blocked"
                ),
                facts=_delivery_run_summary_facts(result, state),
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

    state: dict[str, object] = {}
    try:
        build_id = current_build_marker(
            harness_root,
            str(intent.spec_id),
        ).read_text(encoding="utf-8").strip()
        state_path = runs_dir(harness_root) / build_id / "state" / "default.json"
        value = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            state = value
    except (OSError, ValueError, json.JSONDecodeError):
        state = {}
    reason = str(
        state.get("termination_reason")
        or state.get("blocked_reason")
        or "controller_exception"
    )
    result = DeliveryResult(
        status="blocked",
        termination_reason=reason,
        outer_iterations=durable_counter(
            state.get("outer_iter") or state.get("outer_iteration")
        ),
        inner_iterations=durable_counter(
            state.get("inner_iter") or state.get("inner_iteration")
        ),
        pr_url=str(state.get("pr_url") or "") or None,
        tokens_used=durable_counter(state.get("tokens_used")),
        final_verify=None,
        blocked_phase=(
            str(state.get("blocked_phase"))
            if state.get("blocked_phase")
            in {"implementation", "visual", "review", "finalization"}
            else "implementation"
        ),
        branch=str(state.get("branch") or "") or None,
    )
    _print_delivery_summary(
        intent,
        result,
        state,
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
        status = str(row.get("status") or "?")
        reason = str(row.get("termination_reason") or "?")
        tokens = int(row.get("tokens_used") or 0)
        fields.append(
            (
                short_build,
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
    result: DeliveryResult,
    state: Mapping[str, object],
) -> None:
    if spec_dir is None:
        return
    append_run(
        spec_dir,
        spec_id=spec_id,
        build_id=build_id,
        mode=mode,
        result=result,
        pr_url=str(state.get("pr_url") or result.pr_url or "") or None,
        started_at=str(state.get("started_at") or "") or None,
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

    # The CLI reserves a new build directory before this adapter runs and passes
    # that ID here.  A build ID therefore does not itself mean "resume"; intent
    # is the authority for whether a prior checkpoint must be retained.
    fresh_branch_base = (
        None
        if getattr(intent, "resume", False)
        else _fresh_delivery_baseline(harness_root, intent, gitops)
    )
    fresh_completed_task_ids = _fresh_delivery_completed_tasks(
        harness_root,
        intent,
        fresh_branch_base,
        gitops,
        spec_dir=spec_dir,
    )
    build_id = resume_build_id or make_build_id()
    rd = runs_dir(harness_root)
    rd.mkdir(parents=True, exist_ok=True)
    current_build_marker(harness_root, intent.spec_id).write_text(build_id)
    logger.info("Build ID: %s", build_id)

    controller = DeliveryController(
        provider=provider,
        gitops=gitops,
        config=config,
        base_dir=harness_root,
        build_id=build_id,
        orchestration_root=workspace_root,
        fresh_branch_base=fresh_branch_base,
        fresh_completed_task_ids=fresh_completed_task_ids,
    )
    if fresh_branch_base:
        logger.info(
            "Starting new delivery budget from checkpointed candidate: %s",
            fresh_branch_base[:12],
        )
    try:
        run_gc(config, base_dir=str(harness_root))
    except Exception as exc:
        logger.warning("GC failed (continuing): %s", exc)

    _print_harness_history_summary(spec_dir=spec_dir, title="HARNESS HISTORY")
    result = controller.run(intent)
    state = controller.state()
    _append_harness_history(
        spec_dir=spec_dir,
        spec_id=intent.spec_id,
        build_id=build_id,
        mode=intent.mode,
        result=result,
        state=state,
    )
    _print_harness_history_summary(spec_dir=spec_dir, title="HARNESS HISTORY")

    landing = LandingOutcome("not_requested")
    converged = result.status == "converged"
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
        result,
        state,
        workspace_root,
        spec_dir,
        config,
        landing,
        summary_command,
    )
    return DeliveryRunOutcome(results=(result,), landing=landing)


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
    logger.info("Parsed run intent: spec=%s, mode=%s", intent.spec_id, intent.mode)

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

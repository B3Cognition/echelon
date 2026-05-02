"""accessors.py — Typed state field accessors for the transition evaluator.

Each accessor returns Optional[T] with None on missing or malformed field (fail-closed).
No accessor performs mutation. Pure functions.

Covers every field read by evaluator.py predicates per contracts/evaluator-contract.md.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

State = dict[str, Any]
Config = dict[str, Any]


# ---------------------------------------------------------------------------
# Quality score accessors
# ---------------------------------------------------------------------------


def get_last_quality_scores(state: State) -> Optional[dict[str, Any]]:
    """Return the last entry in state.quality_scores, or None if absent/empty."""
    scores = state.get("quality_scores")
    if not isinstance(scores, list) or len(scores) == 0:
        return None
    last = scores[-1]
    if not isinstance(last, dict):
        return None
    return last


def get_quality_scores_window(state: State, window: int = 2) -> Optional[list[dict[str, Any]]]:
    """Return the last `window` entries from state.quality_scores for convergence checks."""
    scores = state.get("quality_scores")
    if not isinstance(scores, list) or len(scores) == 0:
        return None
    return scores[-window:]


def get_qualitative_scores(state: State) -> Optional[dict[str, Any]]:
    """Return state.qualitative_scores dict (bucketed branch), or None if absent."""
    qs = state.get("qualitative_scores")
    if not isinstance(qs, dict):
        return None
    return qs


# ---------------------------------------------------------------------------
# Issues log accessors
# ---------------------------------------------------------------------------


def get_critical_issues(state: State) -> list[dict[str, Any]]:
    """Return all unresolved CRITICAL issues from state.issues_log."""
    issues = state.get("issues_log")
    if not isinstance(issues, list):
        return []
    return [
        issue for issue in issues
        if isinstance(issue, dict)
        and issue.get("severity") == "CRITICAL"
        and not issue.get("resolved", False)
    ]


def has_critical_issues(state: State) -> bool:
    """True if there are any unresolved CRITICAL issues."""
    return len(get_critical_issues(state)) > 0


# ---------------------------------------------------------------------------
# Iteration accessor
# ---------------------------------------------------------------------------


def get_iteration(state: State) -> Optional[int]:
    """Return state.iteration as int, or None if absent/invalid."""
    val = state.get("iteration")
    if not isinstance(val, int) or isinstance(val, bool):
        return None
    return val


# ---------------------------------------------------------------------------
# Mode accessor
# ---------------------------------------------------------------------------


def get_mode(state: State) -> Optional[str]:
    """Return state.mode string, or None if absent."""
    val = state.get("mode")
    if not isinstance(val, str):
        return None
    return val


# ---------------------------------------------------------------------------
# meta_run accessor
# ---------------------------------------------------------------------------


def get_meta_run(state: State) -> Optional[bool]:
    """Return state.meta_run bool, or None if absent/invalid."""
    val = state.get("meta_run")
    if not isinstance(val, bool):
        return None
    return val


# ---------------------------------------------------------------------------
# defer_count accessor
# ---------------------------------------------------------------------------


def get_defer_count(state: State) -> Optional[int]:
    """Return state.defer_count as int, or None if absent/invalid."""
    val = state.get("defer_count")
    if not isinstance(val, int) or isinstance(val, bool):
        return None
    return val


# ---------------------------------------------------------------------------
# autonomy_mode accessor
# ---------------------------------------------------------------------------


def get_autonomy_mode(state: State) -> Optional[str]:
    """Return state.autonomy_mode string, or None if absent."""
    val = state.get("autonomy_mode")
    if not isinstance(val, str):
        return None
    return val


# ---------------------------------------------------------------------------
# checkpoint_responses accessor
# ---------------------------------------------------------------------------


def get_checkpoint_approved(state: State, checkpoint: str) -> Optional[bool]:
    """Return state.checkpoint_responses[checkpoint].approved, or None if absent."""
    responses = state.get("checkpoint_responses")
    if not isinstance(responses, dict):
        return None
    entry = responses.get(checkpoint)
    if not isinstance(entry, dict):
        return None
    val = entry.get("approved")
    if not isinstance(val, bool):
        return None
    return val


# ---------------------------------------------------------------------------
# last_outputs verdict accessor
# ---------------------------------------------------------------------------


def get_last_outputs_verdict(last_outputs: dict[str, Any]) -> Optional[str]:
    """Return last_outputs.verdict string, or None if absent."""
    if not isinstance(last_outputs, dict):
        return None
    val = last_outputs.get("verdict")
    if not isinstance(val, str):
        return None
    return val


# ---------------------------------------------------------------------------
# dependency_checks accessor
# ---------------------------------------------------------------------------


def get_dependency_check(state: State, dep_name: str) -> Optional[dict[str, Any]]:
    """Return state.dependency_checks[dep_name] dict, or None if absent."""
    checks = state.get("dependency_checks")
    if not isinstance(checks, dict):
        return None
    entry = checks.get(dep_name)
    if not isinstance(entry, dict):
        return None
    return entry


def get_dependency_check_status(state: State, dep_name: str) -> Optional[str]:
    """Return state.dependency_checks[dep_name].status, or None if absent."""
    entry = get_dependency_check(state, dep_name)
    if entry is None:
        return None
    val = entry.get("status")
    if not isinstance(val, str):
        return None
    return val


# ---------------------------------------------------------------------------
# Config accessors (squad-config.yml)
# ---------------------------------------------------------------------------


def get_config_max_iterations(config: Config) -> Optional[int]:
    """Return config.convergence.max_iterations, or None if absent."""
    convergence = config.get("convergence")
    if not isinstance(convergence, dict):
        return None
    val = convergence.get("max_iterations")
    if not isinstance(val, int) or isinstance(val, bool):
        return None
    return val


def get_config_quality_delta_threshold(config: Config) -> Optional[float]:
    """Return config.convergence.quality_delta_threshold, or None if absent."""
    convergence = config.get("convergence")
    if not isinstance(convergence, dict):
        return None
    val = convergence.get("quality_delta_threshold")
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return None
    return float(val)


def get_config_consecutive_passes(config: Config) -> Optional[int]:
    """Return config.convergence.consecutive_passes_required, or None if absent."""
    convergence = config.get("convergence")
    if not isinstance(convergence, dict):
        return None
    val = convergence.get("consecutive_passes_required")
    if not isinstance(val, int) or isinstance(val, bool):
        return None
    return val


def get_config_assess_defer_limit(config: Config) -> Optional[int]:
    """Return config.convergence.assess_defer_loop_limit, or None if absent."""
    convergence = config.get("convergence")
    if not isinstance(convergence, dict):
        return None
    val = convergence.get("assess_defer_loop_limit")
    if not isinstance(val, int) or isinstance(val, bool):
        return None
    return val


def get_config_quality_gates(config: Config) -> Optional[dict[str, Any]]:
    """Return config.quality_gates dict, or None if absent."""
    val = config.get("quality_gates")
    if not isinstance(val, dict):
        return None
    return val


def get_config_guardian_mode(config: Config) -> Optional[str]:
    """Return config.specialists.guardian_mode (or config.guardian_mode), or None if absent."""
    # Try nested path first
    specialists = config.get("specialists")
    if isinstance(specialists, dict):
        val = specialists.get("guardian_mode")
        if isinstance(val, str):
            return val
    # Fall back to top-level
    val = config.get("guardian_mode")
    if not isinstance(val, str):
        return None
    return val

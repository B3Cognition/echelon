"""re_state.py — Pure functions for .specify/echelon/re/state.json management.

Mirrors the squad state machine protocol (last_dispatch sentinel) for the
re-* brownfield extraction sub-system.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_RE_OUTPUT_DIR = ".specify/echelon/re"


def resolve_re_output_dir(
    project_root: str | Path = ".",
    configured_output_dir: str | None = None,
) -> str:
    """Return the RE output directory for the current execution context.

    Standalone re-* commands use the configured/default `.specify/echelon/re`
    location. When that default is in effect and an active echelon spec run exists,
    RE artifacts belong to the active run directory under `runs/<run-id>/re`.
    """
    configured = configured_output_dir or DEFAULT_RE_OUTPUT_DIR
    if configured != DEFAULT_RE_OUTPUT_DIR:
        return configured

    root = Path(project_root)
    current = root / "runs" / ".current"
    if not current.exists():
        return DEFAULT_RE_OUTPUT_DIR

    run_id = current.read_text().strip()
    if not run_id:
        return DEFAULT_RE_OUTPUT_DIR

    run_dir = root / "runs" / run_id
    if not run_dir.exists():
        return DEFAULT_RE_OUTPUT_DIR

    return f"runs/{run_id}/re"

def init_re_state(
    output_dir: str = DEFAULT_RE_OUTPUT_DIR,
    mode: str = "single",
    coverage_threshold: int = 80,
    resolution_threshold: int = 80,
    max_validate_iterations: int = 3,
    max_verify_expand_iterations: int = 5,
) -> dict:
    """Return a fresh re/state.json dict."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "run_id": f"re-{ts}",
        "status": "in_progress",
        "phase": "re-extract-0-preflight",
        "last_dispatch": {
            "phase_id": None,
            "agent": None,
            "post_dispatch_complete": False,
            "dispatched_at": None,
        },
        "mode": mode,
        "output_dir": output_dir,
        "domains": [],
        "coverage_pct": 0,
        "coverage_threshold": coverage_threshold,
        "verify_expand_iterations": 0,
        "max_verify_expand_iterations": max_verify_expand_iterations,
        "resolution_pct": 0,
        "resolution_threshold": resolution_threshold,
        "validate_iterations": 0,
        "max_validate_iterations": max_validate_iterations,
        "artifacts": {
            "analysis_json": f"{output_dir}/analysis.json",
            "repos_manifest": f"{output_dir}/repos-manifest.json",
            "cross_repo": None,
            "codegraph_analysis": f"{output_dir}/codegraph-analysis.json",
            "codegraph_summary": f"{output_dir}/codegraph-summary.json",
        },
        "issues_log": [],
    }


def write_last_dispatch(state: dict, phase_id: str, agent: str) -> dict:
    """Return a copy of state with the pre-dispatch sentinel written.

    Must be called before every agent dispatch. Sets post_dispatch_complete=False
    so that context-compaction recovery can detect incomplete dispatches.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = copy.deepcopy(state)
    s["phase"] = phase_id
    s["last_dispatch"] = {
        "phase_id": phase_id,
        "agent": agent,
        "post_dispatch_complete": False,
        "dispatched_at": ts,
    }
    return s


# Keys agents may write via state_updates. last_dispatch and status are
# COMMANDER-owned and must not be overwritten by agent result blocks.
_ALLOWED_STATE_UPDATE_KEYS = frozenset({
    "coverage_pct", "resolution_pct", "domains", "mode",
    "validate_iterations", "verify_expand_iterations",
    "artifacts", "issues_log",
})


def complete_dispatch(state: dict, echelon_result: dict) -> dict:
    """Return a copy of state with post_dispatch_complete=True and state_updates applied.

    Call after reading the agent's echelon_result: block.

    Only keys in _ALLOWED_STATE_UPDATE_KEYS may appear in state_updates.
    Raises ValueError on unknown keys to protect COMMANDER-owned fields
    (last_dispatch, status) from agent result blocks.
    """
    if "last_dispatch" not in state:
        raise KeyError(
            "complete_dispatch called on state with no last_dispatch sentinel "
            "— was write_last_dispatch called first?"
        )
    s = copy.deepcopy(state)
    s["last_dispatch"]["post_dispatch_complete"] = True
    for key, value in echelon_result.get("state_updates", {}).items():
        if key not in _ALLOWED_STATE_UPDATE_KEYS:
            raise ValueError(
                f"state_updates key {key!r} is not allowed — "
                f"only {sorted(_ALLOWED_STATE_UPDATE_KEYS)} may be written by agents"
            )
        s[key] = value
    return s


def should_redispatch(state: dict) -> bool:
    """Return True if the last dispatch did not complete (compaction-safe resumption guard).

    If `post_dispatch_complete` is absent from `last_dispatch`, it is treated as True (complete — no redispatch).
    """
    ld = state.get("last_dispatch", {})
    if ld.get("phase_id") is None:
        return False
    return not ld.get("post_dispatch_complete", True)


def get_current_phase(state: dict) -> str | None:
    """Return the current phase id from state, or None if not set."""
    return state.get("phase") or None

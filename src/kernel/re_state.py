"""re_state.py — Pure functions for .specify/echelon/re/state.json management.

Mirrors the squad state machine protocol (last_dispatch sentinel) for the
re-* brownfield extraction sub-system.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any


def init_re_state(
    output_dir: str = ".specify/echelon/re",
    mode: str = "single",
    coverage_threshold: int = 80,
    resolution_threshold: int = 80,
    max_validate_iterations: int = 3,
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
        "resolution_pct": 0,
        "resolution_threshold": resolution_threshold,
        "validate_iterations": 0,
        "max_validate_iterations": max_validate_iterations,
        "artifacts": {
            "analysis_json": f"{output_dir}/analysis.json",
            "repos_manifest": f"{output_dir}/repos-manifest.json",
            "cross_repo": None,
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


def complete_dispatch(state: dict, echelon_result: dict) -> dict:
    """Return a copy of state with post_dispatch_complete=True and state_updates applied.

    Call after reading the agent's echelon_result: block.
    """
    s = copy.deepcopy(state)
    s["last_dispatch"]["post_dispatch_complete"] = True
    for key, value in echelon_result.get("state_updates", {}).items():
        s[key] = value
    return s


def should_redispatch(state: dict) -> bool:
    """Return True if the last dispatch did not complete (compaction-safe resumption guard)."""
    ld = state.get("last_dispatch", {})
    if ld.get("phase_id") is None:
        return False
    return not ld.get("post_dispatch_complete", True)


def get_current_phase(state: dict) -> str | None:
    """Return the current phase id from state, or None if not set."""
    return state.get("phase") or None

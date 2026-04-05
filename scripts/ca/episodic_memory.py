"""
T-025 — Episodic Memory Overlay (CA overlay, ADR-005)

Exposes:
  enrich_context(context_pack, run_id, agent_type) -> dict
  index_artifact(agent_type, artifact_path, stage_timestamp, artifact_category, run_id)

Temporal artifact index — append-only, no cross-run persistence (v1 scope).

Human override of P-006 authorized 2026-04-03 (user instruction: "build it anyway").
"""

from __future__ import annotations

import json
import os
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _index_path(run_id: str) -> str:
    root = _repo_root()
    return os.path.join(root, ".specify", "squad", f"episodic-index-{run_id}.json")


def _repo_root() -> str:
    path = os.path.dirname(os.path.abspath(__file__))
    while path != os.path.dirname(path):
        if os.path.isdir(os.path.join(path, ".git")):
            return path
        path = os.path.dirname(path)
    return os.getcwd()


def _load_index(run_id: str) -> list:
    path = _index_path(run_id)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_index(entries: list, run_id: str) -> None:
    path = _index_path(run_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def enrich_context(context_pack: dict, run_id: str, agent_type: str) -> dict:
    """
    Look up the most-recent artifact for the given agent_type and inject into context_pack.

    Adds context_pack["episodic_prior_artifact"] = {artifact_path, stage_timestamp,
    artifact_category} or None if no prior artifact for this agent type exists.

    Does NOT modify COMMANDER routing logic, quality gates, or endocrine triggers (AC-5.1).
    FR-CAO-002: single small dict injected — no token bound issue.
    """
    entries = _load_index(run_id)

    # Query: max(entries where agent_type == requested_type, key=stage_timestamp)
    matching = [e for e in entries if e.get("agent_type") == agent_type]
    if matching:
        best = max(matching, key=lambda e: e.get("stage_timestamp", 0))
        prior_artifact: Optional[dict] = {
            "artifact_path": best.get("artifact_path"),
            "stage_timestamp": best.get("stage_timestamp"),
            "artifact_category": best.get("artifact_category"),
        }
    else:
        prior_artifact = None

    enriched = dict(context_pack)
    enriched["episodic_prior_artifact"] = prior_artifact
    return enriched


def index_artifact(
    agent_type: str,
    artifact_path: str,
    stage_timestamp: float,
    artifact_category: str,
    run_id: str,
) -> None:
    """
    Append a new artifact record to the episodic index.

    Called by COMMANDER post-dispatch, after a successful agent invocation.
    Index is append-only — no deletions (AC-5.1, append-only invariant).
    No cross-run persistence in v1 (spec §2 Out-of-Scope).
    """
    entries = _load_index(run_id)
    entries.append(
        {
            "agent_type": agent_type,
            "artifact_path": artifact_path,
            "stage_timestamp": stage_timestamp,
            "artifact_category": artifact_category,
        }
    )
    _save_index(entries, run_id)

"""
Quarantined prototype: T-021 Goal Stack Overlay (CA overlay, ADR-005).

Exposes:
  enrich_context(context_pack, run_id) -> dict
  update_goal_stack(outcome, run_id)

Human override of P-006 authorized 2026-04-03 (user instruction: "build it anyway").
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stack_path(run_id: str) -> str:
    repo_root = _repo_root()
    return os.path.join(repo_root, ".specify", "squad", f"goal-stack-{run_id}.json")


def _repo_root() -> str:
    path = os.path.dirname(os.path.abspath(__file__))
    while path != os.path.dirname(path):
        if os.path.isdir(os.path.join(path, ".git")):
            return path
        path = os.path.dirname(path)
    return os.getcwd()


def _spec_feature_name() -> str:
    """Extract feature name from the first spec.md found under specs/."""
    root = _repo_root()
    # Look in .specify/specs/ for any spec.md
    specs_dir = os.path.join(root, ".specify", "specs")
    if os.path.isdir(specs_dir):
        for entry in sorted(os.listdir(specs_dir)):
            spec_file = os.path.join(specs_dir, entry, "spec.md")
            if os.path.isfile(spec_file):
                with open(spec_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#"):
                            # Strip leading '#' chars and return
                            return re.sub(r"^#+\s*", "", line)
    return "Echelon Feature"


def _load_stack(run_id: str) -> dict:
    path = _stack_path(run_id)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_stack(stack: dict, run_id: str) -> None:
    path = _stack_path(run_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stack, f, indent=2)


def _init_stack(run_id: str) -> dict:
    """Create a fresh goal stack with the root goal."""
    feature_name = _spec_feature_name()
    stack = {
        "run_id": run_id,
        "goals": [
            {
                "id": "G-001",
                "goal_text": f"Deliver: {feature_name}",
                "priority": 1.0,
                "depth": 0,
                "status": "ACTIVE",
            }
        ],
    }
    _save_stack(stack, run_id)
    return stack


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def enrich_context(context_pack: dict, run_id: str) -> dict:
    """
    Read the goal stack for this run and inject the current active goal.

    Inserts context_pack["active_goal"] = {goal_text, priority, depth}.
    Returns the enriched context_pack (does NOT modify COMMANDER state).

    FR-CAO-002: no token bound exceeded — active_goal is a single small dict.
    """
    stack = _load_stack(run_id)
    if not stack:
        stack = _init_stack(run_id)

    # Active goal = highest-priority ACTIVE goal (lowest depth = root first)
    active_goals = [g for g in stack.get("goals", []) if g.get("status") == "ACTIVE"]
    if active_goals:
        # Sort by priority desc, then depth asc (shallow first)
        active_goals.sort(key=lambda g: (-g.get("priority", 0), g.get("depth", 0)))
        top = active_goals[0]
        active_goal = {
            "goal_text": top["goal_text"],
            "priority": top["priority"],
            "depth": top["depth"],
        }
    else:
        active_goal = {
            "goal_text": "No active goal",
            "priority": 0.0,
            "depth": 0,
        }

    enriched = dict(context_pack)
    enriched["active_goal"] = active_goal
    return enriched


def update_goal_stack(outcome: dict, run_id: str) -> None:
    """
    Called by COMMANDER post-dispatch to update the goal stack.

    outcome dict may contain:
      - "completed_goal_id": str  — mark that goal DONE
      - "new_goal": dict          — push a sub-goal onto the stack
        {"goal_text": str, "priority": float, "depth": int}

    This function is write-only to the stack JSON — never touches context_pack.
    """
    stack = _load_stack(run_id)
    if not stack:
        stack = _init_stack(run_id)

    goals = stack.get("goals", [])

    completed_id = outcome.get("completed_goal_id")
    if completed_id:
        for g in goals:
            if g["id"] == completed_id and g["status"] == "ACTIVE":
                g["status"] = "DONE"

    new_goal = outcome.get("new_goal")
    if new_goal:
        next_id = f"G-{len(goals) + 1:03d}"
        goals.append(
            {
                "id": next_id,
                "goal_text": new_goal.get("goal_text", "Sub-goal"),
                "priority": float(new_goal.get("priority", 0.5)),
                "depth": int(new_goal.get("depth", 1)),
                "status": "ACTIVE",
            }
        )

    stack["goals"] = goals
    _save_stack(stack, run_id)

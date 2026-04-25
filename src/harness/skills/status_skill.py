"""Status skill -- display current loop status.

Per T044 / FR-CLI-003: aggregate status across all strategies.
Render within 3 seconds.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def show_status(base_dir: str = ".") -> Dict[str, Any]:
    """Display and return current loop status.

    Args:
        base_dir: Base directory for harness state.

    Returns:
        Status dict for programmatic use.
    """
    state_dir = Path(base_dir) / ".specify" / "harness" / "state"

    if not state_dir.exists():
        print("No active loops.", file=sys.stderr)
        return {"active_loops": 0, "strategies": {}}

    strategies: Dict[str, Any] = {}

    for spec_dir in state_dir.iterdir():
        if not spec_dir.is_dir():
            continue
        for state_file in spec_dir.glob("*.json"):
            sid = state_file.stem
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                strategies[sid] = {
                    "status": data.get("status", "unknown"),
                    "outer_iter": data.get("outer_iter", 0),
                    "inner_iter": data.get("inner_iter", 0),
                    "tokens_used": data.get("tokens_used", 0),
                    "token_budget": data.get("token_budget"),
                    "pr_url": data.get("pr_url"),
                    "termination_reason": data.get("termination_reason"),
                    "escalation_file": data.get("escalation_file"),
                }
            except (json.JSONDecodeError, Exception) as e:
                strategies[sid] = {
                    "status": "corrupted",
                    "error": str(e),
                }

    active = sum(
        1 for s in strategies.values()
        if s.get("status") in ("running", "blocked", "initialized")
    )

    if not strategies:
        print("No active loops.", file=sys.stderr)
    elif active == 0:
        print("No active loops (all completed).", file=sys.stderr)
    else:
        print(f"\n--- LOOP STATUS ({active} active) ---", file=sys.stderr)

    for sid, info in strategies.items():
        if info.get("status") == "corrupted":
            print(f"  {sid}: STATE CORRUPTED -- run speckit.echelon.harness-resume to recover",
                  file=sys.stderr)
            continue

        budget_str = ""
        if info.get("token_budget") and info["token_budget"] > 0:
            pct = (info["tokens_used"] / info["token_budget"]) * 100
            budget_str = f" ({pct:.0f}% of {info['token_budget']})"

        print(
            f"  {sid}: {info['status']} | "
            f"iter {info['outer_iter']}.{info['inner_iter']} | "
            f"tokens: {info['tokens_used']}{budget_str}",
            file=sys.stderr,
        )

        if info.get("pr_url"):
            print(f"    PR: {info['pr_url']}", file=sys.stderr)

        if info.get("status") == "blocked" and info.get("escalation_file"):
            print(f"    Blocked: see {info['escalation_file']}", file=sys.stderr)

    return {"active_loops": active, "strategies": strategies}

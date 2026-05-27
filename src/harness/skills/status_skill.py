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
    from harness.paths import runs_dir
    base_path = Path(base_dir)
    rd = runs_dir(base_path)

    if not rd.exists():
        print("No active loops.", file=sys.stderr)
        return {"active_loops": 0, "strategies": {}}

    strategies: Dict[str, Any] = {}

    for build in sorted(rd.glob("build-*/")):
        state_dir = build / "state"
        if not state_dir.exists():
            continue
        for state_file in state_dir.glob("*.json"):
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

    from echelon.ui import banner as _banner

    if not strategies:
        _banner("LOOP STATUS", [("active loops", "0")], file=sys.stderr)
        return {"active_loops": 0, "strategies": {}}

    fields: list[tuple[str, str]] = []
    for sid, info in strategies.items():
        if info.get("status") == "corrupted":
            fields.append((sid, "STATE CORRUPTED — run speckit.echelon.harness-resume to recover"))
            continue

        budget_str = ""
        if info.get("token_budget") and info["token_budget"] > 0:
            pct = (info["tokens_used"] / info["token_budget"]) * 100
            budget_str = f" ({pct:.0f}% of {info['token_budget']})"

        val_lines = [
            f"{info['status']}  |  iter {info['outer_iter']}.{info['inner_iter']}  |  tokens: {info['tokens_used']}{budget_str}"
        ]
        if info.get("pr_url"):
            val_lines.append(f"PR: {info['pr_url']}")
        if info.get("status") == "blocked" and info.get("escalation_file"):
            val_lines.append(f"blocked: see {info['escalation_file']}")

        fields.append((sid, "\n".join(val_lines)))

    active_label = f"{active} active" if active > 0 else "all completed"
    _banner(f"LOOP STATUS ({active_label})", fields, file=sys.stderr)

    return {"active_loops": active, "strategies": strategies}

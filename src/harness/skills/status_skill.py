"""Status skill -- display current loop status.

Per T044 / FR-CLI-003: display the current delivery status.
Render within 3 seconds.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

from harness.dirty_adjudicator import dirty_summary_text

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
        return {"active_loops": 0, "delivery": {}}

    delivery: Dict[str, Any] = {}
    for build in sorted(rd.glob("build-*/"), reverse=True):
        state_dir = build / "state"
        state_file = state_dir / "delivery.json"
        if not state_file.is_file():
            continue
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            delivery = {
                "status": data.get("status", "unknown"),
                "outer_iter": data.get("outer_iter", 0),
                "inner_iter": data.get("inner_iter", 0),
                "tokens_used": data.get("tokens_used", 0),
                "token_budget": data.get("token_budget"),
                "pr_url": data.get("pr_url"),
                "termination_reason": data.get("termination_reason"),
                "escalation_file": data.get("escalation_file"),
                "dirty_worktree_adjudication": data.get("dirty_worktree_adjudication"),
                "publication_failure": data.get("publication_failure"),
            }
        except (json.JSONDecodeError, OSError) as error:
            delivery = {"status": "corrupted", "error": str(error)}
        break

    active = int(delivery.get("status") in ("running", "blocked", "initialized"))

    from echelon.ui import banner as _banner

    if not delivery:
        _banner("LOOP STATUS", [("active loops", "0")], file=sys.stderr)
        return {"active_loops": 0, "delivery": {}}

    fields: list[tuple[str, str]] = []
    info = delivery
    if info.get("status") == "corrupted":
        fields.append(("delivery", "STATE CORRUPTED — run echelon delivery resume <spec_id> \"<answer>\" to recover"))
    else:

        budget_str = ""
        if info.get("token_budget") and info["token_budget"] > 0:
            pct = (info["tokens_used"] / info["token_budget"]) * 100
            budget_str = f" ({pct:.0f}% of {info['token_budget']})"

        val_lines = [
            f"{info['status']}  |  iter {info['outer_iter']}.{info['inner_iter']}  |  tokens: {info['tokens_used']}{budget_str}"
        ]
        if info.get("pr_url"):
            val_lines.append(f"PR: {info['pr_url']}")
        dirty_line = dirty_summary_text(info.get("dirty_worktree_adjudication"))
        if dirty_line:
            val_lines.append(dirty_line)
        publication_failure = info.get("publication_failure")
        if isinstance(publication_failure, dict):
            stage = str(publication_failure.get("stage") or "publication")
            error = str(publication_failure.get("error") or "unknown error")
            val_lines.append(f"publish failure: {stage}: {error}")
        if info.get("status") == "blocked" and info.get("escalation_file"):
            val_lines.append(f"blocked: see {info['escalation_file']}")

        fields.append(("delivery", "\n".join(val_lines)))

    active_label = f"{active} active" if active > 0 else "all completed"
    _banner(f"LOOP STATUS ({active_label})", fields, file=sys.stderr)

    return {"active_loops": active, "delivery": delivery}

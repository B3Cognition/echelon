#!/usr/bin/env python3
"""emit_score_deltas.py — Post-run agent score delta emitter.

Usage:
    python emit_score_deltas.py --run-id <run_id> [--runs-root <dir>] [--kb-dir <dir>] [--dry-run]

Walks <runs-root>/<run_id>/ for reasoning-journal.jsonl, extracts agent_output
entries with score data, and emits a per-agent score_delta record to
knowledge-base/agent-scores.yaml.

Contracts:
- Emits >= 1 score_delta per completed run
- Cold-start case uses null_delta when no prior score exists
- Does NOT re-dispatch any agent (pure audit function)
- Budget <= 60s
- Does NOT crash if agent-scores.yaml does not exist (creates stub)

Output: appends to agent-scores.yaml under agents.<AGENT>.history and
        updates agents.<AGENT>.current_run_score + lifetime_score.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
EXT_DIR = SCRIPT_DIR.parent.parent

BUDGET_SECONDS = 60


def _default_runs_root() -> Path:
    return EXT_DIR / "runs"


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_journal(run_dir: Path) -> list:
    """Load reasoning-journal.jsonl from a run directory."""
    journal_path = run_dir / "reasoning-journal.jsonl"
    if not journal_path.exists():
        return []
    entries = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def _load_state(run_dir: Path) -> dict:
    """Load state.json from a run directory."""
    state_path = run_dir / "state.json"
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_agent_scores(kb_dir: Path) -> dict:
    """Load agent-scores.yaml as a dict. Returns minimal stub if absent."""
    scores_path = kb_dir / "agent-scores.yaml"
    if not scores_path.exists():
        return {
            "schema_version": 1,
            "meta": {
                "cold_start": True,
                "total_runs": 0,
                "last_updated": _iso_now(),
                "generated_by": "emit_score_deltas",
            },
            "leaderboard": [],
            "agents": {},
            "runs": [],
        }
    try:
        import yaml  # type: ignore
        with scores_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except ImportError:
        # Minimal YAML parser — read as text and return stub
        return {
            "schema_version": 1,
            "meta": {"cold_start": False, "total_runs": 0, "last_updated": _iso_now()},
            "leaderboard": [],
            "agents": {},
            "runs": [],
        }
    except Exception:
        return {}


def _save_agent_scores(kb_dir: Path, data: dict) -> None:
    """Write agent-scores.yaml using PyYAML if available, else JSON-derived YAML."""
    scores_path = kb_dir / "agent-scores.yaml"
    try:
        import yaml  # type: ignore
        content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        scores_path.write_text(content, encoding="utf-8")
    except ImportError:
        # Fallback: write as JSON (still valid machine-readable, but not YAML-pretty)
        scores_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _extract_score_events(journal: list, run_id: str) -> list:
    """Extract per-agent score events from journal entries.

    Looks for:
    - type: agent_scores (direct score entries from SCOREKEEPER)
    - type: agent_output with a score field in data
    - type: scorekeeper_output with agents array

    Returns list of {agent, score, action, reason, run_id} dicts.
    """
    events = []
    for entry in journal:
        etype = entry.get("type", "")
        data = entry.get("data", {})
        agent = entry.get("agent", "")

        if not isinstance(data, dict):
            continue

        # Direct score entry
        if etype == "agent_scores":
            for item in data.get("scores", []):
                if isinstance(item, dict) and "agent" in item:
                    events.append({
                        "agent": item["agent"],
                        "score": item.get("score"),
                        "action": item.get("action", "unknown_action"),
                        "reason": item.get("reason", ""),
                        "run_id": run_id,
                    })

        # SCOREKEEPER output with agents array
        elif etype in ("scorekeeper_output", "score_summary"):
            for item in data.get("agents", []):
                if isinstance(item, dict) and "agent" in item:
                    events.append({
                        "agent": item["agent"],
                        "score": item.get("score") or item.get("current_run_score"),
                        "action": item.get("action", "scorekeeper_summary"),
                        "reason": item.get("reason", ""),
                        "run_id": run_id,
                    })

        # agent_output with explicit score
        elif etype == "agent_output" and "score" in data:
            if agent:
                events.append({
                    "agent": agent,
                    "score": data.get("score"),
                    "action": data.get("action", "agent_output"),
                    "reason": data.get("reason", ""),
                    "run_id": run_id,
                })

    return events


def _apply_deltas(scores_data: dict, events: list, run_id: str) -> dict:
    """Apply score delta events to the agent-scores dict.

    For each event:
    - If agent has no prior history: null_delta cold-start entry followed by new entry
    - If agent has prior history: compute delta vs last score

    Returns updated scores_data.
    """
    agents = scores_data.setdefault("agents", {})

    for event in events:
        agent_name = event["agent"]
        new_score = event["score"]
        action = event.get("action", "unknown_action")
        reason = event.get("reason", "")

        agent_entry = agents.setdefault(agent_name, {
            "lifetime_score": 0,
            "current_run_score": 0,
            "total_dispatches": 0,
            "avg_score_per_dispatch": 0.0,
            "badges": [],
            "history": [],
        })

        history = agent_entry.setdefault("history", [])

        # Cold-start: no prior history
        if not history:
            # Emit null_delta as first entry to mark the cold-start
            history.append({
                "run_id": "cold_start",
                "score": None,
                "action": "null_delta",
                "reason": "cold-start — no prior score data",
                "delta": None,
                "badges_earned": [],
                "failure_modes": [],
                "peer_appreciation": [],
            })
            prior_score = None
        else:
            # Get last non-cold-start score
            prior_score = None
            for h in reversed(history):
                if h.get("action") != "null_delta" and h.get("score") is not None:
                    prior_score = h["score"]
                    break

        # Compute delta
        if new_score is not None and prior_score is not None:
            delta = round(float(new_score) - float(prior_score), 4)
        else:
            delta = None  # null_delta

        # Append history entry
        history.append({
            "run_id": run_id,
            "score": new_score,
            "action": action,
            "reason": reason,
            "delta": delta,
            "badges_earned": [],
            "failure_modes": [],
            "peer_appreciation": [],
        })

        # Update summary fields
        if new_score is not None:
            agent_entry["current_run_score"] = new_score
            # Lifetime = sum of non-null, non-cold-start scores
            valid_scores = [
                h["score"] for h in history
                if h.get("score") is not None and h.get("action") != "null_delta"
                and h.get("run_id") != "cold_start"
            ]
            agent_entry["lifetime_score"] = sum(valid_scores)
            agent_entry["total_dispatches"] = len(valid_scores)
            agent_entry["avg_score_per_dispatch"] = (
                round(sum(valid_scores) / len(valid_scores), 4)
                if valid_scores else 0.0
            )

    return scores_data


def _update_leaderboard(scores_data: dict) -> dict:
    """Recompute the leaderboard from current_run_score values."""
    agents = scores_data.get("agents", {})
    entries = []
    for name, data in agents.items():
        if data.get("current_run_score") is not None:
            entries.append({
                "agent": name,
                "current_run_score": data.get("current_run_score", 0),
                "lifetime_score": data.get("lifetime_score", 0),
                "badges": [b.get("name", b) if isinstance(b, dict) else b
                           for b in data.get("badges", [])],
            })

    # Sort by current_run_score desc, alpha tiebreak
    entries.sort(key=lambda x: (-x.get("current_run_score", 0), x["agent"]))

    # Assign ranks (tied agents share rank)
    ranked = []
    prev_score = None
    prev_rank = 0
    for i, e in enumerate(entries):
        if e["current_run_score"] != prev_score:
            prev_rank = i + 1
            prev_score = e["current_run_score"]
        ranked.append({
            "rank": prev_rank,
            "agent": e["agent"],
            "current_run_score": e["current_run_score"],
            "lifetime_score": e["lifetime_score"],
            "badges": e["badges"],
        })

    scores_data["leaderboard"] = ranked
    return scores_data


def emit_score_deltas(
    run_id: str,
    runs_root: Path,
    kb_dir: Path,
    dry_run: bool = False,
) -> dict:
    """Main entry point. Returns a report dict.

    Args:
        run_id:    The completed run ID (e.g., spec-1234)
        runs_root: Root directory containing run directories.
        kb_dir:    Path to knowledge-base/
        dry_run:   If True, compute deltas but do not write to agent-scores.yaml

    Returns:
        {run_id, events_found, deltas_emitted, agents_updated, dry_run, elapsed_seconds}
    """
    t_start = time.monotonic()

    run_dir = runs_root / run_id
    if not run_dir.exists():
        return {
            "run_id": run_id,
            "error": f"run directory not found: {run_dir}",
            "events_found": 0,
            "deltas_emitted": 0,
            "agents_updated": [],
            "dry_run": dry_run,
            "elapsed_seconds": round(time.monotonic() - t_start, 2),
        }

    # Load inputs
    journal = _load_journal(run_dir)
    state = _load_state(run_dir)
    scores_data = _load_agent_scores(kb_dir)

    # Extract score events
    events = _extract_score_events(journal, run_id)

    # If no events found from journal, synthesize a single null_delta event
    # to satisfy the "emits >= 1 score_delta per completed run" contract
    if not events:
        run_status = state.get("status", "unknown")
        synthetic_agent = "COMMANDER"  # COMMANDER is always present
        events.append({
            "agent": synthetic_agent,
            "score": None,
            "action": "null_delta",
            "reason": f"no score events in journal (run_status={run_status})",
            "run_id": run_id,
        })

    agents_before = set(scores_data.get("agents", {}).keys())

    # Apply deltas
    scores_data = _apply_deltas(scores_data, events, run_id)
    scores_data = _update_leaderboard(scores_data)

    # Update meta
    meta = scores_data.setdefault("meta", {})
    meta["last_updated"] = _iso_now()
    meta["total_runs"] = meta.get("total_runs", 0) + 1
    if meta.get("cold_start") and len(scores_data.get("agents", {})) > 0:
        meta["cold_start"] = False

    agents_after = set(scores_data.get("agents", {}).keys())
    agents_updated = sorted(agents_after)

    elapsed = round(time.monotonic() - t_start, 2)

    if not dry_run:
        _save_agent_scores(kb_dir, scores_data)

    return {
        "run_id": run_id,
        "events_found": len(events),
        "deltas_emitted": len(events),
        "agents_updated": agents_updated,
        "dry_run": dry_run,
        "elapsed_seconds": elapsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Emit per-agent score deltas from a completed Echelon run."
    )
    parser.add_argument("--run-id", required=True, help="Run ID (e.g., spec-1234)")
    parser.add_argument("--runs-root", default=None,
                        help="Path to the runs root directory")
    parser.add_argument("--kb-dir", default=None,
                        help="Path to knowledge-base/ directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute deltas but do not write to agent-scores.yaml")
    args = parser.parse_args()

    # Auto-detect paths
    if args.runs_root:
        runs_root = Path(args.runs_root)
    else:
        runs_root = _default_runs_root()

    if args.kb_dir:
        kb_dir = Path(args.kb_dir)
    else:
        kb_dir = EXT_DIR / "knowledge-base"

    print(f"Emitting score deltas for run: {args.run_id}", file=sys.stderr)
    print(f"Runs root: {runs_root}", file=sys.stderr)
    print(f"KB dir: {kb_dir}", file=sys.stderr)

    report = emit_score_deltas(
        run_id=args.run_id,
        runs_root=runs_root,
        kb_dir=kb_dir,
        dry_run=args.dry_run,
    )

    print(json.dumps(report, indent=2))

    if "error" in report:
        print(f"ERROR: {report['error']}", file=sys.stderr)
        return 1

    print(
        f"Emitted {report['deltas_emitted']} deltas for "
        f"{len(report['agents_updated'])} agents "
        f"({'dry-run' if args.dry_run else 'written'})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

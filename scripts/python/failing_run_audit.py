#!/usr/bin/env python3
"""failing_run_audit.py — Failing-run gate audit (T036).

Usage:
    python failing_run_audit.py --run-id <run_id> [--runs-root <dir>]

On a failing run, asserts:
    (a) Every agent dispatched has a corresponding echelon_result journal entry
    (b) last_dispatch.post_dispatch_complete is true OR a reason is logged
    (c) No schema_invalid writes occurred

Exit codes:
    0  — All assertions pass (AUDIT_PASS)
    1  — One or more assertions failed (AUDIT_FAIL)
    64 — Usage error (missing args, directory not found)

Budget: <= 60 seconds.
Contract: read-only; does NOT dispatch any agent.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EXT_DIR = SCRIPT_DIR.parent.parent

BUDGET_SECONDS = 60


def _default_runs_root() -> Path:
    return EXT_DIR / "runs"


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_journal(run_dir: Path) -> list:
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
    state_path = run_dir / "state.json"
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _check_echelon_result_coverage(journal: list) -> dict:
    """Assertion (a): every dispatched agent has an echelon_result entry."""
    dispatched_agents = set()
    for entry in journal:
        if entry.get("type") in ("agent_dispatch", "dispatch"):
            data = entry.get("data", {})
            agent = entry.get("agent") or (data.get("agent") if isinstance(data, dict) else None)
            if agent:
                dispatched_agents.add(agent)

    result_agents = set()
    for entry in journal:
        if entry.get("type") in ("echelon_result", "agent_output"):
            data = entry.get("data", {})
            agent = entry.get("agent") or (data.get("agent") if isinstance(data, dict) else None)
            if agent:
                result_agents.add(agent)

    missing = dispatched_agents - result_agents

    if missing:
        return {
            "check": "echelon_result_coverage",
            "verdict": "FAIL",
            "dispatched_agents": sorted(dispatched_agents),
            "result_agents": sorted(result_agents),
            "missing_agents": sorted(missing),
            "detail": f"Dispatched agents without echelon_result: {sorted(missing)}",
        }
    return {
        "check": "echelon_result_coverage",
        "verdict": "PASS",
        "dispatched_agents": sorted(dispatched_agents),
        "result_agents": sorted(result_agents),
        "missing_agents": [],
        "detail": f"All {len(dispatched_agents)} dispatched agents have echelon_result entries",
    }


def _check_post_dispatch_complete(journal: list, state: dict) -> dict:
    """Assertion (b): last_dispatch.post_dispatch_complete is true OR reason is logged."""
    last_dispatch = state.get("last_dispatch", {})
    if not isinstance(last_dispatch, dict):
        last_dispatch = {}

    post_complete = last_dispatch.get("post_dispatch_complete")
    post_reason = last_dispatch.get("post_dispatch_reason")

    has_journal_post = any(
        e.get("type") in ("post_dispatch", "post_dispatch_complete")
        for e in journal
    )

    dispatched_any = any(
        e.get("type") in ("agent_dispatch", "dispatch") for e in journal
    )

    if not dispatched_any:
        return {
            "check": "post_dispatch_complete",
            "verdict": "PASS",
            "detail": "No dispatches found — vacuously passes",
        }

    if post_complete or post_reason or has_journal_post:
        return {
            "check": "post_dispatch_complete",
            "verdict": "PASS",
            "detail": (
                f"post_dispatch_complete={post_complete}, "
                f"reason={post_reason!r}, "
                f"journal_entry={has_journal_post}"
            ),
        }

    return {
        "check": "post_dispatch_complete",
        "verdict": "FAIL",
        "detail": (
            "last_dispatch.post_dispatch_complete not set, no post_dispatch_reason, "
            "and no post_dispatch journal entry found"
        ),
    }


def _check_no_schema_invalid(journal: list) -> dict:
    """Assertion (c): no schema_invalid writes occurred."""
    invalid_entries = []
    for entry in journal:
        if entry.get("type") == "schema_invalid":
            invalid_entries.append(entry.get("id", "?"))
            continue
        data = entry.get("data", {})
        if isinstance(data, dict):
            if data.get("schema_valid") is False:
                invalid_entries.append(entry.get("id", "?"))
            elif "schema_invalid" in str(data):
                invalid_entries.append(entry.get("id", "?"))

    if invalid_entries:
        return {
            "check": "no_schema_invalid_writes",
            "verdict": "FAIL",
            "invalid_entry_ids": invalid_entries,
            "detail": f"{len(invalid_entries)} schema_invalid write(s) detected: {invalid_entries}",
        }
    return {
        "check": "no_schema_invalid_writes",
        "verdict": "PASS",
        "invalid_entry_ids": [],
        "detail": "No schema_invalid entries found in journal",
    }


def run_audit(run_id: str, runs_root: Path) -> dict:
    """Run the failing-run gate audit. Returns a report dict.

    Args:
        run_id:    The run ID to audit (e.g., spec-1234)
        runs_root: Root directory containing run directories.

    Returns:
        {run_id, checked_at, overall_verdict, checks, elapsed_seconds}
    """
    t_start = time.monotonic()

    run_dir = runs_root / run_id
    if not run_dir.exists():
        return {
            "run_id": run_id,
            "error": f"run directory not found: {run_dir}",
            "overall_verdict": "AUDIT_ERROR",
            "checks": [],
            "elapsed_seconds": round(time.monotonic() - t_start, 2),
        }

    journal = _load_journal(run_dir)
    state = _load_state(run_dir)

    checks = [
        _check_echelon_result_coverage(journal),
        _check_post_dispatch_complete(journal, state),
        _check_no_schema_invalid(journal),
    ]

    all_pass = all(c["verdict"] == "PASS" for c in checks)

    elapsed = round(time.monotonic() - t_start, 2)

    return {
        "run_id": run_id,
        "checked_at": _iso_now(),
        "overall_verdict": "AUDIT_PASS" if all_pass else "AUDIT_FAIL",
        "checks": checks,
        "journal_entries_scanned": len(journal),
        "elapsed_seconds": elapsed,
        "budget_ok": elapsed <= BUDGET_SECONDS,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the failing-run gate audit for an Echelon run."
    )
    parser.add_argument("--run-id", required=True, help="Run ID (e.g., spec-1234)")
    parser.add_argument("--runs-root", default=None,
                        help="Path to the runs root directory")
    args = parser.parse_args()

    if args.runs_root:
        runs_root = Path(args.runs_root)
    else:
        runs_root = _default_runs_root()

    report = run_audit(args.run_id, runs_root)
    print(json.dumps(report, indent=2))

    if "error" in report:
        print(f"ERROR: {report['error']}", file=sys.stderr)
        return 64

    print(
        f"Audit: {report['overall_verdict']} "
        f"({report['elapsed_seconds']}s)",
        file=sys.stderr,
    )
    return 0 if report["overall_verdict"] == "AUDIT_PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

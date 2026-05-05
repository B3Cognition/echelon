#!/usr/bin/env python3
"""replay.py — Archive replay tool for Echelon state transitions.

Usage:
    python replay.py --archive <run_id> [--archive-root <root>] [--output <file>]

Reads an archived squad run, walks recorded phase transitions,
calls evaluate_transitions at each, produces a per-transition report.

Contracts:
- MUST NOT re-dispatch any agent (agent dispatch is mocked to assert-never)
- Handles truncation with truncated_at_entry_N marker
- Budget <= 60s per archive

See contracts/evaluator-contract.md § Replay contract.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Ensure kernel is importable
SCRIPT_DIR = Path(__file__).resolve().parent
EXT_DIR = SCRIPT_DIR.parent.parent
if str(EXT_DIR) not in sys.path:
    sys.path.insert(0, str(EXT_DIR))

from kernel.evaluator import PredicateNotDefined, evaluate_transitions_list
from kernel.state_loader import StateLoadError, load

# Budget: 60 seconds per archive
BUDGET_SECONDS = 60


def _load_journal(archive_dir: Path) -> list[dict]:
    """Load reasoning-journal.jsonl entries from archive."""
    journal_path = archive_dir / "reasoning-journal.jsonl"
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


def _load_state(archive_dir: Path) -> dict:
    """Load state.json from archive (permissive — archive state may be incomplete)."""
    state_path = archive_dir / "state.json"
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_config(archive_dir: Path) -> dict:
    """Try to load echelon-config.yml from archive or parent squad dir."""
    # Try YAML first — check both new (.specify/...) and legacy project-root paths
    for config_path in [
        archive_dir / ".specify" / "extensions" / "echelon" / "echelon-config.yml",
        archive_dir.parent.parent / ".specify" / "extensions" / "echelon" / "echelon-config.yml",
        archive_dir / "echelon-config.yml",
        archive_dir.parent.parent / "echelon-config.yml",
    ]:
        if config_path.exists():
            try:
                import yaml  # type: ignore
                with config_path.open(encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                if isinstance(cfg, dict):
                    return cfg
            except ImportError:
                pass  # fall through
            except Exception:
                pass

    # Return minimal config defaults
    return {
        "convergence": {
            "max_iterations": 5,
            "quality_delta_threshold": 0.02,
            "consecutive_passes_required": 2,
            "assess_defer_loop_limit": 2,
        },
        "quality_gates": {"spec": {"overall": 0.7}},
        "specialists": {"guardian_mode": "always_on"},
    }


def replay_archive(
    archive_root: Path,
    run_id: str,
    budget_seconds: float = BUDGET_SECONDS,
) -> dict[str, Any]:
    """Replay a single archived run. Returns a report dict."""
    t_start = time.monotonic()
    archive_dir = archive_root / run_id

    if not archive_dir.exists():
        return {
            "run_id": run_id,
            "error": f"archive not found: {archive_dir}",
            "transitions": [],
            "truncated": False,
            "truncated_at_entry": None,
        }

    state = _load_state(archive_dir)
    config = _load_config(archive_dir)
    journal = _load_journal(archive_dir)

    # Extract phase transitions from journal
    # A transition is any routing_decision entry with phase info
    transitions_found = [
        entry for entry in journal
        if entry.get("type") in ("routing_decision", "phase_transition")
        and isinstance(entry.get("data", {}), dict)
    ]

    report_transitions: list[dict] = []
    truncated = False
    truncated_at_entry = None  # Optional[int]

    for idx, entry in enumerate(transitions_found):
        elapsed = time.monotonic() - t_start
        if elapsed > budget_seconds:
            truncated = True
            truncated_at_entry = idx
            break

        data = entry.get("data", {})
        phase_id = entry.get("phase") or data.get("phase_id") or data.get("phase") or ""

        # Build a synthetic transitions list from the recorded decision
        last_outputs: dict = {}
        if isinstance(data.get("last_outputs"), dict):
            last_outputs = data["last_outputs"]
        elif isinstance(data.get("verdict"), str):
            last_outputs = {"verdict": data["verdict"]}

        # Try to evaluate transitions (pure function — no agent dispatch)
        eval_result: dict = {}
        error_info: str = ""

        try:
            from kernel import evaluator as _eval_mod
            # Build a minimal synthetic transitions list from the recorded decision
            next_phase = data.get("next_phase") or data.get("to")
            condition = data.get("condition") or "always"
            synthetic_transitions = [{"condition": condition, "to": next_phase or "unknown"}]

            eval_result = _eval_mod.evaluate_transitions_list(
                synthetic_transitions, state, config, last_outputs
            )
        except PredicateNotDefined as exc:
            error_info = f"PredicateNotDefined: {exc.predicate_name}"
        except Exception as exc:
            error_info = f"error: {exc}"

        report_transitions.append({
            "entry_id": entry.get("id", f"entry-{idx}"),
            "phase_id": phase_id,
            "condition_recorded": data.get("condition", ""),
            "decision_recorded": data.get("decision", ""),
            "guard_result": eval_result.get("guard_result", "N/A"),
            "matched_transition_index": eval_result.get("matched_transition_index"),
            "trace": eval_result.get("trace", []),
            "error": error_info or None,
        })

    elapsed = time.monotonic() - t_start
    return {
        "run_id": run_id,
        "archive_dir": str(archive_dir),
        "journal_entries_total": len(journal),
        "transitions_evaluated": len(report_transitions),
        "truncated": truncated,
        "truncated_at_entry": truncated_at_entry if truncated else None,
        "elapsed_seconds": round(elapsed, 2),
        "budget_seconds": budget_seconds,
        "transitions": report_transitions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay an archived Echelon run and report per-transition evaluation."
    )
    parser.add_argument("--archive", required=True, help="Run ID to replay")
    parser.add_argument("--archive-root", default=None, help="Root directory for archives")
    parser.add_argument("--output", default=None, help="Output file (default: stdout)")
    parser.add_argument("--budget", type=float, default=BUDGET_SECONDS, help="Time budget in seconds")
    args = parser.parse_args()

    # Auto-detect archive root
    if args.archive_root:
        archive_root = Path(args.archive_root)
    else:
        script_dir = Path(__file__).resolve().parent
        ext_dir = script_dir.parent.parent
        archive_root = ext_dir.parent.parent / ".specify" / "squad" / "archive"
        if not archive_root.exists():
            archive_root = ext_dir.parent.parent / "archive"

    print(f"Replaying archive: {archive_root / args.archive}", file=sys.stderr)

    report = replay_archive(archive_root, args.archive, budget_seconds=args.budget)

    output_text = json.dumps(report, indent=2, default=str)

    if args.output:
        Path(args.output).write_text(output_text + "\n", encoding="utf-8")
        print(f"Report written to: {args.output}", file=sys.stderr)
    else:
        print(output_text)

    # Print summary
    truncated_msg = ""
    if report.get("truncated"):
        truncated_msg = f" [TRUNCATED at entry {report['truncated_at_entry']}]"

    print(
        f"Evaluated {report['transitions_evaluated']} transitions "
        f"in {report['elapsed_seconds']}s{truncated_msg}",
        file=sys.stderr
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())

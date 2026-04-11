#!/usr/bin/env python3
"""seed_from_archive.py — Produce KB YAML files from an archived squad run.

Usage:
    python seed_from_archive.py --archive <run_id> [--kb-dir <kb_dir>] [--archive-root <root>]

Reads:
    <archive_root>/<run_id>/reasoning-journal.jsonl
    <archive_root>/<run_id>/state.json

Produces 5 KB YAML files in <kb_dir>:
    calibration-profile.yaml
    estimates-log.yaml
    patterns.yaml
    pitfalls.yaml
    agent-scores.yaml

Also derives:
    confidence-thresholds.yaml (from calibration-profile + agent-scores)

Budget: ≤ 180s per archive.
Dependencies: stdlib + PyYAML only.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_yaml_stub(path: Path, content: str) -> None:
    """Write YAML content to path, backing up any existing file first."""
    backup_dir = path.parent / ".backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    if path.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / f"{path.name}.{ts}.bak"
        import shutil
        shutil.copy2(path, backup_path)
    path.write_text(content, encoding="utf-8")


def _try_yaml_dump(data: Any) -> str:
    """Attempt YAML dump; fall back to JSON if PyYAML unavailable."""
    try:
        import yaml  # type: ignore
        return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except ImportError:
        # Minimal safe fallback: write as YAML-compatible format
        lines = []
        def _dump_val(v: Any, indent: int = 0) -> str:
            pad = "  " * indent
            if v is None:
                return "null"
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, (int, float)):
                return str(v)
            if isinstance(v, str):
                if any(c in v for c in ":#{}[]|>&*!,?"):
                    return f'"{v}"'
                return v
            if isinstance(v, list):
                if not v:
                    return "[]"
                items = []
                for item in v:
                    items.append(f"{pad}- {_dump_val(item, indent)}")
                return "\n" + "\n".join(items)
            if isinstance(v, dict):
                if not v:
                    return "{}"
                pairs = []
                for k, val in v.items():
                    dumped = _dump_val(val, indent + 1)
                    if "\n" in dumped:
                        pairs.append(f"{pad}  {k}:{dumped}")
                    else:
                        pairs.append(f"{pad}  {k}: {dumped}")
                return "\n" + "\n".join(pairs)
            return str(v)
        for k, v in data.items():
            dumped = _dump_val(v, 1)
            if "\n" in dumped:
                lines.append(f"{k}:{dumped}")
            else:
                lines.append(f"{k}: {dumped}")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Archive reading
# ---------------------------------------------------------------------------

def read_archive(archive_root: Path, run_id: str) -> tuple[dict, list[dict]]:
    """Read state.json and reasoning-journal.jsonl from archive."""
    arc_dir = archive_root / run_id
    if not arc_dir.exists():
        raise FileNotFoundError(f"Archive not found: {arc_dir}")

    state_path = arc_dir / "state.json"
    journal_path = arc_dir / "reasoning-journal.jsonl"

    state: dict = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))

    journal: list[dict] = []
    if journal_path.exists():
        for line in journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    journal.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # skip malformed lines

    return state, journal


# ---------------------------------------------------------------------------
# KB file generators
# ---------------------------------------------------------------------------

def build_calibration_profile(state: dict, journal: list[dict], run_id: str) -> dict:
    """Build calibration-profile.yaml content."""
    quality_scores = state.get("quality_scores", [])
    iterations = len(quality_scores)

    # Extract per-domain quality from scores
    convergence_declared = False
    if quality_scores:
        last = quality_scores[-1]
        convergence_declared = bool(last.get("convergence_declared", False))

    # Extract dispatch counters for agent-level data
    dispatch_counters = state.get("dispatch_counters", {})

    # Build minimal domains from what we know
    domains: dict = {}
    for agent, count in dispatch_counters.items():
        domains[agent.lower()] = {
            "accuracy": 0.7,  # cold-start default
            "correction_factor": 1.0,
            "sample_size": 1,
            "run_type": "validation_run",
            "dispatch_count": count,
            "confidence_level": "LOW"
        }

    return {
        "schema_version": 1,
        "source_run_id": run_id,
        "provenance_timestamp": iso_now(),
        "meta": {
            "cold_start": True,
            "total_runs": 1,
            "first_run_id": run_id,
            "last_updated": iso_now(),
            "generated_by": "seed_from_archive.py"
        },
        "runs": [
            {
                "run_id": run_id,
                "run_type": "validation_run",
                "spec": state.get("spec_id", "unknown"),
                "date": iso_now()[:10],
                "total_iterations": iterations,
                "convergence_declared": convergence_declared,
                "quality_scores": {
                    f"iteration_{i}": score
                    for i, score in enumerate(quality_scores)
                }
            }
        ],
        "confidence_policy": {
            "min_samples_for_correction": 3,
            "cold_start_accuracy": 0.7,
            "cold_start_label": "insufficient data"
        },
        "last_updated": iso_now(),
        "domains": domains
    }


def build_estimates_log(state: dict, journal: list[dict], run_id: str) -> dict:
    """Build estimates-log.yaml content."""
    entries = []
    token_usage = state.get("token_usage", 0)
    if token_usage:
        entries.append({
            "run_id": run_id,
            "date": iso_now()[:10],
            "phase": state.get("phase", "unknown"),
            "predicted_tokens": None,
            "actual_tokens": token_usage,
            "ratio": None,
            "note": "First run — no predicted baseline"
        })

    return {
        "schema_version": 1,
        "source_run_id": run_id,
        "provenance_timestamp": iso_now(),
        "append_only": True,
        "entries": entries
    }


def build_patterns(state: dict, journal: list[dict], run_id: str) -> dict:
    """Build patterns.yaml content — extract from journal routing decisions."""
    patterns = []
    seen: set = set()

    for entry in journal:
        entry_type = entry.get("type", "")
        if entry_type in ("routing_decision", "quality_check"):
            data = entry.get("data", {})
            decision = str(data.get("decision", ""))
            if decision and decision not in seen:
                seen.add(decision)
                patterns.append({
                    "id": f"PAT-{len(patterns)+1:03d}",
                    "source_run": run_id,
                    "agent": entry.get("agent", "COMMANDER"),
                    "context": decision[:200],
                    "confidence": "LOW",
                    "reinforced": 1
                })

    return {
        "schema_version": 1,
        "source_run_id": run_id,
        "provenance_timestamp": iso_now(),
        "entries": patterns[:20]  # cap at 20 for cold start
    }


def build_pitfalls(state: dict, journal: list[dict], run_id: str) -> dict:
    """Build pitfalls.yaml content — extract from issues_log and journal failures."""
    pitfalls = []
    issues = state.get("issues_log", [])

    for issue in issues:
        pitfalls.append({
            "id": f"PIT-{len(pitfalls)+1:03d}",
            "source_run": run_id,
            "source_issue": issue.get("id", ""),
            "severity": issue.get("severity", "MEDIUM"),
            "description": issue.get("description", "")[:300],
            "agent": issue.get("source", "unknown"),
            "resolved": issue.get("resolved", False),
            "mitigation": None
        })

    # Also check journal for FAIL verdicts
    for entry in journal:
        data = entry.get("data", {})
        if data.get("verdict") == "FAIL" or data.get("severity") == "CRITICAL":
            desc = str(data.get("description", data.get("decision", "")))[:300]
            if desc:
                pitfalls.append({
                    "id": f"PIT-{len(pitfalls)+1:03d}",
                    "source_run": run_id,
                    "source_journal_entry": entry.get("id", ""),
                    "severity": data.get("severity", "HIGH"),
                    "description": desc,
                    "agent": entry.get("agent", "unknown"),
                    "mitigation": None
                })

    return {
        "schema_version": 1,
        "source_run_id": run_id,
        "provenance_timestamp": iso_now(),
        "entries": pitfalls[:30]  # cap at 30 for cold start
    }


def build_agent_scores(state: dict, journal: list[dict], run_id: str) -> dict:
    """Build agent-scores.yaml content."""
    agent_scores = state.get("agent_scores", [])
    dispatch_counters = state.get("dispatch_counters", {})

    leaderboard = []
    for rank, score_entry in enumerate(agent_scores, 1):
        leaderboard.append({
            "rank": rank,
            "agent": score_entry.get("agent", ""),
            "current_run_score": score_entry.get("points", 0),
            "lifetime_score": score_entry.get("points", 0),
            "badges": [],
            "dispatch_count": dispatch_counters.get(score_entry.get("agent", ""), 0),
            "note": score_entry.get("reason", "")
        })

    return {
        "schema_version": 1,
        "source_run_id": run_id,
        "provenance_timestamp": iso_now(),
        "meta": {
            "cold_start": True,
            "total_runs": 1,
            "first_run_id": run_id,
            "last_updated": iso_now(),
            "generated_by": "seed_from_archive.py"
        },
        "leaderboard": leaderboard,
        "dispatch_counters": dispatch_counters
    }


def derive_confidence_thresholds(calibration: dict, agent_scores: dict, run_id: str) -> dict:
    """Derive confidence-thresholds.yaml from calibration + agent-scores."""
    domains: dict = {}
    cal_domains = calibration.get("domains", {})
    for domain_name, domain_data in cal_domains.items():
        if isinstance(domain_data, dict):
            domains[domain_name] = {
                "confidence_floor": domain_data.get("accuracy", 0.5),
                "correction_factor": domain_data.get("correction_factor", 1.0),
                "sample_size": domain_data.get("sample_size", 0),
                "confidence_sa": None,
                "confidence_brier": None,
                "confidence_ecc": None
            }

    return {
        "schema_version": 1,
        "source_run_id": run_id,
        "provenance_timestamp": iso_now(),
        "note": "Derived from calibration-profile.yaml + agent-scores.yaml at seed time.",
        "domains": domains
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Produce KB YAML files from an archived squad run."
    )
    parser.add_argument("--archive", required=True, help="Run ID to read from archive")
    parser.add_argument("--kb-dir", default=None, help="Target KB directory (default: auto-detect)")
    parser.add_argument(
        "--archive-root",
        default=None,
        help="Root directory containing archive/<run_id>/ (default: auto-detect)"
    )
    args = parser.parse_args()

    t_start = time.monotonic()
    run_id = args.archive

    # Auto-detect paths
    script_dir = Path(__file__).resolve().parent
    ext_dir = script_dir.parent.parent  # .specify/extensions/echelon

    if args.archive_root:
        archive_root = Path(args.archive_root)
    else:
        # Try .specify/squad/archive relative to extension root
        archive_root = ext_dir.parent.parent / ".specify" / "squad" / "archive"
        if not archive_root.exists():
            # Try relative to repo root
            archive_root = ext_dir.parent.parent / "archive"

    if args.kb_dir:
        kb_dir = Path(args.kb_dir)
    else:
        kb_dir = ext_dir / "knowledge-base"

    kb_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading archive: {archive_root / run_id}", file=sys.stderr)
    print(f"Writing KB to:   {kb_dir}", file=sys.stderr)

    state, journal = read_archive(archive_root, run_id)

    # Build all 5 KB files
    calibration = build_calibration_profile(state, journal, run_id)
    estimates = build_estimates_log(state, journal, run_id)
    patterns = build_patterns(state, journal, run_id)
    pitfalls = build_pitfalls(state, journal, run_id)
    agent_scores = build_agent_scores(state, journal, run_id)
    thresholds = derive_confidence_thresholds(calibration, agent_scores, run_id)

    files = {
        "calibration-profile.yaml": calibration,
        "estimates-log.yaml": estimates,
        "patterns.yaml": patterns,
        "pitfalls.yaml": pitfalls,
        "agent-scores.yaml": agent_scores,
        "confidence-thresholds.yaml": thresholds,
    }

    for filename, data in files.items():
        out_path = kb_dir / filename
        header = (
            f"# {filename} — generated by seed_from_archive.py\n"
            f"# source_run_id: {run_id}\n"
            f"# provenance_timestamp: {iso_now()}\n"
        )
        content = header + _try_yaml_dump(data)
        write_yaml_stub(out_path, content)
        print(f"  wrote: {out_path}", file=sys.stderr)

    elapsed = time.monotonic() - t_start
    print(f"Done in {elapsed:.1f}s", file=sys.stderr)

    if elapsed > 180:
        print(f"WARNING: elapsed {elapsed:.1f}s exceeds 180s budget", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""detect_patterns.py — Pattern detection from journal entries and issue log.

Usage:
    python detect_patterns.py --run-id <run_id> [--squad-dir <dir>] [--kb-dir <dir>] [--dry-run]

Walks journal entries + issues_log; looks for matches against pitfall patterns
in patterns.yaml. Appends new patterns and increments reuse_counter for matches.

Contracts:
- Matches existing pattern → increments reuse_counter
- New pattern detected → appended to patterns.yaml
- Does NOT re-dispatch any agent (pure read + write, no LLM calls)
- Budget <= 60s
- Requires no external dependencies beyond stdlib
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


def _load_yaml_list(path: Path) -> list:
    """Load a YAML file that is expected to be a list at top level."""
    if not path.exists():
        return []
    try:
        import yaml  # type: ignore
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, list):
            return data
        return []
    except ImportError:
        return []
    except Exception:
        return []


def _save_yaml_list(path: Path, data: list) -> None:
    """Save a list to YAML file."""
    try:
        import yaml  # type: ignore
        content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        path.write_text(content, encoding="utf-8")
    except ImportError:
        # Fallback: write as JSON
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _next_pattern_id(existing: list) -> str:
    """Generate next PAT-NNN id."""
    ids = []
    for p in existing:
        pid = p.get("id", "")
        if pid.startswith("PAT-"):
            try:
                ids.append(int(pid[4:]))
            except ValueError:
                pass
    n = max(ids) + 1 if ids else 1
    return f"PAT-{n:03d}"


def _collect_signals(journal: list, issues_log: list) -> list:
    """Collect text signals from journal + issues for pattern matching.

    Returns list of {text, source} dicts.
    """
    signals = []

    for entry in journal:
        data = entry.get("data", {})
        if not isinstance(data, dict):
            continue
        # Collect reason, message, failure fields
        for key in ("reason", "message", "failure", "failure_mode", "detected_cause", "detail"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                signals.append({
                    "text": val.lower(),
                    "source": f"journal:{entry.get('id', '?')}:{key}",
                    "entry_type": entry.get("type", ""),
                })
        # Collect stderr_excerpt
        se = data.get("stderr_excerpt", "")
        if isinstance(se, str) and se.strip():
            signals.append({
                "text": se.lower(),
                "source": f"journal:{entry.get('id', '?')}:stderr",
                "entry_type": entry.get("type", ""),
            })

    for issue in issues_log:
        if isinstance(issue, dict):
            for key in ("message", "detail", "description", "reason"):
                val = issue.get(key)
                if isinstance(val, str) and val.strip():
                    signals.append({
                        "text": val.lower(),
                        "source": f"issue:{issue.get('id', '?')}:{key}",
                        "entry_type": "issue",
                    })

    return signals


def _tags_overlap(pattern_tags: list, signal_text: str) -> bool:
    """Check if any pattern tags appear in the signal text."""
    for tag in pattern_tags:
        normalized = tag.lower().replace("-", " ").replace("_", " ")
        if normalized in signal_text or tag.lower() in signal_text:
            return True
    return False


def _match_pattern(pattern: dict, signals: list) -> bool:
    """Return True if the pattern matches any signal.

    Matching strategy: tag overlap (any pattern tag appears in signal text)
    OR pattern name keywords appear in signal text.
    """
    tags = pattern.get("tags", [])
    name_words = [
        w.lower() for w in pattern.get("name", "").split()
        if len(w) > 4  # skip short words
    ]

    for signal in signals:
        text = signal["text"]
        # Tag overlap
        if _tags_overlap(tags, text):
            return True
        # Name keyword match (>= 2 keywords)
        matches = sum(1 for w in name_words if w in text)
        if matches >= 2:
            return True

    return False


def detect_patterns(
    run_id: str,
    squad_dir: Path,
    kb_dir: Path,
    dry_run: bool = False,
) -> dict:
    """Detect patterns from a completed run. Returns a report dict.

    Args:
        run_id:    The completed run ID (e.g., squad-1234)
        squad_dir: Root of .specify/squad/
        kb_dir:    Path to knowledge-base/
        dry_run:   If True, do not write to patterns.yaml

    Returns:
        {run_id, patterns_matched, reuse_counters_incremented,
         new_patterns_appended, dry_run, elapsed_seconds}
    """
    t_start = time.monotonic()

    run_dir = squad_dir / run_id
    if not run_dir.exists():
        return {
            "run_id": run_id,
            "error": f"run directory not found: {run_dir}",
            "patterns_matched": [],
            "reuse_counters_incremented": 0,
            "new_patterns_appended": 0,
            "dry_run": dry_run,
            "elapsed_seconds": round(time.monotonic() - t_start, 2),
        }

    journal = _load_journal(run_dir)
    state = _load_state(run_dir)
    issues_log = state.get("issues_log", [])
    if not isinstance(issues_log, list):
        issues_log = []

    patterns = _load_yaml_list(kb_dir / "patterns.yaml")
    pitfalls = _load_yaml_list(kb_dir / "pitfalls.yaml")

    # Collect signals from journal + issues
    signals = _collect_signals(journal, issues_log)

    # Match patterns and pitfalls
    matched_pattern_ids = []
    reuse_increments = 0

    for pattern in patterns:
        if time.monotonic() - t_start > BUDGET_SECONDS:
            break
        if _match_pattern(pattern, signals):
            matched_pattern_ids.append(pattern.get("id", "?"))
            # Increment reuse_counter
            pattern["reuse_counter"] = pattern.get("reuse_counter", 0) + 1
            pattern["last_seen_run"] = run_id
            reuse_increments += 1

    # Match pitfalls — if matched, promote to pattern (append as new if not exists)
    new_pattern_ids = []
    for pitfall in pitfalls:
        if time.monotonic() - t_start > BUDGET_SECONDS:
            break
        if not _match_pattern(pitfall, signals):
            continue

        # Check if this pitfall already has a corresponding pattern
        pit_id = pitfall.get("id", "?")
        already_has_pattern = any(
            p.get("source_pitfall") == pit_id
            for p in patterns
        )
        if already_has_pattern:
            # Already promoted — just increment reuse
            for p in patterns:
                if p.get("source_pitfall") == pit_id:
                    p["reuse_counter"] = p.get("reuse_counter", 0) + 1
                    p["last_seen_run"] = run_id
                    reuse_increments += 1
                    matched_pattern_ids.append(p.get("id", "?"))
            continue

        # Promote pitfall to pattern
        new_id = _next_pattern_id(patterns)
        new_pattern = {
            "id": new_id,
            "name": pitfall.get("name", f"Pattern from {pit_id}"),
            "domain": pitfall.get("domain", "unknown"),
            "evidence_grade": "D",  # Initially D (journal analysis)
            "source": f"promoted-from-pitfall:{pit_id}, run:{run_id}",
            "source_pitfall": pit_id,
            "validated_by_feedback": False,
            "confidence": pitfall.get("confidence", 0.60),
            "description": pitfall.get("avoidance", pitfall.get("trigger", "")),
            "tags": pitfall.get("tags", []),
            "status": "active",
            "project_fingerprint": "000000000000",
            "scope": "local_only",
            "reuse_counter": 1,
            "last_seen_run": run_id,
        }
        patterns.append(new_pattern)
        new_pattern_ids.append(new_id)

    elapsed = round(time.monotonic() - t_start, 2)

    if not dry_run and (reuse_increments > 0 or new_pattern_ids):
        _save_yaml_list(kb_dir / "patterns.yaml", patterns)

    return {
        "run_id": run_id,
        "signals_extracted": len(signals),
        "patterns_matched": matched_pattern_ids,
        "reuse_counters_incremented": reuse_increments,
        "new_patterns_appended": len(new_pattern_ids),
        "new_pattern_ids": new_pattern_ids,
        "dry_run": dry_run,
        "elapsed_seconds": elapsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect patterns from a completed Echelon run."
    )
    parser.add_argument("--run-id", required=True, help="Run ID (e.g., squad-1234)")
    parser.add_argument("--squad-dir", default=None,
                        help="Path to .specify/squad/ directory")
    parser.add_argument("--kb-dir", default=None,
                        help="Path to knowledge-base/ directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect patterns but do not write to patterns.yaml")
    args = parser.parse_args()

    if args.squad_dir:
        squad_dir = Path(args.squad_dir)
    else:
        squad_dir = EXT_DIR.parent.parent / ".specify" / "squad"

    if args.kb_dir:
        kb_dir = Path(args.kb_dir)
    else:
        kb_dir = EXT_DIR / "knowledge-base"

    print(f"Detecting patterns for run: {args.run_id}", file=sys.stderr)

    report = detect_patterns(
        run_id=args.run_id,
        squad_dir=squad_dir,
        kb_dir=kb_dir,
        dry_run=args.dry_run,
    )

    print(json.dumps(report, indent=2))

    if "error" in report:
        print(f"ERROR: {report['error']}", file=sys.stderr)
        return 1

    print(
        f"Matched {len(report['patterns_matched'])} patterns, "
        f"incremented {report['reuse_counters_incremented']} reuse_counters, "
        f"appended {report['new_patterns_appended']} new patterns "
        f"({'dry-run' if args.dry_run else 'written'})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

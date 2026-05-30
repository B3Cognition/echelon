#!/usr/bin/env python3
"""
token-logger.py — Echelon Pipeline Token Usage Logger

Reads a reasoning-journal.jsonl (and optionally state.json) produced by a
spec-kit / Echelon squad run, extracts per-invocation token counts, computes
per-agent-type summary statistics, and writes a machine-readable
token-baseline.json artifact plus a human-readable Markdown summary.

When no live token fields are present in journal entries the script falls back
to a word-count × 1.3 heuristic and marks each affected invocation as
``estimated: true``.  The top-level ``collection_method`` is set to
``live_instrumentation`` when at least one real token field was found,
otherwise ``post_hoc_estimation``.

Usage:
    python3 scripts/token-logger.py \\
        --journal .specify/squad/staging/reasoning-journal.jsonl \\
        [--state   .specify/squad/state.json] \\
        [--output  .specify/squad/token-baseline.json] \\
        [--spec-runs <dir-containing-multiple-run-dirs>]

Dependencies: stdlib only (json, pathlib, argparse, statistics, datetime)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"

# Heuristic: average English words → tokens ratio used when no live data exists
WORDS_TO_TOKENS_RATIO = 1.3

# Fields searched (in priority order) for real token usage in journal entries
PROMPT_TOKEN_FIELDS = ("prompt_tokens", "input_tokens", "tokens_prompt")
COMPLETION_TOKEN_FIELDS = ("completion_tokens", "output_tokens", "tokens_completion")
TOTAL_TOKEN_FIELDS = ("total_tokens", "tokens_used", "token_count")

# Fields that indicate a nested usage object (e.g. {"usage": {"total_tokens": N}})
USAGE_OBJECT_FIELDS = ("usage", "token_usage", "llm_usage")


# ---------------------------------------------------------------------------
# Token extraction helpers
# ---------------------------------------------------------------------------


def _get_nested(entry: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    """Return the first integer value found at any of *keys* in *entry*."""
    for k in keys:
        v = entry.get(k)
        if isinstance(v, int) and v >= 0:
            return v
        if isinstance(v, float) and v >= 0:
            return int(v)
    return None


def _extract_from_usage_object(entry: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    """
    Check for a nested usage sub-object and pull prompt/completion/total from it.
    Returns (prompt, completion, total) — any may be None.
    """
    for field in USAGE_OBJECT_FIELDS:
        obj = entry.get(field)
        if isinstance(obj, dict):
            prompt = _get_nested(obj, PROMPT_TOKEN_FIELDS)
            completion = _get_nested(obj, COMPLETION_TOKEN_FIELDS)
            total = _get_nested(obj, TOTAL_TOKEN_FIELDS)
            if any(v is not None for v in (prompt, completion, total)):
                return prompt, completion, total
    return None, None, None


def _word_count(entry: dict[str, Any]) -> int:
    """Estimate word count from all string values in *entry* (shallow pass)."""
    parts: list[str] = []
    for v in entry.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(str(i) for i in v if isinstance(i, str))
    return len(" ".join(parts).split())


def extract_tokens(entry: dict[str, Any]) -> tuple[int, int, int, bool]:
    """
    Extract (prompt_tokens, completion_tokens, total_tokens, estimated) from
    a single journal entry.

    Priority:
    1. Top-level token fields
    2. Nested usage object
    3. Heuristic fallback (estimated=True)
    """
    # --- Top-level fields ---
    prompt = _get_nested(entry, PROMPT_TOKEN_FIELDS)
    completion = _get_nested(entry, COMPLETION_TOKEN_FIELDS)
    total = _get_nested(entry, TOTAL_TOKEN_FIELDS)

    # --- Nested usage object (if top-level had nothing) ---
    if prompt is None and completion is None and total is None:
        prompt, completion, total = _extract_from_usage_object(entry)

    # --- If we have any real data, fill in gaps ---
    if any(v is not None for v in (prompt, completion, total)):
        prompt = prompt or 0
        completion = completion or 0
        if total is None:
            total = prompt + completion
        return prompt, completion, total, False

    # --- Heuristic fallback ---
    words = _word_count(entry)
    estimated_total = max(1, int(words * WORDS_TO_TOKENS_RATIO))
    # Split 70/30 as a rough prompt/completion ratio
    estimated_prompt = int(estimated_total * 0.7)
    estimated_completion = estimated_total - estimated_prompt
    return estimated_prompt, estimated_completion, estimated_total, True


# ---------------------------------------------------------------------------
# Journal parsing
# ---------------------------------------------------------------------------


def load_journal(journal_path: Path) -> list[dict[str, Any]]:
    """
    Load and return a list of journal entries from *journal_path*.

    Raises FileNotFoundError / json.JSONDecodeError on bad input.
    """
    if not journal_path.exists():
        raise FileNotFoundError(f"Journal file not found: {journal_path}")
    raw = journal_path.read_text(encoding="utf-8")
    stripped = raw.strip()
    if not stripped:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        entries = []
        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise json.JSONDecodeError(
                    f"Invalid JSONL entry on line {line_number}: {exc.msg}",
                    exc.doc,
                    exc.pos,
                ) from exc
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Unexpected JSONL entry in {journal_path} on line {line_number}: "
                    f"{type(entry)}"
                )
            entries.append(entry)
        return entries
    else:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Some formats wrap entries under a key
            for key in ("entries", "journal", "invocations", "events"):
                if isinstance(data.get(key), list):
                    return data[key]
            # Treat dict itself as a single entry
            return [data]
        raise ValueError(f"Unexpected journal format in {journal_path}: {type(data)}")


def parse_journal(
    entries: list[dict[str, Any]],
    codebase_id: str = "unknown",
    spec_run_id: str = "unknown",
) -> tuple[list[dict[str, Any]], bool]:
    """
    Convert raw journal *entries* into invocation records.

    Returns (invocations, any_live_data_found).

    Invocation record schema (AC-003-001 required fields):
    {
        "agent": str,
        "phase": str,
        "prompt_tokens": int,
        "completion_tokens": int,
        "total_tokens": int,
        "estimated": bool,
        "timestamp": str,  # ISO-8601
        "codebase_id": str,
        "spec_run_id": str
    }
    """
    invocations: list[dict[str, Any]] = []
    any_live = False

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        agent: str = (
            entry.get("agent")
            or entry.get("agent_codename")
            or entry.get("role")
            or "UNKNOWN"
        )
        phase: str = (
            entry.get("phase")
            or entry.get("step")
            or entry.get("stage")
            or "unknown"
        )
        timestamp: str = (
            entry.get("timestamp")
            or entry.get("ts")
            or datetime.now(timezone.utc).isoformat()
        )

        prompt_t, completion_t, total_t, estimated = extract_tokens(entry)
        if not estimated:
            any_live = True

        invocations.append(
            {
                "agent": str(agent).upper(),
                "phase": str(phase),
                "prompt_tokens": prompt_t,
                "completion_tokens": completion_t,
                "total_tokens": total_t,
                "estimated": estimated,
                "timestamp": timestamp,
                "codebase_id": codebase_id,
                "spec_run_id": spec_run_id,
            }
        )

    return invocations, any_live


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def compute_per_agent_stats(
    invocations: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Group invocations by agent and compute mean, median, p90, count of
    total_tokens.
    """
    groups: dict[str, list[int]] = {}
    for inv in invocations:
        agent = inv["agent"]
        groups.setdefault(agent, []).append(inv["total_tokens"])

    result: dict[str, dict[str, Any]] = {}
    for agent, totals in sorted(groups.items()):
        count = len(totals)
        mean = statistics.mean(totals) if totals else 0.0
        median = statistics.median(totals) if totals else 0.0
        # 90th percentile — manual since statistics.quantiles requires Python 3.8+
        # and we want consistent behaviour
        sorted_totals = sorted(totals)
        if count == 1:
            p90 = sorted_totals[0]
        else:
            idx = (count - 1) * 0.9
            lower = int(idx)
            upper = lower + 1
            frac = idx - lower
            p90 = (
                sorted_totals[lower] + frac * (sorted_totals[upper] - sorted_totals[lower])
                if upper < count
                else sorted_totals[lower]
            )
        result[agent] = {
            "mean": round(mean, 2),
            "median": round(float(median), 2),
            "p90": round(float(p90), 2),
            "count": count,
        }
    return result


def compute_pipeline_total(
    invocations: list[dict[str, Any]],
) -> dict[str, int]:
    """Sum prompt, completion, total tokens across all invocations."""
    return {
        "prompt_tokens": sum(i["prompt_tokens"] for i in invocations),
        "completion_tokens": sum(i["completion_tokens"] for i in invocations),
        "total_tokens": sum(i["total_tokens"] for i in invocations),
    }


# ---------------------------------------------------------------------------
# Artifact assembly
# ---------------------------------------------------------------------------


def build_artifact(
    run_id: str,
    invocations: list[dict[str, Any]],
    any_live: bool,
    codebase_id: str = "unknown",
) -> dict[str, Any]:
    """Assemble the full token-baseline.json structure."""
    collection_method = "live_instrumentation" if any_live else "post_hoc_estimation"
    return {
        "run_id": run_id,
        "codebase_id": codebase_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "collection_method": collection_method,
        "invocations": invocations,
        "per_agent_type": compute_per_agent_stats(invocations),
        "pipeline_total": compute_pipeline_total(invocations),
    }


# ---------------------------------------------------------------------------
# Markdown summary
# ---------------------------------------------------------------------------


def render_markdown_summary(artifact: dict[str, Any]) -> str:
    """Render a human-readable Markdown summary of the token baseline."""
    lines: list[str] = [
        "# Token Baseline Summary",
        "",
        f"**Run ID**: `{artifact['run_id']}`  ",
        f"**Generated**: {artifact['generated_at']}  ",
        f"**Collection method**: `{artifact['collection_method']}`  ",
        f"**Total invocations**: {len(artifact['invocations'])}",
        "",
        "## Pipeline Totals",
        "",
        "| Metric | Tokens |",
        "|--------|--------|",
        f"| Prompt tokens | {artifact['pipeline_total']['prompt_tokens']:,} |",
        f"| Completion tokens | {artifact['pipeline_total']['completion_tokens']:,} |",
        f"| **Total tokens** | **{artifact['pipeline_total']['total_tokens']:,}** |",
        "",
        "## Per-Agent-Type Summary",
        "",
        "| Agent | Count | Mean | Median | P90 |",
        "|-------|-------|------|--------|-----|",
    ]
    for agent, stats in artifact["per_agent_type"].items():
        lines.append(
            f"| {agent} | {stats['count']} | {stats['mean']:,.1f} "
            f"| {stats['median']:,.1f} | {stats['p90']:,.1f} |"
        )

    lines += [
        "",
        "## Invocations",
        "",
        "| # | Agent | Phase | Prompt | Completion | Total | Est? | Timestamp |",
        "|---|-------|-------|--------|------------|-------|------|-----------|",
    ]
    for i, inv in enumerate(artifact["invocations"], start=1):
        est_flag = "yes" if inv["estimated"] else "no"
        lines.append(
            f"| {i} | {inv['agent']} | {inv['phase']} "
            f"| {inv['prompt_tokens']:,} | {inv['completion_tokens']:,} "
            f"| {inv['total_tokens']:,} | {est_flag} | {inv['timestamp']} |"
        )

    lines += ["", "---", f"*Generated by token-logger.py v{VERSION}*", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Multi-run aggregation
# ---------------------------------------------------------------------------


def aggregate_spec_runs(
    spec_runs_dir: Path,
    codebase_id: str = "unknown",
) -> tuple[list[dict[str, Any]], bool, str]:
    """
    Scan *spec_runs_dir* for reasoning-journal.jsonl files (one level deep or
    under a ``staging/`` subdirectory).  Aggregate all invocations across runs.

    Returns (all_invocations, any_live_data_found, run_ids_summary).
    """
    patterns = [
        "*/reasoning-journal.jsonl",
        "*/staging/reasoning-journal.jsonl",
        "reasoning-journal.jsonl",
    ]
    found_journals: list[Path] = []
    for pattern in patterns:
        found_journals.extend(spec_runs_dir.glob(pattern))

    if not found_journals:
        print(
            f"WARNING: No reasoning-journal.jsonl files found under {spec_runs_dir}",
            file=sys.stderr,
        )
        return [], False, "no-runs"

    all_invocations: list[dict[str, Any]] = []
    any_live = False
    run_ids: list[str] = []

    for journal_path in sorted(set(found_journals)):
        try:
            entries = load_journal(journal_path)
            per_run_id = journal_path.parent.name
            invocations, live = parse_journal(
                entries,
                codebase_id=codebase_id,
                spec_run_id=per_run_id,
            )
            all_invocations.extend(invocations)
            if live:
                any_live = True
            run_ids.append(per_run_id)
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
            print(f"WARNING: Skipping {journal_path}: {exc}", file=sys.stderr)

    return all_invocations, any_live, ",".join(run_ids)


# ---------------------------------------------------------------------------
# State file helpers
# ---------------------------------------------------------------------------


def read_run_id(state_path: Path) -> str:
    """
    Read run_id from state.json.  Returns a fallback string if the file is
    missing or malformed.
    """
    if not state_path.exists():
        return "unknown-run"
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return str(data.get("run_id") or data.get("id") or "unknown-run")
    except (json.JSONDecodeError, OSError):
        return "unknown-run"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Instrument the Echelon pipeline to log per-agent-invocation token "
            "counts from reasoning-journal.jsonl entries."
        )
    )
    parser.add_argument(
        "--journal",
        metavar="FILE",
        default=None,
        help="Path to reasoning-journal.jsonl (default: .specify/squad/staging/reasoning-journal.jsonl)",
    )
    parser.add_argument(
        "--state",
        metavar="FILE",
        help="Path to state.json for run_id (default: .specify/squad/state.json)",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        default=".specify/squad/token-baseline.json",
        help="Output JSON artifact path (default: .specify/squad/token-baseline.json)",
    )
    parser.add_argument(
        "--spec-runs",
        metavar="DIR",
        help="Scan a directory of spec run folders and aggregate all journals",
    )
    parser.add_argument(
        "--markdown",
        metavar="FILE",
        help="Write Markdown summary to FILE (default: stdout)",
    )
    parser.add_argument(
        "--codebase-id",
        metavar="ID",
        default="unknown",
        help="Codebase identifier to embed in the artifact and each invocation (default: unknown)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"token-logger.py {VERSION}",
    )
    args = parser.parse_args()

    # ── Resolve paths ──────────────────────────────────────────────────────
    default_journal = Path(".specify/squad/staging/reasoning-journal.jsonl")
    default_state = Path(".specify/squad/state.json")

    journal_path: Path | None = Path(args.journal) if args.journal else None
    state_path: Path = Path(args.state) if args.state else default_state
    output_path: Path = Path(args.output)
    spec_runs_dir: Path | None = Path(args.spec_runs) if args.spec_runs else None

    # ── Collect invocations ────────────────────────────────────────────────
    invocations: list[dict[str, Any]] = []
    any_live = False
    run_id = read_run_id(state_path)

    if spec_runs_dir:
        # Multi-run aggregation mode
        if not spec_runs_dir.exists():
            print(f"ERROR: --spec-runs directory not found: {spec_runs_dir}", file=sys.stderr)
            sys.exit(1)
        invocations, any_live, run_ids_summary = aggregate_spec_runs(spec_runs_dir, codebase_id=args.codebase_id)
        if run_id == "unknown-run":
            run_id = f"aggregate:{run_ids_summary}"
        print(
            f"Aggregated {len(invocations)} invocations from {spec_runs_dir}",
            file=sys.stderr,
        )
    else:
        # Single journal mode
        effective_journal = journal_path or default_journal
        try:
            entries = load_journal(effective_journal)
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"ERROR: Failed to parse journal: {exc}", file=sys.stderr)
            sys.exit(1)

        invocations, any_live = parse_journal(
            entries,
            codebase_id=args.codebase_id,
            spec_run_id=run_id,
        )
        print(
            f"Parsed {len(invocations)} invocations from {effective_journal}",
            file=sys.stderr,
        )

    if not invocations:
        print("WARNING: No invocations found — output will be empty.", file=sys.stderr)

    # ── Build and write artifact ───────────────────────────────────────────
    artifact = build_artifact(run_id, invocations, any_live, codebase_id=args.codebase_id)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"Wrote token-baseline.json → {output_path} "
        f"({len(invocations)} invocations, "
        f"collection_method={artifact['collection_method']}, "
        f"total_tokens={artifact['pipeline_total']['total_tokens']:,})",
        file=sys.stderr,
    )

    # ── Markdown summary ───────────────────────────────────────────────────
    md_summary = render_markdown_summary(artifact)
    if args.markdown:
        md_path = Path(args.markdown)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_summary, encoding="utf-8")
        print(f"Wrote Markdown summary → {md_path}", file=sys.stderr)
    else:
        print(md_summary)


if __name__ == "__main__":
    main()

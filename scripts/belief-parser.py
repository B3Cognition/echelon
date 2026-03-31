#!/usr/bin/env python3
"""
belief-parser.py — Echelon Belief Annotation Parser

Parses @belief(…) annotations from YAML config files and ## Belief Register
tables from agent prompt Markdown files, producing a config-belief-graph.json.

Usage:
    python3 scripts/belief-parser.py \
        --config config-template.yml \
        --agents agents/ \
        --output config-belief-graph.json

Dependencies: stdlib + pyyaml (already used by the project)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"
APPROACHING_EXPIRY_DAYS = 30
LOW_CONFIDENCE_THRESHOLD = 0.5  # strict: < 0.5 is low_confidence


# ---------------------------------------------------------------------------
# Status classification (FR-005)
# ---------------------------------------------------------------------------


def classify_status(belief: dict[str, Any]) -> str:
    """
    Classify a belief into one of: expired | approaching_expiry |
    low_confidence | fresh.

    Priority order: expired > approaching_expiry > low_confidence > fresh.
    """
    today = date.today()

    expires_str = belief.get("expires_date")
    if expires_str:
        try:
            expires = date.fromisoformat(expires_str)
            if expires < today:
                return "expired"
            delta = (expires - today).days
            if delta <= APPROACHING_EXPIRY_DAYS:
                return "approaching_expiry"
        except ValueError:
            pass  # malformed date — treat as no expiry

    confidence = belief.get("confidence")
    if confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD:
        return "low_confidence"

    return "fresh"


# ---------------------------------------------------------------------------
# YAML config file parsing
# ---------------------------------------------------------------------------

# Regex patterns for @belief annotations
_BELIEF_BLOCK_START = re.compile(r"#\s*@belief\(")
_BELIEF_INLINE = re.compile(r"#\s*@belief\((.+)\)\s*$")
_BELIEF_BLOCK_LINE = re.compile(r"#\s*(.*)")
_KV_RE = re.compile(r'(\w+)\s*:\s*"([^"]*)"|([\w]+)\s*:\s*([^\s,)]+)')


def _parse_belief_fields(text: str) -> dict[str, Any] | None:
    """
    Parse the inner content of a @belief(…) block or inline annotation.
    Returns a dict with string keys, or None if 'claim' is missing.

    Handles both quoted strings and unquoted scalars.
    """
    fields: dict[str, Any] = {}
    for m in _KV_RE.finditer(text):
        if m.group(1):  # quoted value
            key, val = m.group(1), m.group(2)
        else:  # unquoted value
            key, val = m.group(3), m.group(4).rstrip(",)")
        if key and val:
            fields[key.strip()] = val.strip()

    if "claim" not in fields:
        return None

    # Type coercions
    if "confidence" in fields:
        try:
            fields["confidence"] = float(fields["confidence"])
        except ValueError:
            pass

    return fields


def _dotted_key_from_path(path: list[str]) -> str:
    return ".".join(str(p) for p in path if p is not None)


def _flatten_yaml(obj: Any, prefix: list[str] | None = None) -> list[tuple[str, Any]]:
    """
    Flatten a nested YAML dict into [(dotted_key, value)] pairs.
    Only yields leaf values.
    """
    if prefix is None:
        prefix = []
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            results.extend(_flatten_yaml(v, prefix + [str(k)]))
    else:
        results.append((_dotted_key_from_path(prefix), obj))
    return results


def parse_config_file(path: Path) -> list[dict[str, Any]]:
    """
    Parse a YAML config file and return a list of belief dicts extracted from
    @belief(…) annotations.

    Raises FileNotFoundError if path does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    # Build a flat map: dotted_key -> value (from YAML parse)
    try:
        yaml_data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        print(f"WARNING: Failed to parse YAML in {path}: {exc}", file=sys.stderr)
        yaml_data = {}

    flat_map = dict(_flatten_yaml(yaml_data))

    beliefs: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # --- Detect annotation start ---
        inline_match = _BELIEF_INLINE.match(stripped)
        if inline_match:
            # Single-line: # @belief(claim: "…")
            fields = _parse_belief_fields(inline_match.group(1))
            annotation_start_line = i + 1  # 1-based
            if fields is None:
                print(
                    f"WARNING: {path.name}:{i+1}: @belief annotation missing 'claim', skipping.",
                    file=sys.stderr,
                )
                i += 1
                continue
            # The config key is on the NEXT non-comment, non-blank line
            config_key, config_line = _next_config_key(lines, i + 1, path)
            if config_key is not None:
                belief = _make_config_belief(
                    fields, config_key, flat_map, path, annotation_start_line
                )
                beliefs.append(belief)
            i += 1
            continue

        block_start_match = _BELIEF_BLOCK_START.match(stripped)
        if block_start_match:
            # Multi-line: # @belief(\n#   key: val\n# )
            block_lines, end_i, ok = _collect_block(lines, i)
            if not ok:
                print(
                    f"WARNING: {path.name}:{i+1}: Unclosed @belief block, skipping.",
                    file=sys.stderr,
                )
                i = end_i + 1
                continue
            inner = " ".join(block_lines)
            fields = _parse_belief_fields(inner)
            annotation_start_line = i + 1
            if fields is None:
                print(
                    f"WARNING: {path.name}:{i+1}: @belief block missing 'claim', skipping.",
                    file=sys.stderr,
                )
                i = end_i + 1
                continue
            config_key, _ = _next_config_key(lines, end_i + 1, path)
            if config_key is not None:
                belief = _make_config_belief(
                    fields, config_key, flat_map, path, annotation_start_line
                )
                beliefs.append(belief)
            i = end_i + 1
            continue

        i += 1

    return beliefs


def _collect_block(lines: list[str], start: int) -> tuple[list[str], int, bool]:
    """
    Collect lines of a multi-line @belief(…) block starting at `start`.
    Returns (inner_text_parts, last_line_index, success).

    The closing paren ) must appear on a comment line by itself or at the end
    of a comment line (e.g. "# )").
    """
    parts: list[str] = []
    # First line: strip "# @belief(" prefix and collect the rest
    first = lines[start].strip()
    after_open = re.sub(r"#\s*@belief\(", "", first, count=1).strip()
    if after_open:
        parts.append(after_open)

    i = start + 1
    while i < len(lines):
        stripped = lines[i].strip()
        # Must be a comment line
        cm = _BELIEF_BLOCK_LINE.match(stripped)
        if not cm:
            # Non-comment line reached before closing — malformed
            return parts, i - 1, False
        content = cm.group(1).strip()
        if content == ")":
            return parts, i, True
        if content.endswith(")"):
            parts.append(content[:-1].rstrip())
            return parts, i, True
        parts.append(content)
        i += 1

    return parts, i - 1, False


def _next_config_key(
    lines: list[str], start: int, path: Path
) -> tuple[str | None, int]:
    """
    Starting from `start`, skip blank and comment lines, then parse the YAML
    key from the next substantive line.
    Returns (dotted_key, line_index) or (None, line_index).
    """
    i = start
    indent_stack: list[tuple[int, str]] = []

    # Build indent context from previous lines
    for prev_i in range(start - 1, -1, -1):
        pl = lines[prev_i]
        if pl.strip() == "" or pl.strip().startswith("#"):
            continue
        # Found a non-comment non-blank line before annotation
        # Build indent stack up to here
        break

    # Walk forward to find the key line
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if stripped == "" or stripped.startswith("#"):
            i += 1
            continue

        # Try to parse a YAML key
        key_match = re.match(r"^(\s*)([\w-]+)\s*:", raw)
        if key_match:
            indent = len(key_match.group(1))
            local_key = key_match.group(2)
            return _resolve_dotted_key(lines, i, indent, local_key), i

        return None, i

    return None, i


def _resolve_dotted_key(lines: list[str], key_line: int, key_indent: int, key: str) -> str:
    """
    Walk backwards through `lines` to build the full dotted path for a YAML key
    at a given indentation level.
    """
    path_parts = [key]
    current_indent = key_indent

    for i in range(key_line - 1, -1, -1):
        raw = lines[i]
        if raw.strip() == "" or raw.strip().startswith("#"):
            continue
        m = re.match(r"^(\s*)([\w-]+)\s*:", raw)
        if m:
            indent = len(m.group(1))
            parent_key = m.group(2)
            if indent < current_indent:
                path_parts.insert(0, parent_key)
                current_indent = indent
                if current_indent == 0:
                    break

    return ".".join(path_parts)


def _make_config_belief(
    fields: dict[str, Any],
    config_key: str,
    flat_map: dict[str, Any],
    path: Path,
    source_line: int,
) -> dict[str, Any]:
    """
    Assemble a belief record for a config-sourced annotation.
    """
    # Normalise config_key: strip leading component names that are just
    # indentation artefacts — use the value from flat_map when possible.
    config_value = flat_map.get(config_key)
    if config_value is None:
        # Try last component only (shallow key)
        last = config_key.split(".")[-1]
        config_value = flat_map.get(last)

    belief: dict[str, Any] = {
        "belief_id": f"config:{config_key}",
        "claim": fields["claim"],
        "verified_date": fields.get("verified"),
        "expires_date": fields.get("expires"),
        "anchor_url": fields.get("anchor"),
        "confidence": fields.get("confidence"),
        "severity": fields.get("severity"),
        "source_file": path.name,
        "source_line": source_line,
        "config_key": config_key,
        "config_value": str(config_value) if config_value is not None else None,
    }
    belief["status"] = classify_status(belief)
    return belief


# ---------------------------------------------------------------------------
# Markdown Belief Register parsing
# ---------------------------------------------------------------------------

_TABLE_HEADER_RE = re.compile(
    r"\|\s*Belief ID\s*\|", re.IGNORECASE
)
_TABLE_SEPARATOR_RE = re.compile(r"^\|[-| :]+\|$")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")


def parse_agent_file(path: Path) -> list[dict[str, Any]]:
    """
    Parse a Markdown agent prompt file and extract beliefs from the
    ## Belief Register table.

    Raises FileNotFoundError if path does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Agent file not found: {path}")

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    beliefs: list[dict[str, Any]] = []
    in_table = False
    header_cols: list[str] = []

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()

        if not in_table:
            if _TABLE_HEADER_RE.search(stripped):
                in_table = True
                header_cols = [c.strip() for c in stripped.strip("|").split("|")]
            continue

        # Skip separator row (| --- | --- |)
        if _TABLE_SEPARATOR_RE.match(stripped):
            continue

        row_match = _TABLE_ROW_RE.match(stripped)
        if not row_match:
            # End of table
            in_table = False
            header_cols = []
            continue

        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < len(header_cols):
            cells.extend([""] * (len(header_cols) - len(cells)))

        row: dict[str, str] = {
            h.lower().replace(" ", "_"): cells[idx]
            for idx, h in enumerate(header_cols)
        }

        # Map column names to belief fields
        confidence_raw = row.get("confidence", "").strip()
        try:
            confidence = float(confidence_raw) if confidence_raw else None
        except ValueError:
            confidence = None

        belief: dict[str, Any] = {
            "belief_id": row.get("belief_id", "").strip(),
            "claim": row.get("claim", "").strip(),
            "verified_date": row.get("verified", "").strip() or None,
            "expires_date": row.get("expires", "").strip() or None,
            "anchor_url": row.get("anchor", "").strip() or None,
            "confidence": confidence,
            "severity": row.get("severity", "").strip() or None,
            "source_file": path.name,
            "source_line": line_no,
        }
        belief["status"] = classify_status(belief)
        beliefs.append(belief)

    return beliefs


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(
    config_files: list[Path] | None = None,
    agent_dirs: list[Path] | None = None,
) -> dict[str, Any]:
    """
    Collect all beliefs from config files and agent dirs, then assemble and
    return the config-belief-graph structure.

    Raises FileNotFoundError for missing agent directories.
    """
    all_beliefs: list[dict[str, Any]] = []

    for cfg_path in config_files or []:
        all_beliefs.extend(parse_config_file(cfg_path))

    for agent_dir in agent_dirs or []:
        agent_dir = Path(agent_dir)
        if not agent_dir.exists():
            raise FileNotFoundError(f"Agent directory not found: {agent_dir}")
        for md_file in sorted(agent_dir.rglob("*.md")):
            beliefs = parse_agent_file(md_file)
            all_beliefs.extend(beliefs)

    # Deterministic ordering: sort by (source_file, source_line) — FR-006
    all_beliefs.sort(key=lambda b: (b["source_file"], b["source_line"]))

    summary = _build_summary(all_beliefs)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
        "beliefs": all_beliefs,
        "summary": summary,
    }


def _build_summary(beliefs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {
        "total": len(beliefs),
        "fresh": 0,
        "approaching_expiry": 0,
        "expired": 0,
        "low_confidence": 0,
    }
    for b in beliefs:
        status = b.get("status", "fresh")
        if status in counts:
            counts[status] += 1
    return counts


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse belief annotations from config YAML files and agent Markdown files."
    )
    parser.add_argument(
        "--config",
        dest="configs",
        action="append",
        metavar="FILE",
        default=[],
        help="Config YAML file(s) to parse (can be repeated)",
    )
    parser.add_argument(
        "--agents",
        dest="agents",
        action="append",
        metavar="DIR",
        default=[],
        help="Directory of agent .md files to parse (can be repeated)",
    )
    parser.add_argument(
        "--output",
        default="config-belief-graph.json",
        metavar="FILE",
        help="Output JSON file path (default: config-belief-graph.json)",
    )
    args = parser.parse_args()

    config_paths = [Path(c) for c in args.configs]
    agent_dirs = [Path(d) for d in args.agents]

    try:
        graph = build_graph(config_files=config_paths, agent_dirs=agent_dirs)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)
    out_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"Wrote {graph['summary']['total']} beliefs "
        f"({graph['summary']['fresh']} fresh, "
        f"{graph['summary']['expired']} expired, "
        f"{graph['summary']['approaching_expiry']} approaching expiry, "
        f"{graph['summary']['low_confidence']} low confidence) "
        f"→ {out_path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

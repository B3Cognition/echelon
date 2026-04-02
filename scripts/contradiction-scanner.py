#!/usr/bin/env python3
"""
contradiction-scanner.py — Echelon Spec Artifact Contradiction Scanner

Scans Echelon spec run artifacts for inter-artifact contradictions between
adjacent agent pairs (DISCOVER→ASSESS, ASSESS→HOW, etc.) within a spec run.

Produces a JSON report with detected contradictions, pair-level rates, and a
manual precision sample (5 randomly selected items, verified=null).

Detection method: heuristic pattern matching (upper bound — over-detects hard
contradictions, misses soft prose contradictions).

Usage:
    python3 scripts/contradiction-scanner.py \\
        --specs-dir <path to .specify/specs/> \\
        [--spec-ids 013 014 015] \\
        [--output <path>] \\
        [--verbose]

Dependencies: stdlib only.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"

# Agent pipeline order — defines which pairs are "adjacent"
PIPELINE_STAGES = [
    "DISCOVER",
    "ASSESS",
    "HOW",
    "PLAN",
    "BUILD",
    "FINALIZE",
]

# Map artifact filenames to pipeline stage labels
ARTIFACT_STAGE_MAP: dict[str, str] = {
    # DISCOVER artifacts
    "assumptions.md": "DISCOVER",
    "glossary.md": "DISCOVER",
    "mental-model.md": "DISCOVER",
    "domain-analysis.md": "DISCOVER",
    "research.md": "DISCOVER",
    "unknowns.md": "DISCOVER",
    "boundaries.md": "DISCOVER",
    "user-intent.md": "DISCOVER",
    # ASSESS artifacts
    "feasibility.md": "ASSESS",
    "estimates.md": "ASSESS",
    "risks.md": "ASSESS",
    "risk-matrix.md": "ASSESS",
    "alternatives.md": "ASSESS",
    "assumption-review.md": "ASSESS",
    "issues.md": "ASSESS",
    # HOW artifacts
    "spec.md": "HOW",
    "data-model.md": "HOW",
    "test-strategy.md": "HOW",
    "test-architecture.md": "HOW",
    "contracts": "HOW",
    # PLAN artifacts
    "tasks.md": "PLAN",
    "plan.md": "PLAN",
    "critical-path.md": "PLAN",
    "prioritization.md": "PLAN",
    "mvp-scope.md": "PLAN",
    # BUILD / FINALIZE
    "ground-check.md": "FINALIZE",
    "learnings.md": "FINALIZE",
    "evolution-report.md": "FINALIZE",
}

# Adjacent pairs to compare (source → target)
ADJACENT_PAIRS: list[tuple[str, str]] = [
    ("DISCOVER", "ASSESS"),
    ("ASSESS", "HOW"),
    ("HOW", "PLAN"),
    ("PLAN", "BUILD"),
    ("BUILD", "FINALIZE"),
]

# Regex patterns for assertion extraction
_NUMBER_RE = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\b")
_BOLD_KEY_RE = re.compile(r"\*\*([^*]+)\*\*\s*[:：]\s*(.+)")
_KV_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 _/-]{1,40})\s*[:：]\s*(.+)$")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
_STATUS_RE = re.compile(
    r"\b(PASS|FAIL|PASSED|FAILED|YES|NO|TRUE|FALSE|VALIDATED|INVALID|"
    r"CONFIRMED|UNCONFIRMED|ENABLED|DISABLED|ACTIVE|INACTIVE)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(
    r"\b(not|no |never|none|absent|missing|does not|do not|cannot|can't|"
    r"doesn't|don't|isn't|aren't|won't|hasn't|haven't)\b",
    re.IGNORECASE,
)

# Generic key names that appear in many artifacts with unrelated values.
# Matching on these keys alone would produce excessive false positives.
_GENERIC_STOP_KEYS: frozenset[str] = frozenset({
    "statement",
    "description",
    "definition",
    "note",
    "notes",
    "source",
    "basis",
    "date",
    "agent",
    "mode",
    "author",
    "version",
    "example",
    "rationale",
    "implication",
    "evidence",
    "approach",
    "summary",
    "detail",
    "details",
    "comment",
    "verdict",
    "text",
    "type",
    "value",
    "result",
})

# ---------------------------------------------------------------------------
# Assertion data structure
# ---------------------------------------------------------------------------


class Assertion:
    """A single extracted factual claim from a spec artifact."""

    __slots__ = ("file", "line_no", "text", "entity", "numbers", "statuses",
                 "negated", "stage")

    def __init__(
        self,
        file: Path,
        line_no: int,
        text: str,
        entity: str,
        numbers: list[str],
        statuses: list[str],
        negated: bool,
        stage: str,
    ) -> None:
        self.file = file
        self.line_no = line_no
        self.text = text
        self.entity = entity
        self.numbers = numbers
        self.statuses = statuses
        self.negated = negated
        self.stage = stage

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": str(self.file),
            "line": self.line_no,
            "text": self.text,
        }


# ---------------------------------------------------------------------------
# Assertion extraction
# ---------------------------------------------------------------------------


def _extract_number_set(text: str) -> list[str]:
    """Return all numeric tokens found in text."""
    return [m.group(1).replace(",", "") for m in _NUMBER_RE.finditer(text)]


def _extract_status_set(text: str) -> list[str]:
    """Return all status tokens found in text (normalised to upper case)."""
    return [m.group(1).upper() for m in _STATUS_RE.finditer(text)]


def _normalise_entity(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    s = raw.lower().strip()
    s = re.sub(r"[*_`#\[\]()]+", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _is_negated(text: str) -> bool:
    return bool(_NEGATION_RE.search(text))


def extract_assertions_from_file(path: Path, stage: str) -> list[Assertion]:
    """
    Parse a Markdown spec artifact and return a list of Assertion objects.

    Extracts:
    - Bold-key patterns (**Key**: value)
    - Key-value lines (Key: value) with a colon
    - Table rows (pipe-delimited)
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"WARNING: Cannot read {path}: {exc}", file=sys.stderr)
        return []

    lines = text.splitlines()
    assertions: list[Assertion] = []
    current_section = ""

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        # Track section headings for context
        if line.startswith("##"):
            current_section = _normalise_entity(
                re.sub(r"^#+\s*", "", line)
            )
            continue

        if not line or line.startswith("#"):
            continue

        # Bold key-value: **Key**: value
        bm = _BOLD_KEY_RE.search(line)
        if bm:
            entity_raw = bm.group(1)
            value_raw = bm.group(2)
            full_text = f"{entity_raw}: {value_raw}"
            entity = _normalise_entity(entity_raw)
            if current_section:
                entity = f"{current_section}::{entity}"
            assertions.append(Assertion(
                file=path,
                line_no=line_no,
                text=full_text[:300],
                entity=entity,
                numbers=_extract_number_set(value_raw),
                statuses=_extract_status_set(value_raw),
                negated=_is_negated(full_text),
                stage=stage,
            ))
            continue

        # Plain key: value lines
        km = _KV_LINE_RE.match(line)
        if km:
            entity_raw = km.group(1)
            value_raw = km.group(2)
            full_text = line
            entity = _normalise_entity(entity_raw)
            if current_section:
                entity = f"{current_section}::{entity}"
            assertions.append(Assertion(
                file=path,
                line_no=line_no,
                text=full_text[:300],
                entity=entity,
                numbers=_extract_number_set(value_raw),
                statuses=_extract_status_set(value_raw),
                negated=_is_negated(full_text),
                stage=stage,
            ))
            continue

        # Table rows
        tm = _TABLE_ROW_RE.match(line)
        if tm and not re.match(r"^\|[-| :]+\|$", line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2:
                entity_raw = cells[0]
                value_raw = " | ".join(cells[1:])
                full_text = line
                entity = _normalise_entity(entity_raw)
                if current_section:
                    entity = f"{current_section}::{entity}"
                assertions.append(Assertion(
                    file=path,
                    line_no=line_no,
                    text=full_text[:300],
                    entity=entity,
                    numbers=_extract_number_set(value_raw),
                    statuses=_extract_status_set(value_raw),
                    negated=_is_negated(full_text),
                    stage=stage,
                ))

    return assertions


# ---------------------------------------------------------------------------
# Contradiction detection heuristics
# ---------------------------------------------------------------------------


class Contradiction:
    """A detected contradiction between two assertions."""

    def __init__(
        self,
        cid: str,
        ctype: str,
        assertion_a: Assertion,
        assertion_b: Assertion,
        entity: str,
        confidence: float,
    ) -> None:
        self.cid = cid
        self.ctype = ctype
        self.assertion_a = assertion_a
        self.assertion_b = assertion_b
        self.entity = entity
        self.confidence = confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.cid,
            "type": self.ctype,
            "artifact_a": self.assertion_a.to_dict(),
            "artifact_b": self.assertion_b.to_dict(),
            "entity": self.entity,
            "confidence": self.confidence,
        }


def _entity_key(entity: str) -> str:
    """Strip section prefix for loose matching."""
    if "::" in entity:
        return entity.split("::")[-1].strip()
    return entity


def _entities_match(e1: str, e2: str) -> bool:
    """
    Return True if two entity strings are likely referring to the same concept.

    Uses exact match on the leaf part, or checks whether one is a substring of
    the other (min 4 chars to avoid noise).

    Generic stop-key names (statement, description, etc.) are excluded from
    matching to prevent cross-artifact false positives.
    """
    k1 = _entity_key(e1)
    k2 = _entity_key(e2)
    # Never match on generic keys — they appear in every artifact with
    # unrelated values and would produce excessive false positives.
    if k1 in _GENERIC_STOP_KEYS or k2 in _GENERIC_STOP_KEYS:
        return False
    if k1 == k2:
        return True
    if len(k1) >= 4 and len(k2) >= 4:
        if k1 in k2 or k2 in k1:
            return True
    return False


def _status_contradicts(s1: str, s2: str) -> bool:
    """Return True if two status tokens are logically opposite."""
    opposites: list[tuple[str, str]] = [
        ("PASS", "FAIL"),
        ("PASSED", "FAILED"),
        ("YES", "NO"),
        ("TRUE", "FALSE"),
        ("VALIDATED", "INVALID"),
        ("CONFIRMED", "UNCONFIRMED"),
        ("ENABLED", "DISABLED"),
        ("ACTIVE", "INACTIVE"),
    ]
    for a, b in opposites:
        if (s1 == a and s2 == b) or (s1 == b and s2 == a):
            return True
    return False


def detect_contradictions(
    assertions_a: list[Assertion],
    assertions_b: list[Assertion],
    pair_label: str,
    counter_start: int,
    verbose: bool = False,
) -> list[Contradiction]:
    """
    Compare two assertion lists (from adjacent stages) for contradictions.

    Heuristics:
    1. Count mismatch — same entity, both have numbers, numbers differ.
    2. Status mismatch — same entity, opposing status tokens.
    3. Boolean mismatch — same entity, one negated and one not, same subject.
    """
    contradictions: list[Contradiction] = []
    counter = counter_start

    for a in assertions_a:
        for b in assertions_b:
            if not _entities_match(a.entity, b.entity):
                continue

            entity_label = _entity_key(a.entity)

            # --- Heuristic 1: Count mismatch ---
            if a.numbers and b.numbers:
                # Find the first significant number in each (ignore line numbers)
                nums_a = [float(n) for n in a.numbers if float(n) > 0]
                nums_b = [float(n) for n in b.numbers if float(n) > 0]
                if nums_a and nums_b and nums_a[0] != nums_b[0]:
                    cid = f"C-{counter:03d}"
                    counter += 1
                    confidence = 0.7
                    if verbose:
                        print(
                            f"  [{pair_label}] {cid} count_mismatch: "
                            f"'{entity_label}' → {nums_a[0]} vs {nums_b[0]}",
                            file=sys.stderr,
                        )
                    contradictions.append(Contradiction(
                        cid=cid,
                        ctype="count_mismatch",
                        assertion_a=a,
                        assertion_b=b,
                        entity=entity_label,
                        confidence=confidence,
                    ))
                    continue  # one contradiction per pair is enough

            # --- Heuristic 2: Status mismatch ---
            for sa in a.statuses:
                for sb in b.statuses:
                    if _status_contradicts(sa, sb):
                        cid = f"C-{counter:03d}"
                        counter += 1
                        confidence = 0.85
                        if verbose:
                            print(
                                f"  [{pair_label}] {cid} status_mismatch: "
                                f"'{entity_label}' → {sa} vs {sb}",
                                file=sys.stderr,
                            )
                        contradictions.append(Contradiction(
                            cid=cid,
                            ctype="status_mismatch",
                            assertion_a=a,
                            assertion_b=b,
                            entity=entity_label,
                            confidence=confidence,
                        ))

            # --- Heuristic 3: Boolean mismatch ---
            if a.negated != b.negated and a.numbers == [] and b.numbers == []:
                # Only flag if the texts are meaningfully similar in length
                # (avoids false positives from unrelated sentences)
                len_ratio = min(len(a.text), len(b.text)) / max(
                    len(a.text), len(b.text), 1
                )
                if len_ratio > 0.4:
                    cid = f"C-{counter:03d}"
                    counter += 1
                    confidence = 0.5
                    if verbose:
                        print(
                            f"  [{pair_label}] {cid} boolean_mismatch: "
                            f"'{entity_label}' → negation differs",
                            file=sys.stderr,
                        )
                    contradictions.append(Contradiction(
                        cid=cid,
                        ctype="boolean_mismatch",
                        assertion_a=a,
                        assertion_b=b,
                        entity=entity_label,
                        confidence=confidence,
                    ))

    return contradictions


# ---------------------------------------------------------------------------
# Spec directory scanning
# ---------------------------------------------------------------------------


def _stage_for_file(path: Path) -> str | None:
    """Return the pipeline stage for a given artifact filename, or None."""
    return ARTIFACT_STAGE_MAP.get(path.name)


def scan_spec_dir(
    spec_dir: Path,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Scan a single spec directory and return the contradiction scan data.

    Returns a dict with keys: spec_id, pairs_scanned, contradictions,
    per_pair_rates.
    """
    spec_id = spec_dir.name
    if verbose:
        print(f"\n[SCAN] {spec_id}", file=sys.stderr)

    # Collect artifact files grouped by stage
    stage_assertions: dict[str, list[Assertion]] = {s: [] for s in PIPELINE_STAGES}

    md_files = sorted(spec_dir.glob("*.md"))
    for md_file in md_files:
        stage = _stage_for_file(md_file)
        if stage is None:
            continue
        if verbose:
            print(f"  Reading {md_file.name} → {stage}", file=sys.stderr)
        assertions = extract_assertions_from_file(md_file, stage)
        stage_assertions[stage].extend(assertions)
        if verbose:
            print(f"    {len(assertions)} assertions extracted", file=sys.stderr)

    # Compare adjacent pairs
    all_contradictions: list[Contradiction] = []
    per_pair_data: dict[str, dict[str, Any]] = {}
    global_counter = 1

    for stage_a, stage_b in ADJACENT_PAIRS:
        pair_label = f"{stage_a}-{stage_b}"
        a_list = stage_assertions.get(stage_a, [])
        b_list = stage_assertions.get(stage_b, [])

        pairs_count = len(a_list) * len(b_list)

        if verbose:
            print(
                f"  Comparing {stage_a}({len(a_list)}) "
                f"× {stage_b}({len(b_list)}) = {pairs_count} assertion pairs",
                file=sys.stderr,
            )

        found = detect_contradictions(
            a_list, b_list, pair_label, global_counter, verbose=verbose
        )
        global_counter += len(found)
        all_contradictions.extend(found)

        rate = len(found) / max(pairs_count, 1)
        per_pair_data[pair_label] = {
            "pairs": pairs_count,
            "contradictions": len(found),
            "rate": round(rate, 6),
        }

    return {
        "spec_id": spec_id,
        "pairs_scanned": sum(v["pairs"] for v in per_pair_data.values()),
        "contradictions": all_contradictions,
        "per_pair_rates": per_pair_data,
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _manual_precision_sample(
    contradictions: list[Contradiction],
    n: int = 5,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Select up to n contradictions at random for manual precision review."""
    rng = random.Random(seed)
    sample = rng.sample(contradictions, min(n, len(contradictions)))
    result = []
    for c in sample:
        entry = c.to_dict()
        entry["verified"] = None  # to be filled by human reviewer
        result.append(entry)
    return result


def build_report(
    specs_dir: Path,
    spec_ids: list[str] | None,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Scan one or more spec directories and assemble the full contradiction report.
    """
    run_id = f"scan-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    scanned_at = datetime.now(timezone.utc).isoformat()

    # Resolve spec directories
    if spec_ids:
        spec_dirs: list[Path] = []
        for sid in spec_ids:
            # Support partial prefix match (e.g. "013" matches "013-...")
            matches = [
                d for d in sorted(specs_dir.iterdir())
                if d.is_dir() and d.name.startswith(sid)
            ]
            if not matches:
                print(
                    f"WARNING: No spec directory matching '{sid}' in {specs_dir}",
                    file=sys.stderr,
                )
            spec_dirs.extend(matches)
    else:
        spec_dirs = [d for d in sorted(specs_dir.iterdir()) if d.is_dir()]

    if not spec_dirs:
        print("WARNING: No spec directories found to scan.", file=sys.stderr)

    # Scan each spec
    all_contradictions: list[Contradiction] = []
    total_pairs = 0
    per_pair_totals: dict[str, dict[str, Any]] = {
        f"{a}-{b}": {"pairs": 0, "contradictions": 0, "rate": 0.0}
        for a, b in ADJACENT_PAIRS
    }
    spec_ids_scanned: list[str] = []

    for spec_dir in spec_dirs:
        result = scan_spec_dir(spec_dir, verbose=verbose)
        spec_ids_scanned.append(result["spec_id"])
        all_contradictions.extend(result["contradictions"])
        total_pairs += result["pairs_scanned"]
        for pair_label, data in result["per_pair_rates"].items():
            per_pair_totals[pair_label]["pairs"] += data["pairs"]
            per_pair_totals[pair_label]["contradictions"] += data["contradictions"]

    # Recompute per-pair rates across all specs
    for pair_label, data in per_pair_totals.items():
        data["rate"] = round(
            data["contradictions"] / max(data["pairs"], 1), 6
        )

    overall_rate = round(len(all_contradictions) / max(total_pairs, 1), 6)

    # Re-number contradictions globally (C-001, C-002, ...)
    for idx, c in enumerate(all_contradictions, start=1):
        c.cid = f"C-{idx:03d}"

    sample = _manual_precision_sample(all_contradictions)

    report: dict[str, Any] = {
        "run_id": run_id,
        "spec_ids_scanned": spec_ids_scanned,
        "scanned_at": scanned_at,
        "detection_method": "heuristic-pattern-matching",
        "bound_type": "upper_bound",
        "method_limitations": (
            "This scanner applies three syntactic heuristics (count mismatch, "
            "status mismatch, boolean mismatch) over structured key-value lines, "
            "bold patterns, and table rows in Markdown artifacts. "
            "It is an UPPER BOUND estimator: (1) false positives occur when "
            "different entities share the same key name across artifacts; "
            "(2) false negatives occur for contradictions expressed in unstructured "
            "prose, multi-sentence reasoning, or non-adjacent pipeline stages. "
            "The output contradiction_rate_per_run is not a true precision-recall "
            "metric and must be interpreted as a detection signal, not a ground truth. "
            "Manual verification of the precision sample is required to calibrate "
            "the signal."
        ),
        "pairs_scanned": total_pairs,
        "contradictions_detected": len(all_contradictions),
        "contradiction_rate_per_run": overall_rate,
        "per_pair_rates": per_pair_totals,
        "contradictions": [c.to_dict() for c in all_contradictions],
        "manual_precision_sample": sample,
    }

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scan Echelon spec run artifacts for inter-artifact contradictions "
            "across adjacent pipeline stage pairs. Produces a JSON report."
        )
    )
    parser.add_argument(
        "--specs-dir",
        required=True,
        metavar="DIR",
        help="Path to the .specify/specs/ directory containing spec run subdirectories.",
    )
    parser.add_argument(
        "--spec-ids",
        nargs="+",
        metavar="ID",
        default=None,
        help=(
            "One or more spec ID prefixes to scan (e.g. 013 014 015). "
            "If omitted, all spec directories are scanned."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help=(
            "Output JSON file path. If omitted, prints to stdout. "
            "If writing to a spec directory, the file is placed at "
            "<specs-dir>/<spec-id>/contradiction-report.json by default."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print progress details to stderr.",
    )
    args = parser.parse_args()

    specs_dir = Path(args.specs_dir)
    if not specs_dir.exists():
        print(f"ERROR: specs-dir not found: {specs_dir}", file=sys.stderr)
        sys.exit(1)
    if not specs_dir.is_dir():
        print(f"ERROR: specs-dir is not a directory: {specs_dir}", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(
            f"[contradiction-scanner] v{VERSION} — scanning {specs_dir}",
            file=sys.stderr,
        )

    report = build_report(
        specs_dir=specs_dir,
        spec_ids=args.spec_ids,
        verbose=args.verbose,
    )

    json_out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_out, encoding="utf-8")
        print(
            f"[contradiction-scanner] Wrote report → {out_path}",
            file=sys.stderr,
        )
    else:
        print(json_out)

    print(
        f"[contradiction-scanner] "
        f"specs={len(report['spec_ids_scanned'])} "
        f"pairs_scanned={report['pairs_scanned']} "
        f"contradictions={report['contradictions_detected']} "
        f"rate={report['contradiction_rate_per_run']:.4%}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

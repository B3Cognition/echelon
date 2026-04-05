# Code Review Report — Build 1775154996

Reviewer: CODE REVIEWER (automated, claude-sonnet-4-6)
Date: 2026-04-02
Reference style: `scripts/belief-parser.py`

---

## TASK-006: token-logger.py

**Verdict**: CHANGES_REQUESTED

### Issues Found

**MEDIUM — Dead code / misleading logic in `_word_count` (lines 87-99)**

The function constructs a `text` variable on lines 88-91 that is immediately discarded. The `text` variable is never read after assignment; only the `parts` list (built separately on lines 93-98) feeds the return value. Additionally, the guard `if isinstance(v, str) or True` on line 91 is always `True`, causing the first join to silently coerce list objects via `str(v)` (producing strings like `"['a', 'b']"`). Since `text` is unused this is harmless, but the dead code makes it impossible to audit the function's correctness at a glance without tracing both code paths. The correct implementation is the `parts` block alone.

**LOW — Per-invocation records missing `spec_run_id` and `codebase_id` (AC-003-001)**

AC-003-001 requires five fields in every logged record: (a) prompt token count, (b) completion token count, (c) agent identifier, (d) spec run ID, (e) codebase identifier. The invocation records produced by `parse_journal` contain `agent`, `phase`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `estimated`, `timestamp`. Field (d) spec run ID is present only at the artifact top level (`run_id`) but is not embedded in each individual invocation record. Field (e) codebase identifier is absent from both per-invocation records and the artifact entirely. The spec compliance gap is: AC-003-001 says "All five fields must be present in every logged record."

**LOW — `--journal` default not set via `default=` on argparse argument (lines 439-443)**

`--journal` documents a default path in its `help=` string but sets no `default=` value on `add_argument`. The code handles this correctly in the body via a local `default_journal` variable (line 473), so there is no runtime bug. However, `--help` output shows `default: None` rather than the documented default, which is misleading to users and future implementers.

### AC Compliance Check

- **REQ-015-003 schema match**: PARTIAL — prompt_tokens, completion_tokens, agent identifier, collection_method, and timestamp are present. `spec_run_id` is top-level only (not per-record). `codebase_id` (AC-003-001 field e) is absent from both invocation records and the artifact entirely.
- **Statistics correctness**: YES — mean and median delegate to `statistics.mean` / `statistics.median` (correct). P90 uses linear interpolation on sorted list with correct boundary handling for single-element and upper-boundary cases. The arithmetic is correct.
- **No hardcoded absolute paths**: YES — all paths are relative or user-supplied; defaults use relative `Path(".specify/...")` strings.
- **Type hints complete**: YES — all public function signatures carry type hints; `from __future__ import annotations` is present at line 26.
- **Error handling**: YES — `FileNotFoundError` and `json.JSONDecodeError` caught with useful messages; `sys.exit(1)` on fatal errors; all status output goes to `stderr`.

---

## TASK-007: contradiction-scanner.py

**Verdict**: APPROVED

### Issues Found

No blocking issues. The following are informational observations only:

**INFO — `random.Random(seed=None)` makes sample non-deterministic across runs (line 583)**
When no seed is provided the sample changes each run. The spec does not require reproducibility for the manual precision sample, so this is acceptable. Documented for awareness.

**INFO — `"contracts"` entry in `ARTIFACT_STAGE_MAP` can never match (lines 75, 521)**
`scan_spec_dir` globs only `*.md` files; `"contracts"` is a directory name. The map entry is dead but does not affect correctness or output.

**INFO — Substring entity matching may conflate short related keys (lines 369-371)**
The `k1 in k2 or k2 in k1` heuristic with `min len >= 4` is a stated trade-off. The stop-key list and the `method_limitations` field in the output adequately document this. Acceptable as-is.

### AC Compliance Check

- **REQ-015-005 schema match**: YES — output contains `run_id`, `spec_ids_scanned`, `scanned_at`, `detection_method`, `bound_type`, `method_limitations`, `pairs_scanned`, `contradictions_detected`, `contradiction_rate_per_run`, `per_pair_rates` (rates for all ADJACENT_PAIRS), `contradictions` list, and `manual_precision_sample`. All AC-005-003 fields present.
- **Bound type stated**: YES — `"bound_type": "upper_bound"` present in output schema. `method_limitations` explains false positive sources (why upper bound) and prose miss-rate (why not lower bound). AC-005-005 satisfied.
- **Manual precision sample**: YES — `_manual_precision_sample` selects up to 5 contradictions with `"verified": null` placeholders. AC-005-004 satisfied.
- **Heuristic documented**: YES — three heuristics (count_mismatch, status_mismatch, boolean_mismatch) named in code docstrings and in `method_limitations` in the output JSON. AC-005-002 satisfied — method operates on structured key-value lines, bold patterns, and table rows; explicitly excludes prose. Detection method is stated and applied consistently.

---

## Summary

| Script | Verdict | Critical | High | Medium | Low |
|--------|---------|---------|------|--------|-----|
| token-logger.py | CHANGES_REQUESTED | 0 | 0 | 1 | 2 |
| contradiction-scanner.py | APPROVED | 0 | 0 | 0 | 0 |

---

## Fixes Required (IMPLEMENTER — next cycle)

All three fixes apply to `scripts/token-logger.py` only.

### Fix 1 — MEDIUM: Remove dead `text` variable in `_word_count`

Replace the entire `_word_count` function body (lines 87-99) with:

```python
def _word_count(entry: dict[str, Any]) -> int:
    """Estimate word count from all string values in *entry* (shallow pass)."""
    parts: list[str] = []
    for v in entry.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(str(i) for i in v if isinstance(i, str))
    return len(" ".join(parts).split())
```

The `text = " ".join(...)` block on the original lines 88-91 is dead code and must be removed.

### Fix 2 — LOW: Add `codebase_id` to per-invocation records and artifact

Add a `--codebase-id` CLI argument (optional, `default="unknown"`). Propagate it through `build_artifact` and embed it in:
- Each invocation dict inside `parse_journal` (as `"codebase_id": codebase_id`)
- The artifact root (as `"codebase_id": codebase_id`)

Also embed `run_id` into each invocation record (as `"run_id": run_id`) so AC-003-001 field (d) is satisfied at the per-record level, not just at the artifact level.

### Fix 3 — LOW: Set explicit `default=None` on `--journal` argparse argument

Change:
```python
parser.add_argument(
    "--journal",
    metavar="FILE",
    help="Path to reasoning-journal.json (default: .specify/squad/staging/reasoning-journal.json)",
)
```
To:
```python
parser.add_argument(
    "--journal",
    metavar="FILE",
    default=None,
    help="Path to reasoning-journal.json (default: .specify/squad/staging/reasoning-journal.json)",
)
```

No logic change — the body already handles `None` correctly. This makes `--help` output consistent with the documented behaviour.

---

*Generated by CODE REVIEWER agent — Build 1775154996 — 2026-04-02*

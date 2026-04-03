# Code Review Report — Spec 018 SOAR Cognitive Architecture Overlay

**Gate**: CODE REVIEWER  
**Tasks in scope**: T-027 through T-035  
**Reviewer**: CODE REVIEWER automated gate  
**Date**: 2026-04-03  
**Files reviewed**:
- `scripts/ca/soar.py` (primary review target)
- `scripts/ca/actr_buffer.py` (ISS-004 fix, lines 172–181)
- `COMMANDER.md` (T-035 amendment)

---

## soar.py — Full Code Review

### 1. Security: `_validate_run_id`

**Finding: PASS with one note**

The validator correctly rejects:
- Non-string types (type check)
- Strings exceeding 128 chars
- Path traversal via `..`
- Forward slash `/`
- Backslash `\`
- Null byte `\x00`
- Any character outside `[a-zA-Z0-9_\-.]` (regex)
- **Empty string** — the regex `^[a-zA-Z0-9_\-.]+$` requires at least one character (`+` quantifier), so empty string fails the regex check. Empty string is correctly rejected.
- Special chars including space, `@`, `!`, `;`, `$` are all rejected by the regex.

**Coverage note**: The validator is defense-in-depth: path traversal via `..` is caught by the explicit check AND again by the regex (since `.` followed by `.` is technically allowed by the character class but `..` is blocked by the literal string check first). The redundancy is intentional and acceptable.

**One note**: The regex character class `[a-zA-Z0-9_\-.]` uses `\-` inside `[]`. This is unambiguous in Python `re` because the hyphen is escaped. No bug here, but conventional style places hyphens at the start or end of the class (e.g., `[-a-zA-Z0-9_.]`). Purely cosmetic.

**Security verdict**: `_validate_run_id` is sufficient for RAR-001 mitigation. All dangerous characters are rejected.

---

### 2. Logic Correctness: `_match_rules` First-Match Tie Breaking

**Finding: PASS — correct for FR-SOAR-006**

```python
if conf > best_confidence:
    best_confidence = conf
    best_rule = rule
```

Using strict `>` means: when a later rule has the same confidence as `best_confidence`, the condition `conf > best_confidence` is False, so `best_rule` is NOT updated. The first rule that achieves a given confidence level wins the tie.

This is exactly what FR-SOAR-006 specifies: "the overlay selects the rule that appears first in ProceduralMemoryStore load order." The implementation is correct.

No ImpasseEvent is triggered on tie (the tie resolves to a winner; `_log_impasse` is only called from the `winning_rule is None` branch). AC-1.3 is satisfied.

---

### 3. Edge Case: Empty SEED_RULES

**Finding: PASS — graceful**

If `SEED_RULES = []`, then `_load_procedural_store` initializes `store["rules"] = []`. `_match_rules(wmes, [])` immediately returns `None` (loop body never executes). `enrich_context` detects `winning_rule is None`, calls `_log_impasse`, and sets the impasse `soar_state`. No exception or crash. The impasse path handles the empty-rules case correctly.

This edge case does not currently arise because `SEED_RULES` has 5 entries, but the code is robust against it.

---

### 4. Atomic Write: `_save_procedural_store`

**Finding: PASS**

```python
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(store, f, indent=2)
os.replace(tmp, path)
```

`os.replace()` is atomic on POSIX systems when source and destination are on the same filesystem (POSIX rename semantics). The tmp file and target file share the same parent directory (`.specify/squad/`), so they are on the same filesystem. Atomic write is correct.

`os.makedirs(os.path.dirname(path), exist_ok=True)` ensures the directory exists before the write. Correct.

**Note**: `_log_impasse` does NOT use the atomic tmp+replace pattern — it uses a direct `open(path, "w")` write. Under A-005 (sequential COMMANDER), this is safe. If concurrency were ever introduced, the impasse log would be at risk of partial writes. This is flagged as a low-priority robustness note; it is not a bug under current assumptions.

---

### 5. Thread Safety

**Finding: NOTE ONLY (not a defect)**

A-005 (VALIDATED) confirms sequential operation within a run. No concurrent writes to `soar-procedural-{run_id}.json` are possible under this assumption. The atomic write (`os.replace`) on the procedural store is a defense-in-depth measure. The non-atomic write on the impasse log is acceptable under A-005.

If A-005 were ever invalidated (parallel COMMANDER), both write paths would require locking or full atomic patterns. This is out of scope per spec.

---

### 6. 200-Char Cap Edge Case: Mathematical Verification

**Finding: PASS — fallback is guaranteed ≤200 chars**

**Worst-case mandatory-fields-only payload**:
```
{"operator_applied": "<64 chars>", "impasse": false, "cycle": 999999, "wme_count": 99}
```
Measured: **140 characters**.

This leaves 60 chars of headroom. Even with `impasse: true` and the longest impasse indicator, the mandatory-fields-only payload cannot reach 200 chars:
- `operator_applied` is capped at 64 chars (enforced by `[:64]`)
- `cycle` as an int has at most 10 digits in reasonable execution counts
- `wme_count` cannot exceed 5 (only 5 keys in `_WME_ATTRS`)
- `impasse` is a JSON boolean (4–5 chars)

The fallback path in `_apply_operator` unconditionally satisfies ≤200 chars. AC-1.7 and FR-SOAR-008 are provably satisfied regardless of input.

---

### 7. Additional Code Quality Observations

**enrich_context — double impasse=False assignment**:

Lines 336 and 338 both set `soar_state["impasse"] = False`:
- Line 336: `_apply_operator` initializes `soar_state["impasse"] = False`
- Line 338: `soar_state["impasse"] = False` (redundant re-assignment)

This is not a bug but is redundant. Low-priority cleanup candidate.

**_load_config regex**:

```python
m = re.search(r"chunking_enabled\s*:\s*(true|false)", text, re.IGNORECASE)
```

This regex matches the FIRST occurrence of `chunking_enabled` in the file, regardless of YAML section context. If another section of `squad-config.yml` also has a `chunking_enabled` key (e.g., a different overlay), the wrong value could be used. This is a known limitation of the regex-based YAML parsing approach (no YAML library per ADR-005). Acceptable for v1.

**_extract_wmes — extra_key in AC-1.6**:

When `context_pack` contains `extra_key`, `_extract_wmes` silently skips it because it is not in `_WME_ATTRS`. The WME set will contain 5 entries for the 5 standard keys (if all present). `extra_key` produces no WME. This is correct per AC-1.6.

**update_soar_memory — last_cycle usage**:

`_build_chunk` uses `last_cycle = store.get("last_cycle", 0)` from the store. `last_cycle` is set to `cycle` in `enrich_context` before calling `_save_procedural_store`. If `enrich_context` and `update_soar_memory` are called in the correct sequence (as per COMMANDER), `last_cycle` will be the cycle of the dispatch just completed. The dependency on correct call ordering is implicit. Acceptable under A-005.

---

## actr_buffer.py — ISS-004 Fix Review

### Fix Scope

**Finding: PASS — fix is minimal**

The fix is contained to lines 172–181 (the return statement and its comment). No other logic in `enrich_context` was changed. The buffer classification, TF-IDF retrieval, and token eviction logic are unchanged.

### Return Statement Correctness

```python
# ISS-004 / FR-SOAR-011: return only actr_buffers (no original key duplication)
return {
    "actr_buffers": {
        "declarative": buffers["declarative"],
        "procedural": buffers["procedural"],
        "goal": buffers["goal"],
        "imaginal": buffers["imaginal"],
        "retrieval_buffer": retrieval_buffer,
    }
}
```

**AC-5.1**: Returns a dict with exactly one top-level key (`actr_buffers`). SATISFIED.

**AC-5.2**: The returned dict contains no keys from the input `context_pack`. The original `context_pack` is iterated only to populate `buffers` (internal structure). None of those keys appear in the return value. SATISFIED.

**Critical integration defect (ISS-004-REG-001)**: Correctly identified in the spec compliance report. The fix satisfies its own ACs but causes `active_goal` and all other prior overlay outputs to be dropped from `context_pack` when COMMANDER does assignment-not-merge. This will cause SOAR to impasse on every call. The defect is in the COMMANDER integration pattern, not in `actr_buffer.py` itself. However, the implementation team should resolve this before shipping T-034.

---

## COMMANDER.md — T-035 Amendment Review

### Pre-Dispatch Try/Except Block (AC-6.1)

```python
# 6. SOAR Cognitive Architecture Overlay (position 6)
try:
    from scripts.ca import soar
    context_pack = soar.enrich_context(context_pack, run_id)
except Exception as _soar_exc:  # noqa: BLE001
    # NFR-SOAR-004 / AC-6.1: exception does not block dispatch
    _log(f"SOAR overlay exception (non-blocking): {_soar_exc}")
```

Both `import` and `enrich_context` call are inside the try block. If the import fails (module not found), the exception is caught and dispatch proceeds. This is correct and complete.

### Post-Dispatch Try/Except Block (AC-6.2)

```python
# 4. SOAR Cognitive Architecture Overlay — post-dispatch learning
try:
    from scripts.ca import soar as _soar_mod
    _soar_mod.update_soar_memory(outcome, run_id)
except Exception as _soar_exc:  # noqa: BLE001
    # NFR-SOAR-004 / AC-6.2: exception does not corrupt dispatch outcome
    _log(f"SOAR update_soar_memory exception (non-blocking): {_soar_exc}")
```

Both try/except blocks present. Exception handling pattern is correct. AC-6.1 and AC-6.2 SATISFIED.

### Overlay Specification Table (Section 6)

| Field | Present | Value |
|-------|---------|-------|
| Interface | Yes | `soar.enrich_context(context_pack, run_id) -> dict` |
| Post-dispatch | Yes | `soar.update_soar_memory(outcome, run_id) -> None (mandatory)` |
| Injected key | Yes | `soar_state` (dict, max 200 chars serialized) |
| State files | Yes | Both `soar-procedural-{run_id}.json` and `soar-impasse-{run_id}.json` listed |
| Seed rules | Yes | 5 hand-coded rules, confidence range stated |
| Chunking | Yes | Disabled by default |
| Exception policy | Yes | Both hooks non-blocking |
| Write constraint | Yes | Does NOT modify state.json |

All required fields present. FR-SOAR-012 and FR-SOAR-013 SATISFIED.

---

## Issues Summary

| ID | Severity | File | Description | Action Required |
|----|----------|------|-------------|-----------------|
| ISS-004-REG-001 | CRITICAL | actr_buffer.py / COMMANDER.md | actr_buffer returns only `{actr_buffers}`, COMMANDER assigns (not merges), losing `active_goal` and all prior overlay outputs. Every SOAR seed rule requires `active_goal` — SOAR will impasse on every dispatch in the integrated stack. | CHANGES_REQUESTED: COMMANDER must merge actr_buffer output, or actr_buffer must return full enriched pack. |
| STYLE-001 | LOW | soar.py:338 | Redundant `soar_state["impasse"] = False` after `_apply_operator` already sets it. | Optional cleanup. |
| STYLE-002 | LOW | soar.py:131 | `_load_config` regex matches first `chunking_enabled` in file regardless of YAML section. Acceptable for v1 but fragile. | Document limitation or add section-aware parsing in v2. |
| ROBUSTNESS-001 | LOW | soar.py:293 | `_log_impasse` uses non-atomic write. Safe under A-005; fragile if concurrency is ever introduced. | No action required now; note for v2. |

---

## Verdict

**CODE REVIEW: CHANGES_REQUESTED**

`soar.py` is well-structured and correctly implements the SOAR Match-Select-Apply cycle. Security validation is complete, edge cases are handled gracefully, the atomic write pattern is correct, and the 200-char cap is provably satisfiable in all cases. The module is stdlib-only, subprocess-free, and exception-safe.

The `actr_buffer.py` ISS-004 fix is internally correct per its spec. The `COMMANDER.md` amendment is complete with both required try/except blocks and a fully populated overlay table.

**The blocking issue is ISS-004-REG-001**: the combination of the actr_buffer return contract (AC-5.2: return only `actr_buffers`) and the COMMANDER assignment pattern (`context_pack = actr_buffer.enrich_context(...)`) destroys `active_goal` from `context_pack` at position 2, causing SOAR to impasse on every call at position 6. This is a correctness defect that prevents the SOAR overlay from functioning in the integrated stack.

Recommended fix: In COMMANDER.md, change the actr_buffer call from:
```python
context_pack = actr_buffer.enrich_context(context_pack, run_id)
```
to:
```python
context_pack.update(actr_buffer.enrich_context(context_pack, run_id))
```

This preserves all prior overlay outputs while adding `actr_buffers` exactly once, satisfying AC-5.1 and AC-5.2 while not breaking the chain. No change to `actr_buffer.py` or `soar.py` is required.

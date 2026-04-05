# Spec Compliance Report — Spec 018 SOAR Cognitive Architecture Overlay

**Gate**: SPEC GUARD  
**Tasks in scope**: T-027 through T-035  
**Reviewer**: SPEC GUARD automated gate  
**Date**: 2026-04-03  
**Files reviewed**:
- `scripts/ca/soar.py` (T-027–T-033)
- `scripts/ca/actr_buffer.py` (T-034, ISS-004 fix)
- `COMMANDER.md` (T-035)
- `.specify/specs/018-soar-overlay/spec.md`

---

## Acceptance Criteria Results

### Scenario 1: Context Enrichment via Production Rule Match

| AC | Requirement | Finding | Status |
|----|-------------|---------|--------|
| AC-1.1 | soar_state serialized length ≤200 | `_apply_operator` enforces `len(json.dumps(soar_state)) <= 200` check. Mandatory-fields-only fallback produced. | PASS |
| AC-1.2 | operator_applied = selected rule name, impasse=False on match | `_apply_operator` sets `operator_applied = rule["rule_id"][:64]`, `impasse=False`. `enrich_context` re-confirms `soar_state["impasse"] = False` on match. | PASS |
| AC-1.3 | First-match on equal confidence, no ImpasseEvent on tie | `_match_rules` uses strict `conf > best_confidence`. The first rule encountered at a given confidence level stays as `best_rule`; subsequent equal-confidence rules do not displace it. Correct for FR-SOAR-006. No `_log_impasse` call on tie. | PASS |
| AC-1.4 | 100ms budget, no subprocess | Linear scan O(R×C×W). No `subprocess` import or call in soar.py (confirmed by AST inspection). stdlib I/O only (json file read/write). | PASS |
| AC-1.5 | Prior overlay keys preserved unchanged | `enriched = dict(context_pack)` shallow copy, then `enriched["soar_state"] = soar_state`. All prior keys retained. | PASS |
| AC-1.6 | 5 WMEs for 5 standard keys; extra_key ignored | `_extract_wmes` iterates over `_WME_ATTRS = [active_goal, actr_buffers, gwt_workspace, episodic_prior_artifact, lida_broadcast]`. Keys not in this list are silently skipped. `extra_key` is not in `_WME_ATTRS`. Values string-coerced and truncated to 200 chars. | PASS |
| AC-1.7 | Truncation path: mandatory-fields only when >200 chars; operator_applied ≤64 chars | `_apply_operator` calls `str(rule["rule_id"])[:64]` for `op_name`, then checks `len(json.dumps(soar_state)) <= 200`. On overflow: returns dict with only the four mandatory keys. Mathematical verification: worst-case mandatory-only payload (64-char name, cycle=999999, wme_count=99) = 140 chars ≤ 200. | PASS |

### Scenario 2: Impasse Handling

| AC | Requirement | Finding | Status |
|----|-------------|---------|--------|
| AC-2.1 | operator_applied="default-no-match", impasse=True on no-match | `enrich_context` else-branch (line 342–348): `soar_state = {"operator_applied": "default-no-match", "impasse": True, "cycle": cycle, "wme_count": len(wmes)}`. | PASS |
| AC-2.2 | ImpasseEvent appended with type/run_id/cycle/wme_snapshot | `_log_impasse` constructs event with all four mandatory fields: `type="no-operator"`, `run_id`, `cycle`, `wme_snapshot`. Appended to file. | PASS |
| AC-2.3 | Impasse file created if absent | `_log_impasse`: `if os.path.exists(path): load else: events = []`. File created fresh on first impasse. `os.makedirs(..., exist_ok=True)` ensures parent dir. | PASS |
| AC-2.4 | Always returns valid dict, never None | `enrich_context` always sets `soar_state` (either from `_apply_operator` or the impasse dict) before `enriched["soar_state"] = soar_state`. Returns `enriched`. No code path returns None. | PASS |

**Note on AC-2.3**: `_log_impasse` writes the impasse file non-atomically (no tmp+replace pattern). This is an observability concern but not an AC violation since the spec only requires the file be created; it does not mandate atomic write for the impasse log.

### Scenario 3: Post-Dispatch Procedural Learning

| AC | Requirement | Finding | Status |
|----|-------------|---------|--------|
| AC-3.1 | ChunkRecord with learned=True, rule_id="chunk-" prefix on non-blocked | `_build_chunk` returns `{"rule_id": f"chunk-{run_id}:{cycle}", ..., "learned": True}`. `update_soar_memory` appends to store on success path. | PASS |
| AC-3.2 | No write on BLOCKED/ESCALATED | `update_soar_memory` returns early at `if outcome.get("status") in ["BLOCKED", "ESCALATED"]: return`. | PASS |
| AC-3.3 | Silent skip when episodic index absent | `if not os.path.exists(index_path): return` — silent, no exception raised. | PASS |
| AC-3.4 | No write when chunking_enabled=False | `cfg = _load_config(); if not cfg.get("chunking_enabled", False): return` — returns before any store modification. | PASS |

**Note on AC-3.2 ordering**: The BLOCKED/ESCALATED check runs before the `chunking_enabled` check (AC-3.4). This is functionally correct but slightly inconsistent with the spec ordering in FR-SOAR-010 (chunking gate is logically prior). No AC is violated.

### Scenario 4: ProceduralMemoryStore Initialization

| AC | Requirement | Finding | Status |
|----|-------------|---------|--------|
| AC-4.1 | First call creates file with seed rules only | `_load_procedural_store`: if file absent, builds store with `"rules": [dict(r) for r in SEED_RULES]`, calls `_save_procedural_store`. No ChunkRecords (none exist at this point). | PASS |
| AC-4.2 | ≥5 seed rules, each covering Tier 1 or Tier 2 | SEED_RULES contains exactly 5 rules. seed-001 covers active_goal (T1); seed-002 covers active_goal+actr_buffers (T1+T2); seed-003 covers active_goal+gwt_workspace (T1+T2); seed-004 covers active_goal+actr_buffers+gwt_workspace+episodic_prior_artifact (T1+T2); seed-005 covers active_goal+lida_broadcast (T1+T3). All cover at least one T1 or T2. | PASS |
| AC-4.3 | Existing file not overwritten | `_load_procedural_store`: `if os.path.exists(path): with open(path) as f: return json.load(f)`. Load-if-exists path skips initialization entirely. | PASS |

### Scenario 5: ACT-R Buffer Key De-duplication Fix (ISS-004)

| AC | Requirement | Finding | Status |
|----|-------------|---------|--------|
| AC-5.1 | actr_buffers appears exactly once as top-level key | `actr_buffer.py` lines 173–181 return `{"actr_buffers": {...}}`. Only one top-level key. Subsequent overlays receive this as `context_pack` (via COMMANDER assignment). Downstream overlays using `dict(context_pack)` copy and add their own key will produce `actr_buffers` exactly once. | PASS |
| AC-5.2 | No original context_pack keys in returned dict | The return block (lines 173–181) is a fresh dict containing only the `actr_buffers` key. No `dict(context_pack)` merge precedes it. None of the original keys (`role`, `task`, `spec_text`, `prior_artifacts`, `constitution`, `active_goal`, etc.) appear in the returned dict. | PASS |

**CRITICAL DEFECT — ISS-004-REG-001 (Integration Regression)**: While AC-5.1 and AC-5.2 are individually satisfied, the fix creates a critical integration regression. COMMANDER.md line 37 does `context_pack = actr_buffer.enrich_context(context_pack, run_id)` (assignment, not merge). This replaces `context_pack` with `{"actr_buffers": {...}}`, causing ALL keys added by prior overlays (including `active_goal` from goal_stack at position 1) to be permanently lost from `context_pack` for the remainder of the dispatch sequence.

Consequence for soar.py (position 6): `enrich_context` calls `_extract_wmes(context_pack)`. At dispatch time, `context_pack` will contain `actr_buffers`, `gwt_workspace`, `episodic_prior_artifact`, but NOT `active_goal` (stripped at position 2). Since all 5 seed rules require `active_goal` as a condition, and `active_goal` is absent from the WME set, every SOAR call will result in an impasse. The SOAR overlay will never match a seed rule in the integrated stack.

This defect is in the contract between AC-5.2 (return only `actr_buffers`) and the COMMANDER integration pattern (assignment, not merge). The spec does not define how COMMANDER should integrate the return value; it specifies only what the return value contains. The COMMANDER.md code snippet uses direct assignment. **The fix is internally self-consistent per its spec but breaks the six-overlay chain.** A correction requires either: (a) COMMANDER merges rather than replaces on the actr_buffer call, or (b) actr_buffer returns the full enriched dict (violating AC-5.2), or (c) goal_stack is moved to position 6 (after actr_buffer). This defect is flagged as a CHANGES_REQUESTED item.

### Scenario 6: Overlay Failure Resilience

| AC | Requirement | Finding | Status |
|----|-------------|---------|--------|
| AC-6.1 | SOAR exception doesn't block dispatch | COMMANDER.md lines 54–59: `try: context_pack = soar.enrich_context(...) except Exception as _soar_exc: _log(...)`. Exception caught, dispatch proceeds with unenriched pack. | PASS |
| AC-6.2 | update_soar_memory exception doesn't corrupt outcome | COMMANDER.md lines 94–99: `try: soar.update_soar_memory(outcome, run_id) except Exception as _soar_exc: _log(...)`. Exception caught, outcome preserved. | PASS |

---

## Non-Functional Requirements

| NFR | Requirement | Finding | Status |
|-----|-------------|---------|--------|
| NFR-SOAR-001 | stdlib only | Imports: `__future__`, `json`, `os`, `re`, `datetime`, `typing` — all stdlib. Zero non-stdlib imports confirmed by AST analysis. | PASS |
| NFR-SOAR-002 | Runtime files use `.specify/squad/` path | `_procedural_path`: `.specify/squad/soar-procedural-{run_id}.json`. `_impasse_path`: `.specify/squad/soar-impasse-{run_id}.json`. Both correct. | PASS |
| NFR-SOAR-003 | No subprocess in enrich_context | No `subprocess` import. No `os.system`, `os.popen`, or subprocess calls found. | PASS |
| NFR-SOAR-004 | Exception handling pattern documented in module docstring | Module docstring line 13: "On any exception: caller should catch and proceed without soar_state (NFR-SOAR-004)." | PASS |

---

## Functional Requirements (FR)

| FR | Requirement | Finding | Status |
|----|-------------|---------|--------|
| FR-CAO-006 | soar.py never writes state.json | Grep for "state.json" in soar.py: zero matches. Write targets limited to `soar-procedural-*.json` and `soar-impasse-*.json`. | PASS |
| FR-SOAR-012 | COMMANDER.md documents position-6 enrich_context | COMMANDER.md lines 52–59: `# 6. SOAR Cognitive Architecture Overlay (position 6)` with code snippet. | PASS |
| FR-SOAR-013 | COMMANDER.md documents update_soar_memory post-dispatch | COMMANDER.md lines 93–99: `# 4. SOAR Cognitive Architecture Overlay — post-dispatch learning` with code snippet. | PASS |

---

## Issues Summary

| ID | Severity | AC/FR | Description |
|----|----------|-------|-------------|
| ISS-004-REG-001 | CRITICAL | AC-5.1, AC-5.2 (integration) | The ISS-004 fix in actr_buffer.py causes active_goal (and all other prior overlay outputs) to be lost from context_pack when COMMANDER does assignment-not-merge at position 2. All 5 seed rules require active_goal. In the integrated six-overlay stack, SOAR will impasse on every call. |
| MINOR-001 | LOW | AC-2.3 | _log_impasse uses non-atomic write (no tmp+replace). Race-free under A-005 (sequential), but noted for robustness. |
| MINOR-002 | LOW | AC-3.2 | BLOCKED/ESCALATED check runs before chunking_enabled check; functionally correct but spec ordering inconsistency. |

---

## Verdict

**SPEC GUARD: CONDITIONAL FAIL**

All individual acceptance criteria for soar.py (AC-1.x through AC-4.x, AC-6.x) and COMMANDER.md (AC-6.1, AC-6.2, FR-SOAR-012, FR-SOAR-013) are SATISFIED in isolation. The NFRs are all SATISFIED. soar.py is correctly implemented per its own specification.

However, **ISS-004-REG-001** represents a critical integration defect introduced by the actr_buffer.py ISS-004 fix (T-034). The fix satisfies AC-5.1 and AC-5.2 per their literal wording but breaks the six-overlay chain in a way that guarantees SOAR impasse on every dispatch. This defect must be resolved before the gate can be declared PASS.

**Recommended resolution**: COMMANDER must merge the actr_buffer return value into the existing context_pack rather than replace it. Specifically, line 37 of COMMANDER.md's pre-dispatch sequence should be changed from `context_pack = actr_buffer.enrich_context(context_pack, run_id)` to `context_pack.update(actr_buffer.enrich_context(context_pack, run_id))`, or equivalent merge pattern. This preserves active_goal and all other prior overlay outputs while adding actr_buffers exactly once.

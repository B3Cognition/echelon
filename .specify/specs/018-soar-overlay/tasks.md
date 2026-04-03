# Tasks — Spec 018: SOAR Cognitive Architecture Overlay

**Role**: ORCHESTRATOR (PLAN agent)
**Date**: 2026-04-03
**Spec**: 018-soar-overlay
**Upstream verdict**: CONDITIONAL — all conditions resolved in plan.md
**Task range**: T-027 – T-035 (continuing from spec 017: T-021–T-026)

---

## Section 1: Task List

---

## T-027: `soar.py` — Security helper `_validate_run_id` + file path helpers

**File**: `scripts/ca/soar.py`
**FRs**: FR-SOAR-002, FR-SOAR-005
**Estimated effort**: S (Small — under 50 lines)
**Depends on**: NONE
**Description**: Create the `soar.py` module from scratch with its module docstring (including ADR-005 interface declaration and the required P-006 override notice `Human override of P-006 authorized 2026-04-03 (user instruction: "build it anyway")`), stdlib imports (`json`, `os`, `re`, `datetime`), and the four private path helpers: `_repo_root()`, `_validate_run_id(run_id)`, `_procedural_path(run_id)`, `_impasse_path(run_id)`, and `_episodic_index_path(run_id)`. `_validate_run_id` must reject any `run_id` containing `..`, `/`, `\`, null bytes, or characters outside `[a-zA-Z0-9_\-.]`, and enforce a 128-character maximum length; it raises `ValueError` on violation and returns `None` silently on success. All path-constructing helpers must call `_validate_run_id` before building any path string.
**Acceptance criteria**: RAR-001 path-traversal mitigation is in place; NFR-SOAR-001 (stdlib-only imports) is satisfied from line 1; NFR-SOAR-002 is structurally enabled by the `.specify/squad/` path prefix used in `_procedural_path` and `_impasse_path`.

---

## T-028: `soar.py` — `SEED_RULES` constant + ProceduralMemoryStore load/save/init functions

**File**: `scripts/ca/soar.py`
**FRs**: FR-SOAR-002, FR-SOAR-007, FR-SOAR-009
**Estimated effort**: M (Medium — 50–100 lines)
**Depends on**: T-027
**Description**: Add the `SEED_RULES` module-level constant — a list of exactly 5 hand-coded ProductionRule dicts as specified in plan.md Section 6 (seed-001 through seed-005, confidence range 0.70–0.90, `learned: false`). Then implement `_load_config()` (reads `ca_overlays.soar.chunking_enabled` from `squad-config.yml` via regex or YAML parsing; defaults to `false` when the key or section is absent — BUILD must NOT add the key to `squad-config.yml`), `_load_procedural_store(run_id)` (create-if-absent using `SEED_RULES`, do-not-overwrite on subsequent calls; returned dict contains `run_id`, `last_updated`, `cycle_count`, `last_matched_rule_id`, `last_cycle`, `last_wme_snapshot`, and `rules`), and `_save_procedural_store(store, run_id)` (atomic write). The ProceduralMemoryStore JSON schema is specified in plan.md Appendix B.
**Acceptance criteria**: AC-4.1 (first-call creates file with seed rules and no ChunkRecords), AC-4.2 (at least 5 seed rules each covering at least one Tier 1 or Tier 2 WME attribute), AC-4.3 (subsequent calls load existing file, do not overwrite), AC-3.4 (chunking_enabled defaults to false when key absent), FR-SOAR-007 config-absent behavior.

---

## T-029: `soar.py` — WME extraction `_extract_wmes`

**File**: `scripts/ca/soar.py`
**FRs**: FR-SOAR-003
**Estimated effort**: S (Small — under 50 lines)
**Depends on**: T-027
**Description**: Implement `_extract_wmes(context_pack)` which iterates over exactly five recognized WME attribute names in declaration order — `active_goal` (Tier 1), then `actr_buffers`, `gwt_workspace`, `episodic_prior_artifact` (Tier 2), then `lida_broadcast` (Tier 3) — and for each attribute present in `context_pack` constructs a WME dict `{"id": "<attr>-wme", "attr": "<attr>", "value": <coerced_value>}`. Value coercion: if the value is a dict or list, `json.dumps()` it first; then cast to `str`; then truncate to 200 characters. Keys NOT in the recognized set are silently ignored. Tier 3 (`lida_broadcast`) is included in the WME set when present and absent without error when missing. **Critical constraint from plan.md Section 5**: `active_goal` is sourced from `context_pack["active_goal"]` directly (the top-level key injected by position-1 Goal Stack overlay) — `_extract_wmes` must NOT parse inside `context_pack["actr_buffers"]` to find `active_goal`.
**Acceptance criteria**: AC-1.6 (exactly 5 WMEs for the five standard keys when all are present; no WME for `extra_key`; each WME `attr` equals the key name and `value` equals the string-coerced, truncated key value), FR-SOAR-003 Tier 3 inclusion/omission behavior.

---

## T-030: `soar.py` — Match-Select-Apply cycle: `_match_rules` + `_apply_operator`

**File**: `scripts/ca/soar.py`
**FRs**: FR-SOAR-001, FR-SOAR-004, FR-SOAR-006, FR-SOAR-008
**Estimated effort**: M (Medium — 50–100 lines)
**Depends on**: T-029
**Description**: Implement `_match_rules(wmes, rules)` — a linear scan over the ordered `rules` list evaluating each rule's `conditions` list against the WME set. A condition `{"attr": A}` matches if any WME has `attr == A`; a condition `{"attr": A, "value": V}` additionally requires `V` to be a substring of the WME's `value` field. A rule is fully matched when all conditions match. Among fully matched rules, select the one with the highest `confidence` float; on equal confidence, the rule appearing first in list order wins and no ImpasseEvent is created (FR-SOAR-006). Returns the winning rule dict or `None`. Then implement `_apply_operator(winning_rule, cycle, wme_count)` — constructs `soar_state` by merging the mandatory four fields (`operator_applied`: `winning_rule["rule_id"]` truncated to 64 chars, `impasse`: `false`, `cycle`: int, `wme_count`: int) with the rule's `actions` payload. After constructing the full dict, checks `len(json.dumps(soar_state)) <= 200`; if the check fails, falls back to a mandatory-fields-only dict (truncating `operator_applied` to 64 chars). **Truncation algorithm note**: the mandatory-fields-only fallback must handle `operator_applied` values longer than 64 characters by hard-slicing to 64 chars before serializing.
**Acceptance criteria**: AC-1.2 (operator_applied contains selected rule name, impasse is false on match), AC-1.3 (first-match tie resolution, no ImpasseEvent on tie), AC-1.4 (completes under 100ms — linear scan over ≤50 rules satisfies this without optimization), AC-1.7 (soar_state truncates to mandatory-fields-only when full payload exceeds 200 chars, operator_applied truncated to 64 chars), AC-1.1 (soar_state serialized length ≤200 always), NFR-SOAR-003.

---

## T-031: `soar.py` — Impasse handling: `_log_impasse` + DefaultOperator

**File**: `scripts/ca/soar.py`
**FRs**: FR-SOAR-005
**Estimated effort**: S (Small — under 50 lines)
**Depends on**: T-027
**Description**: Implement `_log_impasse(run_id, wmes, cycle)` which constructs an `ImpasseEvent` dict with the four mandatory fields — `type` (always `"no-operator"`), `run_id`, `cycle`, `wme_snapshot` (a dict mapping each WME's `attr` to its `value`) — then loads the existing impasse log at `soar-impasse-{run_id}.json` as a list (creates empty list if file absent), appends the new event, and writes the updated list back. This is the standard append-only JSON write pattern matching `episodic_memory.index_artifact()`. The DefaultOperator is not a class but a convention used in `enrich_context` (T-032): when `_match_rules` returns `None`, `enrich_context` sets `operator_applied = "default-no-match"` and `impasse = true` and calls `_log_impasse`.
**Acceptance criteria**: AC-2.1 (operator_applied equals "default-no-match", impasse is true on no-match), AC-2.2 (ImpasseEvent appended to soar-impasse-{run_id}.json with all four mandatory fields), AC-2.3 (file created if absent on first impasse), AC-2.4 (returned context pack is a valid dict, never None), NFR-SOAR-006 (all four mandatory fields in each log entry).

---

## T-032: `soar.py` — `enrich_context` public function

**File**: `scripts/ca/soar.py`
**FRs**: FR-SOAR-001, FR-SOAR-002, FR-SOAR-004, FR-SOAR-005, FR-SOAR-008, FR-SOAR-009
**Estimated effort**: S (Small — under 50 lines)
**Depends on**: T-027, T-028, T-029, T-030, T-031
**Description**: Implement the `enrich_context(context_pack, run_id)` public function — the sole ADR-005 pre-dispatch entrypoint. Execution sequence per plan.md Section 4.8: (1) call `_validate_run_id`; (2) call `_load_procedural_store` (seeds on first call); (3) call `_extract_wmes`; (4) increment `cycle_count` from store metadata (default 0); (5) call `_match_rules`; (6) if a rule matches, call `_apply_operator` to produce `soar_state` with `impasse: false`; (7) if no match, call `_log_impasse` and produce `soar_state` with `operator_applied: "default-no-match"`, `impasse: true`; (8) save updated `cycle_count`, `last_matched_rule_id`, `last_cycle`, and `last_wme_snapshot` to the procedural store; (9) return `dict(context_pack)` merged with `{"soar_state": soar_state}`. The function docstring must include `# Does NOT modify COMMANDER state.` per FR-CAO-006. All five prior overlay keys are preserved in the returned dict (the merge-on-copy idiom at step 9 guarantees this).
**Acceptance criteria**: AC-1.1 (soar_state present, serialized ≤200 chars), AC-1.4 (under 100ms), AC-1.5 (all five prior overlay keys preserved unchanged), AC-2.4 (always returns valid dict), AC-4.1/4.3 (store initialization and idempotency), NFR-SOAR-001, NFR-SOAR-003, NFR-SOAR-004.

---

## T-033: `soar.py` — Chunking engine: `_build_chunk` + `update_soar_memory` public function

**File**: `scripts/ca/soar.py`
**FRs**: FR-SOAR-007, FR-SOAR-010
**Estimated effort**: M (Medium — 50–100 lines)
**Depends on**: T-027, T-028, T-032
**Description**: Implement `_build_chunk(matched_rule, run_id, cycle)` which constructs a ChunkRecord dict per plan.md Section 4.9: `rule_id` is `f"chunk-{run_id}:{cycle}"`, `conditions` is copied verbatim from `matched_rule["conditions"]` (OQ-005 resolved as Option B — triggering rule's conditions only), `actions` is copied from `matched_rule["actions"]`, `confidence` is `0.6`, `learned` is `true`, `episode_id` is `f"{run_id}:{cycle}"`. Returns the ChunkRecord dict without writing to disk. Then implement `update_soar_memory(outcome, run_id)` per plan.md Section 4.10: (1) validate run_id; (2) check success criterion `outcome.get("status") not in ["BLOCKED", "ESCALATED"]` — return None immediately if not met (AC-3.2); (3) load config and check `chunking_enabled` — return None if false (AC-3.4); (4) check episodic index file exists — return None silently if absent (AC-3.3); (5) load procedural store, retrieve `last_matched_rule_id`, `last_cycle`, `last_wme_snapshot`; (6) find matched rule by `last_matched_rule_id`; (7) call `_build_chunk`; (8) append ChunkRecord to `rules` list; (9) update `last_updated`, call `_save_procedural_store`. **OQ-005 resolution note**: chunking generalization uses Option B verbatim — no additional WMEs beyond the triggering rule's conditions list.
**Acceptance criteria**: AC-3.1 (ChunkRecord appended with `learned: true` and `rule_id` prefixed `"chunk-"` on non-blocked outcome), AC-3.2 (no write on BLOCKED/ESCALATED outcome), AC-3.3 (silent skip when episodic index absent), AC-3.4 (no write when chunking_enabled is false), AC-3.5 (newly written ChunkRecord available for matching on next `enrich_context` call — guaranteed by load-then-scan pattern in T-028/T-030), NFR-SOAR-004.

---

## T-034: `actr_buffer.py` — ISS-004 fix (remove original keys from returned dict)

**File**: `scripts/ca/actr_buffer.py`
**FRs**: FR-SOAR-011
**Estimated effort**: S (Small — 4–8 lines changed; lines 172–180 only)
**Depends on**: NONE
**Description**: Replace the current lines 172–180 in `actr_buffer.py` — specifically the `enriched = dict(context_pack)` initialization that copies all input keys, and the subsequent `enriched["actr_buffers"] = {...}` assignment — with a single return statement that emits ONLY `{"actr_buffers": { ... }}`. The local variables `buffers` and `retrieval_buffer` (already in scope from prior lines) are accessed directly in the return. Add a comment referencing `ISS-004 / FR-SOAR-011` on the return line. Lines 1–171 (TF-IDF helpers, buffer classification, eviction logic) are unchanged. **Downstream impact flagged for BUILD**: after this fix, `context_pack["active_goal"]` continues to exist in COMMANDER's running context_pack (it was injected by position-1 Goal Stack and is not touched by ACT-R). SOAR's `_extract_wmes` (T-029) sources `active_goal` from `context_pack["active_goal"]` directly — not from inside `actr_buffers`. BUILD must also locate and update any existing tests that assert original keys (`role`, `task`, `spec_text`, `prior_artifacts`, `constitution`, `active_goal`) are present in `actr_buffer.enrich_context`'s return value; those assertions will fail after the fix and must be corrected before committing.
**Acceptance criteria**: AC-5.1 (actr_buffers appears exactly once as a top-level key; no original context_pack key present in the returned dict alongside actr_buffers), AC-5.2 (returned dict does NOT contain `role`, `task`, `spec_text`, `prior_artifacts`, `constitution`, `active_goal` or any other key that was in the input context_pack at call time), AC-5.3 (six-overlay stack token overhead ≤25% net-new — the de-duplication fix reduces total overhead, directly supporting this NFR).

---

## T-035: `COMMANDER.md` — Position-6 pre-dispatch hook + post-dispatch `update_soar_memory` hook

**File**: `COMMANDER.md`
**FRs**: FR-SOAR-012, FR-SOAR-013
**Estimated effort**: S (Small — ~40 lines added)
**Depends on**: T-032, T-033 (conceptually — COMMANDER.md documents the interface those tasks implement)
**Description**: Amend `COMMANDER.md` in three places per plan.md Section 7. Amendment 1: in the pre-dispatch sequence code block, after the position-5 `episodic_memory.enrich_context(...)` call (currently the last line before the closing code fence), add `from scripts.ca import soar` to the import block and insert the position-6 call with try/except wrapper: `context_pack = soar.enrich_context(context_pack, run_id)` with a comment noting that exceptions are caught, logged, and dispatch proceeds without soar_state (NFR-SOAR-004, AC-6.1). Amendment 2: in the post-dispatch sequence block, after the comment `# ACT-R Buffer and LIDA Broadcast: no post-dispatch action required.`, add entry 4: `soar.update_soar_memory(outcome, run_id)` in a try/except with a comment noting exceptions are logged without corrupting the dispatch outcome (AC-6.2). Amendment 3: after the position-5 Episodic Memory overlay specification table entry, add a new section "6. SOAR Cognitive Architecture Overlay (`scripts/ca/soar.py`)" with the specification table from plan.md Section 7.3 (pre-dispatch call, post-dispatch call, injected key, state files, seed rules, chunking status, exception policy, write-constraint comment).
**Acceptance criteria**: FR-SOAR-012 (COMMANDER.md documents `soar.enrich_context` as position 6 in the pre-dispatch sequence), FR-SOAR-013 (COMMANDER.md documents `soar.update_soar_memory` as a mandatory post-dispatch call), AC-6.1 (exception from enrich_context does not block dispatch — documented in try/except comment), AC-6.2 (exception from update_soar_memory does not corrupt outcome — documented in try/except comment), NFR-SOAR-004.

---

## Section 2: Critical Path

### Dependency Graph

```
T-027 (security helpers + path helpers)
  ├── T-028 (SEED_RULES + store init)       ← depends on T-027
  │     └── T-033 (chunking + update_soar_memory) ← depends on T-027, T-028, T-032
  ├── T-029 (WME extraction)                ← depends on T-027
  │     └── T-030 (match-select-apply)      ← depends on T-029
  │           └── T-032 (enrich_context)    ← depends on T-027, T-028, T-029, T-030, T-031
  │                 └── T-033               ← depends on T-027, T-028, T-032
  └── T-031 (impasse + log)                 ← depends on T-027
        └── T-032 (enrich_context)

T-034 (actr_buffer.py ISS-004 fix)         ← INDEPENDENT of all soar.py tasks
T-035 (COMMANDER.md amendment)             ← depends on T-032, T-033 (interface consumers)
```

### Sequential Spine (must be ordered)

```
T-027 → T-028 → T-032 → T-033 → T-035
T-027 → T-029 → T-030 → T-032
T-027 → T-031 → T-032
```

The critical path runs: **T-027 → T-029 → T-030 → T-032 → T-033 → T-035** (6 steps). T-028 must complete before T-032 but can be developed in parallel with T-029 and T-031 after T-027 is done.

### Parallelizable Groups

After T-027 is complete, the following tasks can proceed in parallel:
- **Group A** (can parallelize): T-028, T-029, T-031
- **Group B** (after Group A): T-030 (requires T-029), T-033 requires T-028 and T-032
- **Independent**: T-034 has no dependency on any `soar.py` task and can be developed at any time

Earliest possible parallel schedule:
1. T-027 (foundation — must be first)
2. T-028 + T-029 + T-031 in parallel
3. T-030 (requires T-029)
4. T-032 (requires T-028 + T-029 + T-030 + T-031)
5. T-033 (requires T-028 + T-032) | T-034 (independent — can be done at any step)
6. T-035 (requires T-032 + T-033 conceptually)

---

## Section 3: Verification Checklist

After all tasks are complete, BUILD must verify the following before declaring the spec DONE.

### FR Coverage Map

| FR | Description | Implementing Task(s) | Verifying AC(s) |
|----|------------|---------------------|-----------------|
| FR-SOAR-001 | `enrich_context` runs Match-Select-Apply cycle | T-030, T-032 | AC-1.1, AC-1.2, AC-1.4 |
| FR-SOAR-002 | ProceduralMemoryStore as run-scoped JSON | T-028, T-032 | AC-4.1, AC-4.3 |
| FR-SOAR-003 | WME extraction from Tier 1/2/3 keys | T-029 | AC-1.6 |
| FR-SOAR-004 | Argmax-confidence operator selection | T-030, T-032 | AC-1.2, AC-1.3 |
| FR-SOAR-005 | Impasse handling with ImpasseEvent logging | T-031, T-032 | AC-2.1, AC-2.2, AC-2.3, AC-2.4 |
| FR-SOAR-006 | First-match tie-breaking, no tie-impasse | T-030 | AC-1.3 |
| FR-SOAR-007 | `chunking_enabled` config flag, default false | T-028, T-033 | AC-3.4 |
| FR-SOAR-008 | `soar_state` 200-char hard cap with mandatory-fields fallback | T-030, T-032 | AC-1.1, AC-1.7 |
| FR-SOAR-009 | 5+ seed rules initialized on first call | T-028 | AC-4.1, AC-4.2, AC-4.3 |
| FR-SOAR-010 | `update_soar_memory` with success criterion and ChunkRecord | T-033 | AC-3.1, AC-3.2, AC-3.3, AC-3.4, AC-3.5 |
| FR-SOAR-011 | `actr_buffer.py` ISS-004 de-duplication fix | T-034 | AC-5.1, AC-5.2, AC-5.3 |
| FR-SOAR-012 | COMMANDER.md position-6 pre-dispatch amendment | T-035 | FR-SOAR-012 satisfied by documentation presence |
| FR-SOAR-013 | COMMANDER.md post-dispatch `update_soar_memory` amendment | T-035 | FR-SOAR-013 satisfied by documentation presence |

### NFR Coverage Map

| NFR | Verifying task(s) | Verification method |
|-----|------------------|---------------------|
| NFR-SOAR-001 (stdlib-only) | T-027, T-028, T-029, T-030, T-031, T-032, T-033 | Static analysis: `grep -n "^import\|^from" scripts/ca/soar.py` — must show only `json`, `os`, `re`, `datetime` |
| NFR-SOAR-002 (gitignore) | T-027 (path prefix), existing .gitignore | `git check-ignore -v .specify/squad/soar-procedural-test.json` must return a match |
| NFR-SOAR-003 (< 100ms) | T-030, T-032 | Time `enrich_context` over 10 consecutive calls with a 50-rule store; all must complete < 100ms |
| NFR-SOAR-004 (no blocked dispatch) | T-035 (COMMANDER try/except) | Inject an exception in `enrich_context`; confirm COMMANDER proceeds without `soar_state` |
| NFR-SOAR-005 (≤25% token overhead) | T-034, T-030 | Token count of six-overlay output vs. pre-overlay baseline; soar_state ≤200 chars hard cap enforces this |
| NFR-SOAR-006 (impasse log completeness) | T-031 | Inspect `soar-impasse-{run_id}.json` after a forced no-match scenario; confirm all four mandatory fields present in every entry |

### AC Verification Checklist (all 25 ACs)

- [ ] AC-1.1: `soar_state` present and `len(json.dumps(soar_state)) <= 200` on every `enrich_context` call
- [ ] AC-1.2: `soar_state["operator_applied"]` is rule name; `soar_state["impasse"]` is `false` on rule match
- [ ] AC-1.3: Tie on confidence → first rule in load order selected; no ImpasseEvent created
- [ ] AC-1.4: `enrich_context` completes in < 100ms; no subprocess or external process called
- [ ] AC-1.5: All five prior overlay keys present and unchanged in returned context pack
- [ ] AC-1.6: Exactly 5 WMEs for the five standard keys; `extra_key` produces no WME; attr/value match spec
- [ ] AC-1.7: Over-200-char payload falls back to mandatory-fields-only; `operator_applied` truncated to 64 chars
- [ ] AC-2.1: `operator_applied == "default-no-match"` and `impasse == true` when no rule matches
- [ ] AC-2.2: ImpasseEvent appended to `soar-impasse-{run_id}.json` with `type`, `run_id`, `cycle`, `wme_snapshot`
- [ ] AC-2.3: Impasse log file created when absent
- [ ] AC-2.4: Returned context pack is always a valid dict (no exception propagated, no None)
- [ ] AC-3.1: ChunkRecord with `learned: true` and `rule_id` prefixed `"chunk-"` appended on non-blocked outcome when chunking enabled
- [ ] AC-3.2: No ChunkRecord written when `outcome["status"]` is `"BLOCKED"` or `"ESCALATED"`
- [ ] AC-3.3: Chunking skipped silently when `episodic-index-{run_id}.json` is absent
- [ ] AC-3.4: No ChunkRecord written when `chunking_enabled: false`
- [ ] AC-3.5: Newly written ChunkRecord is available for matching on next `enrich_context` call
- [ ] AC-4.1: New run_id → file created with exactly SEED_RULES and no ChunkRecords
- [ ] AC-4.2: At least 5 seed rules; each covers at least one Tier 1 or Tier 2 WME attribute
- [ ] AC-4.3: Existing file loaded on subsequent calls; seed rules not overwritten
- [ ] AC-5.1: `actr_buffers` appears exactly once in returned dict; no original context_pack key present alongside it
- [ ] AC-5.2: Returned dict from `actr_buffer.enrich_context` does NOT contain `role`, `task`, `spec_text`, `prior_artifacts`, `constitution`, `active_goal`, or any other input key
- [ ] AC-5.3: Six-overlay stack token overhead ≤ 25% net-new relative to pre-overlay baseline
- [ ] AC-6.1: Exception in `enrich_context` caught by COMMANDER; dispatch proceeds without `soar_state`
- [ ] AC-6.2: Exception in `update_soar_memory` caught by COMMANDER; dispatch outcome record preserved; no run state corruption
- [ ] gitignore: `git check-ignore -v .specify/squad/soar-procedural-*.json` returns a match; no runtime artifacts in `git status` after a test run

---

## Section 4: Risk Matrix

### T-027: Security helper `_validate_run_id`

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| RAR-001 path traversal | HIGH | If `_validate_run_id` is incomplete or not called by all path helpers, a malicious `run_id` could write outside `.specify/squad/` | All path helper functions must call `_validate_run_id` as their first line; BUILD must verify every path-building function has this call |
| Overly restrictive regex | LOW | Rejecting valid run_id formats from COMMANDER state.json | Test `_validate_run_id` with real run_id samples from prior spec runs |

---

### T-028: SEED_RULES + ProceduralMemoryStore init

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| seed-001 impasse coverage gap | LOW | If `active_goal` is ever absent from context_pack, all 5 seed rules will fail to match | Per spec: `active_goal` is Tier 1 (always present); BUILD should add a comment noting this assumption (A-003) |
| Config-absent default | LOW | `_load_config()` must return `chunking_enabled: false` when `ca_overlays.soar` section is absent | Do not add the key to `squad-config.yml`; verify default-false behavior with a config-absent test case |
| ProceduralMemoryStore schema drift | MEDIUM | `last_matched_rule_id`, `last_cycle`, `last_wme_snapshot` fields (required by T-033) must be initialized to `null` in newly created stores | BUILD must include all three metadata fields in the store template returned by `_load_procedural_store` on first call |

---

### T-029: WME extraction `_extract_wmes`

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| R-006: `actr_buffers` value sentinel matching | MEDIUM | `actr_buffers` is a complex dict; JSON-serialized truncation at 200 chars is not stable for sentinel matching | Seed rules must use presence-only conditions for `actr_buffers` (no `value` field); BUILD must enforce this in T-028 SEED_RULES |
| `active_goal` sourcing from wrong location | HIGH | **Critical** — `active_goal` must be sourced from `context_pack["active_goal"]` (top-level), NOT from inside `context_pack["actr_buffers"]["goal"]` | Enforced by plan.md Section 4.4 constraint; BUILD must not attempt to read inside `actr_buffers` to find `active_goal` |

---

### T-030: Match-Select-Apply cycle

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| 200-char truncation with long operator names | MEDIUM | `operator_applied` values longer than 64 chars must be hard-sliced BEFORE serializing the mandatory-fields-only fallback dict | BUILD must truncate `operator_applied` to `rule_id[:64]` in the fallback path — not after building the full dict |
| Fallback-path test coverage | MEDIUM | The 200-char fallback path is exercised only when the full soar_state exceeds 200 chars — easy to miss in basic testing | BUILD must write a test case where `actions` payload is large enough to trigger the fallback |
| Confidence float comparison stability | LOW | Float equality on argmax can be platform-sensitive at edge values | Use `max()` with `key=lambda r: r["confidence"]` and verify first-match tie by preserving list insertion order |

---

### T-031: Impasse handling

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| Impasse log file concurrent write | LOW | A-005 confirms sequential dispatch; no concurrent write risk in v1 | No additional mitigation needed; comment referencing A-005 should appear near the log write |
| `wme_snapshot` serialization of large values | LOW | WME values are already truncated to 200 chars in `_extract_wmes`; wme_snapshot uses these truncated values | No additional risk; truncation in T-029 bounds this |

---

### T-032: `enrich_context` public function

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| Cycle counter not persisted on impasse | MEDIUM | If `_save_procedural_store` is only called on rule-match paths, cycle count and WME snapshot will not be updated after impasses | BUILD must call `_save_procedural_store` unconditionally at step 8, regardless of whether a rule matched or an impasse occurred |
| FR-CAO-006 compliance | HIGH | `enrich_context` must never write to `state.json` or `reasoning-journal.json` | Enforced by write-only to `soar-procedural-*.json` and `soar-impasse-*.json`; `# Does NOT modify COMMANDER state.` comment required in docstring |
| Prior overlay key preservation | MEDIUM | Step 9 (`dict(context_pack)` merged with `{"soar_state": ...}`) must not overwrite any prior overlay key | `soar_state` key confirmed non-conflicting with prior overlays (A-010 validated); no special handling needed |

---

### T-033: Chunking engine `_build_chunk` + `update_soar_memory`

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| OQ-005 implementation — Option B verbatim | HIGH | ChunkRecord `conditions` must be copied verbatim from triggering rule's `conditions` list (plan.md Section 2 resolution); any deviation from this produces incorrectly generalized chunks | BUILD must copy `matched_rule["conditions"]` directly without modification; do not add or remove conditions |
| `last_matched_rule_id` null on first call | MEDIUM | If `update_soar_memory` is called before the first `enrich_context` call, `last_matched_rule_id` will be `null` in the store; `find rule by null` must be handled gracefully | BUILD must guard: if `last_matched_rule_id is None`, skip chunking silently and return without writing |
| `last_wme_snapshot` missing from older stores | LOW | If a store was created by an earlier version of the code that did not persist `last_wme_snapshot`, the field may be absent | BUILD should use `.get("last_wme_snapshot", {})` with a fallback to empty dict |
| Chunking disabled by default — test coverage | MEDIUM | With `chunking_enabled: false` (the default), AC-3.1 through AC-3.5 are only testable by temporarily enabling the flag | BUILD must test chunking paths with `chunking_enabled: true` in a controlled test context; the default must remain false in `squad-config.yml` |

---

### T-034: `actr_buffer.py` ISS-004 fix

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| **CRITICAL: downstream impact on SOAR WME extraction** | HIGH | After the fix, `active_goal` is NO LONGER in `actr_buffer.enrich_context`'s returned dict. COMMANDER merges the result, so `context_pack["active_goal"]` remains present at position 6 (SOAR). BUILD must verify this merge behavior in COMMANDER's dispatch loop and confirm `_extract_wmes` sources `active_goal` from `context_pack["active_goal"]` (top-level), not from inside `actr_buffers`. | Read COMMANDER's dispatch loop to confirm the merge-on-assignment idiom (`context_pack = overlay.enrich_context(context_pack, run_id)`) preserves prior keys; do not refactor the merge idiom |
| Existing tests asserting original keys preserved | MEDIUM | Tests that assert `actr_buffer.enrich_context` returns `role`, `task`, `spec_text`, etc. will fail after the fix | BUILD must locate all such test files and update the assertions before committing; check `scripts/ca/tests/` or equivalent test directories |
| Local variable scope in fixed return | LOW | `buffers` and `retrieval_buffer` must be in scope at the point of the new return statement | BUILD must confirm both variables are assigned before line 172 in the current code and are not conditional |

---

### T-035: COMMANDER.md amendment

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| Position-6 availability | LOW | plan.md confirms position 6 is available (feasibility.md Section 1.3); no conflict expected | Verify by reading COMMANDER.md pre-dispatch block before inserting |
| try/except pattern consistency | LOW | Exception handling for position-6 `enrich_context` must match the style of existing COMMANDER error handling | Read COMMANDER.md's existing try/except patterns (if any) before writing the amendment; match the logging call format exactly |
| `squad-config.yml` — no new key | LOW | FR-SOAR-007 / plan.md Section 7.4 explicitly prohibits BUILD from adding `ca_overlays` to `squad-config.yml` | BUILD must NOT modify `squad-config.yml`; the overlay defaults to `chunking_enabled: false` when the key is absent |

---

## Summary

**Total tasks**: 9 (T-027 through T-035)
**Critical path length**: 6 sequential steps (T-027 → T-029 → T-030 → T-032 → T-033 → T-035)
**Parallelizable after T-027**: T-028, T-029, T-031 can all proceed in parallel; T-034 is fully independent
**FR coverage**: All 13 FRs (FR-SOAR-001 through FR-SOAR-013) covered
**AC coverage**: All 25 ACs covered across the 9 tasks

### Tasks that must be sequenced with care

1. **T-027 must be first** — all other `soar.py` tasks import its helpers; no `soar.py` task can start without it.
2. **T-034 must not be merged before verifying test suite** — the ISS-004 fix changes a public contract; existing tests asserting original key preservation must be updated in the same commit or the test suite will fail.
3. **T-033 depends on the `last_matched_rule_id`/`last_wme_snapshot` schema established in T-028** — if T-028 does not initialize these metadata fields to `null` in the store template, T-033's `update_soar_memory` will encounter `KeyError` at runtime. BUILD must treat the ProceduralMemoryStore JSON schema (plan.md Appendix B) as normative and implement it fully in T-028 before starting T-033.
4. **T-030 truncation algorithm** — the mandatory-fields-only fallback for `soar_state > 200 chars` must truncate `operator_applied` to 64 chars before re-serializing; performing the truncation after re-serializing the mandatory dict will not correctly handle the edge case where `rule_id` itself exceeds 64 characters.

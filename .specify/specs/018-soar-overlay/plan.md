# Implementation Plan — Spec 018: SOAR Cognitive Architecture Overlay

**Role**: ARCHITECT (HOW agent)
**Date**: 2026-04-03
**Spec**: 018-soar-overlay
**Verdict upstream**: CONDITIONAL — all conditions resolved herein
**Human override**: P-006 authorized 2026-04-03

---

## Section 1: Architecture Overview

### 1.1 File List

| File | Action | Description |
|------|--------|-------------|
| `scripts/ca/soar.py` | CREATE | New SOAR overlay module (~270 lines) |
| `scripts/ca/actr_buffer.py` | MODIFY | ISS-004 fix: 4–8 lines changed |
| `COMMANDER.md` | MODIFY | Position-6 amendment: ~40 lines added |
| `.specify/squad/soar-procedural-{run_id}.json` | RUNTIME ARTIFACT | ProceduralMemoryStore; gitignored by existing `.specify/squad/` exclusion |
| `.specify/squad/soar-impasse-{run_id}.json` | RUNTIME ARTIFACT | Impasse event log; gitignored by same exclusion |

No new directories. No new gitignore entries required — `.specify/squad/` exclusion already covers both runtime files (NFR-SOAR-002 confirmed).

### 1.2 `soar.py` Module Structure

The module exports exactly two public functions and has no importable classes. All other identifiers are module-private (prefixed `_`). Stdlib imports only: `json`, `os`, `re`, `datetime` (NFR-SOAR-001 confirmed).

```
soar.py
├── MODULE DOCSTRING          — T-028, ADR-005, P-006 override notice
├── IMPORTS                   — json, os, re, datetime (stdlib only)
├── SEED_RULES                — list[dict], 5 hand-coded seed rules (constant)
├── _repo_root()              — filesystem traversal to locate .git root
├── _validate_run_id()        — security guard: path traversal mitigation
├── _procedural_path()        — returns .specify/squad/soar-procedural-{run_id}.json
├── _impasse_path()           — returns .specify/squad/soar-impasse-{run_id}.json
├── _episodic_index_path()    — returns .specify/squad/episodic-index-{run_id}.json
├── _load_config()            — reads ca_overlays.soar.chunking_enabled from squad-config.yml
├── _load_procedural_store()  — load-or-initialize with SEED_RULES
├── _save_procedural_store()  — atomic write to soar-procedural-{run_id}.json
├── _extract_wmes()           — context_pack → list of WME dicts
├── _match_rules()            — linear scan: confidence-ranked, first-match tie resolution
├── _apply_operator()         — merge payload, enforce 200-char soar_state cap
├── _log_impasse()            — append ImpasseEvent to soar-impasse-{run_id}.json
├── _build_chunk()            — construct ChunkRecord from successful episode
├── enrich_context()          — PUBLIC: full MSA cycle
└── update_soar_memory()      — PUBLIC: post-dispatch learning hook
```

### 1.3 `actr_buffer.py` ISS-004 Change (exact location)

**File**: `scripts/ca/actr_buffer.py`

**Current line 172**:
```
enriched = dict(context_pack)
```
This copies all input keys from `context_pack` into `enriched`, then line 173 adds `actr_buffers` alongside them — violating FR-SOAR-011 (AC-5.1, AC-5.2).

**Change**: Replace lines 172–180 (the `enriched = dict(context_pack)` construction and its `return enriched`) with a return that emits ONLY `actr_buffers` as the overlay-added key, with no original context_pack keys carried forward.

The conceptual fixed return:
```
return {"actr_buffers": { ... buffers dict ... }}
```

No keys from the original `context_pack` are included in the returned dict. The caller (COMMANDER) is responsible for merging overlay output into the running context_pack (the `context_pack = overlay.enrich_context(context_pack, run_id)` idiom at the call site already handles this correctly — the issue is the overlay itself was doing the merge internally, causing duplication).

**Lines changed**: Lines 172–180 only. Lines 1–171 (TF-IDF helpers, buffer classification, eviction logic) are unchanged.

**Test impact**: Any existing test that asserts original keys (`role`, `task`, `spec_text`, etc.) are present in the returned dict will fail after the fix. BUILD must locate and update such tests before committing.

### 1.4 `COMMANDER.md` Amendment

**File**: `COMMANDER.md`

**Amendment 1 — Pre-Dispatch Sequence**: After line 51 (the `episodic_memory.enrich_context(...)` call at position 5), insert position 6 as described in Section 7 below.

**Amendment 2 — Post-Dispatch Sequence**: After line 83 (the comment `# ACT-R Buffer and LIDA Broadcast: no post-dispatch action required.`), insert the `soar.update_soar_memory(outcome, run_id)` call and comment as described in Section 7 below.

**Amendment 3 — Overlay Specifications table**: After the position-5 Episodic Memory entry (line 160), insert a new overlay specification entry for position 6 (SOAR) as described in Section 7 below.

---

## Section 2: OQ-005 Resolution — Chunking Generalization Strategy

**Status**: RESOLVED-BY-ARCHITECT-DESIGN-DECISION (2026-04-03)

### Decision: Option B — Triggering Rule's Conditions Only

The ChunkRecord's `conditions` list is constructed from the `conditions` list of the matched production rule (the rule that was selected as the active SOAR operator for the successful dispatch). No additional WMEs are added to the conditions list.

### Rationale

Option A (all WMEs at dispatch time) produces overly specific chunks. A chunk that requires the presence of all five overlay keys simultaneously will only fire in near-identical future contexts, making it effectively dead weight for early-run dispatches where some overlays have not yet contributed.

Option C (minimal set: `active_goal` + agent_type) is maximally general but risks over-firing. `agent_type` is not a standard WME attribute in the current Tier 1/2/3 classification — adding it would require extending the WME extraction logic beyond what FR-SOAR-003 specifies, adding implementation risk.

Option B (triggering rule's conditions) captures exactly the conditions that caused the rule to fire, which is the semantically correct definition of "what caused this outcome." It preserves the matched rule's generalization level — if the triggering rule matched on presence-only conditions, the chunk does too. If the triggering rule matched on a value sentinel, the chunk inherits that specificity. This is the closest analog to canonical SOAR's chunking procedure ("backtracing the justification of a result").

Chunk `confidence` is initialized to `0.6`. This is deliberately below the seed rule confidence range (see SEED_RULES in Section 6, which use 0.7–0.9) so that newly learned chunks do not displace well-validated seed rules when confidence values are equal on a present-but-unresolved tie.

### ChunkRecord Dict Schema

```json
{
  "rule_id":    "chunk-{run_id}:{cycle}",
  "conditions": [ { "attr": "active_goal" }, ... ],
  "actions":    { "soar_state_hint": "<string>", ... },
  "confidence": 0.6,
  "learned":    true,
  "episode_id": "{run_id}:{cycle}"
}
```

Field constraints:
- `rule_id` is unique within the ProceduralMemoryStore; format `chunk-{run_id}:{cycle}` guarantees uniqueness within a run.
- `conditions` is copied verbatim from the triggering rule's conditions list.
- `actions` is the soar_state enrichment payload that was applied on the successful dispatch (the `payload` from the winning operator).
- `confidence` is always `0.6` for v1 chunks (fixed initial value; no increment formula in v1 — post-MVP per spec scope).
- `learned` is always `true` and immutable.
- `episode_id` links the chunk to its originating dispatch.

---

## Section 3: OQ-007 Resolution — EpisodicIndex Schema

**Status**: RESOLVED-BY-CODE-INSPECTION (2026-04-03)
**Source**: `scripts/ca/episodic_memory.py` lines 38–43 (`_load_index`, `_save_index`) and lines 99–109 (`index_artifact`)

### EpisodicIndex JSON Schema

File path: `.specify/squad/episodic-index-{run_id}.json`

The file is a JSON array. Each element is a flat dict with exactly four fields:

```json
[
  {
    "agent_type":        "<string>  — agent codename, e.g. 'SCOUT', 'BUILD'",
    "artifact_path":     "<string>  — relative path to produced artifact",
    "stage_timestamp":   "<float>   — Unix timestamp (time.time())",
    "artifact_category": "<string>  — 'spec', 'tasks', 'report', etc."
  }
]
```

When the index is empty (no dispatches yet in the run), the file contains `[]`. There are no nested objects. There are no additional fields written by `episodic_memory.index_artifact()`.

### Fields ChunkingEngine Reads

`update_soar_memory` reads the episodic index for one purpose only: to confirm the most recent episode that corresponds to the current `run_id`. ChunkingEngine reads the following fields per entry:

- `agent_type` — to locate entries relevant to the current dispatch context (optional use in v1; not required for condition construction under Option B).
- `stage_timestamp` — to identify the most recent episode (max by timestamp).
- `artifact_category` — available for future chunk condition enrichment (post-MVP one-level WME flattening); not used in v1 condition construction.

In v1 (Option B chunking), the episodic index is read to confirm the index exists and is non-empty. The actual entry content is not used to construct ChunkRecord conditions — conditions come from the triggering rule. The index read serves as a runtime presence check aligned with AC-3.3.

### Fallback: Index File Absent (AC-3.3)

If `episodic-index-{run_id}.json` does not exist at the path returned by `_episodic_index_path(run_id)`, the ChunkingEngine skips chunking entirely and returns without raising an exception or writing any record. No warning is logged. The ProceduralMemoryStore is not modified. This is the canonical silent-skip behavior specified by AC-3.3.

---

## Section 4: `soar.py` Component Design

### 4.1 `_validate_run_id(run_id)`

Accepts a `run_id` string and raises `ValueError` if the string contains path-traversal characters or patterns that could cause the procedural store or impasse log paths to resolve outside the `.specify/squad/` directory. Specifically, the function rejects any `run_id` containing: `..`, `/`, `\`, null bytes, or any character not in `[a-zA-Z0-9_\-.]`. This mitigates RAR-001 (path traversal on run-scoped file writes). All other path-constructing helpers call `_validate_run_id` before building the path. Maximum length: 128 characters. If validation passes, the function returns `None` silently.

### 4.2 `_load_procedural_store(run_id)`

Reads `soar-procedural-{run_id}.json` from `.specify/squad/`. If the file exists, it is loaded and its `rules` list is returned. If the file does not exist (first call for this `run_id`), the function initializes a new store dict containing only the hand-coded `SEED_RULES`, writes it to disk via `_save_procedural_store`, and returns the newly written store dict. This create-if-absent, do-not-overwrite pattern is identical to `goal_stack._load_stack()` (lines 55–60) and `episodic_memory._load_index()` (lines 38–43). The returned value is always a dict with at minimum the keys `run_id`, `last_updated`, and `rules`.

### 4.3 `SEED_RULES` Constant

A module-level list of exactly 5 hand-coded production rule dicts, hard-coded in `soar.py`. Each rule follows the ProductionRule schema from spec section "Key Entities". The 5 rules cover the combinations of Tier 1 and Tier 2 WME presence needed to ensure impasse rate < 100% across common dispatch patterns. The full schema and individual rule designs are specified in Section 6. The constant is named `SEED_RULES` (uppercase, module-level) so that it is visible to tests without instantiating the overlay.

### 4.4 `_extract_wmes(context_pack)`

Iterates over a fixed set of recognized WME attribute names in declaration order: `active_goal` (Tier 1), then `actr_buffers`, `gwt_workspace`, `episodic_prior_artifact` (Tier 2), then `lida_broadcast` (Tier 3). For each attribute name, if the key is present in `context_pack`, a WME dict is constructed: `{"id": "<attr>-wme", "attr": "<attr>", "value": <coerced_value>}`. The `value` field is produced by: (1) if the context_pack value is a dict or list, `json.dumps()` it; (2) cast to `str`; (3) truncate to 200 characters. Keys that are NOT in the recognized set of 5 WME attributes are silently ignored — they do not produce WMEs. This behavior is required by AC-1.6. The function returns a list of WME dicts containing only those attributes that were present in the context_pack (0 to 5 elements).

**Key constraint for BUILD**: After the ISS-004 fix, the ACT-R overlay returns ONLY `{"actr_buffers": ...}`. COMMANDER's dispatch loop performs `context_pack = actr_buffer.enrich_context(context_pack, run_id)` which merges the result into the running context_pack, so `context_pack["actr_buffers"]` will be present at position 6 (SOAR). The `active_goal` key is injected at position 1 (Goal Stack overlay) and will be present at `context_pack["active_goal"]` — a dict `{goal_text, priority, depth}`. WME extraction for `active_goal` must read from `context_pack["active_goal"]` directly (not from inside `actr_buffers`). See Section 5 for the downstream constraint on `active_goal` WME sourcing.

### 4.5 `_match_rules(wmes, rules)`

Performs a linear scan over the `rules` list (ordered list of ProductionRule dicts loaded from ProceduralMemoryStore). For each rule, evaluates all conditions in the rule's `conditions` list against the `wmes` list. A condition `{"attr": A}` matches if any WME in `wmes` has `attr == A`. A condition `{"attr": A, "value": V}` matches if any WME has `attr == A` AND `V` is a substring of that WME's `value` field. A rule is "fully matched" if every condition in its list is matched. Collects all fully matched rules, then selects the one with the highest `confidence` float. On tie (equal confidence), the rule appearing first in the list wins — no ImpasseEvent is created for ties (FR-SOAR-006). Returns the single winning rule dict, or `None` if no rule fully matches. The scan has O(R × C × W) complexity where R = rule count, C = max conditions per rule, W = WME count; for ≤50 rules, ≤10 conditions, ≤5 WMEs this is comfortably within the 100ms budget (NFR-SOAR-003).

### 4.6 `_apply_operator(operator, context_pack)`

Receives the winning ProductionRule dict (the operator) and the current context_pack. Constructs the `soar_state` dict by merging four mandatory fields with the operator's `actions` payload. Mandatory fields: `operator_applied` (the rule's `rule_id`, truncated to 64 chars), `impasse` (`false`), `cycle` (current integer cycle count), `wme_count` (count of WMEs in the current working memory). After constructing the full `soar_state`, checks `len(json.dumps(soar_state)) <= 200`. If the check fails, the function falls back to the mandatory-fields-only dict, truncating `operator_applied` to 64 characters (FR-SOAR-008, AC-1.7). Returns the final `soar_state` dict. Does NOT write to `state.json`. Does NOT modify context_pack in-place — returns only the `soar_state` value for the caller to merge.

### 4.7 `_log_impasse(run_id, wmes, cycle)`

Constructs an `ImpasseEvent` dict with fields: `type` (always `"no-operator"`), `run_id`, `cycle`, `wme_snapshot` (a dict mapping each WME's `attr` to its `value`). Loads the existing impasse log from `soar-impasse-{run_id}.json` (as a list; creates empty list if file absent — AC-2.3). Appends the new ImpasseEvent to the list. Writes the updated list back to `soar-impasse-{run_id}.json`. Returns `None`. This is the standard append-only JSON write pattern used by `episodic_memory.index_artifact()`. The four mandatory fields (`type`, `run_id`, `cycle`, `wme_snapshot`) satisfy NFR-SOAR-006.

### 4.8 `enrich_context(context_pack, run_id)`

The sole ADR-005 public entrypoint for context enrichment. Execution sequence:

1. Call `_validate_run_id(run_id)`.
2. Call `_load_procedural_store(run_id)` to get the current rule list (seeding on first call).
3. Call `_extract_wmes(context_pack)` to build the current working memory WME set.
4. Increment the cycle counter (read from the store's metadata; default 0 on fresh store).
5. Call `_match_rules(wmes, rules)` to find the winning rule.
6. If a winning rule is found: call `_apply_operator(winning_rule, context_pack)` to produce `soar_state` with `impasse: false`.
7. If no rule matches: call `_log_impasse(run_id, wmes, cycle)`; produce `soar_state` with `operator_applied: "default-no-match"`, `impasse: true`, `cycle`, `wme_count`.
8. Save the updated cycle count to the procedural store.
9. Construct the return dict: `dict(context_pack)` merged with `{"soar_state": soar_state}`.
10. Return the enriched dict.

The function does NOT write to `state.json` (FR-CAO-006 confirmed). All five prior overlay keys (`active_goal`, `actr_buffers`, `lida_broadcast`, `gwt_workspace`, `episodic_prior_artifact`) are preserved unchanged in the returned dict (AC-1.5).

**Note on cycle counter storage**: The cycle count is stored as a top-level field `cycle_count` in the ProceduralMemoryStore JSON (alongside `run_id`, `last_updated`, `rules`). It is incremented and written on every `enrich_context` call. This is append-safe because A-005 confirms sequential dispatch (no concurrent writes).

### 4.9 `_build_chunk(outcome, wmes, matched_rule, cycle)`

Constructs a ChunkRecord dict from a successful dispatch. Inputs: the `outcome` dict from COMMANDER, the `wmes` list from the most recent working memory, the `matched_rule` dict that was applied (the winning rule from the last `enrich_context` call), and the `cycle` integer. Output: a ChunkRecord dict conforming to the schema in Section 2. The `conditions` list is copied from `matched_rule["conditions"]` (Option B resolution for OQ-005). The `actions` dict is derived from `matched_rule["actions"]` (the operator payload that was applied). `rule_id` is `f"chunk-{run_id}:{cycle}"`. `confidence` is `0.6`. `learned` is `True`. `episode_id` is `f"{run_id}:{cycle}"`. Does NOT write to disk — returns the ChunkRecord dict for the caller to append.

**Design constraint**: `_build_chunk` requires the `matched_rule` from the most recent `enrich_context` call. `update_soar_memory` is called post-dispatch with the `outcome` but does NOT receive the context_pack or the matched_rule directly. The ProceduralMemoryStore must record the `last_matched_rule_id` and `last_cycle` as metadata fields so that `update_soar_memory` can reconstruct what was applied. BUILD must include these two metadata fields in the store schema and keep them updated on every `enrich_context` call.

### 4.10 `update_soar_memory(outcome, run_id)`

The second ADR-005 public entrypoint. Called by COMMANDER post-dispatch. Execution sequence:

1. Call `_validate_run_id(run_id)`.
2. Evaluate success criterion: if `outcome.get("status") in ["BLOCKED", "ESCALATED"]`, return `None` immediately (AC-3.2).
3. Call `_load_config()` to read `chunking_enabled`. If `false` (the default), return `None` immediately (AC-3.4, FR-SOAR-007).
4. Check for `episodic-index-{run_id}.json` via `_episodic_index_path(run_id)`. If the file does not exist, return `None` silently (AC-3.3).
5. Load the ProceduralMemoryStore to retrieve `last_matched_rule_id` and `last_cycle`.
6. Find the matched rule by `last_matched_rule_id` in the rules list.
7. Call `_build_chunk(outcome, wmes=[], matched_rule, cycle=last_cycle)` — WMEs are reconstructed from the stored `last_wme_snapshot` (BUILD must also persist the WME snapshot in metadata alongside `last_matched_rule_id`).
8. Append the ChunkRecord to the `rules` list.
9. Update `last_updated` timestamp.
10. Call `_save_procedural_store()`.
11. Return `None`.

Does NOT write to `state.json` (FR-CAO-006 confirmed).

---

## Section 5: `actr_buffer.py` ISS-004 Fix Design

### Exact Location of Bug

**File**: `/Users/ladislavbihari/myWork/competition/echelon-proto/scripts/ca/actr_buffer.py`

**Line 172** (confirmed by reading):
```python
enriched = dict(context_pack)
```
This line copies all keys from `context_pack` into the `enriched` dict. Line 173 then adds `actr_buffers` alongside the copied keys. The returned dict therefore contains both the original keys (e.g., `role`, `task`, `spec_text`, `constitution`, `active_goal`, and any other key present at call time) AND `actr_buffers` — violating FR-SOAR-011, AC-5.1, AC-5.2.

### Fixed Return Statement (conceptual)

Replace lines 172–180 with a single return statement that builds the output dict from scratch, containing only the `actr_buffers` key:

```
return {"actr_buffers": { "declarative": ..., "procedural": ..., "goal": ..., "imaginal": ..., "retrieval_buffer": ... }}
```

No variable named `enriched` is needed. The local variable `buffers` (populated in the classification step) and `retrieval_buffer` (populated in the TF-IDF step) are already in scope — the return statement accesses them directly.

The ISS-004 fix requires exactly the following changes:
1. Delete line 172 (`enriched = dict(context_pack)`).
2. Delete line 173 (`enriched["actr_buffers"] = { ... }`).
3. Replace lines 172–180 with `return {"actr_buffers": { ... }}`.
4. Add a comment on the return line referencing ISS-004 and FR-SOAR-011.

### Downstream Impact: Constraint for BUILD on SOAR WME Extraction

After the ISS-004 fix, COMMANDER's dispatch loop performs:
```python
context_pack = actr_buffer.enrich_context(context_pack, run_id)
```
This merges the returned `{"actr_buffers": ...}` into the running context_pack using the dict-update-on-assignment idiom at the call site. The result is that `context_pack["actr_buffers"]` is present and `context_pack["active_goal"]` is ALSO still present (it was injected by position 1 / goal_stack and is not removed by the ACT-R fix).

Therefore:
- `_extract_wmes(context_pack)` in `soar.py` reads `context_pack["active_goal"]` directly. It does NOT look inside `actr_buffers` for `active_goal`.
- `actr_buffers` contains a `goal` buffer whose entries are `{"key": "active_goal", "value": <the goal dict>}` — this is an internal ACT-R classification artifact. SOAR's WME extraction must not parse the interior of `actr_buffers` to find `active_goal`.
- The WME for `active_goal` is sourced from `context_pack["active_goal"]` (top-level key).
- The WME for `actr_buffers` is sourced from `context_pack["actr_buffers"]` (top-level key, value is a complex dict that will be JSON-serialized and truncated to 200 chars for the WME value field).
- Seed rules targeting `actr_buffers` MUST use presence-only conditions (`{"attr": "actr_buffers"}` with no `value` field) because the JSON-serialized truncation of `actr_buffers` is not stable enough for sentinel matching (R-006 from feasibility.md).

**BUILD MUST NOT** attempt to match `active_goal` by looking inside `context_pack["actr_buffers"]["goal"][i]["key"] == "active_goal"`. The top-level key is authoritative.

---

## Section 6: SEED_RULES Design (5 Rules)

All five seed rules have `learned: false`. All are initialized once on first `enrich_context` call for a new `run_id`. Confidence values are in the range 0.7–0.9 to ensure they consistently outscore learned chunks (0.6) in tie scenarios.

---

### Rule 1: Tier 1 Only — Dispatch with `active_goal` alone

**Scenario**: Earliest dispatch in a run, before any other overlay has contributed. Only the Goal Stack overlay has run.

```json
{
  "rule_id":    "seed-001",
  "conditions": [
    { "attr": "active_goal" }
  ],
  "actions": {
    "soar_state_hint": "goal-only context: proceed with primary goal"
  },
  "confidence": 0.70,
  "learned":    false
}
```

Fires whenever `active_goal` is present and no higher-confidence rule matches. Lowest seed confidence because it provides minimal disambiguation.

---

### Rule 2: Tier 1 + ACT-R — `active_goal` + `actr_buffers`

**Scenario**: Goal Stack and ACT-R overlays have both contributed. GWT, Episodic, and LIDA are absent or not yet triggered.

```json
{
  "rule_id":    "seed-002",
  "conditions": [
    { "attr": "active_goal" },
    { "attr": "actr_buffers" }
  ],
  "actions": {
    "soar_state_hint": "goal + typed buffers: structured retrieval available"
  },
  "confidence": 0.75,
  "learned":    false
}
```

Presence-only condition on `actr_buffers` (no value sentinel) per R-006 constraint.

---

### Rule 3: Tier 1 + GWT — `active_goal` + `gwt_workspace`

**Scenario**: Goal Stack and GWT overlays contributed. ACT-R and Episodic are absent (unusual but possible if ACT-R raises an exception that COMMANDER catches).

```json
{
  "rule_id":    "seed-003",
  "conditions": [
    { "attr": "active_goal" },
    { "attr": "gwt_workspace" }
  ],
  "actions": {
    "soar_state_hint": "goal + workspace: global broadcast context available"
  },
  "confidence": 0.75,
  "learned":    false
}
```

---

### Rule 4: All Tier 1 + Tier 2 — All four stable WMEs present

**Scenario**: All four overlays at positions 1–5 (excluding LIDA) contributed successfully. This is the expected steady-state for most dispatches after initial ramp-up.

```json
{
  "rule_id":    "seed-004",
  "conditions": [
    { "attr": "active_goal" },
    { "attr": "actr_buffers" },
    { "attr": "gwt_workspace" },
    { "attr": "episodic_prior_artifact" }
  ],
  "actions": {
    "soar_state_hint": "full Tier1+Tier2 context: all structured overlays active"
  },
  "confidence": 0.90,
  "learned":    false
}
```

Highest seed confidence. Expected to be the most commonly fired rule in steady-state runs.

---

### Rule 5: `lida_broadcast` Present — Tier 3 signal active

**Scenario**: COMMANDER has triggered a LIDA broadcast for this dispatch. The broadcast payload is present in context_pack.

```json
{
  "rule_id":    "seed-005",
  "conditions": [
    { "attr": "active_goal" },
    { "attr": "lida_broadcast" }
  ],
  "actions": {
    "soar_state_hint": "LIDA broadcast active: global conscious event in context"
  },
  "confidence": 0.80,
  "learned":    false
}
```

The `lida_broadcast` condition is Tier 3 (opportunistic). This rule only fires when LIDA is explicitly present. Confidence 0.80 ensures it outscores Rule 1 (Tier 1-only at 0.70) but yields to Rule 4 (full Tier 1+2 at 0.90) when `lida_broadcast` appears alongside all four Tier 2 keys.

---

### Seed Rule Summary

| rule_id | Conditions | Confidence | Expected firing scenario |
|---------|-----------|------------|-------------------------|
| seed-001 | `active_goal` | 0.70 | First dispatch, no other overlays yet |
| seed-002 | `active_goal` + `actr_buffers` | 0.75 | Goal + ACT-R only |
| seed-003 | `active_goal` + `gwt_workspace` | 0.75 | Goal + GWT only |
| seed-004 | `active_goal` + `actr_buffers` + `gwt_workspace` + `episodic_prior_artifact` | 0.90 | Steady-state full Tier 1+2 |
| seed-005 | `active_goal` + `lida_broadcast` | 0.80 | LIDA broadcast dispatches |

**Note on tie-breaking**: Rules 2 and 3 share confidence 0.75. If both match simultaneously (both `actr_buffers` and `gwt_workspace` present but `episodic_prior_artifact` absent), Rule 2 fires first per FR-SOAR-006 (first in load order). This is intentional — ACT-R buffer context is the tiebreaker over GWT when both are present without episodic memory.

**Coverage check**: Because `active_goal` is always present (Tier 1 anchor per spec glossary), seed-001 provides a universal fallback with confidence 0.70. Impasse is only possible if `active_goal` itself is absent from context_pack — an edge case outside normal operation. This satisfies MVP Success criterion ("at least one [seed rule] matches per ... impasse rate < 100%").

---

## Section 7: COMMANDER.md Amendment Design

### 7.1 Pre-Dispatch Sequence: Position 6 Hook

**Location in COMMANDER.md**: Line 51, after the position-5 `episodic_memory.enrich_context(...)` call (currently the last line of the pre-dispatch sequence code block, before the closing ` ``` `).

**Amendment text (paragraph-level)**: Add a `from scripts.ca import soar` to the import line at the top of the code block (alongside the existing imports). Then add the position-6 call immediately after position 5:

```python
# 6. SOAR Cognitive Architecture Overlay
context_pack = soar.enrich_context(context_pack, run_id)
```

The call is wrapped by COMMANDER in a try/except block so that any unhandled exception from `soar.enrich_context` does not block dispatch (NFR-SOAR-004, AC-6.1). The try/except pattern and exception logging text should match any existing error-handling convention in COMMANDER; BUILD should add a comment noting this requirement.

### 7.2 Post-Dispatch Sequence: `update_soar_memory` Hook

**Location in COMMANDER.md**: After line 83, the comment `# ACT-R Buffer and LIDA Broadcast: no post-dispatch action required.` This is the last line of the post-dispatch code block before the closing ` ``` `.

**Amendment text (paragraph-level)**: Add the following call as a new numbered post-dispatch entry:

```python
# 4. SOAR Memory — record successful episode for procedural learning
soar.update_soar_memory(outcome, run_id)
```

The call is wrapped in a try/except. An exception from `update_soar_memory` must not corrupt the dispatch outcome record or the run's `state.json` (AC-6.2). The comment must note this resilience requirement for COMMANDER's implementation.

### 7.3 Overlay Specification Table Entry

**Location in COMMANDER.md**: After the position-5 Episodic Memory specification table (currently ending at line 160), add a new section:

```markdown
### 6. SOAR Cognitive Architecture Overlay (`scripts/ca/soar.py`)

| Aspect | Detail |
|--------|--------|
| Pre-dispatch | `soar.enrich_context(context_pack, run_id)` |
| Post-dispatch | `soar.update_soar_memory(outcome, run_id)` |
| Injects | `context_pack["soar_state"]` = `{operator_applied, impasse, cycle, wme_count}` (≤200 chars serialized) |
| State files | `.specify/squad/soar-procedural-<run_id>.json` (ProceduralMemoryStore, gitignored) |
|              | `.specify/squad/soar-impasse-<run_id>.json` (ImpasseEvent log, gitignored) |
| Seed rules | 5 hand-coded rules initialized on first call for a run_id |
| Chunking | SOAR-inspired procedural learning; disabled by default (`ca_overlays.soar.chunking_enabled: false`) |
| Exception policy | Both enrich_context and update_soar_memory must be wrapped in try/except by COMMANDER; exceptions are logged and do not block dispatch (NFR-SOAR-004) |
| Constraint | Read-only on COMMANDER state. soar-procedural-*.json and soar-impasse-*.json are the only write targets. |
```

### 7.4 Configuration Note for COMMANDER.md and squad-config.yml

`squad-config.yml` does NOT currently have a `ca_overlays` section. The SOAR overlay reads this config key via `_load_config()`. The function must default to `chunking_enabled: false` when the key is absent (FR-SOAR-007: "if the `ca_overlays.soar` section or the `chunking_enabled` key is absent from `squad-config.yml`, the overlay defaults to `chunking_enabled: false`"). BUILD must NOT add a `ca_overlays` section to `squad-config.yml` as part of this implementation — the default-to-false behavior in `_load_config()` is sufficient and the config can be added by operators who wish to enable chunking.

---

## Appendix A: Constitution Compliance Confirmations

| Requirement | Status | Confirmation |
|-------------|--------|--------------|
| NFR-SOAR-001: stdlib only | CONFIRMED | `soar.py` imports: `json`, `os`, `re`, `datetime` only. No external packages. TF-IDF is not used in SOAR — presence+sentinel matching is pure Python. |
| FR-CAO-006: never writes state.json | CONFIRMED | `soar.py` writes only to `soar-procedural-{run_id}.json` and `soar-impasse-{run_id}.json` — both overlay-scoped, neither is `state.json` or `reasoning-journal.json`. Comment `# Does NOT modify COMMANDER state.` must appear in `enrich_context` docstring. |
| ADR-005: uniform interface | CONFIRMED | Public exports: `enrich_context(context_pack: dict, run_id: str) -> dict` and `update_soar_memory(outcome: dict, run_id: str) -> None`. No other public symbols. |
| NFR-SOAR-002: gitignore | CONFIRMED | `.specify/squad/` exclusion already covers runtime artifacts. No new gitignore entry required. |
| P-006 / P-023: build authorization | CONFIRMED | Override comment `Human override of P-006 authorized 2026-04-03 (user instruction: "build it anyway")` must appear in `soar.py` module docstring, matching the pattern in all 5 prior CA overlay files. |

---

## Appendix B: ProceduralMemoryStore JSON Schema

```json
{
  "run_id":              "<string>",
  "last_updated":        "<ISO 8601 timestamp>",
  "cycle_count":         "<integer — incremented each enrich_context call>",
  "last_matched_rule_id": "<string | null — rule_id of last winning rule>",
  "last_cycle":          "<integer | null — cycle number of last enrich_context call>",
  "last_wme_snapshot":   "<dict | null — {attr: value} map from last working memory>",
  "rules": [
    {
      "rule_id":    "<string>",
      "conditions": [ { "attr": "<string>", "value?": "<string>" } ],
      "actions":    { "<key>": "<value>" },
      "confidence": "<float 0.0–1.0>",
      "learned":    "<boolean>",
      "episode_id": "<string | null — null for seed rules>"
    }
  ]
}
```

The `last_matched_rule_id`, `last_cycle`, and `last_wme_snapshot` metadata fields are required by `_build_chunk` in `update_soar_memory` (see Section 4.9 / 4.10 constraint). They are `null` on a freshly initialized store and updated on every `enrich_context` call regardless of whether chunking is enabled.

---

## Appendix C: ImpasseEvent JSON Schema

```json
[
  {
    "type":         "no-operator",
    "run_id":       "<string>",
    "cycle":        "<integer>",
    "wme_snapshot": { "<attr>": "<value>", ... }
  }
]
```

File is a JSON array (append-only, same pattern as `episodic-index-{run_id}.json`). Created on first impasse for a run_id. Entries are never removed.

---

## Appendix D: OQ Resolution Summary

| OQ | Resolution | Method |
|----|-----------|--------|
| OQ-005 | Option B — triggering rule's conditions only; initial confidence 0.6 | RESOLVED-BY-ARCHITECT-DESIGN-DECISION |
| OQ-007 | Flat JSON list of `{agent_type, artifact_path, stage_timestamp, artifact_category}` records | RESOLVED-BY-CODE-INSPECTION (episodic_memory.py lines 38–50, 99–109) |

OQ-002, OQ-003, OQ-006 are NOT HOW-blockers per feasibility.md §4 and are not resolved here. They are tracked in spec.md for post-MVP investigation.

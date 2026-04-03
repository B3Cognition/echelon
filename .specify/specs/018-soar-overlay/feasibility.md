# Feasibility Assessment — Spec 018: SOAR Cognitive Architecture Overlay

**Role**: GATEKEEPER (ASSESS)
**Date**: 2026-04-03
**Spec**: 018-soar-overlay — 6th CA Overlay
**Verdict**: CONDITIONAL
**WHY3 scores**: Overall 78.2%, Structure 82.0%, Testability 80.0% (all gates passed)

---

## 1. Implementation Complexity

### 1.1 SOAR Core — Match-Select-Apply Cycle (`soar.py`)

**Rating: MEDIUM**

The core cycle is algorithmically straightforward: load a JSON rule store, construct WMEs from a fixed set of context_pack keys, perform a linear scan with condition matching (presence + optional substring sentinel), apply argmax-confidence selection, and merge the winning operator payload into the context_pack. All of this is achievable with stdlib only (`json`, `os`, `re`, `datetime`).

Complexity contributors:
- WME extraction must handle Tier 1/2/3 key classification plus nested-dict serialization (Tier 2 values like `actr_buffers` are dicts — string-coerce + truncate to 200 chars).
- The 200-character payload hard cap (FR-SOAR-008) requires a post-construction size check and a truncation-to-mandatory-fields fallback path.
- Chunking logic (`update_soar_memory`) requires reading the EpisodicIndex JSON (OQ-007, currently unresolved) and appending a ChunkRecord to the ProceduralMemoryStore; this is append-only and structurally simple.
- The seed rule set (≥5 rules, FR-SOAR-009) must be designed by the developer. The rules themselves are pure data (JSON dicts); the design decision is the main work.
- ProceduralMemoryStore initialization with idempotency guard (create-if-absent, do-not-overwrite) follows the exact same pattern as `episodic_memory.py` (lines 38–43) and `goal_stack.py` (lines 55–60) — well-understood within the codebase.

No canonical SOAR libraries, Rete network, or multi-cycle elaboration are required. Single-pass linear scan over ≤50 rules is comfortably within the 100ms budget (NFR-SOAR-003) with no optimization needed.

**Rationale for MEDIUM (not LOW)**: the 200-char payload cap with truncation fallback, the nested-dict WME serialization edge case, the EpisodicIndex dependency in chunking, and the seed rule design all add non-trivial decision points beyond pure boilerplate.

---

### 1.2 ACT-R Buffer Fix — ISS-004 Option A (`actr_buffer.py`)

**Rating: LOW**

The bug is clearly identified: `actr_buffer.py` line 172 does `enriched = dict(context_pack)` which copies all input keys, then adds `actr_buffers` alongside them. FR-SOAR-011 requires that the returned dict contains only `actr_buffers` as the overlay-added key — all pre-existing input keys must be removed.

The fix is a return-value reconstruction: instead of `enriched = dict(context_pack)`, build the return dict as `{k: v for k, v in context_pack.items() if k not in input_keys} | {"actr_buffers": ...}` — or equivalently, start from an empty dict and only add `actr_buffers`. The fix requires reading the current file carefully to confirm no other input keys need to be preserved.

Estimated lines changed: **4–8 lines** (swap the `enriched = dict(context_pack)` construction and return statement; add a comment referencing ISS-004). No logic changes to TF-IDF, buffer classification, or eviction policy.

**Caveat**: The fix changes the public contract of `actr_buffer.enrich_context`. Any existing tests that assert original keys are preserved will fail. ARCHITECT must confirm whether tests exist.

---

### 1.3 COMMANDER Integration (`COMMANDER.md`)

**Rating: LOW**

`COMMANDER.md` has a clear, well-structured template for overlay documentation (positions 1–5 documented consistently). Position 6 is available — confirmed by reading COMMANDER.md: the pre-dispatch sequence currently ends at position 5 (Episodic Memory), and no other overlay occupies position 6.

Two amendments are needed:
1. Add position 6 to the Pre-Dispatch Sequence code block: `context_pack = soar.enrich_context(context_pack, run_id)`.
2. Add a post-dispatch call in the Post-Dispatch Sequence block: `soar.update_soar_memory(outcome, run_id)`.
3. Add an overlay specification table for SOAR (matching the format of positions 1–5).

**Estimated effort**: ~40 lines of documentation added. No structural changes to existing COMMANDER.md content.

---

## 2. Effort Estimates

### 2.1 `soar.py` Core (Match-Select-Apply + Seed Rules + Impasse + Chunking)

| Component | Estimated Lines |
|-----------|----------------|
| Module header, imports, constants | 15 |
| `_repo_root()`, `_procedural_path()`, `_impasse_path()` helpers | 20 |
| `_load_config()` — read `chunking_enabled` from `squad-config.yml` | 20 |
| `_load_store()` / `_save_store()` — ProceduralMemoryStore I/O | 20 |
| `_seed_rules()` — 5+ hand-coded seed rules as Python list-of-dicts | 40 |
| `_extract_wmes()` — Tier 1/2/3 key extraction with string-coerce + truncate | 30 |
| `_match_rule()` — single rule condition evaluation (presence + sentinel) | 20 |
| `_run_cycle()` — Match phase (scan all rules), Select phase (argmax + first-match tie), Apply phase (payload cap, truncation) | 40 |
| `_log_impasse()` — append ImpasseEvent to `soar-impasse-{run_id}.json` | 20 |
| `enrich_context()` — public entrypoint (init store, run cycle, merge soar_state) | 25 |
| `update_soar_memory()` — success criterion check, chunking_enabled guard, EpisodicIndex read, ChunkRecord construction, store append | 40 |
| **Total estimate** | **~270 lines** |

Comparable reference: `actr_buffer.py` = 181 lines (complex TF-IDF logic); `goal_stack.py` = 90 lines (simple). `soar.py` sits between these: more state management than `goal_stack.py`, less mathematical complexity than `actr_buffer.py`.

**Refined estimate: 240–290 lines.**

---

### 2.2 `actr_buffer.py` Fix (ISS-004 Option A)

**Estimated lines changed: 4–8 lines**

Specifically: replace the `enriched = dict(context_pack)` line and restructure the return to emit only `actr_buffers` as the overlay-added key. All other logic (TF-IDF, classification, eviction) is unchanged.

---

### 2.3 `COMMANDER.md` Amendment

**Estimated effort: ~40 lines added** (pre-dispatch block entry + post-dispatch block entry + overlay specification table). Draft time: ~20 minutes. No structural refactoring required.

---

## 3. Risk Assessment

The following three risks are rated highest and most directly affect ARCHITECT's design decisions.

### Risk 1: OQ-007 — EpisodicIndex Schema Unknown (MEDIUM)

**Rating: MEDIUM**

`update_soar_memory` must read `episodic-index-{run_id}.json` to construct ChunkRecord conditions (per AC-3.3: if file is absent, chunking is silently skipped). The actual JSON schema of this file is defined by `episodic_memory.py`'s `_save_index()` function and is visible from reading the code (lines 46–50, 100–109):

```
[
  {
    "agent_type": str,
    "artifact_path": str,
    "stage_timestamp": float,
    "artifact_category": str
  },
  ...
]
```

The schema is effectively resolved by reading the existing code — it is a flat list of dicts. The ARCHITECT can treat OQ-007 as RESOLVED: the EpisodicIndex schema is a list of `{agent_type, artifact_path, stage_timestamp, artifact_category}` records.

**Mitigation**: ARCHITECT documents the resolved schema in the HOW spec and closes OQ-007 as RESOLVED-BY-CODE-INSPECTION. This is not a blocker.

**Residual risk**: The ChunkRecord's `conditions` field population strategy (all WMEs vs. triggering rule conditions only vs. minimal set) remains governed by OQ-005. The EpisodicIndex schema itself does not block implementation; it only informs what data is available for generalization.

---

### Risk 2: OQ-005 — Chunking Generalization Strategy Unresolved (HIGH for chunking; LOW for MVP)

**Rating: HIGH for chunking path; LOW for overall MVP**

Three options exist for constructing ChunkRecord conditions:
- (a) All WMEs at dispatch time — maximally specific, low utility in future matches
- (b) Triggering rule's conditions only — captures what matched, but ignores broader context
- (c) Minimal set (`active_goal` + agent_type) — maximally general, high fire rate, risk of over-generalization

Because `chunking_enabled` defaults to `false` in v1 (FR-SOAR-007), this open question does NOT block the MVP implementation. ARCHITECT must make a design decision but it does not need to be empirically validated before BUILD — it only needs to be recorded in the HOW spec with a rationale.

**Recommended resolution for ARCHITECT**: Default to Option (b) — triggering rule's conditions — as a reasonable middle ground. Document it as a v1 approximation. Chunk confidence capped at 0.6 (below typical seed rule confidence) to prevent chunks from displacing well-designed seed rules.

**Mitigation**: Mark OQ-005 RESOLVED-BY-DESIGN in HOW spec with the chosen option and rationale. Not a HOW-blocker.

---

### Risk 3: Token Budget for 6-Overlay Stack (R-002) (MEDIUM)

**Rating: MEDIUM**

FR-SOAR-008 hard-caps `soar_state` at 200 characters serialized (~50 tokens). This is a strong mitigation for NFR-SOAR-005 (≤25% net-new token overhead). The mandatory-fields-only fallback further limits the worst case. The SOAR overlay's token contribution is therefore bounded and small.

The interaction risk is indirect: the ACT-R overlay's token eviction policy fires when total `actr_buffers` content exceeds the original context_pack token count. If `soar_state` (added by the SOAR overlay earlier in the chain — but SOAR runs at position 6, AFTER ACT-R at position 2) bloats subsequent context packs passed back to COMMANDER, the next dispatch cycle's ACT-R eviction threshold will be slightly higher, causing marginally more eviction.

However, since SOAR runs at position 6 (last before dispatch), it does not affect ACT-R's eviction calculation within the same dispatch cycle. The risk is minimal.

**Mitigation**: ARCHITECT confirms overlay ordering (SOAR at position 6, after ACT-R at position 2). The 200-char cap on `soar_state` is sufficient to keep 6-overlay stack overhead within NFR-SOAR-005 bounds. No additional design constraint needed.

---

## 4. Dependency Check — HOW-Blockers

### OQ-005 (Chunking Generalization Strategy)

**NOT a HOW-blocker.** Chunking is disabled by default (`chunking_enabled: false`). The chunking code must be implemented and functional, but the generalization strategy selection (option a/b/c) is an ARCHITECT design decision that can be made unilaterally within the HOW spec without awaiting further investigation. Recommended: Option (b) as documented in Risk 2 above.

### OQ-007 (EpisodicIndex Schema)

**NOT a HOW-blocker.** The schema is resolvable by code inspection of `episodic_memory.py` (lines 46–50, 100–109): a flat JSON list of `{agent_type, artifact_path, stage_timestamp, artifact_category}` records. ARCHITECT should close this as RESOLVED-BY-CODE-INSPECTION in the HOW spec.

### OQ-002 (COMMANDER context_pack keys per agent type) and OQ-003 (LIDA broadcast frequency)

**NOT HOW-blockers for implementation, but relevant for seed rule design.** The seed rules cover Tier 1 (`active_goal`) and Tier 2 (`actr_buffers`, `gwt_workspace`, `episodic_prior_artifact`) keys — all guaranteed-or-guarded. OQ-003 affects whether `lida_broadcast`-conditional seed rules are included in the initial set of 5. ARCHITECT may include one `lida_broadcast`-conditional rule as a lower-confidence rule (0.5) without risk, since its absence does not cause impasse (Tier 3 treatment per FR-SOAR-003).

### Remaining unresolved: R-006 (nested dict WME matchability)

The `actr_buffers` WME value will be a truncated JSON string fragment when string-coerced. Seed rules cannot meaningfully match on the ACT-R buffer content via value sentinels. The HOW spec should limit ACT-R-related seed rules to presence-only conditions (`{"attr": "actr_buffers"}` with no `value` sentinel). This is a design decision, not a blocker.

---

## 5. Priority Recommendation — MVP vs. Post-MVP Scope

### Confirmation: All 13 FRs are MVP Scope

| FR | Title | MVP Assessment |
|----|-------|---------------|
| FR-SOAR-001 | `enrich_context` runs Match-Select-Apply cycle | FEASIBLE in single pass |
| FR-SOAR-002 | ProceduralMemoryStore as run-scoped JSON | FEASIBLE — identical pattern to episodic_memory.py |
| FR-SOAR-003 | WME extraction from Tier 1/2/3 keys | FEASIBLE — 5 fixed keys, simple classification |
| FR-SOAR-004 | Argmax-confidence operator selection | FEASIBLE — trivial argmax over matched rules |
| FR-SOAR-005 | Impasse handling with ImpasseEvent logging | FEASIBLE — append-only JSON write, same as other overlays |
| FR-SOAR-006 | First-match tie-breaking (no tie-impasse) | FEASIBLE — preserve rule order, select first in case of tie |
| FR-SOAR-007 | `chunking_enabled` config flag, default false | FEASIBLE — regex config read follows gwt_workspace.py pattern |
| FR-SOAR-008 | `soar_state` 200-char hard cap with mandatory-fields fallback | FEASIBLE — post-construction size check, straightforward |
| FR-SOAR-009 | 5+ seed rules initialized on first call | FEASIBLE — inline data structure, no external source |
| FR-SOAR-010 | `update_soar_memory` with success criterion and ChunkRecord | FEASIBLE — simple condition + JSON append |
| FR-SOAR-011 | `actr_buffer.py` ISS-004 de-duplication fix | FEASIBLE — 4–8 line fix |
| FR-SOAR-012 | COMMANDER.md position-6 pre-dispatch amendment | FEASIBLE — position 6 confirmed available |
| FR-SOAR-013 | COMMANDER.md post-dispatch `update_soar_memory` amendment | FEASIBLE — follows post-dispatch pattern of other overlays |

All 13 FRs can be implemented in a single implementation pass. No FR requires a multi-sprint dependency chain.

### Post-MVP Items (correctly scoped out)

The following items from the spec's Post-MVP scope are correctly deferred and should not be included in the HOW spec:
- Chunking enabled by default
- Confidence increment formula for ChunkRecords
- One-level WME flattening for nested dict values
- Endocrine system wiring for impasse/chunking events
- Cross-run ProceduralMemoryStore persistence
- `max_rules` cap and pruning policy

Note: R-007 (unbounded ProceduralMemoryStore growth) is rated LOW likelihood for MVP-length runs. The HOW spec should include a comment noting the future `max_rules` cap without implementing it in v1.

---

## 6. Constitution Compliance Check

### NFR-SOAR-001 — stdlib only

**COMPLIANT by design.** No external packages are required. The Match-Select-Apply cycle uses only `json`, `os`, `re`, `datetime` (all stdlib). The TF-IDF-like matching is replaced by a simpler presence + substring sentinel approach requiring no `math` or `Counter`. Zero risk of accidental external import.

Verification path specified in the spec is correct: static analysis of import statements confirms compliance.

### FR-CAO-006 — read-only on `state.json`

**COMPLIANT.** `soar.py` writes only to:
- `.specify/squad/soar-procedural-{run_id}.json` (its own state file)
- `.specify/squad/soar-impasse-{run_id}.json` (its own impasse log)

Neither file is `state.json` or `reasoning-journal.json`. The pattern follows all five prior overlays exactly. ARCHITECT must include the explicit constraint comment (matching the `# Does NOT modify COMMANDER state.` pattern in `goal_stack.py` line 94 and `episodic_memory.py` line 64).

The spec's Out-of-Scope section explicitly prohibits "COMMANDER state.json reads or writes" — this is compliant with FR-CAO-006.

### ADR-005 — uniform interface

**COMPLIANT.** The spec prescribes the standard `enrich_context(context_pack, run_id) -> dict` signature (FR-SOAR-001) and a second function `update_soar_memory(outcome, run_id)` (FR-SOAR-010). The `enrich_context` signature is identical to all prior overlays (positions 1–5). The `update_soar_memory` function follows the same post-dispatch pattern as `goal_stack.update_goal_stack()` and `episodic_memory.index_artifact()`.

One minor interface deviation: `episodic_memory.enrich_context` takes an additional `agent_type` parameter beyond ADR-005's standard two-argument signature. `soar.enrich_context` conforms strictly to the two-argument standard — this is cleaner than the episodic overlay.

### P-006 / P-023 — Build Authorization

**COMPLIANT.** P-023 (Constitution Amendment 2, v1.2.0) explicitly authorizes implementation of CA overlays under human override "build it anyway" (2026-04-03). Spec 018 is the sixth CA overlay and falls under the same authorization that covered specs 014–017. ARCHITECT should include the P-006 override comment (matching the existing pattern in all five prior CA overlays: `Human override of P-006 authorized 2026-04-03`).

### P-012 — state.json single source of truth

**COMPLIANT.** The SOAR overlay's runtime files (`soar-procedural-*.json`, `soar-impasse-*.json`) are overlay-scoped state, not COMMANDER run state. This mirrors the prior overlays' scoped state files (`goal-stack-*.json`, `gwt-workspace-*.json`, etc.). No conflict with P-012.

### NFR-SOAR-002 — gitignore

**COMPLIANT.** The existing `.specify/squad/` gitignore exclusion (confirmed: `.gitignore` contains `.specify/squad/`) covers `soar-procedural-{run_id}.json` and `soar-impasse-{run_id}.json` by the wildcard entry `.specify/squad/`. No additional gitignore entry is needed. The spec's success criterion (`git check-ignore -v .specify/squad/soar-procedural-*.json` returning a match) will pass without any new gitignore configuration.

---

## 7. Summary Assessment

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Overall Feasibility | **CONDITIONAL** | Conditional on ARCHITECT resolving OQ-005 and OQ-007 by design decision (both closeable without additional investigation) |
| SOAR Core complexity | MEDIUM | Doable in one pass; ~270 lines |
| ACT-R fix complexity | LOW | 4–8 lines |
| COMMANDER amendment | LOW | ~40 lines |
| Constitution conflicts | NONE | All NFRs and FR-CAO-006 compliant |
| HOW-blockers | NONE | OQ-005 and OQ-007 are resolvable by ARCHITECT decision |
| MVP scope alignment | CONFIRMED | All 13 FRs feasible in single implementation pass |

**Conditions for proceeding to HOW (ARCHITECT):**
1. ARCHITECT must resolve OQ-005 by selecting a generalization strategy (recommended: Option b — triggering rule's conditions) and documenting the decision with rationale.
2. ARCHITECT must close OQ-007 as RESOLVED-BY-CODE-INSPECTION, citing the `episodic_memory.py` schema.
3. ARCHITECT must specify that seed rules targeting `actr_buffers` use presence-only conditions (no value sentinel) to avoid R-006 (nested dict matchability).
4. ARCHITECT must confirm that the ACT-R buffer fix (FR-SOAR-011) is tested against the existing overlay test suite; if tests assert original key preservation, they must be updated.

None of these conditions require human escalation. ARCHITECT may proceed autonomously.

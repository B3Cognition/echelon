# Contradictions and Gaps — Spec 018 (SOAR Cognitive Architecture Overlay)

**Produced by**: SYNTHESIZER (FUSE) — NEW document, unique to SYNTHESIZER  
**Date**: 2026-04-03 | **Spec**: 018-soar-overlay  
**Sources cross-referenced**: glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, reference-architectures.md, reasoning-journal.json (all SCOUT/DISCOVER)

---

## Summary Counts

| Category | Count |
|----------|-------|
| Contradictions (source A vs source B disagree) | 3 |
| Gaps (something in one source, missing from another) | 7 |
| Suspicious findings (potential inconsistencies) | 3 |
| Patterns from cross-source analysis | 4 |
| Typos / defects in source documents | 1 |

---

## Contradictions

### C-001: Tie Impasse Behavior — Overlay vs. Canonical SOAR
- **Source A (glossary.md, SCOUT):** "An impasse fires" when two operators are equally applicable (tie). ImpasseEvent type `"tie"` is defined.
- **Source B (mental-model.md, SCOUT — DecisionProcedure entity):** "tie_break: `first-match` when confidence values are equal." The decision procedure picks first-match on ties — does NOT fire an impasse.
- **Conflict type:** BEHAVIORAL CONTRADICTION — the glossary implies ties produce ImpasseEvents; the mental model says ties are resolved by first-match (no impasse).
- **Impact:** HOW spec must choose one behavior. If tie → impasse (canonical SOAR behavior): impasse log grows larger; tie detection must be implemented. If tie → first-match: simpler implementation but deviates from SOAR semantics.
- **Resolution recommendation:** The mental-model.md behavior (first-match on tie) is more consistent with the spirit of a context-enrichment overlay (both operators are valid; arbitrarily picking one is fine). The glossary's implied tie-impasse is more canonically correct. This is a design decision, not an implementation error.
- **Who resolves:** WHY1 / User (design decision)
- **Sources:** glossary.md §Preference (SCOUT), mental-model.md §DecisionProcedure (SCOUT)

---

### C-002: ImpasseEvent Type Set — Two vs. One Source-Defined Types
- **Source A (mental-model.md §ImpasseEvent, SCOUT):** Defines two types: `"no-operator"` and `"tie"`.
- **Source B (boundaries.md §SOAR Overlay Module, SCOUT):** States impasse occurs "when no production rule's conditions match" — describes only the no-operator case. Does not mention a tie-type impasse.
- **Conflict type:** INCOMPLETE — boundaries.md omits the tie-type impasse case. Either boundaries.md is incomplete, or the tie case is not an impasse in the overlay (consistent with C-001's mental-model behavior).
- **Impact:** boundaries.md's out-of-scope section should be explicit about whether tie → first-match (no impasse) is the intended behavior.
- **Who resolves:** WHY1 (resolve C-001 first; C-002 follows from that resolution)
- **Sources:** mental-model.md §ImpasseEvent (SCOUT), boundaries.md §SOAR Overlay Module (SCOUT)

---

### C-003: Chunking Trigger — Post-Dispatch vs. Within-Dispatch
- **Source A (mental-model.md §Concept Map, SCOUT):** Chunking described under "POST-DISPATCH (per agent, after result received)" — suggesting it runs after the agent returns its artifact.
- **Source B (mental-model.md §ChunkRecord, SCOUT):** States "Created post-dispatch when outcome is successful → appended to procedural memory JSON → available for matching in subsequent dispatches within the same run."
- **Source C (boundaries.md §SOAR Overlay Module, SCOUT):** "`update_soar_memory` called by COMMANDER post-dispatch" — consistent with post-dispatch.
- **Non-contradiction clarification:** These are consistent (all say post-dispatch). However, the mental-model.md §Behavioral Pattern 3 says "Post-dispatch: COMMANDER calls `update_soar_memory`" which implies COMMANDER must explicitly call it — this is an interface assumption that conflicts with no other source but is worth flagging as a gap (see G-003 below).
- **Status:** NOT a true contradiction — sources are consistent. Logged here for completeness; downgraded to gap.

---

## Gaps

### G-001: WME Pattern Schema (U-002) — Defined as Open but No Candidate Schema Provided
- **Present in:** unknowns.md (U-002, SCOUT) — identifies the gap and lists four options
- **Missing from:** glossary.md, mental-model.md, boundaries.md — none of these documents propose even a candidate schema
- **Impact:** WHY1 cannot challenge a schema that doesn't exist yet. WHAT cannot write acceptance criteria. HOW cannot implement matching.
- **SYNTHESIZER action:** unknowns.md (unified) includes a proposed minimal candidate schema for SCIENTIST evaluation. This is the only gap where SYNTHESIZER has synthesized a candidate resolution — clearly labeled for WHY1 to challenge.
- **Sources:** SCOUT unknowns.md (U-002)

---

### G-002: Confidence Increment Formula for SOAR Chunks — Defined as "increases" but Rate Not Specified
- **Present in:** mental-model.md §ChunkRecord (SCOUT) — "confidence starts at 0.6, increases with repeated successful application"
- **Missing from:** All other documents — no document specifies the increment amount, decay policy, or ceiling.
- **Impact:** HOW spec cannot implement confidence update without knowing the formula. Options: fixed increment (+0.05 per success), multiplicative scaling, Bayesian update.
- **Who resolves:** SCIENTIST / HOW spec author
- **Sources:** SCOUT mental-model.md §ChunkRecord

---

### G-003: COMMANDER Amendment Required — No Spec 018 COMMANDER.md Change Documented
- **Present in:** boundaries.md (SCOUT) — states COMMANDER is the sole caller of `enrich_context` and `update_soar_memory`
- **Missing from:** All documents — no document describes the specific COMMANDER.md lines that must be added to wire position-6 and the post-dispatch `update_soar_memory` call
- **Impact:** BUILD cannot wire the overlay without knowing exactly where in COMMANDER.md to add the calls. This is a prerequisite for deployment.
- **Who resolves:** HOW spec must include a COMMANDER.md amendment section
- **Sources:** SCOUT boundaries.md §COMMANDER

---

### G-004: DefaultOperator — Defined by Name Only, No Payload Specified
- **Present in:** mental-model.md §Behavioral Pattern 2 (SCOUT) — "DefaultOperator fires: injects a minimal `soar_state` dict with `operator_applied: 'default-no-match'`"
- **Missing from:** No document specifies the full DefaultOperator payload schema. What fields does it inject beyond `operator_applied`? Does it carry `impasse: true`? `wme_count`? `cycle`?
- **Impact:** HOW spec needs the complete DefaultOperator payload definition. Without it, BUILD will guess.
- **Who resolves:** HOW spec must define the complete DefaultOperator payload schema
- **Sources:** SCOUT mental-model.md §Behavioral Pattern 2

---

### G-005: EpisodicIndex Schema — Referenced but Not Described
- **Present in:** mental-model.md (SCOUT) — ChunkingEngine "reads EpisodicIndex for prior outcomes"; boundaries.md (SCOUT) — ChunkingEngine reads `episodic-index-{run_id}.json`
- **Missing from:** No document in spec 018 describes the EpisodicIndex JSON schema. What fields does it have? How does ChunkingEngine identify "successful" episodes from its structure?
- **Impact:** ChunkingEngine cannot be implemented without knowing the EpisodicIndex schema. This may be defined in spec 017 — if so, spec 018 needs a reference, not a re-definition.
- **Who resolves:** SCIENTIST (read spec 017 research.md or episodic_memory.py to extract the EpisodicIndex schema)
- **Sources:** SCOUT mental-model.md §ChunkingEngine, SCOUT boundaries.md §Episodic Memory Overlay

---

### G-006: Seed Rule Set — No Seed Rules Defined in Any DISCOVER Document
- **Present in:** Implied by mental-model.md (SCOUT) — "hand-coded seed rules initialized at module load"; assumptions.md (SCOUT) — A-004 assumes 5-10 seed rules
- **Missing from:** No DISCOVER document provides even one example seed rule. No WME pattern is given for any of the five stable context_pack keys.
- **Impact:** HOW spec must define at least one concrete seed rule per stable WME attribute. Without this, BUILD starts from scratch with no guidance.
- **Who resolves:** HOW spec author (after U-002 schema is resolved)
- **Sources:** SCOUT assumptions.md (A-004), SCOUT mental-model.md §ProceduralMemoryStore

---

### G-007: squad-config.yml — soar section not defined in any DISCOVER document
- **Present in:** boundaries.md (SCOUT) — `ca_overlays.soar.*` keys listed with defaults
- **Missing from:** No document provides the actual YAML block to add to squad-config.yml. The defaults (max_wmes: 50, chunking_enabled: true, min_chunk_confidence: 0.6) are stated but no amendment is drafted.
- **Impact:** BUILD cannot update squad-config.yml without the exact YAML block.
- **Who resolves:** HOW spec must include squad-config.yml amendment YAML block
- **Sources:** SCOUT boundaries.md §squad-config.yml

---

## Suspicious Findings

### S-001: Retroactive U-CA-004 Validity Concern
- **Finding:** The five existing CA overlays were implemented after a NEGATIVE U-CA-004 result (Cohen's d = 0.40, commit `e1976fc`, human override P-006 dated 2026-04-03). Spec 018 adds a sixth overlay to this stack without a new controlled experiment.
- **Why suspicious:** The U-CA-004 experiment was designed for a specific overlay count and configuration. Adding a sixth overlay changes the experimental conditions retroactively. If the combined 6-overlay stack is later tested, the SOAR overlay's contribution to AQS delta cannot be isolated from the 5-overlay baseline.
- **Risk level:** MEDIUM — this is a measurement validity problem. If the 6-overlay stack underperforms the 5-overlay baseline on a future U-CA-004 run, the spec 018 decision will be questioned without the ability to attribute the degradation to SOAR specifically.
- **Recommended action:** User should decide whether to run a partial U-CA-004 (Condition C: 5-overlay baseline vs. 6-overlay with SOAR) before committing spec 018 to production. If not run, the decision to add the SOAR overlay is based on architectural reasoning alone, not empirical AQS evidence.
- **Sources:** SCOUT unknowns.md §Potential Unknown Unknowns (U-CA-004 retroactive impact), SCOUT reasoning-journal.json (RJ-007)

---

### S-002: A-004 (5-10 Seed Rules Sufficient) Has No Empirical Basis
- **Finding:** The assumption that 5-10 hand-coded seed rules are sufficient to avoid impasse in the majority of dispatches is based on analogy to the ACT-R overlay (which has 4 buffer classifications), not on measurement.
- **Why suspicious:** The ACT-R overlay's 4 classifications cover the buffer taxonomy — a closed set. The SOAR overlay's seed rules must cover context_pack key combinations — an open set that grows as more overlays are added. A 5-overlay enrichment stack produces ~13-20 WMEs (5 overlay-injected keys + ~8 base keys). The number of distinct WME-combination contexts may be much larger than 5-10.
- **Risk level:** MEDIUM — if impasse rate > 50% on first dispatch, the overlay provides no enrichment value and must be redesigned or disabled.
- **Recommended action:** SCIENTIST should enumerate likely WME-combination contexts from existing dispatch logs before finalizing the seed rule count.
- **Sources:** SCOUT assumptions.md (A-004), SYNTHESIZER cross-analysis of WME count from boundaries.md §WME Extraction Layer

---

### S-003: Chunking Generates SOAR Chunk Rules with No Expiration or Pruning Policy
- **Finding:** ChunkRecords are appended to ProceduralMemoryStore and described as "never overwrite existing rules." No expiration, pruning, or maximum-rule-count policy is defined. If a run generates many failed SOAR chunk attempts (low-confidence rules that rarely fire), the ProceduralMemoryStore grows unboundedly within a run.
- **Why suspicious:** With no pruning, the match phase scans ALL rules on every dispatch, including stale or low-quality SOAR chunks. This increases dispatch latency proportionally to ProceduralMemoryStore growth. The v1 assumption of ≤50 rules (U-001 threshold) may be violated within a long run.
- **Risk level:** LOW (v1 scope limits runs; bounded by run length). But the design has no safety valve.
- **Recommended action:** HOW spec should define a `max_rules` cap (e.g., 100) and a pruning strategy (e.g., discard lowest-confidence SOAR chunks when cap is reached).
- **Sources:** SCOUT mental-model.md §ChunkRecord, SCOUT boundaries.md §ProceduralMemoryStore, U-001 (SCOUT)

---

## Patterns Emerging from Cross-Source Analysis

### P-001: All Three "Cannot Resolve Without Dependency Tracing" Unknowns Point to the Same Root Cause
- **Pattern:** U-001 (condition expression format), U-002 (WME pattern schema), and U-003 (SOAR chunking generalization) all ultimately stem from the same root constraint: no dependency tracing. In full SOAR, dependency tracing tells the system which WMEs were causally relevant to a result. Without it, the overlay cannot know: which conditions to write (U-002), how to generalize chunks (U-003), or even whether the condition format matters for learning (U-001). These three unknowns form a dependency cluster.
- **Implication:** Resolving U-002 (schema) first enables U-001 (performance benchmark) and U-003 (chunking strategy) to be evaluated empirically. U-002 is the gateway unknown.
- **Sources:** SCOUT unknowns.md (U-001, U-002, U-003), SCOUT reasoning-journal.json (RJ-006)

---

### P-002: The Four SOAR Domain Invariants Are All Respected by the Overlay Design
- **Pattern:** The reference architectures analysis (SCOUT) identified four invariants found across all 5 SOAR reference implementations: (1) WME as atomic data unit, (2) parallel rule firing in elaboration, (3) match/select separation, (4) impasse as first-class event. The Echelon overlay design honors all four:
  - WME as atomic unit: YES (Python dict triples)
  - Parallel rule firing: YES (all matching rules fire in single-pass elaboration)
  - Match/select separation: YES (match phase produces proposals; DecisionProcedure selects)
  - Impasse as first-class event: YES (ImpasseEvent, impasse log, explicit DefaultOperator)
- **Implication:** The overlay design is architecturally coherent relative to SOAR's domain invariants. The deviations (no Rete, no substates, no full preference calculus, approximate chunking) are all in the implementation layer, not in the architectural invariants.
- **Sources:** SCOUT reference-architectures.md §Common Patterns, SCOUT mental-model.md, RJ-008 (SCOUT)

---

### P-003: Six-Overlay Stack Creates a New Validation Boundary That Doesn't Exist in Any Source
- **Pattern:** Every DISCOVER source discusses the SOAR overlay in isolation. None of them analyze the 6-overlay stack as a system. The combined effect of running six overlays in sequence (Goal Stack → ACT-R → LIDA → GWT → Episodic Memory → SOAR) on token budget, enrichment quality, and dispatch latency is entirely unmodeled.
- **Implication:** SCIENTIST must run at least one end-to-end test of all 6 overlays combined before HOW is finalized. The 6-overlay integration is an emergent behavior that cannot be predicted from individual overlay analysis.
- **Sources:** SCOUT unknowns.md (token budget unknown), SYNTHESIZER cross-analysis of all six overlay boundary descriptions

---

### P-004: The Overlay Design Is Biased Toward the Happy Path
- **Pattern:** All five DISCOVER documents spend the most detail on Pattern 1 (successful production rule match). Pattern 2 (impasse), Pattern 3 (chunking), and Pattern 4 (overlay failure) are described at lower precision. The DefaultOperator, impasse log schema, and failure-recovery behavior are underspecified relative to the happy path.
- **Implication:** HOW spec and BUILD must give equal attention to impasse handling and failure recovery. The impasse path is the most novel architectural contribution of the SOAR overlay (vs. a simpler "always fire a default enrichment" design). Underspecifying it loses the architectural value.
- **Sources:** SCOUT mental-model.md §Behavioral Patterns (asymmetric detail between patterns), SYNTHESIZER cross-source analysis

---

## Typos / Defects in Source Documents

### T-001: "ImpasseCvent" in mental-model.md (SCOUT)
- **Location:** mental-model.md §SOAR Operator entity, bullet "may trigger ImpasseCvent if no operator is selected" (line 24 of source)
- **Correct form:** ImpasseEvent
- **Impact:** Documentation defect — no implementation impact. Corrected in unified mental-model.md.
- **Sources:** SCOUT mental-model.md

# Risks — Spec 018 (SOAR Cognitive Architecture Overlay)

**Produced by**: SYNTHESIZER (FUSE) — NEW document, unique to SYNTHESIZER  
**Date**: 2026-04-03 | **Spec**: 018-soar-overlay  
**Sources merged**: unknowns.md (SCOUT), assumptions.md (SCOUT), boundaries.md (SCOUT), reasoning-journal.json (SCOUT), contradictions-and-gaps.md (SYNTHESIZER)

---

## Risk Register

| Risk ID | Title | Severity | Likelihood | Blocking? | Owner |
|---------|-------|----------|------------|-----------|-------|
| R-001 | Retroactive U-CA-004 validity concern | HIGH | MEDIUM | No | User |
| R-002 | Token budget violation for 6-overlay stack (FR-CAO-002) | HIGH | MEDIUM | Conditional | SCIENTIST |
| R-003 | Impasse rate too high — seed rules insufficient | MEDIUM | MEDIUM | No | SCIENTIST |
| R-004 | SOAR chunking generalization produces noisy/useless rules | MEDIUM | MEDIUM | No | SCIENTIST |
| R-005 | WME pattern schema incompatible with SOAR chunk auto-construction | MEDIUM | LOW | Yes (blocks HOW) | SCIENTIST |
| R-006 | actr_buffers nested dict produces unmatchable WMEs | MEDIUM | MEDIUM | No | SCIENTIST |
| R-007 | ProceduralMemoryStore grows unboundedly — dispatch latency degrades | LOW | LOW | No | HOW spec |
| R-008 | COMMANDER.md position-6 slot unavailable | LOW | LOW | Yes (blocks BUILD) | SCIENTIST |
| R-009 | Tie-impasse behavioral deviation creates semantic inconsistency | LOW | LOW | No | WHY1 |

---

## Risk Details

### R-001: Retroactive U-CA-004 Validity Concern
- **Description:** The five CA overlays (specs 014-017) were implemented after a NEGATIVE U-CA-004 AQS-delta measurement (Cohen's d = 0.40, human override P-006, commit `e1976fc`, 2026-04-03). Spec 018 adds a sixth overlay to that stack. If a future U-CA-004 run tests the 6-overlay stack and finds AQS degradation, the contribution of the SOAR overlay cannot be isolated from the 5-overlay baseline — because no 6-vs-5 controlled comparison was run before deployment.
- **Severity: HIGH** — this is a measurement validity risk that could retrospectively invalidate the rationale for spec 018 without the ability to diagnose cause.
- **Likelihood: MEDIUM** — future U-CA-004 runs are plausible; degradation from adding a 6th overlay with non-trivial matching logic is possible.
- **Blocking?** No — the overlay can be built and deployed. But the user should make an explicit decision about whether to run a partial experiment.
- **Mitigation options:**
  1. **(Preferred)** Run a partial U-CA-004 rerun: Condition C baseline (5 overlays) vs. Condition C with SOAR (6 overlays). Requires ~20 dispatch samples. Decision required before spec 018 is marked COMPLETE.
  2. **(Acceptable)** Document explicitly in spec 018 that the AQS impact of the SOAR overlay is NOT empirically measured and that the decision to deploy is based on architectural reasoning only. Add a risk acknowledgment to spec 018 constitution.
  3. **(Minimum)** Tag spec 018 as "experimental" in squad-config.yml until a future U-CA-004 confirms or refutes the AQS impact.
- **Decision required from:** User
- **Sources:** SCOUT unknowns.md §U-CA-004 retroactive impact, SCOUT reasoning-journal.json (RJ-007)

---

### R-002: Token Budget Violation for 6-Overlay Stack (FR-CAO-002)
- **Description:** FR-CAO-002 constrains each overlay to not exceed the original context_pack token count. The five existing overlays were validated individually. The 6-overlay combined stack has not been measured. The ACT-R overlay's eviction policy fires when total token count exceeds the original — but this policy was tuned for a 5-overlay stack. With a 6th overlay adding `soar_state`, the eviction threshold may be crossed more frequently, causing the ACT-R overlay to evict content that other overlays (including SOAR) depend on.
- **Severity: HIGH** — a token budget violation would cause the ACT-R eviction to fire, potentially evicting SOAR-overlay-derived WMEs from subsequent calls (circular degradation).
- **Likelihood: MEDIUM** — depends on `soar_state` payload size. The base payload (operator_name string, confidence float, cycle int, wme_count int) is small (~50 tokens). But if chunked rule payloads grow, soar_state could be larger.
- **Blocking?** Conditional — if the token budget test fails, SOAR overlay must reduce its soar_state payload or the seed rules must be redesigned to produce smaller payloads.
- **Mitigation:**
  1. SCIENTIST must measure the token delta of all 6 overlays combined on 3 representative context_packs before HOW is finalized.
  2. Cap soar_state payload size explicitly in the HOW spec (e.g., soar_state must not exceed 200 tokens).
  3. If FR-CAO-002 is violated, reduce soar_state to `{operator_applied: str, confidence: float}` only (remove wme_count and other diagnostic fields).
- **Sources:** SCOUT unknowns.md §Token budget impact, SYNTHESIZER contradictions-and-gaps.md (P-003)

---

### R-003: Impasse Rate Too High — Seed Rules Insufficient
- **Description:** Assumption A-004 asserts that 5-10 hand-coded seed rules will cover the majority of dispatch contexts without triggering impasse. This assumption has no empirical basis — it is an analogy to the ACT-R overlay's 4 buffer classifications. If the actual context_pack key combination space is larger than anticipated, impasse rate may exceed 50%, rendering the overlay's enrichment value negligible.
- **Severity: MEDIUM** — if impasse rate > 50%, the overlay's contribution is `{"operator_applied": "default-no-match"}` on most dispatches. Not dangerous, but wasteful.
- **Likelihood: MEDIUM** — the 5-overlay enrichment stack produces ~13-20 WMEs per dispatch; the number of distinct meaningful combinations may require more than 10 rules to cover adequately.
- **Mitigation:**
  1. Instrument the impasse log during BUILD testing. After 10 dispatches, compute impasse rate. If > 50%, expand seed rule set to 15-20 rules.
  2. SCIENTIST should enumerate likely WME-combination contexts from existing dispatch logs before finalizing the seed rule count (before BUILD).
  3. Consider starting with a broader "catch-all" seed rule (matches on `agent_type` only, confidence 0.5) as a backstop to reduce baseline impasse rate.
- **Sources:** SCOUT assumptions.md (A-004, S-002 in contradictions-and-gaps.md)

---

### R-004: SOAR Chunking Generalization Produces Noisy or Useless Rules
- **Description:** The chunking generalization strategy (U-003) is unresolved. The three available options range from maximally specific (SOAR chunks rarely fire — low utility) to maximally general (SOAR chunks fire too often — over-generalization, wrong enrichments applied). Without dependency tracing, there is no principled way to choose the "correct" level of generalization.
- **Severity: MEDIUM** — if SOAR chunks are noisy, the overlay's learned rules may start overriding better-matching hand-coded seed rules in future dispatch cycles within the same run.
- **Likelihood: MEDIUM** — this is a known limitation of the no-dependency-tracing approximation. The risk is proportional to run length (longer runs = more SOAR chunks accumulated).
- **Mitigation:**
  1. **(Recommended)** Disable chunking in v1 (`chunking_enabled: false` default in squad-config.yml). Implement chunking as an opt-in feature for v2 after the seed rule set is validated.
  2. If chunking is enabled in v1, cap chunk confidence at 0.6 (lower than any hand-coded seed rule's typical confidence) so SOAR chunks never outbid seed rules in the select phase.
  3. SCIENTIST must test generalization options (a), (b), (c) as described in U-003 before HOW is finalized.
- **Sources:** SCOUT unknowns.md (U-003), SCOUT reasoning-journal.json (RJ-006), SYNTHESIZER contradictions-and-gaps.md (S-003)

---

### R-005: WME Pattern Schema Incompatible with SOAR Chunk Auto-Construction
- **Description:** U-002 (WME pattern schema) is a must-resolve-before-WHAT unknown. If the schema chosen for hand-coded seed rules uses Python lambdas or closures (as in the Taseer Python reference architecture), SOAR chunks cannot be stored in the ProceduralMemoryStore JSON — because lambdas are not JSON-serializable. This would break the entire chunking mechanism.
- **Severity: MEDIUM** — the constraint (JSON-serializable schema) is not explicitly stated in any DISCOVER document. It is a derived requirement from the ProceduralMemoryStore being a JSON file.
- **Likelihood: LOW** — the DISCOVER glossary already points toward Python dicts (not lambdas), and the reference architecture clearly shows the dict-based approach. But it is not yet a hard requirement.
- **Blocking?** Yes — if schema is chosen incorrectly before U-002 is resolved, chunking will need to be redesigned.
- **Mitigation:** HOW spec must explicitly require that all condition pattern types be JSON-serializable. Lambda-based conditions are prohibited.
- **Sources:** SYNTHESIZER cross-analysis of SCOUT reference-architectures.md (Taseer Python), SCOUT unknowns.md (U-002)

---

### R-006: `actr_buffers` Nested Dict Produces Unmatchable WMEs
- **Description:** The ACT-R overlay injects `context_pack["actr_buffers"]` as a nested dict with 5 sub-buffers. The WME extraction layer string-coerces this to a JSON string truncated at 200 characters. The resulting WME value is nearly unmatchable by production rules (truncated JSON fragment). Any seed rule intended to fire when ACT-R retrieval is populated cannot do so effectively.
- **Severity: MEDIUM** — this reduces the overlay's ability to fire on ACT-R state, which is one of the richest signals in the enriched context_pack.
- **Likelihood: MEDIUM** — U-007 explicitly identifies this as a known concern.
- **Mitigation:** U-007 options (presence-only match, one-level flattening with dotted attr names) must be decided before HOW. Recommended: add one-level flattening as a special case in the WME extraction layer for dict-valued top-level keys.
- **Sources:** SCOUT unknowns.md (U-007), SYNTHESIZER contradictions-and-gaps.md

---

### R-007: ProceduralMemoryStore Grows Unboundedly — Dispatch Latency Degrades
- **Description:** SOAR chunks are appended to ProceduralMemoryStore with no expiration or pruning policy. For a long run (50+ agents dispatched), the rule store could accumulate 100+ rules. The match phase scans ALL rules on every dispatch (O(rules × WMEs)). At 100 rules × 50 WMEs, latency impact is noticeable for a function called on every agent dispatch.
- **Severity: LOW** — v1 scope limits runs; the concern is more relevant to future long-running runs.
- **Likelihood: LOW** — a typical Echelon run has 5-20 agents dispatched; SOAR chunks accumulate slowly.
- **Mitigation:** HOW spec should define a `max_rules` cap (e.g., 100) and a pruning strategy when cap is exceeded. Lowest-confidence SOAR chunks pruned first. This is a safety valve, not a primary design feature.
- **Sources:** SYNTHESIZER contradictions-and-gaps.md (S-003)

---

### R-008: COMMANDER.md Position-6 Slot Unavailable
- **Description:** The SOAR overlay assumes it will be inserted at position 6 in the COMMANDER pre-dispatch sequence (A-009, unvalidated). If another overlay was added at position 6 during spec 017 development, or if COMMANDER.md has been amended since the DISCOVER analysis, position 6 may already be occupied.
- **Severity: LOW** — position conflicts are immediately visible and easily resolved.
- **Likelihood: LOW** — spec 017 research.md describes 5 overlays (positions 1-5); SOAR is explicitly a spec 018 addition.
- **Mitigation:** SCIENTIST reads COMMANDER.md pre-dispatch sequence before HOW is finalized. Confirms available position for SOAR overlay insertion.
- **Sources:** SCOUT assumptions.md (A-009), SYNTHESIZER boundaries.md §Gap

---

### R-009: Tie-Impasse Behavioral Deviation Creates Semantic Inconsistency
- **Description:** Contradiction C-001 (contradictions-and-gaps.md): the glossary implies ties produce ImpasseEvents (canonical SOAR behavior); the mental model says ties use first-match tie-breaking (no impasse). This inconsistency may cause spec 018 to be evaluated against canonical SOAR behavior by a WHY1 challenge, finding the tie-handling to be a spec defect.
- **Severity: LOW** — the deviation is acceptable for an enrichment overlay (ties between equally valid enrichments are benign). But it should be explicitly documented as an intentional deviation.
- **Likelihood: LOW** — the deviation is small and does not affect the happy path.
- **Mitigation:** HOW spec must explicitly state: "Ties in operator selection use first-match tie-breaking rather than canonical SOAR tie-impasse. This is an intentional deviation; the overlay treats tied operators as equivalently valid enrichments."
- **Sources:** SYNTHESIZER contradictions-and-gaps.md (C-001), SCOUT glossary.md §Preference, SCOUT mental-model.md §DecisionProcedure

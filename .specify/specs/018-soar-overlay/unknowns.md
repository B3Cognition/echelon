# Unknowns — Spec 018 (SOAR Cognitive Architecture Overlay)

**Produced by**: SYNTHESIZER (FUSE) — unified and prioritized from DISCOVER outputs  
**Updated by**: SAGE (WHY1) — 2026-04-03 — U-NEW-001, U-NEW-002 added; U-001 and U-002 promoted with additional context  
**Date**: 2026-04-03 | **Spec**: 018-soar-overlay  
**Sources merged**: unknowns.md (SCOUT), reasoning-journal.json (SCOUT), assumptions.md (SCOUT), COMMANDER.md (code evidence), scripts/ca/*.py (code evidence)  
**Prioritization:** must-resolve-before-WHAT → should-resolve-before-HOW → can-defer

---

## Priority Tier 1: Must Resolve Before WHAT

These unknowns block the WHAT spec from being written. If they are unresolved when WHAT runs, it will produce requirements that cannot be implemented.

---

### U-NEW-001: Agent-specific context_pack key variance — WHY1 addition
- **Why it matters:** DISCOVER documents assume context_pack has 5 overlay-injected keys + 3 base keys (~8 total WMEs). COMMANDER constructs the initial context_pack before calling the overlay chain and may inject agent-specific keys (task description, prior review text, spec section, etc.) that differ by agent type. If the WME set for a SCOUT dispatch differs from a GUARDIAN dispatch differs from a BUILD dispatch, seed rules cannot be agent-type-neutral. Any seed rule targeting non-overlay WME attributes will fire inconsistently across agent types.
- **Investigation questions:**
  1. What keys does COMMANDER inject into context_pack before the overlay chain runs, for at minimum: SCOUT, WHAT, GUARDIAN, PROSPECTOR?
  2. What is the total WME count (overlay keys + base keys + agent-specific keys) for each agent type?
  3. Are agent-specific keys stable within an agent type across different spec runs, or do they vary by run phase?
  4. Should seed rules be scoped to overlay-keys-only (guaranteed stable) or can they also target agent-specific keys (if stable within type)?
- **Who resolves:** SCIENTIST (read COMMANDER.md dispatch documentation; instrument one live dispatch to log pre-overlay context_pack contents)
- **Priority:** MUST-RESOLVE-BEFORE-WHAT
- **Sources:** SAGE WHY1 assumption-review.md (A-003 challenge, DM-003 finding)

---

### U-NEW-002: LIDA broadcast injection frequency — WHY1 addition
- **Why it matters:** `lida_broadcast` is listed as a "known stable WME attribute" in mental-model.md. This is incorrect: LIDA uses consume-once bash semantics and is only present when COMMANDER explicitly triggered a broadcast. Seed rules conditioned on `lida_broadcast` presence will fire at the same frequency as LIDA broadcast triggers — which may be very low (5-20% of dispatches) or zero in runs where no LIDA broadcast was ever called.
- **Investigation questions:**
  1. What triggers a LIDA broadcast in COMMANDER's current dispatch protocol?
  2. How many dispatches per spec run typically receive a `lida_broadcast` key in context_pack?
  3. If LIDA frequency is <20%, should `lida_broadcast`-conditional seed rules be deprioritized or eliminated from the seed rule set?
  4. Should the WME extraction layer handle absent-key vs. present-but-None differently? (Currently, absent keys produce no WME; keys present with None value produce a WME with value "None")
- **Who resolves:** SCIENTIST (review COMMANDER.md for explicit LIDA trigger conditions; examine existing dispatch logs or uca004_runner.py for LIDA usage patterns)
- **Priority:** MUST-RESOLVE-BEFORE-WHAT
- **Sources:** SAGE WHY1 assumption-review.md (DM-003, DM-006 findings)

---

### U-001: Condition expression format — how are production rule conditions represented without a Rete network?
- **Why it matters:** The condition format determines: (a) what "matching" means operationally, (b) the matching algorithm complexity, (c) how chunked rules generalize. This is the central implementation decision for the overlay.
- **Investigation questions (synthesized):**
  1. Which match type is sufficient for the seed rules needed to cover `active_goal`, `actr_buffers`, `lida_broadcast`, `gwt_workspace`, `episodic_prior_artifact`? Options:
     - `{attr: "active_goal"}` — presence-only (simplest; can't distinguish null from non-null)
     - `{attr: "active_goal", value: "not null"}` — sentinel-value match
     - `{attr: "active_goal", value_regex: ".*Deliver.*"}` — content-regex (powerful; complex; breaks if value is truncated)
     - `{attr: "active_goal", value_type: "dict"}` — type-based (works for nested dict detection)
  2. At what rule count does the O(rules × WMEs) naive scan become perceptible in dispatch latency? (Benchmark: 50 rules × 50 WMEs, stdlib only)
  3. Can one condition schema support both hand-coded seed rules AND SOAR-generated chunk rules without a parser? (Chunks need a schema that the ChunkingEngine can construct programmatically from WME snapshots)
- **Who resolves:** SCIENTIST (benchmark + design decision)
- **Priority:** MUST-RESOLVE-BEFORE-WHAT
- **Related assumptions:** A-002 (stdlib only), A-004 (5-10 seed rules sufficient)
- **Sources:** SCOUT unknowns.md (U-001), SCOUT reasoning-journal.json (RJ-003)

---

### U-002: Python dict schema for production rule condition patterns
- **Why it matters:** The schema is a fundamental requirement. Without it, WHAT cannot write testable acceptance criteria for production rule matching. HOW cannot implement a matching algorithm. BUILD cannot write seed rules.
- **Investigation questions (synthesized):**
  1. Should conditions support compound expressions (AND is implicit; does OR need to be supported)?
  2. Should conditions support negation (`{attr: "active_goal", absent: true}` — match if key NOT present)?
  3. Must the schema be JSON-serializable without lambdas? (Required for SOAR chunk storage in ProceduralMemoryStore JSON)
  4. Proposed minimal schema for evaluation:
     ```json
     {
       "attr": "active_goal",
       "match": "present"  // or "absent", "value_eq", "value_regex", "value_type"
       "value": null        // required when match is "value_eq" or "value_regex" or "value_type"
     }
     ```
     Does this schema cover all seed rule needs? Does it support SOAR chunk auto-construction?
- **Who resolves:** SCIENTIST (evaluate schema options); User (confirm expressiveness requirement)
- **Priority:** MUST-RESOLVE-BEFORE-WHAT
- **Related assumptions:** A-003 (key stability)
- **Sources:** SCOUT unknowns.md (U-002)

---

## Priority Tier 2: Should Resolve Before HOW

These unknowns do not block WHAT but must be resolved before HOW can produce an implementable specification.

---

### U-003: SOAR-inspired chunking generalization strategy
- **Why it matters:** This is the highest-risk open question for implementation quality. Without dependency tracing (excluded by stdlib constraint), any generalization strategy is a heuristic. The three options produce fundamentally different learning behavior:
  - **(a) All WMEs present at dispatch time:** Maximally specific chunks — these will rarely fire in novel contexts. Safest (no over-generalization) but least useful.
  - **(b) Only the WMEs matching the triggering rule's conditions:** Same specificity as the triggering rule — no new generalization. Effectively copies the triggering rule. Low utility; slightly more reusable than (a).
  - **(c) Only `active_goal` + `agent_type` WMEs:** Maximally general — SOAR chunks fire whenever these two keys match. High fire rate but significant over-generalization risk; may apply enrichments in wrong contexts.
- **Investigation questions (synthesized):**
  1. For the Echelon use case (short dispatch runs, 5-20 agents per run), does chunking accumulate enough rules within a single run to provide measurable value, or is it always starting from seed rules effectively?
  2. Is option (b) "same as triggering rule" actually valuable — does it create duplicate rules with learned=True that clutter ProceduralMemoryStore?
  3. Is there a hybrid strategy: start with option (c) minimally-general, but only fire SOAR chunks when confidence > 0.8 to reduce over-generalization risk?
  4. Should chunking be DISABLED in v1 entirely (all rules hand-coded) and activated in v2 once the seed rule set is validated? This would avoid the U-003 risk entirely for the initial implementation.
- **Who resolves:** SCIENTIST (experiment with options across 5+ spec runs; measure impasse rate pre- vs post-chunking)
- **Priority:** SHOULD-RESOLVE-BEFORE-HOW
- **Related assumptions:** A-004 (seed rules sufficient), A-008 (cross-run persistence out of scope)
- **SYNTHESIZER recommendation:** Consider Option D — disable chunking in v1, implement as a flag (`chunking_enabled: false` in squad-config.yml default), enable in v2 after seed rules are validated. This decouples the chunking risk from the core MSA cycle delivery.
- **Sources:** SCOUT unknowns.md (U-003), SCOUT reasoning-journal.json (RJ-006)

---

### U-004: Should impasse events surface to dispatched agents via context_pack?
- **Why it matters:** Determines whether `soar_state` carries an `impasse: true` flag and whether downstream agents can/should adapt their behavior.
- **Investigation questions (synthesized):**
  1. Do any of the current 42 Echelon agents have conditional logic that reads `context_pack["soar_state"]`? (If not, surfacing impasse is moot for v1)
  2. Is the impasse signal architecturally consistent with how other overlays signal uncertainty? (e.g., does GWT broadcast carry a "no-consensus" flag that agents act on?)
  3. If impasse is surfaced, should it be `context_pack["soar_state"]["impasse"] = true` (within soar_state) or `context_pack["soar_impasse"] = true` (top-level key visible to all agents)?
- **Who resolves:** User (architectural decision); SCIENTIST (test whether agents behave differently with impasse context)
- **Priority:** SHOULD-RESOLVE-BEFORE-HOW
- **Sources:** SCOUT unknowns.md (U-004)

---

### U-005: Endocrine system wiring for SOAR overlay events
- **Why it matters:** Impasse events are semantically meaningful triggers (potential cortisol/vigilance signals). The existing five overlays have documented endocrine wiring points. If the SOAR overlay is not wired to the endocrine system, it is the only overlay that is not.
- **Investigation questions (synthesized):**
  1. Does COMMANDER.md define a general overlay → endocrine wiring pattern, or is each overlay wired individually?
  2. What endocrine signals would impasse plausibly trigger? (Hypothesis: high impasse rate → cortisol up; successful chunking → dopamine up)
  3. Can endocrine wiring be deferred to a v2 amendment without blocking v1 dispatch?
- **Who resolves:** User (architectural decision); COMMANDER.md (check for general wiring pattern)
- **Priority:** SHOULD-RESOLVE-BEFORE-HOW (can be deferred to v1.1 if wiring is additive)
- **Sources:** SCOUT unknowns.md (U-005)

---

### U-006: Success criterion for triggering SOAR-inspired chunking
- **Why it matters:** ChunkingEngine fires on "successful" dispatch outcomes. The definition of success determines what gets learned.
- **Investigation questions (synthesized):**
  1. Does COMMANDER always set `outcome["artifact_path"]` on success? Is non-null artifact_path the right criterion?
  2. Should AQS score ≥ threshold gate chunking? (Powerful but requires NS-003 instrumentation)
  3. Is any dispatch that completes without BLOCKED or ESCALATED state sufficient? (Conservative — learns from most dispatches)
  4. Does the success criterion need to be configurable (via squad-config.yml `ca_overlays.soar.chunk_success_criterion`)?
- **Who resolves:** User (what level of success justifies learning a new rule?); SCIENTIST (does AQS-gated chunking outperform unconditional chunking?)
- **Priority:** SHOULD-RESOLVE-BEFORE-HOW
- **Related assumptions:** A-005 (sequential dispatch), A-008 (cross-run out of scope)
- **Sources:** SCOUT unknowns.md (U-006)

---

### U-007: WME representation for nested dict values (e.g., `actr_buffers`)
- **Why it matters:** `context_pack["actr_buffers"]` is a nested dict with 5 sub-buffers. String-coercing to JSON produces a 200-char-truncated string that is nearly unmatchable by production rules. This affects whether the SOAR overlay can usefully pattern-match on ACT-R overlay outputs.
- **Investigation questions (synthesized):**
  1. Is presence-only matching for `actr_buffers` sufficient? (Rule condition: `{attr: "actr_buffers", match: "present"}` — detects that ACT-R ran, but ignores content)
  2. Should the WME extraction layer apply one-level flattening for dict values? (`actr_buffers.goal`, `actr_buffers.retrieval`, etc. become separate WMEs with dotted attr names)
  3. Is one-level flattening consistent with how the SCOUT glossary defines WME extraction? (Currently: one WME per top-level key only)
  4. Which flattening strategy produces the most useful seed rules for the ACT-R buffer combinations?
- **Who resolves:** SCIENTIST (WME extraction design decision)
- **Priority:** SHOULD-RESOLVE-BEFORE-HOW
- **Related assumptions:** A-006 (200-char truncation), A-003 (key stability)
- **Sources:** SCOUT unknowns.md (U-007)

---

## Priority Tier 3: Can Defer

These unknowns do not block WHAT or HOW but should be addressed before or during BUILD.

---

### U-008 (new — SYNTHESIZER; reclassified SHOULD-RESOLVE-BEFORE-HOW by SAGE WHY1): Token budget impact of 6-overlay stack
- **SAGE WHY1 reclassification:** This unknown was placed in Tier 3 (CAN-DEFER) by SYNTHESIZER. SAGE reclassifies it to Tier 2 (SHOULD-RESOLVE-BEFORE-HOW). FR-CAO-002 is a hard constraint. The ACT-R eviction policy fires at position 2 against the original pre-overlay context_pack size. If the final 6-overlay enriched context_pack exceeds the original token count, FR-CAO-002 is violated at system level even if each overlay claimed individual compliance. This must be confirmed before HOW finalizes the soar_state payload size cap.
- **Why it matters:** FR-CAO-002 constrains overlays to not exceed the original context_pack token count. The existing five overlays were validated individually, but their combined 6-overlay stack with SOAR's `soar_state` addition has not been measured as a system.
- **Investigation questions (synthesized):**
  1. What is the token delta introduced by each of the 5 existing overlays individually?
  2. What is the cumulative token delta of all 5 overlays combined?
  3. Does adding `soar_state` (small payload: operator_name, confidence, cycle, wme_count) push the 6-overlay stack over FR-CAO-002's limit on any tested context_pack?
  4. If the ACT-R eviction policy fires when 6 overlays are stacked (because combined token count exceeds original), does it evict SOAR-overlay-derived WMEs (which may not be in the ACT-R buffer at all)?
- **Who resolves:** SCIENTIST (measure token deltas for 6-overlay stack)
- **Priority:** CAN-DEFER (but recommended before BUILD to avoid FR-CAO-002 violation at deploy time)
- **Sources:** SCOUT unknowns.md (Potential Unknown Unknowns — token budget impact)

---

### U-009 (new — SYNTHESIZER): Interaction effects between SOAR overlay and existing overlays
- **Why it matters:** The SOAR overlay reads outputs of all 5 prior overlays as WMEs. Production rules that fire based on multi-overlay WME combinations have never been analyzed. Some combinations may produce unexpectedly useful or noisy enrichments.
- **Investigation questions:**
  1. What are the most common multi-key WME combinations across 10 test dispatches?
  2. Are there combinations (e.g., ACT-R retrieval non-empty + Episodic prior artifact present) that merit specific seed rules?
  3. Do any inter-overlay WME combinations produce systematically misleading SOAR operator selections?
- **Who resolves:** SCIENTIST (run 10 dispatches with all 6 overlays; inspect WME set distributions)
- **Priority:** CAN-DEFER
- **Sources:** SCOUT unknowns.md (Potential Unknown Unknowns — interaction effects)

---

### U-010 (new — SYNTHESIZER): Semantic legitimacy of "SOAR overlay" label without substate creation
- **Why it matters:** The overlay's most significant deviation from canonical SOAR is the absence of substate creation on impasse. Substates are the mechanism SOAR uses for hierarchical task decomposition — arguably the most distinctive SOAR feature. Without substates, the overlay is a simplified rule-matching context enricher with SOAR-inspired terminology.
- **Investigation questions:**
  1. Is the "SOAR overlay" label appropriate given the absence of substates and full preference calculus?
  2. Should the overlay be labeled "SOAR-inspired" in the spec title and all documentation to prevent over-claiming?
  3. Does the absence of substates disqualify the chunking approximation from being labeled "SOAR chunking"?
- **Who resolves:** User (architectural labeling decision); SCIENTIST (assess whether approximation is patent-differentiating)
- **Priority:** CAN-DEFER (labeling issue, does not block implementation)
- **Sources:** SCOUT unknowns.md (Potential Unknown Unknowns — semantic correctness of chunking)

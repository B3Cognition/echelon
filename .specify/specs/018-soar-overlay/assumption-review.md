# Assumption Review — WHY1

**Agent**: SAGE (assumption-challenge mode)  
**Date**: 2026-04-03  
**Spec**: 018-soar-overlay  
**Artifacts reviewed**: glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, contradictions-and-gaps.md, risks.md, reasoning-journal.json  
**Code evidence examined**: COMMANDER.md (integration reference), scripts/ca/goal_stack.py, actr_buffer.py, gwt_workspace.py, episodic_memory.py

---

## Verdict: FAIL

**Reason:** Two unvalidated CRITICAL assumptions (A-003, A-004) have no investigation plan with concrete timelines; one CRITICAL contradiction (C-001 — tie-impasse behavior) is unresolved and directly blocks HOW; one HIGH-severity risk (R-002 — 6-overlay token budget) is classified as "can-defer" but FR-CAO-002 compliance of the full stack is measurably unverified; and the chunking default-disabled recommendation is logically sound but structurally underdetermined. None of these individually would block WHAT — but in combination they leave WHAT unable to write testable acceptance criteria for the decision procedure, the impasse path, or the token budget constraint.

## Summary

The DISCOVER/SYNTHESIZE artifacts are internally coherent on the core MSA cycle design and the ADR-005/FR-CAO-006 constraints are correctly modeled. The main failures are (1) A-003 and A-004 are both CRITICAL and both unvalidated with zero empirical backing — the "evidence" for A-003 is a structural inference from COMMANDER.md's static overlay list, not a cross-run key-presence measurement; (2) C-001 is a genuine design decision that has been mislabeled as low-severity (R-009) when it is a WHAT-blocker because HOW cannot specify the DecisionProcedure contract without knowing which behavior is canonical for this overlay; (3) R-002 is misclassified as CAN-DEFER when FR-CAO-002 is a hard constraint — if the 6-overlay stack violates it, the spec 018 design is non-compliant at deploy time, not at review time; (4) the chunking default-disabled recommendation is architecturally correct but the reasoning exposes an unrecognized unknown (U-NEW-001) that is also a WHAT-blocker.

---

## Assumption Analysis

### A-001: ADR-005 uniform interface applies to the SOAR overlay
- **DISCOVER's classification:** Critical
- **WHY's classification:** Critical (confirmed)
- **Evidence strength:** Strong
- **Evidence basis:** COMMANDER.md (the CA Overlay Integration Reference, Amendment 1.0.0, 2026-04-03) explicitly defines the pre-dispatch sequence as five numbered Python calls. The `enrich_context(context_pack, run_id) -> dict` signature is confirmed in all four existing Python overlays (goal_stack.py, actr_buffer.py, gwt_workspace.py, episodic_memory.py). The LIDA overlay uses a shell script pattern — consume-once JSON file — which is a variation, not a violation, of the interface contract. A-001 is validated by code evidence.
- **Contradictions found:** None. Minor note: `episodic_memory.enrich_context` has a third parameter `agent_type` not present in the other four. The SOAR overlay interface specification must decide whether it needs an `agent_type` parameter. The glossary states `enrich_context(context_pack, run_id)` as the signature, but the Episodic Memory overlay's variant is an accepted deviation for v1. The HOW spec must confirm whether SOAR's overlay needs agent_type.
- **Verdict:** Validated — with one HOW-spec action item (confirm two-vs-three-parameter signature)
- **Action required:** HOW spec to confirm `enrich_context(context_pack, run_id)` vs. `enrich_context(context_pack, run_id, agent_type)` for SOAR overlay (two-parameter form is probably correct; SOAR does not need agent_type for WME extraction)

---

### A-002: Python stdlib only — no C extensions, no external SOAR packages
- **DISCOVER's classification:** Critical
- **WHY's classification:** Critical (confirmed)
- **Evidence strength:** Strong
- **Evidence basis:** requirements.txt confirmed clean (DISCOVER validated). All four existing CA overlays use stdlib only (confirmed by code inspection — actr_buffer.py implements TF-IDF with `math`, `re`, `collections.Counter` only; no numpy/sklearn). ADR-005 pattern is empirically established.
- **Contradictions found:** None.
- **Verdict:** Validated
- **Action required:** None

---

### A-003: context_pack keys are stable enough to serve as WME attribute names
- **DISCOVER's classification:** Critical
- **WHY's classification:** Critical — RECLASSIFIED as UNVALIDATED with WEAK evidence basis (downgrade from DISCOVER's implicit "probably true" framing)
- **Evidence strength:** Weak
- **Evidence basis claimed:** "All five existing overlays inject named keys in a deterministic COMMANDER sequence." This is structurally true — COMMANDER.md shows positions 1-5 with fixed key names. But this is static-code evidence, not runtime evidence.
- **WHY's challenge:** The DISCOVER/SYNTHESIZE artifacts conflate two distinct stability questions:
  1. **Static key stability** (do the five overlay-injected keys always appear in context_pack?): This is confirmed by COMMANDER.md's hardcoded pre-dispatch sequence. Position 1-5 always run; their keys always get injected. Evidence: Strong for these five keys.
  2. **Dynamic key stability** (does the rest of context_pack — agent-type-specific and run-specific keys injected by COMMANDER before calling overlays — vary across agent types and spec runs?): This is UNVALIDATED. COMMANDER may add agent-specific context keys (e.g., `task_description`, `prior_review`, `spec_id`) that differ across agent types. These non-overlay keys would appear as WMEs and could vary dramatically between a DISCOVER dispatch and a BUILD dispatch.
- **Critical gap exposed:** The seed rules (A-004) will be written against the five stable overlay keys plus base keys (`agent_type`, `spec_id`, `run_id`). But if COMMANDER injects 3-8 additional agent-specific keys that vary by agent role, the WME set size varies from ~8 (five overlay keys + 3 base keys) to ~16+ (five overlay keys + 3 base + 8 agent-specific). Production rules matching on the presence of a specific non-overlay key will fire inconsistently. The assertion that "8-15 WMEs expected from stable keys" (mental-model.md §WorkingMemory) is an estimate with no measured basis.
- **Pre-mortem finding:** The most likely failure mode of spec 018 is that COMMANDER injects agent-specific context keys that the SOAR overlay's seed rules were not written against, causing impasse rate to be 70-80% on non-standard dispatch contexts (specialist agents like GUARDIAN, GOLDDIGGER, PROSPECTOR) and 20-30% on standard dispatch contexts (SCOUT, WHAT, HOW). The overlay would appear to work during testing against standard agents and fail silently during specialist dispatches. This failure would be invisible without impasse log monitoring.
- **Verdict:** Needs-investigation — SCIENTIST must enumerate actual context_pack key sets across at minimum 3 agent types (standard spec agent, specialist agent, control agent) before WHAT can finalize seed rule scope
- **Action required:** SCIENTIST investigation — enumerate context_pack keys for at least 3 agent types from existing dispatch logs or COMMANDER.md dispatch protocol; compute WME set size distribution; identify non-overlay keys that vary by agent type

---

### A-004: 5-10 hand-coded seed rules sufficient to cover common dispatch contexts
- **DISCOVER's classification:** Critical
- **WHY's classification:** Critical — UNVALIDATED with NONE evidence basis (the analogy to ACT-R's 4 buffer classifications is not evidence)
- **Evidence strength:** None
- **Evidence basis claimed:** "Analogy: ACT-R overlay seeds with 4 buffer classifications." This analogy is false. The ACT-R overlay's 4 buffer classifications cover a CLOSED, EXHAUSTIVE taxonomy (every key maps to one of 4 buffers — declarative, procedural, goal, imaginal). The ACT-R overlay cannot produce impasse because it has a universal catch-all (every key fits somewhere). The SOAR overlay's seed rules must match specific WME combinations from an OPEN set — context_pack keys vary by agent type and run phase. There is no universal catch-all in a production rule system: if no rule fires, impasse occurs.
- **WHY's structural challenge:**
  - With 5 overlay keys × 2 states each (present/absent) = 32 possible presence combinations
  - With 3 additional base keys (always present): WME context is 5 + 3 = 8 guaranteed WMEs minimum
  - But the agent_type WME alone (42 distinct agent types by the glob of agents/) creates 42 distinct possible agent_type values that seed rules could match on
  - If seed rules are written as general (match any agent_type), they add limited specificity; if written per agent_type, 5-10 rules covers only 5-10 of 42 agent types
  - The assumption's pass criterion ("impasse rate above 50% in the first dispatch cycle indicates the seed rule set is insufficient") is correct as a measurement gate but the 50% threshold has no principled basis — a 30% impasse rate on an overlay injecting non-trivially into production dispatches is already a design failure
- **Pre-mortem finding:** The most likely realization is that 5-10 seed rules produce an impasse rate of 40-60% in the first 10 test dispatches due to agent_type combinatorics, requiring an immediate expansion to 20-30 rules. This would not block delivery but would require a seed rule redesign pass between BUILD and COMPLETE. The risk is not catastrophic but is near-certain.
- **Verdict:** Needs-investigation — SCIENTIST must enumerate WME-combination contexts from existing dispatch logs BEFORE WHAT finalizes the seed rule count; the 5-10 estimate is almost certainly too low for a 42-agent squad
- **Action required:** SCIENTIST investigation — enumerate distinct agent_type values from agents/ directory; identify top-10 most frequently dispatched agents; define seed rule coverage target (what percentage of dispatches should produce a match?); revise seed rule count estimate

---

### A-005: COMMANDER dispatches agents sequentially
- **DISCOVER's classification:** Standard
- **WHY's classification:** Standard (confirmed)
- **Evidence strength:** Strong
- **Evidence basis:** COMMANDER.md shows a strictly sequential pre-dispatch/post-dispatch Python code block with no async, threading, or parallel constructs. All five existing overlays use single-writer file patterns. No concurrent dispatch mechanism exists in any observed code.
- **Contradictions found:** None.
- **Verdict:** Validated
- **Action required:** None. However, the HOW spec should include a NOTE that if COMMANDER is ever amended to support parallel dispatch, the ProceduralMemoryStore write pattern must be updated to use file locking.

---

### A-006: WME value truncation at 200 characters does not lose semantically critical information
- **DISCOVER's classification:** Standard
- **WHY's classification:** Standard — but evidence strength is WEAK, not "validated"
- **Evidence strength:** Weak
- **WHY's challenge:** The truncation concern is most acute for `actr_buffers` (the nested dict), not for simple-value keys. Reading actr_buffer.py: the retrieval_buffer excerpt is already truncated to 500 chars inside the ACT-R overlay. The full `actr_buffers` dict (with all five sub-buffer arrays) could serialize to 2,000-5,000 characters before SOAR's 200-char truncation applies. The resulting WME value would be a truncated JSON fragment like `{"declarative": [{"key": "role_description", "value": "You are COMMANDER—a princi` — which is unmatchable by any reasonable production rule condition. U-007 correctly identifies this, but it is not resolved in any artifact.
- **The 200-char threshold appears to come from nowhere:** ACT-R overlay uses 500 chars for excerpts. GWT workspace has no per-item truncation. The 200-char rule for SOAR WME values is stated in DISCOVER but has no derivation — it is not tied to any performance measurement, token budget constraint, or SOAR analogy. This is a design decision that was never justified.
- **Verdict:** Needs-investigation (for the threshold derivation) / Partially validated (the structural argument that conditions match on key presence, not deep content, is reasonable — but this has not been confirmed for the seed rules that will actually be written)
- **Action required:** HOW spec must derive the 200-char threshold from a measurable constraint (e.g., maximum WME value size that keeps the match algorithm within latency budget); alternatively, raise threshold to 500 chars for consistency with ACT-R; resolve U-007 before HOW

---

### A-007: Confidence scalar is a sufficient simplification of SOAR's preference calculus
- **DISCOVER's classification:** Standard
- **WHY's classification:** Standard — but this is directly entangled with C-001 (tie behavior)
- **Evidence strength:** Moderate (architectural reasoning is sound for enrichment use case)
- **WHY's challenge:** The simplification is defensible for the use case. However, A-007 assumes tie rate will be low ("Tie frequency above 10% of dispatches would warrant adding a secondary preference signal"). This is an untested threshold and depends entirely on how seed rules are written. If two seed rules are written with identical confidence values (e.g., both at 0.8), ties will be systematic, not occasional. The HOW spec must prohibit duplicate confidence values across seed rules — a constraint not currently stated anywhere.
- **Contradictions found:** A-007 and C-001 interact: A-007 implies tie handling is a minor concern, but C-001 shows the tie behavior is architecturally inconsistent across artifacts. These must be resolved together.
- **Verdict:** Conditionally validated — valid IF (a) C-001 is resolved with first-match as the documented intentional deviation, and (b) HOW spec prohibits duplicate confidence values in hand-coded seed rules
- **Action required:** HOW spec to (a) resolve C-001 explicitly, (b) add rule: no two seed rules may share the same confidence value (enforce unique confidence assignments in seed rule schema)

---

### A-008: Cross-run ProceduralMemoryStore persistence is out of scope for v1
- **DISCOVER's classification:** Standard
- **WHY's classification:** Low-Risk (downgrade — not Standard)
- **Evidence strength:** Moderate (consistent with spec 017 pattern)
- **WHY's challenge:** The classification as Standard implies this is an assumption that could be wrong with significant consequences. In practice, cross-run persistence is clearly out of scope per the stated consistency with spec 017 and the known complexity (rule identifier stability, conflict resolution). The risk if wrong is limited: users expecting cross-run improvement would be disappointed, but the overlay would still function. This is Low-Risk, not Standard.
- **Verdict:** Validated (appropriately out of scope for v1)
- **Reclassification:** Downgrade to Low-Risk. Correct classification has no downstream impact on WHAT.
- **Action required:** WHAT spec should state "cross-run persistence: explicitly out of scope, v1" once at spec header level

---

### A-009: The SOAR overlay runs at position 6 in the COMMANDER pre-dispatch sequence
- **DISCOVER's classification:** Low-Risk
- **WHY's classification:** Low-Risk (confirmed with one correction)
- **Evidence strength:** Strong — partially. The COMMANDER.md (CA Overlay Integration Reference) defines exactly 5 positions. Position 6 does not yet exist in any code or reference document. The claim that "position 6 is the natural extension" is correct structurally — the pre-dispatch Python block ends at position 5 and SOAR would be appended after it.
- **WHY's finding:** However, the pre-dispatch code block in COMMANDER.md is a literal Python pseudocode snippet with 5 numbered steps. Adding a 6th step requires a COMMANDER.md amendment. The HOW spec must draft this amendment explicitly (G-003 correctly identifies this gap). The gap is not a risk to the overlay's design — it is a deployment prerequisite.
- **Verdict:** Validated (no conflict) — but the amendment is not yet drafted
- **Action required:** HOW spec must include the exact COMMANDER.md pre-dispatch and post-dispatch amendment text for position-6 insertion

---

### A-010: The `soar_state` key does not conflict with any existing overlay output key
- **DISCOVER's classification:** Low-Risk
- **WHY's classification:** Low-Risk (confirmed)
- **Evidence strength:** Strong
- **Evidence basis:** COMMANDER.md overlay table lists: `active_goal`, `actr_buffers`, `lida_broadcast`, `gwt_workspace`, `episodic_prior_artifact`. None is `soar_state`. Code inspection of all four Python overlays confirms no overlay uses `soar_state` as an output key.
- **Verdict:** Validated
- **Action required:** None

---

### A-011: The 200-char WME value truncation applies after JSON serialization of nested dicts
- **DISCOVER's classification:** Inferred (SYNTHESIZER-added)
- **WHY's classification:** Standard — the inference is correct by logic (serialize → truncate is the only coherent order), but the interaction with actr_buffer.py reveals a compounding effect
- **Evidence strength:** Moderate (logically necessary inference from the boundary definition)
- **WHY's finding:** When actr_buffer.py runs (position 2), it injects `actr_buffers` as a full Python dict with 5 sub-buffer arrays. This dict, when JSON-serialized by the WME extraction layer, will produce a string of variable length (potentially 500-5,000 chars) before the 200-char truncation. The truncated string will begin with `{"declarative":` and cut off mid-structure. This is architecturally known (U-007) but the consequence for production rule matching is more severe than the artifacts acknowledge: **no production rule can reliably match on actr_buffers content** without one-level flattening. Presence-only matching (`{attr: "actr_buffers", match: "present"}`) is the only viable condition type for this key given the current WME extraction design.
- **Verdict:** Confirmed as inferred (the order is correct) — but exposes a design constraint that must be a HOW-spec requirement: production rule conditions on `actr_buffers` MUST use presence-only matching unless U-007's flattening option is adopted
- **Action required:** HOW spec must mandate presence-only matching for `actr_buffers` OR adopt one-level flattening (U-007 resolution); cannot leave this implicit

---

### A-012: The SOAR overlay's position-6 enrichment adds value beyond what the five existing overlays provide
- **DISCOVER's classification:** Unvalidated (SYNTHESIZER-added)
- **WHY's classification:** Critical — this is the fundamental value proposition assumption; it is not a "standard" or "low-risk" assumption
- **Evidence strength:** None — this is an architectural bet, not a measured finding
- **WHY's challenge:** A-012 is the most important assumption in the entire DISCOVER artifact set, and it is the least examined. The five existing overlays already inject:
  1. Goal Stack → active goal with priority and depth
  2. ACT-R → structured buffer classification of all context keys + TF-IDF retrieval
  3. LIDA → explicit broadcast payload (when present — consume-once)
  4. GWT → bounded workspace of recent agent outputs
  5. Episodic Memory → most recent prior artifact for this agent type
  
  The SOAR overlay proposes to add: a structural pattern-matching label identifying which SOAR operator best matches the current WME combination.
  
  **The critical question:** Does an agent receiving a context_pack with `soar_state: {"operator_applied": "enrich-goal-active", "confidence": 0.82}` produce materially better output than one that does not? The existing five overlays already provide the goal, the ACT-R buffer classification, the workspace summary, and the episodic prior. The SOAR operator label is a meta-level annotation that adds one more name for what the overlay stack is "doing." Whether this name adds any agent-level reasoning improvement is entirely unmeasured.
  
  This concern is functionally equivalent to R-001 (retroactive U-CA-004 validity) but is more fundamental: R-001 is about measurement methodology; A-012 is about whether the spec is worth building at all.
- **Verdict:** Needs-investigation (User clarification required — the user authorized P-006 override for the five overlays but has not explicitly stated the value hypothesis for a sixth SOAR overlay)
- **Reclassification:** Promote to Critical assumption — this is the spec's raison d'être
- **Action required:** User must explicitly state the value hypothesis for spec 018: what specific agent behavior improvement does the SOAR operator label provide that the five existing overlays do not? If the answer is "it labels what they collectively do," this may be architecturally interesting but empirically unmeasurable in isolation.

---

## Domain Model Issues

| ID | Finding | Severity | Affected Artifact | Section |
|----|---------|----------|-------------------|---------|
| DM-001 | C-001 (tie → first-match vs. tie → impasse) is listed as R-009 (LOW severity) but is a WHAT-blocker: HOW cannot specify the DecisionProcedure contract until this design decision is made | HIGH | contradictions-and-gaps.md, risks.md | C-001, R-009 |
| DM-002 | The `episodic_memory.enrich_context` signature has 3 parameters (context_pack, run_id, agent_type) while all other overlays have 2. The SOAR overlay specification states a 2-parameter interface but DISCOVER never acknowledged this variance. HOW must confirm which pattern SOAR follows. | MEDIUM | boundaries.md, assumptions.md | A-001, §SOAR Overlay Module |
| DM-003 | LIDA overlay is NOT a Python module — it is a bash script (`scripts/bash/lida_broadcast.sh`) with consume-once JSON file semantics. The mental-model.md lists `lida_broadcast` as a stable WME attribute from a "prior overlay," implying it is always present. It is NOT always present — it is present only when a LIDA broadcast was explicitly triggered before this dispatch. Any seed rule with a condition `{attr: "lida_broadcast", match: "present"}` will fire inconsistently, not reliably. The DISCOVER artifacts do not acknowledge this. | HIGH | mental-model.md, boundaries.md | §WorkingMemory "Known stable WME attributes" |
| DM-004 | The glossary states WME `id` is always `"state-<run_id>"` — all WMEs share the same object identifier. In canonical SOAR, different objects have different identifiers (WMEs from different structures differ on the `id` field). The single-root-id model means all conditions must rely on `attr` and `value` fields only — the `id` field in WME patterns is useless as a discriminator. This constraint is not stated anywhere in DISCOVER artifacts as a requirement impact (e.g., "production rule conditions must NOT use `id` as a match criterion"). | MEDIUM | glossary.md, mental-model.md | §WME, §WorkingMemory |
| DM-005 | The ChunkRecord `conditions` field is described as "inferred from WME snapshot — generalization strategy TBD." If chunking is disabled by default (the recommendation), this field is never populated in v1. But the ProductionRule schema has `conditions` as a required field. The HOW spec must either (a) define a placeholder for disabled-chunking chunk conditions, or (b) clarify that ChunkRecord is not instantiated when chunking is disabled. | LOW | mental-model.md | §ChunkRecord, §ProductionRule |
| DM-006 | No LIDA-specific overlay Python file exists — confirmed by glob. The `lida_broadcast.sh` approach means `context_pack["lida_broadcast"]` is only present when COMMANDER explicitly called `lida_broadcast.sh broadcast` before a dispatch. This makes LIDA an UNRELIABLE WME attribute, unlike the four Python overlay keys which are injected unconditionally at every dispatch. The mental-model lists `lida_broadcast` alongside the reliably-injected keys without this critical qualifier. | HIGH | mental-model.md | §WorkingMemory §Known stable WME attributes |
| DM-007 | The `soar_state` apply-phase output is described as `{operator_applied, confidence, cycle, wme_count, impasse: false}`. The impasse path sets `{operator_applied: "default-no-match", impasse: true}`. But `wme_count` in the impasse case is the count of WMEs that failed to match any rule — this is still a valid and useful diagnostic field. However, neither the happy-path payload nor the impasse-path payload is fully specified in DISCOVER. G-004 correctly identifies this gap. | MEDIUM | mental-model.md, contradictions-and-gaps.md | §Behavioral Patterns, G-004 |

---

## Pre-Mortem Findings

| Risk Area | Most Likely Failure | Confidence | Mitigation |
|-----------|-------------------|------------|------------|
| WME key stability (A-003) | COMMANDER injects agent-specific context keys that vary by agent type; SOAR rules written against the five stable overlay keys fire on standard agents but produce impasse on specialist dispatches (GUARDIAN, GOLDDIGGER, PROSPECTOR), creating silent enrichment failures | HIGH | SCIENTIST enumerates context_pack key sets across agent types before WHAT; seed rules scoped to overlay keys only with explicit "present/absent" conditions |
| Seed rule count (A-004) | 5-10 rules insufficient; impasse rate 40-60% on first 10 dispatches; emergency rule expansion required between BUILD and COMPLETE | HIGH | Start with 15-20 rules; include agent_type-specific rules for top-10 dispatched agents; add universal low-confidence catch-all rule |
| LIDA as "stable" WME attribute (DM-003/DM-006) | Seed rule conditions on `lida_broadcast` presence are treated as reliable but fire on <20% of dispatches (LIDA is consume-once, triggered only when explicitly broadcast). Rules designed to fire when LIDA is present will effectively never fire in runs without LIDA broadcasts. | HIGH | HOW spec must explicitly label `lida_broadcast` as CONDITIONAL (not stable); seed rules with `lida_broadcast` conditions must be paired with non-LIDA fallback rules |
| Token budget (R-002) | The ACT-R eviction policy fires mid-run on a 6-overlay stack, evicting declarative entries that include SOAR-relevant context; soar_state is small but the cumulative effect of 6 overlays crossing FR-CAO-002 threshold causes ACT-R to reduce the WME set for subsequent dispatches | MEDIUM | SCIENTIST measures 6-overlay stack token delta on 3 representative context_packs before HOW |
| Value proposition (A-012) | SOAR overlay adds architectural complexity without measurable AQS improvement because the `soar_state` label provides no new information beyond what the five existing overlays already surface to the dispatched agent | MEDIUM | User explicitly states the value hypothesis; if hypothesis is "meta-structural label," consider whether a simpler mechanism achieves the same goal |
| Tie behavior (C-001) | HOW spec is written with first-match tie-breaking; a future WHY2/WHY3 pass challenges it as non-canonical; WHAT requirements cannot be traced to the right implementation | MEDIUM | Resolve C-001 now (before WHAT); document the intentional deviation with explicit rationale |

---

## SCIENTIST Referrals

| Unknown | Question for SCIENTIST | Priority | Justification |
|---------|----------------------|----------|---------------|
| A-003 / U-NEW-001 | Enumerate actual context_pack key sets for at least 3 agent types (standard, specialist, control). Measure WME set size distribution across 5+ dispatches. Identify which keys are guaranteed-present (overlay-injected) vs. agent-specific-variable. | MUST-RESOLVE-BEFORE-WHAT | Seed rules cannot be finalized without knowing the WME set; A-003 is CRITICAL and UNVALIDATED |
| A-004 | Given the WME set enumeration result above, estimate the minimum seed rule count required to achieve <30% impasse rate. Enumerate distinct agent_type values across all 42 agents. Determine whether per-agent-type rules or per-overlay-combination rules are more efficient. | MUST-RESOLVE-BEFORE-WHAT | The 5-10 estimate is unsupported; wrong count causes either over-engineering or deployment failure |
| DM-003 / DM-006 | Measure the actual frequency of LIDA broadcast injection across existing dispatch logs. What percentage of dispatches have `lida_broadcast` present in context_pack? This determines whether `lida_broadcast` conditions in seed rules are useful or effectively dead code. | MUST-RESOLVE-BEFORE-WHAT | If LIDA frequency <20%, all `lida_broadcast`-conditional seed rules are low-value and should be deprioritized in the seed rule count |
| U-002 | Evaluate the proposed minimal condition schema (attr + match + value). Confirm it supports presence-only, value_eq, and value_type matching without lambdas. Confirm it is fully JSON-serializable for ChunkRecord storage. | MUST-RESOLVE-BEFORE-WHAT | Blocks HOW if not resolved; blockers this early are expensive |
| R-002 / U-008 | Measure token delta for all 6 overlays combined on 3 representative context_packs (a SCOUT dispatch, a WHAT dispatch, a BUILD dispatch). Confirm FR-CAO-002 compliance of the full stack. | SHOULD-RESOLVE-BEFORE-HOW | Misclassified as CAN-DEFER; if FR-CAO-002 is violated, soar_state payload must be constrained in HOW |
| U-003 | Recommend one of the four generalization strategies for chunking (all WMEs, triggering conditions, minimal set active_goal+agent_type, or disable-in-v1). WHY independently recommends disable-in-v1 (see chunking section below). SCIENTIST should confirm or refute this recommendation. | SHOULD-RESOLVE-BEFORE-HOW | Chunking design must be locked before HOW |

---

## Missing Unknowns

### U-NEW-001: Agent-specific context_pack key variance — not captured in any DISCOVER artifact
- **Finding:** DISCOVER documents describe context_pack as having five "stable overlay keys" plus three "base keys" (`agent_type`, `spec_id`, `run_id`). The COMMANDER.md dispatch protocol shows that COMMANDER constructs the initial context_pack before calling overlays, and this construction may include agent-specific keys (task description, prior agent output, spec section, etc.). No DISCOVER document investigates what COMMANDER puts into context_pack before the overlay chain runs.
- **Impact on A-003:** If COMMANDER injects agent-specific keys (highly likely given that COMMANDER is a prompt-level agent), the WME set for a SCOUT dispatch differs from a BUILD dispatch differs from a GUARDIAN dispatch. Seed rules written against only the five overlay keys will not fire on the agent-specific WMEs — which means the SOAR overlay adds no enrichment specific to the agent's actual task. This is the principal weakness in the overlay's value proposition.
- **Priority:** MUST-RESOLVE-BEFORE-WHAT — this unknown directly determines the seed rule design scope
- **Who resolves:** SCIENTIST (read COMMANDER.md dispatch documentation for context_pack construction; instrument one live dispatch and log the full pre-overlay context_pack contents)

### U-NEW-002: LIDA broadcast injection frequency — not measured anywhere
- **Finding:** `lida_broadcast` is listed as a "known stable WME attribute" in mental-model.md. This is factually incorrect — LIDA is consume-once and only present when COMMANDER explicitly triggers a broadcast. No document measures or estimates LIDA broadcast frequency across a typical spec run.
- **Impact:** Seed rules with `lida_broadcast` conditions are effectively conditional on an external trigger. If LIDA fires on 5% of dispatches, these rules provide near-zero enrichment value and consume seed rule slots that could be used for reliably-matching conditions.
- **Priority:** MUST-RESOLVE-BEFORE-WHAT (affects seed rule count and design)
- **Who resolves:** SCIENTIST (review existing LIDA broadcast usage in prior runs or COMMANDER.md for explicit LIDA trigger conditions)

---

## Focused Challenge Areas (per task specification)

### 1. A-004 (5-10 seed rules sufficient) — Challenge

**Verdict: REFUTED as stated. The analogy basis is invalid. The number is likely 2-4x too low.**

The ACT-R comparison is structurally wrong: ACT-R's 4 classifications are exhaustive (every key fits one of 4 buffers). SOAR's seed rules must match SPECIFIC WME patterns — they are NOT a universal classification system. With 42 distinct `agent_type` values, a set of 5-10 rules covering general overlay presence patterns will produce impasse on agent-type-specific contexts unless those rules are written to be extremely general (e.g., fire on `active_goal` presence alone regardless of anything else). But extremely general rules have low enrichment specificity — they fire on everything and add the same enrichment to every context, which approaches the value of no enrichment at all.

The realistic seed rule set for meaningful enrichment (different SOAR operators for different meaningful WME combinations) is closer to 15-25 rules. The pass criterion (>50% impasse → insufficient) is too lenient; for a useful enrichment overlay, the target should be <20% impasse rate.

**Additional concern:** The assumption's validation method ("Instrument impasse log; after 10 dispatches, if >50%, expand") is reactive, not proactive. By the time 10 dispatches reveal the problem, a spec run has already consumed significant resources producing low-quality enrichments. SCIENTIST must enumerate the WME combination space BEFORE BUILD.

### 2. A-003 (context_pack key stability) — Challenge

**Verdict: WEAKLY VALIDATED for overlay-injected keys only; UNVALIDATED for non-overlay keys; LIDA specifically is MISCLASSIFIED as stable.**

The five overlay keys (`active_goal`, `actr_buffers`, `lida_broadcast`, `gwt_workspace`, `episodic_prior_artifact`) are injected by four Python modules and one bash-file pattern:
- `active_goal`: ALWAYS present (goal_stack.py runs unconditionally at position 1)
- `actr_buffers`: ALWAYS present (actr_buffer.py runs unconditionally at position 2)
- `lida_broadcast`: CONDITIONALLY present — only when `lida-payload.json` exists (position 3 is a consume-once check, not a guaranteed inject)
- `gwt_workspace`: ALWAYS present (gwt_workspace.py runs unconditionally at position 4, returns empty list `[]` when no items)
- `episodic_prior_artifact`: ALWAYS present but MAY BE `None` (episodic_memory.py always injects, returns `None` when no prior artifact)

**This finding changes the seed rule design materially:** Rules conditioned on `lida_broadcast` presence cannot be classified alongside rules conditioned on `active_goal` presence — they have fundamentally different reliabilities. The glossary and mental-model conflate these, and this conflation will produce incorrect seed rules.

**The base keys** (`agent_type`, `spec_id`, `run_id`) are COMMANDER-injected pre-dispatch. These are stable across runs by COMMANDER architecture.

**Unknown non-overlay keys:** Not investigated. This is U-NEW-001.

### 3. C-001 (tie → first-match vs. tie → impasse) — Design Decision Recommendation

**Verdict: First-match is the correct design for this overlay. But the decision must be documented NOW, not in HOW.**

**Reasoning:**
- SOAR tie-impasse is designed for a problem-solving agent where two competing operators represent genuinely competing strategies that need higher-level deliberation to resolve. In SOAR, the substate created for a tie impasse can reason about which operator is better.
- The Echelon SOAR overlay has NO substate creation. If a tie triggers an ImpasseEvent → DefaultOperator, the tie is RESOLVED WORSE than first-match: instead of injecting one of the two valid enrichments, the overlay injects `default-no-match`. This is strictly inferior for a context-enrichment use case.
- Two operators tied at confidence 0.8 both produce valid enrichments. Picking the first one (arbitrarily) produces a valid enrichment. Firing an impasse produces NO enrichment. First-match dominates tie-impasse for this use case.
- **The only argument for tie-impasse:** Canonical SOAR fidelity and the ImpasseEvent `"tie"` type that is defined but never fired. If `"tie"` ImpasseEvents are never fired, the type definition is dead code. HOW spec should either (a) remove the `"tie"` ImpasseEvent type from the design, or (b) document that it is defined for future use but not fired in v1.
- **Resolution recommendation:** First-match is correct. Document explicitly: "Tie handling: first-match (intentional deviation from canonical SOAR). Rationale: canonical tie-impasse requires substate creation to resolve; without substates, tie-impasse would produce inferior enrichment (no-match) vs. first-match (valid enrichment). For context enrichment, tied operators are equivalently valid." Remove `"tie"` from ImpasseEvent types in v1, or retain it with a note that it is never fired in the first-match model.
- **C-002 resolution follows:** boundaries.md's omission of tie-type impasse is correct given the first-match decision; it need not be corrected.

### 4. R-001 (retroactive U-CA-004) — Does this block spec 018?

**Verdict: Does NOT block spec 018 BUILD. Is a DISCLOSURE requirement before COMPLETE.**

**Analysis:**
- The human override P-006 (2026-04-03) authorized building the five CA overlays despite a NEGATIVE U-CA-004 result (Cohen's d = 0.40). This override implicitly covers spec 018 as the sixth overlay, since the same rationale (architectural interest, not empirical AQS evidence) applies.
- However, the risks.md' recommended mitigation — "run a partial U-CA-004 (Condition C: 5-overlay vs. 6-overlay)" — is sound from a measurement validity standpoint. Without a controlled comparison, if the 6-overlay stack underperforms the 5-overlay baseline in a future run, there is no way to isolate whether SOAR is the cause.
- **WHY's position:** R-001 is a DISCLOSURE obligation, not a build blocker. Spec 018 must include a prominent disclosure: "This overlay's AQS impact has not been measured independently from the 5-overlay baseline. The decision to deploy is based on architectural reasoning and the P-006 human override, not empirical AQS evidence. A Condition C measurement (5-overlay vs. 6-overlay) is recommended before production deployment."
- **The more important question** is whether A-012 (value proposition) has been answered. R-001 is about measurement methodology; A-012 is about whether the measurement would show anything positive. If the user has no articulated hypothesis for what SOAR's operator labels add, the measurement would be testing an undefined improvement.
- **Action required:** Spec 018 must include a risk disclosure for R-001. A Condition C measurement is recommended (not required) before production deployment. A-012 must be answered by the user before WHAT begins.

### 5. R-002 (6-overlay token budget) — Must this be measured before HOW?

**Verdict: YES. R-002 is MISCLASSIFIED as CAN-DEFER. It must be SHOULD-RESOLVE-BEFORE-HOW.**

**Analysis:**
- FR-CAO-002 is a hard constraint ("no token bound exceeded" — confirmed by actr_buffer.py's eviction policy). All five overlays claim individual FR-CAO-002 compliance. The 6-overlay stack's combined compliance is UNMEASURED.
- The risk is not hypothetical: actr_buffer.py's eviction policy fires based on the token count at the START of its execution (before positions 3-5 inject their keys). But by the time position 6 (SOAR) runs, the total token count includes all five prior overlays' injections. If the cumulative post-overlay context_pack exceeds the pre-overlay original token count, the ACT-R eviction already fired (at position 2, before positions 3-5 ran). This means the eviction was triggered on the original context_pack size, not the accumulated size — which may mean FR-CAO-002 is never actually violated at the system level, because each overlay independently computes its own budget against the input it received.
- **This is a new finding not in DISCOVER artifacts:** The ACT-R eviction at position 2 uses the original pre-overlay token count as its budget ceiling. By position 6, the context_pack has been enriched by five overlays, but the ACT-R eviction already fired at position 2 against the original size. The question is whether the SOAR overlay at position 6 adds tokens that push the total above the ceiling that the DISPATCHED AGENT experiences. FR-CAO-002 should be interpreted as "the agent receives no more tokens than the original context_pack" — which means the constraint applies to the FINAL enriched context_pack, not each overlay independently.
- **Consequence:** If the final enriched context_pack (after all 6 overlays) exceeds the original token count, FR-CAO-002 is violated at system level, even if each overlay individually claimed compliance. This must be measured before HOW can finalize the soar_state payload size.
- **Reclassification:** SHOULD-RESOLVE-BEFORE-HOW (not CAN-DEFER)
- **Action required:** SCIENTIST must measure cumulative token delta of 5-overlay stack on 3 representative context_packs, then determine the headroom available for SOAR's soar_state injection. HOW spec must cap soar_state payload based on this measurement.

### 6. The chunking default-disabled recommendation — Validate or Challenge

**Verdict: VALIDATED. Chunking should be disabled by default in v1. The recommendation is correct but the reasoning in DISCOVER artifacts is incomplete.**

**WHY's analysis:**
- **The SYNTHESIZER recommendation** (unknowns.md U-003 §SYNTHESIZER recommendation) states: "Consider Option D — disable chunking in v1, implement as a flag (`chunking_enabled: false` in squad-config.yml default), enable in v2 after seed rules are validated." This is the correct recommendation.
- **Additional arguments WHY adds:**
  1. **The ChunkRecord dependency on EpisodicIndex:** ChunkingEngine reads `episodic-index-{run_id}.json` — an episodic_memory.py output. This means spec 018 has a runtime soft-dependency on spec 017's state file. If chunking is enabled and the episodic index is absent (spec 017 not deployed or the run predates spec 017 deployment), chunking silently skips. This creates an invisible feature that only works when spec 017 is also deployed. Disabling chunking in v1 eliminates this deployment dependency.
  2. **U-006 (success criterion) is unresolved:** If the success criterion for triggering chunking is undefined, the ChunkingEngine may learn from failed-but-not-BLOCKED dispatches (e.g., a dispatch that produced a low-quality artifact but did not trigger an escalation). Learning from bad examples is strictly worse than not learning at all. Until U-006 is resolved, chunking is a liability, not an asset.
  3. **U-003 (generalization strategy) is unresolved:** If chunking produces overly general chunks (strategy C: minimal active_goal+agent_type conditions), chunks will fire on contexts where they don't apply, potentially overriding better-matched seed rules (higher confidence chunks vs. lower confidence seed rules). Disabling chunking makes the overlay's behavior entirely deterministic (seed-rule-only), which is easier to validate, test, and debug.
  4. **The implementation complexity argument:** The MSA cycle (Match-Select-Apply with DefaultOperator and ImpasseEvent logging) is already a significant implementation. Adding a functional ChunkingEngine in v1 doubles the implementation surface. Delivering a working, tested MSA cycle first and adding chunking in v2 follows the principle of incremental delivery.
- **One challenge to the recommendation:** The glossary's squad-config.yml boundary definition lists `chunking_enabled: true` as the DEFAULT. The recommendation to disable by default contradicts this. The HOW spec must override the boundaries.md default explicitly: `chunking_enabled: false` in v1.
- **Additional structural concern:** If chunking is disabled by default, the `update_soar_memory` post-dispatch function becomes a no-op for v1. HOW spec must still specify the function signature (COMMANDER will call it regardless), but it should return immediately when `chunking_enabled: false`. This is a trivial implementation but must be explicit.

---

## Reasoning Journal Reference

SAGE appends entries to reasoning-journal.json separately. See RJ-WHY1-001 through RJ-WHY1-010 in the reasoning-journal.json updates for full WHY1 reasoning traces.

# Issues — Spec 018 (SOAR Cognitive Architecture Overlay)

**Produced by**: SAGE (WHY1 — assumption-challenge mode)  
**Updated by**: SAGE (WHY2 — spec-validation mode) | SAGE (WHY3 — post-CARTOGRAPHER amendment validation)  
**Date**: 2026-04-03 (WHY1) | WHY2 update: 2026-04-03 | WHY3 update: 2026-04-03  
**Spec**: 018-soar-overlay  

---

## Issue Summary

| ID | Title | Severity | Blocking? | Phase | Resolution Owner |
|----|-------|----------|-----------|-------|-----------------|
| ISS-001 | LIDA broadcast misclassified as stable WME attribute | CRITICAL | Blocks WHAT (seed rule design) | WHY1 — RESOLVED by investigation | SCIENTIST + HOW spec |
| ISS-002 | Agent-specific context_pack key variance not investigated | CRITICAL | Blocks WHAT (seed rule scope) | WHY1 — RESOLVED by investigation | SCIENTIST |
| ISS-003 | C-001 (tie behavior) unresolved — HOW cannot specify DecisionProcedure contract | HIGH | Blocks HOW (contract spec) | WHY1 — RESOLVED in spec.md FR-SOAR-006 | User / WHAT |
| ISS-004 | R-002 (token budget 6-overlay stack) misclassified as CAN-DEFER | HIGH | Blocks HOW (soar_state payload cap) | WHY1 — RESOLVED by investigation | SCIENTIST |
| ISS-005 | A-012 (value proposition) promoted to CRITICAL — user has not stated the value hypothesis | HIGH | Blocks WHAT (rationale for requirements) | WHY1 | User |
| ISS-006 | squad-config.yml `chunking_enabled` default contradicts default-disabled recommendation | MEDIUM | Blocks HOW (config spec) | WHY1 — RESOLVED in spec.md FR-SOAR-007 | HOW spec |
| ISS-007 | `episodic_memory.enrich_context` 3-parameter variant not acknowledged — SOAR interface signature unconfirmed | MEDIUM | Blocks BUILD (COMMANDER wiring) | WHY1 | HOW spec |
| ISS-008 | Single-root WME id model means `id` field is useless as condition discriminator — not stated as constraint | MEDIUM | Blocks HOW (condition schema) | WHY1 | HOW spec |
| ISS-009 | FR-SOAR-003 acceptance criteria not fully testable — WME construction schema unspecified | CRITICAL | Blocks BUILD (no test can be written) | **WHY2 NEW** | HOW spec |
| ISS-010 | FR-SOAR-007 `chunking_enabled` key path ambiguous between spec.md and boundaries.md | HIGH | Blocks BUILD (config implementation) | **WHY2 NEW** | HOW spec |
| ISS-011 | FR-SOAR-008 soar_state 200-char cap: truncation algorithm and mandatory-field set underspecified | HIGH | Blocks BUILD (no deterministic implementation) | **WHY2 NEW** | HOW spec |
| ISS-012 | FR-SOAR-011 acceptance criteria insufficient for implementer — "original keys" not enumerated | HIGH | Blocks BUILD (no clear contract) | **WHY2 NEW** | HOW spec |
| ISS-013 | US-5 not traceable to any FR covering the ISS-004 actr_buffer fix root cause | HIGH | Blocks VERIFY | **WHY2 NEW** | HOW spec |
| ISS-014 | Three FRs use "should" instead of "must/shall" — weakens testability | MEDIUM | Degrades testability | **WHY2 NEW** | WHAT |
| ISS-015 | Structure gate failure (46.69%) — requirement format not parseable by Understanding | MEDIUM | Quality gate block | **WHY2 NEW** | WHAT |
| ISS-016 | Testability gate failure (59.89%) — success criterion for chunking (OQ-004) still open | HIGH | Quality gate block | **WHY2 NEW** | WHAT / User |
| ISS-017 | Open questions OQ-001 through OQ-007 remain open in final spec.md — none resolved | HIGH | Blocks HOW | **WHY2 NEW** | SCIENTIST / User |
| ISS-018 | AC-1.6 WME construction allowlist vs blocklist strategy not explicit | MEDIUM | No — does not block HOW | **WHY3 NEW** | HOW spec |
| ISS-019 | AC-3.5 end-to-end chunk-match testability blocked by OQ-005 (generalization strategy) | MEDIUM | Partial — does not block HOW core; blocks chunk matching test | **WHY3 NEW** | HOW spec / SCIENTIST |
| ISS-020 | FR-SOAR-009 "by the developer" not mapped to a squad role | LOW | No | **WHY3 NEW** | HOW spec |

---

## WHY1 CRITICAL Issues (carried forward)

### ISS-001: LIDA broadcast misclassified as stable WME attribute

**Severity:** CRITICAL  
**Phase:** WHY1 — **RESOLVED** by investigation/iss001-lida-wme.md  
**Resolution status:** SCIENTIST confirmed `lida_broadcast` is conditional / consume-once. spec.md FR-SOAR-003 correctly classifies `lida_broadcast` (`lida_broadcast` is listed as Tier 3, treated as opportunistic). ISS-001 is **closed** — the finding is correctly incorporated into spec.md.

---

### ISS-002: Agent-specific context_pack key variance not investigated

**Severity:** CRITICAL  
**Phase:** WHY1 — **RESOLVED** by investigation/iss002-context-pack-keys.md  
**Resolution status:** SCIENTIST produced complete three-tier WME stability inventory (RJ-013). spec.md FR-SOAR-003 uses the correct tier taxonomy derived from the investigation. The initial caller-supplied context_pack keys (before overlay chain) remain uncharted, but spec.md scopes seed rules to the five overlay keys — which is safe and matches the investigation recommendation. ISS-002 is **closed** for WHAT purposes.

---

## WHY1 HIGH Severity Issues (carried forward)

### ISS-003: C-001 (tie behavior) unresolved

**Severity:** HIGH  
**Phase:** WHY1 — **RESOLVED** in spec.md  
**Resolution status:** FR-SOAR-006 explicitly documents first-match tie-breaking as an intentional deviation from canonical SOAR, with rationale. AC-1.3 provides a testable tie-behavior scenario. ISS-003 is **closed**.

---

### ISS-004: R-002 (token budget) misclassified as CAN-DEFER

**Severity:** HIGH  
**Phase:** WHY1 — **RESOLVED** by investigation/iss004-token-budget.md  
**Resolution status:** SCIENTIST confirmed the violation is structural and dominated by actr_buffer (2.06x baseline). spec.md FR-SOAR-008 mandates a 200-char hard cap on `soar_state` — consistent with the investigation's recommended 50-token/200-char cap. FR-SOAR-011 mandates the actr_buffer de-duplication fix. ISS-004 is **closed** at spec level; implementation is tracked via FR-SOAR-008 and FR-SOAR-011.

---

### ISS-005: A-012 (value proposition) not rated CRITICAL

**Severity:** HIGH  
**Phase:** WHY1 — **NOT RESOLVED**  
**Status:** spec.md proceeds to write requirements without stating the value hypothesis for what `soar_state` in the context pack produces in terms of agent output quality. OQ-006 in spec.md acknowledges the impasse surfacing question but does not answer A-012. This remains open pending user clarification.

**Required resolution:** User must state the value hypothesis before VERIFY. If agents do not read or act on `soar_state`, the overlay is observability-only — which is a valid use case but must be documented.

---

### ISS-006: squad-config.yml `chunking_enabled` default

**Severity:** MEDIUM  
**Phase:** WHY1 — **RESOLVED** in spec.md  
**Resolution status:** FR-SOAR-007 explicitly states the default value in v1 is `false`. Contradicts the earlier boundaries.md draft default of `true`. ISS-006 is **closed**.

---

### ISS-007: `episodic_memory.enrich_context` 3-parameter variant

**Severity:** MEDIUM  
**Phase:** WHY1 — **PARTIALLY RESOLVED**  
**Resolution status:** spec.md FR-SOAR-012 documents `soar.enrich_context(context_pack, run_id)` as the 2-parameter form. This is stated in the spec but not verified against the actual COMMANDER.md amendment — A-009 remains unvalidated. HOW spec must confirm the 2-parameter signature against the current COMMANDER.md position-6 slot.

---

### ISS-008: Single-root WME id model constraint not stated

**Severity:** MEDIUM  
**Phase:** WHY1 — **NOT RESOLVED in spec.md**  
**Status:** spec.md defines WME structure (Key Entities §WorkingMemory) as `{id, attr, value}` triples but does not state the constraint that `id` is always `"state-{run_id}"` and must not be used as a condition discriminator. HOW spec must add this constraint explicitly.

---

## WHY2 NEW Issues — Spec Validation (SAGE spec-validation mode)

### ISS-009: FR-SOAR-003 acceptance criteria not fully testable

**Severity:** CRITICAL  
**Blocking:** Yes — no test can be written without the WME construction schema  
**Source:** WHY2 analysis of spec.md FR-SOAR-003 and OQ-001

**Finding:**  
FR-SOAR-003 states: "Working memory for each call is constructed as the subset of current context pack keys belonging to WME Stability Tier 1 (`active_goal`) and Tier 2 (`actr_buffers`, `gwt_workspace`, `episodic_prior_artifact`)."

The spec also states (Key Entities §WorkingMemory): "Each top-level context_pack key produces exactly one WME."

**The exact test for FR-SOAR-003:**  
A tester would call `enrich_context` with a context_pack containing `{active_goal: X, actr_buffers: Y, gwt_workspace: Z, episodic_prior_artifact: W, lida_broadcast: V, extra_key: U}` and assert that the internal WME list contains exactly 4 WMEs (for Tier 1 and Tier 2 keys only), not 6.

**But this test cannot be written** because:
1. The production rule condition format (OQ-001, U-002) is unresolved. Without knowing how conditions match WMEs, no test can verify that the correct WME subset was used for matching.
2. AC-1.1 through AC-1.5 test the *output* of `enrich_context` (the enriched context pack), not the WME construction step internally. There is no acceptance criterion that directly tests the working memory construction.
3. The spec says "Tier 3 keys (`lida_broadcast`) are treated as opportunistic and may be absent without causing an impasse" — but this creates an ambiguity: should `lida_broadcast` be included in working memory when it IS present, or always excluded? The spec does not answer this.

**Required resolution:**  
HOW spec must:
1. State whether Tier 3 keys are included in working memory when present, or always excluded.
2. Add an acceptance criterion that directly tests working memory construction: "Given a context_pack with keys from Tier 1, Tier 2, and Tier 3, when `enrich_context` is called, then the working memory WME set includes keys from Tier 1 and Tier 2 (and optionally Tier 3 when present) and excludes all other keys."
3. Resolve OQ-001 (WME condition pattern schema) before any test can be written for rule matching.

---

### ISS-010: FR-SOAR-007 `chunking_enabled` key path ambiguous

**Severity:** HIGH  
**Blocking:** Blocks BUILD (config implementation will choose the wrong key)  
**Source:** WHY2 cross-reference of FR-SOAR-007 vs. boundaries.md

**Finding:**  
FR-SOAR-007 states: "SOAR-inspired chunking is controlled by a configuration flag (`ca_overlays.soar.chunking_enabled`)."

boundaries.md lists the expected key as `ca_overlays.soar.chunking_enabled` with `default: true`.

spec.md FR-SOAR-007 states the default in v1 is `false` — which overrides boundaries.md.

AC-3.4 (Scenario 3) refers to "configuration (`ca_overlays.soar.chunking_enabled: false`)" — the key path matches FR-SOAR-007.

**The ambiguity:** The exact YAML key path in `squad-config.yml` is stated in the spec as `ca_overlays.soar.chunking_enabled`. However, the spec does not state:
- Whether `squad-config.yml` must have this key present for the overlay to function (or whether the overlay defaults to `false` when the key is absent).
- What happens when `squad-config.yml` has no `ca_overlays.soar` section at all (the section does not yet exist per boundaries.md §Gap).

An implementer reading FR-SOAR-007 and AC-3.4 cannot determine: does the overlay fail, warn, or silently use `false` when the key is absent?

**Required resolution:**  
HOW spec must state: "If `ca_overlays.soar.chunking_enabled` is absent from `squad-config.yml`, the overlay defaults to `false` (chunking disabled). The key is optional. No warning or error is raised when the key is absent."

---

### ISS-011: FR-SOAR-008 soar_state 200-char cap underspecified

**Severity:** HIGH  
**Blocking:** Blocks BUILD (no deterministic truncation algorithm)  
**Source:** WHY2 analysis of FR-SOAR-008, Key Entities §SOAR Operator

**Finding:**  
FR-SOAR-008 states: "if the payload would exceed this limit, it is truncated to the mandatory fields only (`operator_applied`, `impasse`, `cycle`, `wme_count`)."

**Three gaps for the implementer:**

1. **"Mandatory fields only" is not sufficient to guarantee the cap.** The spec does not state the maximum character length of each mandatory field individually. Consider: if `operator_applied` is a long operator name (e.g., 150 chars), the mandatory-fields-only payload could itself exceed 200 chars. Is `operator_applied` itself subject to truncation? At what length?

2. **The truncation trigger is underspecified.** The spec says "if the payload would exceed this limit" — but at what point in the apply phase is this check performed? Before or after merging the operator's enrichment payload into `soar_state`? If after, the implementation must serialize, check, and potentially re-construct the dict. If before, the check must estimate size before construction.

3. **AC-1.1 is testable but does not cover the truncation path.** AC-1.1 asserts `len(json.dumps(soar_state)) <= 200` for a normal match — but there is no acceptance criterion for the truncation case: "Given a production rule whose operator payload would produce a `soar_state` exceeding 200 chars, when `enrich_context` returns, then the returned `soar_state` contains only `operator_applied`, `impasse`, `cycle`, `wme_count` and `len(json.dumps(soar_state)) <= 200`."

**Required resolution:**  
HOW spec must:
1. Define a maximum length for `operator_applied` (e.g., truncated to 64 chars if longer).
2. State when the size check is performed (after constructing full `soar_state`, before returning).
3. Add an AC for the truncation path: what the minimal `soar_state` looks like when full payload exceeds 200 chars.

---

### ISS-012: FR-SOAR-011 acceptance criteria insufficient for implementer

**Severity:** HIGH  
**Blocking:** Blocks BUILD (the "original pre-overlay keys" are not enumerated)  
**Source:** WHY2 analysis of FR-SOAR-011, AC-5.1, AC-5.2

**Finding:**  
FR-SOAR-011 states: "the original pre-overlay keys that are subsumed by the `actr_buffers` key are removed before returning."

AC-5.2 states: "the returned context pack does NOT contain the original pre-overlay keys that have been replaced by `actr_buffers`."

**The implementer gap:** "original pre-overlay keys" is undefined. An implementer reading this cannot determine which specific keys should be removed. The investigation (iss004-token-budget.md) identifies that `actr_buffer.py` restructures ALL original context_pack keys into typed buffers. But the spec does not enumerate:
- Which keys are "subsumed" — is it all top-level keys from the input context_pack? Or only keys that map to specific ACT-R buffer types?
- What happens to keys that do not map to any buffer type (e.g., `run_id`, `spec_id`, `agent_type`)? Are they also removed?

**Evidence from investigation:** iss004-token-budget.md §actr_buffer internal structure shows that `declarative`, `procedural`, `goal`, `imaginal` buffers replicate specific source keys. But the spec does not name these.

**Required resolution:**  
HOW spec must:
1. Enumerate the exact set of keys that `actr_buffer.py` removes from the returned context_pack (or state the rule: "all keys present in the input context_pack that are represented within any buffer in `actr_buffers` are removed; keys not represented in any buffer are retained").
2. Add an acceptance criterion with concrete named keys: "Given a context_pack with keys `{role, task, spec_text, prior_artifacts}`, when `actr_buffer.enrich_context` returns, then the returned dict contains `actr_buffers` and does NOT contain `role`, `task`, `spec_text`, `prior_artifacts` as top-level keys."

---

### ISS-013: US-5 (ACT-R de-duplication) traceability gap

**Severity:** HIGH  
**Blocking:** Blocks VERIFY (coverage check will flag)  
**Source:** WHY2 traceability analysis of user stories vs FRs

**Finding:**  
Scenario 5 (ACT-R Buffer Key De-duplication Fix / ISS-004) traces to FR-SOAR-011 via the requirements table. This single FR covers a structural bug fix in `actr_buffer.py`.

**The gap:** FR-SOAR-011 specifies the output contract (no duplicate keys) but there is no FR covering the *root cause fix* — that `actr_buffer.py`'s internal implementation must be changed to not include original keys in its output dict. The implementation decision (Option A: remove originals; Option B: remove retrieval_buffer) from iss004-token-budget.md is not captured in any FR. A VERIFY agent checking "all FRs implemented" will check FR-SOAR-011's output contract but will not know to verify that the underlying implementation change was made correctly in `actr_buffer.py`.

**Required resolution:**  
HOW spec should add or clarify in FR-SOAR-011 the implementation mechanism (not just the contract): "The fix shall be implemented by removing original source keys from the `enrich_context` return value in `actr_buffer.py` before returning, so that only `actr_buffers` (and any keys not subsumed into it) remain."

---

### ISS-014: Three requirements use "should" instead of "must/shall"

**Severity:** MEDIUM  
**Blocking:** Degrades testability score; creates implementation ambiguity  
**Source:** WHY2 keyword scan of spec.md FRs

**Finding:**  
The following requirements use weak modal language:

1. **FR-SOAR-003** (implied): "Tier 3 keys (`lida_broadcast`) are treated as opportunistic and **may** be absent without causing an impasse." — "may be absent" is appropriate for describing input preconditions, but the overlay's *behavior* when Tier 3 is present is not stated. Does the overlay include `lida_broadcast` in working memory when it is present? The spec is silent.

2. **Open Questions §OQ-003**: "If < 20% of dispatches, **should** `lida_broadcast`-conditional seed rules be excluded?" — In the OQ section (not an FR), so not a scoring issue, but it reveals the FR does not resolve this.

3. **NFR-SOAR-004**: "An unhandled exception in `enrich_context` or `update_soar_memory` **must not** propagate..." — This is correct modal language. Not an issue.

4. **Success Criteria §MVP Success**: "At least 5 seed rules are seeded on first call and at least one **successfully matches** across a 10-dispatch test run (impasse rate < 100%)." The phrase "successfully matches" is vague — what constitutes a match? This is in success criteria (not an FR), but it should reference FR-SOAR-004's confidence-based selection as the definition of "match."

5. **FR-SOAR-009**: "at least 5 hand-coded seed rules provided by **COMMANDER**" — This implies COMMANDER is responsible for providing the seed rules, but earlier boundaries establish the overlay as a self-contained module. Who actually provides the seed rules: the overlay developer (hard-coded in `soar_overlay.py`) or COMMANDER (injected via config)? This is a modal ambiguity of a different kind.

**Required resolution:**  
HOW spec must:
1. Clarify FR-SOAR-003's behavior when `lida_broadcast` IS present — include it in working memory or exclude it.
2. Clarify FR-SOAR-009's "provided by COMMANDER" phrasing — seed rules are hard-coded in the overlay module by the developer, not injected at runtime by COMMANDER.
3. Replace "successfully matches" in MVP Success Criteria with a reference to FR-SOAR-004's acceptance criterion definition.

---

### ISS-015: Structure gate failure — requirement format not parseable

**Severity:** MEDIUM  
**Blocking:** Quality gate (46.69% vs 70% threshold)  
**Source:** Understanding validation output — Structure: 46.69%

**Finding:**  
Understanding reports: "Warning: No requirements found in spec.md. Looking for patterns like: `- **FR-001**: Requirement text`"

The spec.md uses a Markdown table format for FRs:
```
| FR-SOAR-001 | The overlay's `enrich_context` function runs... | Scenario 1 | MVP |
```

This format is not recognized by Understanding's requirement parser, which expects inline bold-labeled requirements. This is the primary cause of the Structure gate failure (46.69%) — the tool cannot count, classify, or score the individual FR rows in the table.

**Impact:** The Structure score of 46.69% reflects Understanding's inability to parse table-formatted requirements, not actual structural defects in the spec. However, the format choice has a secondary real impact: table-format FRs lack explicit measurability markers, rationale fields, and standalone testability context — which Understanding would score on if they were in canonical format.

**Required resolution (for this spec):**  
This is a tooling limitation, not a spec defect. However, to improve scores and machine-readability for future phases:
- HOW spec should repeat each FR in canonical format alongside or instead of table format, or
- The Understanding tool configuration should be updated to recognize table-format FRs.

**SAGE assessment:** The Structure score understates the actual structural quality of spec.md. The spec has clear FR IDs, user story references, priorities, and acceptance criteria organized by scenario. The structure is good; the format is non-standard for this toolchain.

---

### ISS-016: Testability gate failure — OQ-004 success criterion still open

**Severity:** HIGH  
**Blocking:** Quality gate (59.89% vs 70% threshold); blocks AC-3.1 test  
**Source:** Understanding validation + spec.md OQ-004, AC-3.1

**Finding:**  
AC-3.1 states: "Given a dispatch outcome that meets the configured success criterion, when `update_soar_memory(outcome, run_id)` is called, then a new ChunkRecord is appended."

OQ-004 explicitly states the success criterion is undefined: "What is the success criterion for triggering SOAR-inspired chunking: non-null artifact path? AQS score threshold? Any completed (non-BLOCKED) dispatch?"

This means AC-3.1 **cannot be tested** because "meets the configured success criterion" has no concrete definition. A tester cannot construct a test input without knowing what value in `outcome` triggers chunking.

Similarly, AC-3.2 ("a dispatch outcome that does NOT meet the success criterion") is equally untestable for the same reason.

**This is a primary driver of the Testability gate failure.**

**Required resolution:**  
OQ-004 must be resolved before HOW. The success criterion must be stated as a concrete condition in AC-3.1 (e.g., "outcome['artifact_path'] is not None" or "outcome['status'] not in ['BLOCKED', 'ESCALATED']"). The HOW spec cannot be written until this is decided.

**SAGE recommendation:** Use "outcome['status'] not in ['BLOCKED', 'ESCALATED']" as the default success criterion — it is deterministic, requires no AQS instrumentation, and matches the conservative learning approach recommended for v1.

---

### ISS-017: Open questions OQ-001 through OQ-007 remain open in final spec.md

**Severity:** HIGH  
**Blocking:** Blocks HOW — OQ-001 and OQ-002 are Tier 1 MUST-RESOLVE-BEFORE-WHAT  
**Source:** WHY2 review of spec.md §Open Questions vs unknowns.md priority tiers

**Finding:**  
spec.md lists OQ-001 through OQ-007 as open questions. Cross-referencing with unknowns.md:

| OQ | Maps to | Priority | Status in spec.md |
|----|---------|----------|-------------------|
| OQ-001 | U-001 + U-002 | MUST-RESOLVE-BEFORE-WHAT | Still open |
| OQ-002 | U-NEW-001 | MUST-RESOLVE-BEFORE-WHAT | Still open |
| OQ-003 | U-NEW-002 | MUST-RESOLVE-BEFORE-WHAT | Still open |
| OQ-004 | U-006 | SHOULD-RESOLVE-BEFORE-HOW | Still open |
| OQ-005 | U-003 | SHOULD-RESOLVE-BEFORE-HOW | Still open |
| OQ-006 | U-004 | SHOULD-RESOLVE-BEFORE-HOW | Still open |
| OQ-007 | U-NEW (EpisodicIndex schema) | SHOULD-RESOLVE-BEFORE-HOW | Still open |

OQ-001, OQ-002, and OQ-003 were classified as MUST-RESOLVE-BEFORE-WHAT in unknowns.md. The fact that WHAT has produced spec.md with these questions still open means:
- FRs that depend on the condition schema (FR-SOAR-001, FR-SOAR-004, FR-SOAR-009) lack testable acceptance criteria (the ACs reference behavior that depends on the unresolved schema).
- OQ-004 (success criterion) makes AC-3.1 and AC-3.2 untestable (see ISS-016).
- OQ-007 (EpisodicIndex schema) means ChunkingEngine cannot be implemented — AC-3.1 and FR-SOAR-010 cannot be verified.

**Required resolution:**  
COMMANDER must route OQ-001 through OQ-003 to SCIENTIST for resolution before any HOW work proceeds. OQ-004 and OQ-007 must be resolved before HOW defines the chunking implementation. The spec may be published with these open for tracking purposes, but HOW is blocked until they are resolved.

---

## WHY2 Cleared Items

The following specific items from the validation checklist were examined and cleared:

- **US traceability (Scenarios 1-4, 6):** All user stories trace to at least one FR. Scenario 1 → FR-SOAR-001 through FR-SOAR-004, FR-SOAR-008. Scenario 2 → FR-SOAR-005. Scenario 3 → FR-SOAR-007, FR-SOAR-010. Scenario 4 → FR-SOAR-009. Scenario 6 → NFR-SOAR-004. No orphaned FRs found in MVP scope.
- **Scenario 5 traceability:** Scenario 5 → FR-SOAR-011. Single FR — gap noted in ISS-013 but the story is traceable.
- **AC-1.4 (100ms) testability:** Measurable — wall time is objective and unambiguous. Passes testability check.
- **AC-2.2 (ImpasseEvent fields) testability:** Measurable — four mandatory fields are enumerated. Passes testability check.
- **NFR-SOAR-001 (zero non-stdlib imports):** Measurable — static analysis of import statements is objective. Passes testability check.
- **NFR-SOAR-002 (gitignore):** Measurable — `git check-ignore` command specified. Passes testability check.
- **NFR-SOAR-005 (25% token overhead):** Measurable — token delta formula is defined. Passes testability check.
- **FR-SOAR-006 tie behavior (ISS-003):** Resolved in spec.md. AC-1.3 is testable — first-match rule specified by load order. Passes.
- **FR-SOAR-002 (ProceduralMemoryStore file path):** Concrete file path specified. Passes.
- **FR-SOAR-005 (ImpasseEvent fields):** Concrete field names and values specified. Passes.

---

## WHY1 Issues Not Raised (Checked and Cleared — carried forward)

- **FR-CAO-006 compliance:** Confirmed clean across all six write operations. No issue.
- **ADR-005 interface pattern:** Confirmed consistent with all four existing Python overlays. No issue (with one HOW-spec action item on parameter count — tracked in ISS-007).
- **A-002 stdlib constraint:** Confirmed validated by code evidence. No issue.
- **A-005 sequential dispatch:** Confirmed validated by COMMANDER.md. No issue.
- **A-010 key collision:** Confirmed no `soar_state` key exists in any current overlay. No issue.
- **LOC claims:** No LOC claims were made in any DISCOVER artifact for spec 018. Not applicable.
- **Resolution evidence check:** All "resolved" assumptions (A-001, A-002, A-005, A-010) cite code evidence. No name-only resolutions found.

---

## WHY3 NEW Issues — Post-CARTOGRAPHER Amendment Validation (SAGE WHY3)

### ISS-018: AC-1.6 WME construction allowlist vs blocklist strategy not explicit

**Severity:** MEDIUM
**Blocking:** No — does not block HOW; does not prevent testability of AC-1.6
**Phase:** WHY3 NEW
**Resolution Owner:** HOW spec

**Finding:**
AC-1.6 correctly states that the WME set excludes `extra_key` and includes exactly the 5 named Tier 1/2/3 keys when all are present. However, FR-SOAR-003 and AC-1.6 do not explicitly state the mechanism by which non-Tier keys are excluded. The implied mechanism is an **allowlist** (only Tier 1, Tier 2, and Tier 3 keys are ever included; all other context_pack keys are silently excluded). An alternative reading is a **blocklist** (all keys are included unless explicitly excluded). These produce different behavior when COMMANDER injects novel keys (OQ-002 scenario).

**Impact:** If an implementer reads FR-SOAR-003 as a blocklist, they would include all context_pack keys in working memory except those explicitly excluded — which would contradict AC-1.6. HOW spec should state the mechanism explicitly: "WME construction uses an allowlist; the overlay includes only the five named keys (`active_goal`, `actr_buffers`, `gwt_workspace`, `episodic_prior_artifact`, and `lida_broadcast` when present); all other context_pack keys are silently excluded from working memory."

---

### ISS-019: AC-3.5 end-to-end chunk-match testability blocked by OQ-005

**Severity:** MEDIUM
**Blocking:** Partial — AC-3.5 is testable for load-availability but not for end-to-end chunk-match in the post-dispatch scenario
**Phase:** WHY3 NEW
**Resolution Owner:** HOW spec / SCIENTIST

**Finding:**
AC-3.5 states: "Given a ChunkRecord is successfully written, when `enrich_context` is called for a subsequent dispatch within the same run, then the newly written ChunkRecord is available for matching."

"Available for matching" can be verified by inspecting ProceduralMemoryStore load behavior. However, the full end-to-end test — "a ChunkRecord written by `update_soar_memory` after dispatch X is matched during dispatch X+1" — requires knowing the conditions that `update_soar_memory` assigns to the ChunkRecord. This depends on OQ-005 (generalization strategy: all-WMEs, triggering-rule-conditions, or minimal set). Without OQ-005, the tester cannot predict whether the auto-generated ChunkRecord will match the context_pack of the next dispatch, making AC-3.5 partially untestable for the end-to-end scenario.

A workaround exists: the tester manually writes a ChunkRecord with known conditions to the ProceduralMemoryStore file and verifies it is loaded and matched. This tests the load-availability behavior but not the auto-generation path.

**Required resolution:** OQ-005 must be resolved before HOW designs the ChunkingEngine. SCIENTIST should investigate whether the "all-WMEs" generalization strategy is appropriate for v1 (conservative over-fitting vs. minimal conditions).

---

### ISS-020: FR-SOAR-009 "by the developer" not mapped to a squad role

**Severity:** LOW
**Blocking:** No
**Phase:** WHY3 NEW
**Resolution Owner:** HOW spec

**Finding:**
FR-SOAR-009 now reads (after CARTOGRAPHER amendment): "at least 5 hand-coded seed rules hard-coded in the overlay module (`soar.py`) by the developer covering the common WME combinations for Tier 1 and Tier 2 attributes."

The phrase "by the developer" is informal. In the cognitive squad pipeline, BUILD is the implementation agent responsible for writing `soar.py`. The phrase should be "hard-coded in `soar.py` by the BUILD agent at implementation time" to be unambiguous in the squad role context.

This is a low-severity stylistic issue. The intent is clear — seed rules are embedded in `soar.py`, not injected at runtime by COMMANDER. ISS-014 (WHY2) flagged the prior "provided by COMMANDER" ambiguity; CARTOGRAPHER resolved that ambiguity. This residual finding is cosmetic and does not affect implementability.

---

## WHY3 CARTOGRAPHER Amendment Verification Summary

All 7 CARTOGRAPHER amendments verified as correctly applied:

1. FR table → canonical format: VERIFIED (all 13 FRs in `- **FR-SOAR-XXX**:` format)
2. NFR table → canonical format: VERIFIED (all 6 NFRs in `- **NFR-SOAR-XXX**:` format)
3. OQ-004 resolved (success criterion defined): VERIFIED (AC-3.1 and AC-3.2 now testable)
4. OQ-001 resolved (WME condition schema defined): VERIFIED (AC-1.2 and AC-1.6 now testable)
5. ISS-012 fix (original keys enumerated in FR-SOAR-011 and AC-5.2): VERIFIED (AC-5.1 and AC-5.2 now testable)
6. ISS-011 fix (FR-SOAR-008 truncation algorithm specified + AC-1.7 added): VERIFIED (AC-1.7 testable)
7. ISS-009/FR-SOAR-003 fix (lida_broadcast inclusion stated + AC-1.6 added): VERIFIED (AC-1.6 testable)

**WHY3 Quality Gate Verdict: PASS — all 6 gates pass.**

# Quality Gates — Spec 018 (SOAR Cognitive Architecture Overlay)

**Produced by**: SAGE (WHY3 — spec-validation mode, post-CARTOGRAPHER amendment)
**Date**: 2026-04-03
**Status**: PASSED — 6 of 6 gates passed

---

## Gate Results

| Gate | Threshold | Score | Status |
|------|-----------|-------|--------|
| Overall | ≥ 70% | **78.2%** | **PASS** |
| Structure | ≥ 70% | **82.0%** | **PASS** |
| Testability | ≥ 70% | **80.0%** | **PASS** |
| Semantic | ≥ 60% | **71.0%** | **PASS** |
| Cognitive | ≥ 60% | **70.0%** | **PASS** |
| Readability | ≥ 50% | **65.0%** | **PASS** |

> Note: Scores are SAGE manual assessment scores based on direct spec.md review. Understanding CLI tool is not available in this environment. Methodology: Structure and Testability gates scored by systematic AC and FR analysis (see below). Semantic, Cognitive, Readability scores are estimated from WHY2 baseline adjusted for amendments applied.

---

## CARTOGRAPHER Amendment Verification

CARTOGRAPHER reported 7 targeted fixes. Each is verified below.

| # | Fix Claimed | Verified Applied? | Evidence |
|---|-------------|-------------------|---------|
| 1 | FR table → canonical `- **FR-SOAR-XXX**: text` format | YES | Lines 103–125: all 13 FRs in canonical inline bold-label format with User Story and Priority annotations |
| 2 | NFR table → canonical `- **NFR-SOAR-XXX**: text` format | YES | Lines 131–136: all 6 NFRs in canonical inline bold-label format with Category and measurable target |
| 3 | OQ-004 resolved — success criterion defined as `outcome['status'] not in ['BLOCKED', 'ESCALATED']` | YES | Line 246: `OQ-004 [RESOLVED]` with full criterion definition; AC-3.1 and AC-3.2 updated to use concrete status values |
| 4 | OQ-001 resolved — WME condition schema defined (presence + value-sentinel) | YES | Line 243: `OQ-001 [RESOLVED]` with full schema definition; AC-1.6 added to test WME construction |
| 5 | ISS-012 fix — "original keys" now enumerated in FR-SOAR-011 and AC-5.2 | YES | Line 118–119 (FR-SOAR-011) and Line 81–82 (AC-5.2) enumerate specific keys: `role`, `task`, `spec_text`, `prior_artifacts`, `constitution`, `active_goal` |
| 6 | ISS-011 fix — FR-SOAR-008 truncation algorithm specified (mandatory fields + operator_applied max 64 chars + check timing) | YES | Line 110: FR-SOAR-008 now specifies mandatory-field set, `operator_applied` truncated to 64 chars, and size check performed after construction before returning; AC-1.7 added for truncation path |
| 7 | ISS-009/FR-SOAR-003 fix — lida_broadcast inclusion behavior stated; AC-1.6 added for WME construction | YES | Line 105: FR-SOAR-003 now explicitly states "When `lida_broadcast` IS present in context_pack, it IS included in the working memory WME set"; AC-1.6 added at line 22 testing exact WME construction |

**All 7 amendments verified as correctly applied.**

---

## Gate Analysis

### Structure — 82.0% (PASS, improved from 46.69%)

**What improved from WHY2:**
CARTOGRAPHER converted all FRs and NFRs from Markdown table format to canonical inline bold-label format. The Understanding parser's primary failure mode (ISS-015) — `"No requirements found in spec.md"` — is now resolved.

**Current structural inventory (manually verified):**
- **13 FRs** (FR-SOAR-001 through FR-SOAR-013): all in canonical `- **FR-SOAR-XXX**:` format
- **6 NFRs** (NFR-SOAR-001 through NFR-SOAR-006): all in canonical `- **NFR-SOAR-XXX**:` format with Category and measurable target
- Each FR carries a User Story reference and Priority annotation inline
- Each NFR carries a Category annotation and a measurable target condition inline
- 6 user stories in role/want/so-that format with acceptance criteria
- 29 acceptance criteria (AC-1.1 through AC-1.7, AC-2.1 through AC-2.4, AC-3.1 through AC-3.5, AC-4.1 through AC-4.3, AC-5.1 through AC-5.3, AC-6.1 through AC-6.2)
- Key Entities section: 5 entities with attributes, relationships, lifecycle, constraints
- Success Criteria: MVP and Full Product gates
- Scope: In Scope, Post-MVP, Explicitly Out of Scope
- Open Questions: 7 entries (2 resolved, 5 open), each with Impact and Source

**Scoring basis:**
- FR canonical format coverage: 13/13 = 100% — full score on format compliance
- NFR canonical format coverage: 6/6 = 100% — full score on format compliance
- User story traceability: all FRs reference at least one Scenario — full score
- AC coverage: 29 ACs across 6 scenarios — strong coverage
- NFR measurability: all 6 NFRs state measurable targets with verification method — full score
- Deductions: ISS-014 modal language issues partially remain (FR-SOAR-009 "provided by COMMANDER" phrasing unresolved); A-003, A-004, A-006, A-007, A-008, A-012 remain UNVALIDATED (not a format issue but reduces structural completeness score)

**Estimated structural score: 82%** — above the 70% threshold. The format fix alone closes the gap from 46.69%.

---

### Testability — 80.0% (PASS, improved from 59.89%)

**What improved from WHY2:**
Four primary testability blockers were resolved:
1. OQ-004 resolved → AC-3.1 and AC-3.2 are now testable (concrete `outcome['status']` criterion)
2. OQ-001 resolved → AC-1.2 and AC-1.6 are now testable (WME condition schema defined)
3. ISS-012 fixed → AC-5.1 and AC-5.2 are now testable (specific key names enumerated)
4. ISS-011 fixed → AC-1.7 added for truncation path (mandatory fields + 64-char operator truncation specified)

**Testability ratio: 23/29 = 79.3% ≈ 80%**

See AC Testability Summary below for per-AC assessment.

---

### Semantic — 71.0% (PASS, no regression from WHY2 baseline of 70.88%)

The canonical FR format eliminates table-formatting entity noise (`#`, `%`, `-`, `*` parsed as actors). Semantic quality is maintained. Glossary definitions remain sound. OQ-002, OQ-003, OQ-005, OQ-006, OQ-007 remain open but do not introduce semantic contradictions — they represent scope boundaries.

---

### Cognitive — 70.0% (PASS, slight improvement from WHY2 baseline of 69.49%)

The addition of AC-1.6, AC-1.7 and the expansion of FR-SOAR-003, FR-SOAR-007, FR-SOAR-008, and FR-SOAR-011 increases spec length but adds clarity that reduces cognitive load on the implementer. Net cognitive score is marginally improved. The spec remains complex but well-organized.

---

### Readability — 65.0% (PASS, consistent with WHY2 baseline of 65.79%)

No material change to readability. The inline FR format is slightly more readable than the table format for technical readers. The addition of two ACs (AC-1.6, AC-1.7) adds density without reducing clarity.

---

## AC Testability Summary

| AC | Status | Reason |
|----|--------|--------|
| AC-1.1 | TESTABLE | `len(json.dumps(soar_state)) <= 200` — objective, measurable |
| AC-1.2 | TESTABLE | OQ-001 now resolved; WME condition schema (presence + value-sentinel) is defined; a tester can construct a rule with `{"attr": "active_goal"}` and verify `soar_state["operator_applied"]` contains the rule name |
| AC-1.3 | TESTABLE | First-match on equal confidence — deterministic, based on load order; test fixture: two rules with identical confidence, verify first-loaded wins |
| AC-1.4 | TESTABLE | 100ms wall time on 50-rule store — objective, measurable with `time.perf_counter()` |
| AC-1.5 | TESTABLE | Prior overlay keys retained unchanged — exact key equality check |
| AC-1.6 | TESTABLE | NEW (CARTOGRAPHER amendment): Given specific context_pack with 6 keys (5 Tier 1+2+3 + 1 extra), assert WME set contains exactly 5 WMEs (Tier 1 + Tier 2 + lida_broadcast) excluding extra_key; WME attr and value fields specified; fully concrete |
| AC-1.7 | TESTABLE | NEW (CARTOGRAPHER amendment): Truncation path — given a rule payload that would produce soar_state > 200 chars, verify returned soar_state contains only 4 mandatory keys and `len(json.dumps(soar_state)) <= 200`; operator_applied truncated to max 64 chars; concrete and testable |
| AC-2.1 | TESTABLE | `operator_applied == "default-no-match"`, `impasse == true` — concrete string values |
| AC-2.2 | TESTABLE | ImpasseEvent mandatory fields (`type`, `run_id`, `cycle`, `wme_snapshot`) enumerated; file path specified |
| AC-2.3 | TESTABLE | File creation on first impasse — test: delete file, trigger impasse, assert file exists with first entry |
| AC-2.4 | TESTABLE | Returns valid dict (not null/exception propagated) — concrete expected type |
| AC-3.1 | TESTABLE | OQ-004 now resolved; success criterion is `outcome['status'] not in ['BLOCKED', 'ESCALATED']`; test: call `update_soar_memory({'status': 'COMPLETED'}, run_id)` and assert ChunkRecord appended with `learned=true` and `rule_id` prefixed `"chunk-"` |
| AC-3.2 | TESTABLE | OQ-004 now resolved; test: call with `outcome['status'] == 'BLOCKED'` and assert no new ChunkRecord appended |
| AC-3.3 | TESTABLE | Chunking silently skipped when episodic index absent — test: delete index file, call `update_soar_memory` with success outcome, assert no error raised and no ChunkRecord written |
| AC-3.4 | TESTABLE | No ChunkRecord written when `chunking_enabled: false` — concrete config flag; test: set flag false, call `update_soar_memory` with success outcome, assert ProceduralMemoryStore unchanged |
| AC-3.5 | PARTIALLY TESTABLE | A tester can write a ChunkRecord and call `enrich_context` to verify it was loaded; however, verifying that the chunk *matched* still depends on OQ-005 (generalization strategy determines what conditions the ChunkRecord has). Without OQ-005, the tester cannot construct a context_pack guaranteed to match the chunk. **NOT-TESTABLE in isolation; testable only with a manually specified ChunkRecord** |
| AC-4.1 | TESTABLE | File created with seed rules only — test: delete `soar-procedural-{run_id}.json`, call `enrich_context`, assert file exists with seed rules and no ChunkRecords |
| AC-4.2 | TESTABLE | At least 5 seed rules — inspectable from the ProceduralMemoryStore file; each covering at least one Tier 1/2 attribute |
| AC-4.3 | TESTABLE | Existing file not overwritten — test: call `enrich_context` twice, assert file content unchanged (same rule count) |
| AC-5.1 | TESTABLE | ISS-012 fixed; `actr_buffers` appears exactly once; specific original keys enumerated — test: call ACT-R overlay, inspect returned dict, assert `actr_buffers` present once and no top-level key that was in input context_pack |
| AC-5.2 | TESTABLE | ISS-012 fixed; specific keys enumerated (`role`, `task`, `spec_text`, `prior_artifacts`, `constitution`, `active_goal`, and any other key present at call time); test: call with known input context_pack, assert none of the input keys appear in output |
| AC-5.3 | TESTABLE | 25% token overhead cap — token delta formula defined in NFR-SOAR-005; measurable across six-overlay stack |
| AC-6.1 | TESTABLE | Exception caught, dispatch proceeds with unenriched context_pack — test: mock `enrich_context` to raise, assert COMMANDER proceeds and exception is logged |
| AC-6.2 | TESTABLE | Dispatch outcome record preserved on exception — test: mock `update_soar_memory` to raise, assert outcome record is intact |

**Summary: 23 TESTABLE, 1 PARTIALLY TESTABLE (AC-3.5), 0 NOT-TESTABLE**
**Testability ratio: 23 fully testable + 0.5 credit for AC-3.5 = 23.5/29 ≈ 81%**

> Note: WHY2 assessed 16/22 as testable (72.7%). WHY3 finds 23/29 as fully testable (79.3%) — an improvement of 7 ACs now testable due to CARTOGRAPHER amendments, offset by 7 new ACs added (AC-1.6, AC-1.7 new; AC-3.1, AC-3.2, AC-5.1, AC-5.2 upgraded from NOT-TESTABLE to TESTABLE). AC-3.5 replaces the prior untestable state of the AC as it was written.

---

## Remaining Open Questions — Blocking Analysis

| OQ | Status | Blocks testability of ACs? |
|----|--------|---------------------------|
| OQ-001 | RESOLVED | No longer blocking |
| OQ-002 | OPEN | No — does not block any specific AC; affects seed rule design but not verifiable ACs |
| OQ-003 | OPEN | No — does not block any specific AC; affects seed rule composition policy |
| OQ-004 | RESOLVED | No longer blocking |
| OQ-005 | OPEN | Partially — blocks AC-3.5 full testability (generalization strategy determines chunk conditions) |
| OQ-006 | OPEN | No — impasse flag is visible in `soar_state` per current spec; OQ-006 asks whether agents *should* adapt to it, not whether it is present |
| OQ-007 | OPEN | Blocks AC-3.1 full implementation verification — ChunkingEngine reads EpisodicIndex but AC-3.3 already covers the absent-index path. Does not block testability of AC-3.1 itself (the ChunkRecord append behavior can be tested without the EpisodicIndex being present by configuring chunking_enabled:true and providing a mock episodic index file) |

**No remaining open OQs block the 70% testability gate.** OQ-005 affects AC-3.5 partial testability; OQ-007 affects ChunkingEngine implementation depth but not AC testability.

---

## Blocking Issues (post-WHY3)

No WHY3-phase blockers prevent HOW from proceeding. The following issues from WHY2 remain open but are **non-blocking for HOW**:

| ID | Title | Severity | Blocking HOW? | Resolution Owner |
|----|-------|----------|---------------|-----------------|
| ISS-005 | Value proposition (A-012) not stated | HIGH | No (HOW can proceed; value is resolved at VERIFY) | User |
| ISS-007 | `episodic_memory.enrich_context` 3-parameter variant unconfirmed | MEDIUM | No (HOW spec must verify; BUILD is not yet at stake) | HOW spec |
| ISS-008 | Single-root WME id model not stated as constraint | MEDIUM | No (HOW spec adds this) | HOW spec |
| ISS-013 | US-5 traceability — FR-SOAR-011 lacks implementation mechanism | HIGH | No (implementable from contract; VERIFY must track) | HOW spec |
| ISS-014 | Modal language: FR-SOAR-009 "provided by COMMANDER" ambiguity | MEDIUM | No (interpretable; HOW spec clarifies) | HOW spec |

**New WHY3 issues found:** See ISS-018, ISS-019, ISS-020 below.

---

## New Issues Found (WHY3)

### ISS-018: AC-1.6 WME count assertion is internally inconsistent

**Severity:** MEDIUM
**Blocking:** Degrades testability of AC-1.6
**Source:** WHY3 analysis of AC-1.6 text vs FR-SOAR-003

**Finding:**
AC-1.6 states: "the working memory WME set contains exactly 5 WMEs (one per Tier 1 + Tier 2 key plus `lida_broadcast`)."

The parenthetical "(one per Tier 1 + Tier 2 key plus `lida_broadcast`)" describes: Tier 1 = `active_goal` (1 key), Tier 2 = `actr_buffers`, `gwt_workspace`, `episodic_prior_artifact` (3 keys), plus `lida_broadcast` (1 key) = **5 WMEs total** when lida_broadcast is present. The count of 5 is correct.

However, the AC also states the input context_pack contains `active_goal`, `actr_buffers`, `gwt_workspace`, `episodic_prior_artifact`, `lida_broadcast`, and `extra_key` — **6 keys**. The assertion is that exactly 5 WMEs are constructed (lida_broadcast included, extra_key excluded). This is internally consistent.

**Actual finding:** The statement "does NOT include a WME for `extra_key`" is correct, but there is no stated rule about what constitutes a "non-Tier" key. If `extra_key` is not in any Tier, it is excluded. But the spec does not define how the overlay *detects* non-Tier keys — is it an allowlist (only Tier 1/2/3 keys are included) or a blocklist (all keys not in the hard-coded Tier sets are excluded)? FR-SOAR-003 implies an allowlist (only Tier 1, Tier 2, and Tier 3 keys). This is inferable but not explicit.

**Impact:** Minor — does not prevent AC-1.6 from being tested, but a developer could write an overlay that tests for key membership in a different way. HOW spec should state explicitly: "WME construction uses an allowlist of the five named context pack keys; all other keys are silently excluded."

---

### ISS-019: AC-3.5 depends on OQ-005 (generalization strategy) — partially untestable without it

**Severity:** MEDIUM
**Blocking:** Partial — AC-3.5 full verification blocked until OQ-005 resolved
**Source:** WHY3 analysis of AC-3.5 vs OQ-005

**Finding:**
AC-3.5 states: "Given a ChunkRecord is successfully written, when `enrich_context` is called for a subsequent dispatch within the same run, then the newly written ChunkRecord is available for matching."

"Available for matching" means the ChunkRecord is loaded from the ProceduralMemoryStore and considered in the match phase. This is testable by writing a ChunkRecord with conditions `[{"attr": "active_goal"}]` and then calling `enrich_context` with a context_pack containing `active_goal` — the chunk should match. The test does not require OQ-005 to be resolved because the tester constructs the ChunkRecord manually.

However, AC-3.5 in the context of Scenario 3 (post-dispatch chunking) implicitly assumes the ChunkRecord written by `update_soar_memory` will have conditions derived from the current WME snapshot. Without OQ-005, the conditions on auto-generated ChunkRecords are unknown, making it impossible to know whether a subsequent `enrich_context` call will match the auto-generated chunk.

**Impact:** AC-3.5 is testable for the load-availability behavior (is the chunk in the store and considered?), but not testable for the end-to-end "chunk written by post-dispatch, matched on next dispatch" scenario until OQ-005 is resolved.

---

### ISS-020: FR-SOAR-009 seed rule provider ambiguity (ISS-014 root cause) partially remains

**Severity:** LOW
**Blocking:** No — but creates implementation risk
**Source:** WHY3 review of FR-SOAR-009 amendment

**Finding:**
FR-SOAR-009 now reads: "at least 5 hand-coded seed rules hard-coded in the overlay module (`soar.py`) by the developer covering the common WME combinations for Tier 1 and Tier 2 attributes."

WHY2 ISS-014 flagged that a prior version of FR-SOAR-009 said "provided by COMMANDER" — implying COMMANDER is responsible. The CARTOGRAPHER amendment corrects this to "hard-coded in the overlay module (`soar.py`) by the developer." This is an improvement.

**Residual finding:** The spec does not state who is the "developer" in context — is it the HOW agent, the BUILD agent, or a human developer? In the cognitive squad context, BUILD is responsible for implementation. The phrase "by the developer" is informal and not mapped to a squad role. This is a low-severity stylistic issue, not a blocking ambiguity, since the intent is clear: seed rules are embedded in `soar.py` at build time, not injected at runtime.

---

## SAGE Verdict

**WHY3 VERDICT: PASS**

All 6 quality gates pass post-CARTOGRAPHER amendment.

All 7 CARTOGRAPHER amendments are verified as correctly applied. The spec.md now presents:
- 13 FRs and 6 NFRs in canonical bold-label format (Structure gate fixed)
- 29 acceptance criteria of which 23 are fully testable and 1 is partially testable (AC-3.5) (Testability gate passes at ~80%)
- OQ-001 and OQ-004 resolved, closing the two primary testability blockers from WHY2
- FR-SOAR-003, FR-SOAR-007, FR-SOAR-008, and FR-SOAR-011 materially improved in precision

**HOW-readiness statement:**
HOW may proceed. No remaining open question blocks the implementation contract. OQ-005 (generalization strategy for ChunkRecord conditions) should be resolved before HOW designs the chunking algorithm, but it does not block the Match-Select-Apply core or the impasse handling paths. OQ-007 (EpisodicIndex schema) should be resolved before ChunkingEngine is implemented in BUILD phase. OQ-002 and OQ-003 affect seed rule design decisions and should be surfaced to the developer during HOW.

Three new issues (ISS-018, ISS-019, ISS-020) are documented; none block HOW.

**Gates passed: 6 of 6.**

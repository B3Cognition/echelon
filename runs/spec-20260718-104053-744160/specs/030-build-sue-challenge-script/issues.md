# Issues — WHY2

## Summary
- **CRITICAL:** 0
- **HIGH:** 0
- **MEDIUM:** 4
- **LOW:** 7
- **Verdict:** PASS

All 8 Understanding quality gates pass (see quality-gates.md). No CRITICAL or HIGH issues found. All 11 issues below are advisory — none is a required amendment blocking the transition to ASSESS; MEDIUMs should be addressed when spec.md or the base artifacts are next touched, and unaddressed MEDIUMs escalate to HIGH at WHY3 per the iteration-awareness rule.

WHY1 follow-up: all 3 WHY1 HIGH issues were substantively addressed in the spec (ISS-001 → FR-010 + Limitations + OQ-002; ISS-002 → FR-026/FR-027 extraction contract + OQ-001; ISS-003 → AC-023/SC-001 explicit tolerance). WHY1 MEDIUMs ISS-004..ISS-007 are encoded as FR-007, FR-006/FR-019/FR-020/FR-041, FR-038/AC-008, FR-018 respectively. Residuals from WHY1 ISS-006/ISS-008/ISS-010 (base-artifact patches, spike scoping) are carried below as ISS-204, ISS-205, ISS-209.

## Issues

### ISS-201: Element-counting semantics differ between the round-1 and round-2 prompt requirements
- **Severity:** MEDIUM
- **Type:** inconsistency
- **Description:** FR-014 counts the round-1 instruction as one of its "exactly 2 elements" (spec text + generation instruction). FR-021 says the round-2 prompt holds "exactly 2 content blocks" (spec text + question ids/texts) — yet FR-023 mandates a round-2 answering instruction that must also be in that prompt. Under FR-014's counting convention the round-2 prompt contains 3 elements; under a literal reading of FR-021/AC-011, a prompt containing the FR-023 instruction fails the "exactly 2" check.
- **Affected artifact:** spec.md
- **Affected section:** FR-014, FR-021, FR-023, AC-011
- **Evidence:** FR-014: "exactly 2 elements: the full line-numbered specification text (FR-018) plus the question-generation instruction of FR-015". FR-021: "exactly 2 content blocks: the line-numbered specification text (FR-018) plus the round-1 question identifiers with their question texts". FR-023: "The round-2 instruction MUST direct the model…" — an element FR-021 does not count.
- **Recommendation:** Reword FR-021 to "exactly 3 elements: the line-numbered specification text, the round-1 question identifiers with their question texts, plus the answering instruction of FR-023", or add a glossary definition making "content block" exclude instructions — and align AC-011's stub assertion with whichever convention is chosen. Intent is recoverable from context (FR-022 + FR-023 make it obvious the instruction is present), so this is advisory, but a literal AC-011 test would currently be written against the wrong count.
- **Responsible agent:** WHAT

### ISS-202: No assigned behavior for out-of-range or non-positive line references at render time
- **Severity:** MEDIUM
- **Type:** incompleteness
- **Description:** FR-016 and FR-024 validate line references only as "a list of integer line references". A reference of 0, a negative number, or a number beyond the specification's last line passes validation, but FR-039 then requires the report to "quote exactly 1 line of text from the specification file" for it — a line that does not exist. No requirement assigns behavior to this path (skip with a note, clamp, render as unverifiable, or classify as parse failure).
- **Affected artifact:** spec.md
- **Affected section:** FR-016, FR-024, FR-039, AC-009
- **Evidence:** FR-024: "…plus a list of integer evidence line references"; FR-039: "For each cited evidence line number, the report MUST quote exactly 1 line of text from the specification file". Nothing constrains the integers to [1, line_count].
- **Recommendation:** Assign one deterministic behavior. Recommended: render out-of-range citations as an explicit "line N not present in specification" marker rather than failing the run (a validation-failure classification would burn the single retry on a cosmetic model slip). SENTINEL needs this decision to enumerate the rendering unit tests.
- **Responsible agent:** WHAT

### ISS-203: AC-002 "exactly 4 facts" conflicts with the truncation-note header on truncated runs
- **Severity:** MEDIUM
- **Type:** inconsistency
- **Description:** AC-002's Given clause covers any "completed challenge run" and asserts the header "states exactly 4 facts". FR-036 and AC-020 require a 5th header element — the truncation note — whenever round 1 over-produced. For a completed run with truncation, AC-002 and AC-020 assert conflicting header contents (acceptance_criteria_conflict).
- **Affected artifact:** spec.md
- **Affected section:** AC-002, AC-020, FR-036
- **Evidence:** AC-002: "the report header states exactly 4 facts…"; FR-036: "exactly 4 base facts — … — plus the FR-019 truncation note when truncation occurred".
- **Recommendation:** Scope AC-002's Given clause to runs without truncation, or reword its Then clause to "states exactly 4 base facts" mirroring FR-036's wording.
- **Responsible agent:** WHAT

### ISS-204: mental-model.md still asserts atomic report writes that spec U-010 explicitly declined
- **Severity:** MEDIUM
- **Type:** inconsistency
- **Description:** The spec's Resolved-During-WHAT table (U-010) decides "plain overwrite of the report file; no atomicity or concurrency guarantee claimed in v1" (FR-034). mental-model.md's Challenge Report lifecycle still reads "written atomically at the end of a successful run" — the exact embellishment WHY1 ISS-008 flagged. The spec side was fixed (option 1 of the WHY1 recommendation); the model was not patched, and the two artifacts now directly contradict each other. Risk: SENTINEL derives an atomicity test from the mental model for behavior the spec deliberately does not guarantee.
- **Affected artifact:** mental-model.md
- **Affected section:** Challenge Report — Lifecycle (line 39)
- **Evidence:** mental-model.md: "written atomically at the end of a successful run"; spec.md U-010: "Plain overwrite of the report file; no atomicity or concurrency guarantee claimed in v1".
- **Recommendation:** Delete the word "atomically" from mental-model.md's Challenge Report lifecycle (one-line patch). Previously raised in WHY1 as ISS-008 (LOW); escalated one step because the artifacts now actively contradict rather than merely embellish.
- **Responsible agent:** DISCOVER

### ISS-205: Base-artifact report definitions still omit the collapsed audit rendering
- **Severity:** LOW
- **Type:** inconsistency
- **Description:** FR-038/AC-008 correctly restore the collapsed audit-appendix rendering in the spec (the WHY1 ISS-006 substance is resolved and spec.md is authoritative). The glossary.md "Challenge report" and mental-model.md "Challenge Report" definitions still describe the audit appendix without the collapsed property.
- **Affected artifact:** glossary.md, mental-model.md
- **Affected section:** Challenge report definitions
- **Evidence:** glossary.md: "(3) audit appendix — answered-and-discarded questions with their answering lines" — no collapsed rendering; same in mental-model.md.
- **Recommendation:** Patch both definitions when next touched. Residual of WHY1 ISS-006; not escalated because the authoritative artifact (spec.md) now carries the requirement.
- **Responsible agent:** DISCOVER

### ISS-206: Weakness-category enum tokens are unpinned across artifacts
- **Severity:** LOW
- **Type:** ambiguity
- **Description:** FR-015 names the 5 categories in human-readable form ("hidden assumption", "undefined term", "missing boundary"); mental-model.md's Socratic Question schema uses tokens (`assumption`, `undefined-term`, `boundary`). FR-016 validates "exactly 1 category from FR-015" — if the round-1 prompt taxonomy and the validator enum drift apart (one using names, the other tokens), every run burns its retry on a category mismatch.
- **Affected artifact:** spec.md, mental-model.md
- **Affected section:** FR-015, FR-016; mental-model.md Socratic Question
- **Evidence:** FR-015: "ambiguity, hidden assumption, contradiction, undefined term, missing boundary" vs mental-model.md: "`ambiguity` | `assumption` | `contradiction` | `undefined-term` | `boundary`".
- **Recommendation:** Pin the exact JSON enum tokens at HOW (single shared constant per MODELER's contract map) and instruct the prompt with the same tokens; a one-line spec clarification that FR-015's names are display names for those tokens would close it fully.
- **Responsible agent:** WHAT (clarification) / HOW (constant)

### ISS-207: Debug-dump content unspecified when the failing call is a timeout
- **Severity:** LOW
- **Type:** incompleteness
- **Description:** FR-030/ERR-004 require "saving the raw output of the failing calls" to `.sue-debug`. A timed-out call (FR-011) may have produced no output at all; what gets dumped for that call (empty file, partial output, a timeout marker) is unassigned.
- **Affected artifact:** spec.md
- **Affected section:** FR-030, ERR-004, AC-017
- **Evidence:** FR-011 routes timeouts to the parse-failure path; FR-030 assumes raw output exists for every failing call.
- **Recommendation:** One sentence at WHAT or a HOW decision: dump whatever partial output was captured plus a one-line timeout marker so the dump is never silently empty.
- **Responsible agent:** WHAT

### ISS-208: No bounds on the question-count and timeout option values
- **Severity:** LOW
- **Type:** incompleteness
- **Description:** FR-002 and FR-004 assign defaults (15, 300) but no validity range. `--questions 0` arguably collapses to the FR-020 zero-question path via the prompt instruction, but negative N and timeout ≤ 0 have no assigned behavior.
- **Affected artifact:** spec.md
- **Affected section:** FR-002, FR-004
- **Evidence:** Neither requirement constrains the accepted value range.
- **Recommendation:** Treat non-positive values as invalid invocation input (argparse-level rejection) — a HOW-level decision; note it in the spec only if CARTOGRAPHER touches these FRs anyway.
- **Responsible agent:** HOW

### ISS-209: OQ-001 spike scope omits the A-005 size measurement WHY1 recommended
- **Severity:** LOW
- **Type:** incompleteness
- **Description:** WHY1 ISS-010 recommended folding a size measurement (chars/tokens of spec 029 plus both prompt templates) into the U-001/OQ-001 spike. The spec's OQ-001 row covers prompt delivery and output flags only; A-005 remains "unvalidated; observed at acceptance".
- **Affected artifact:** spec.md
- **Affected section:** Open Questions (OQ-001), Assumptions in Effect (A-005)
- **Evidence:** OQ-001 impact column: "FR-026, FR-028 implementation freeze; stub fixture design" — no size measurement.
- **Recommendation:** Add the size measurement to the OQ-001 spike instructions when INVESTIGATOR is dispatched (near-zero cost); no spec text change strictly required. Previously raised in WHY1 as ISS-010, partially addressed (A-005 is now an explicit limitation).
- **Responsible agent:** INVESTIGATOR (spike scoping)

### ISS-210: "Unreadable" specification path does not explicitly cover decode failures
- **Severity:** LOW
- **Type:** ambiguity
- **Description:** FR-005 exits 1 when the path is "missing or unreadable". A file that exists and is permission-readable but fails text decoding (non-UTF-8 bytes) is not clearly either. Line-numbered embedding (FR-018) and line quoting (FR-039) require successful decoding, so this input must land somewhere deterministic.
- **Affected artifact:** spec.md
- **Affected section:** FR-005, ERR-001
- **Evidence:** "missing or unreadable" — readability is not defined to include decodability.
- **Recommendation:** Define "unreadable" to include decode failure (exit 1, pre-flight) — one glossary-addition line.
- **Responsible agent:** WHAT

### ISS-211: AC-012 asserts a temp-directory location constraint absent from FR-010
- **Severity:** LOW
- **Type:** inconsistency
- **Description:** AC-012 requires the recorded working directory to be "outside the repository"; FR-010 requires only "1 newly created neutral temporary directory". If the operator's temp root lives inside the repository tree (e.g. TMPDIR override), FR-010 is satisfiable while AC-012 fails.
- **Affected artifact:** spec.md
- **Affected section:** FR-010, AC-012
- **Evidence:** AC-012: "exactly 1 newly created temporary directory outside the repository"; FR-010 carries no location constraint.
- **Recommendation:** Add "outside the challenged specification's repository tree" (or "outside any git working tree") to FR-010 so the FR carries the constraint its AC tests.
- **Responsible agent:** WHAT

## Per-Requirement Failures

Document-level gates all pass; rows below are per-requirement dips below the resolved gates, for speckit-echelon-cartographer (CARTOGRAPHER) consumption. Constraint diagnostics for all testability-0.0 rows: `hard_constraints: null`, `soft_words: []`, diagnosis "no numeric thresholds" — a parser artifact for these rows (each does contain numeric constraints, e.g. "exit code 3", "first N"); treat as re-phrasing hints, not defects.

| Requirement | Category | Score | Gate | Verdict |
|------------|----------|-------|------|---------|
| AC-015 | testability | 0.00 | 0.75 | FAIL |
| AC-020 | testability | 0.00 | 0.75 | FAIL |
| FR-017 | testability | 0.00 | 0.75 | FAIL |
| FR-019 | testability | 0.00 | 0.75 | FAIL |
| FR-025 | testability | 0.00 | 0.75 | FAIL |
| FR-033 | testability | 0.00 | 0.75 | FAIL |
| FR-040 | testability | 0.00 | 0.75 | FAIL |
| NFR-004 | testability | 0.00 | 0.75 | FAIL |
| FR-015 | behavioral | 0.00 | 0.55 | FAIL |
| FR-022 | behavioral | 0.00 | 0.55 | FAIL |
| FR-035 | behavioral | 0.00 | 0.55 | FAIL |
| FR-039 | behavioral | 0.00 | 0.55 | FAIL |
| NFR-003 | behavioral | 0.00 | 0.55 | FAIL |
| FR-044 | readability | 0.31 | 0.55 | FAIL |
| FR-016 | readability | 0.44 | 0.55 | FAIL |
| FR-015 | readability | 0.49 | 0.55 | FAIL |
| FR-010 | readability | 0.51 | 0.55 | FAIL |
| AC-011 | readability | 0.53 | 0.55 | FAIL |
| AC-012 | readability | 0.54 | 0.55 | FAIL |
| AC-023 | cognitive | 0.63 | 0.65 | FAIL |
| AC-017 | cognitive | 0.63 | 0.65 | FAIL |
| SC-001 | cognitive | 0.64 | 0.65 | FAIL |
| FR-010 | cognitive | 0.64 | 0.65 | FAIL |
| FR-016 | structure | 0.15 | 0.75 | FAIL |
| AC-018 | structure | 0.18 | 0.75 | FAIL |
| AC-011 | structure | 0.23 | 0.75 | FAIL |
| SC-003 | structure | 0.23 | 0.75 | FAIL |
| FR-022 | structure | 0.25 | 0.75 | FAIL |
| ERR-001 | structure | 0.33 | 0.75 | FAIL |

Granularity note (do not iterate on these): per-requirement depth is below 0.4 for 83/83 requirements and per-requirement structure below 0.75 for 73/83 — depth and structure are document-level metrics that single bullets cannot individually satisfy; the document-level scores (0.872, 0.8342) both PASS. Only the structure rows ≤ 0.35 above are worth touching. Semantic: 0/83 failures.

## Contradiction Detection (Step 8 — systematic sweep)

Artifacts scanned: 6 (spec.md, glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md) plus reasoning-journal.jsonl. Contradiction types checked: requirement_conflict, assumption_requirement_misalignment, boundary_violation, priority_inversion, acceptance_criteria_conflict. **Contradictions found: 2 (both WARNING, neither BLOCKING).**

| Field | Contradiction 1 | Contradiction 2 |
|-------|-----------------|-----------------|
| contradiction_type | acceptance_criteria_conflict | acceptance_criteria_conflict |
| artifact_a | spec.md AC-002 | spec.md AC-011 / FR-021 |
| artifact_b | spec.md AC-020 / FR-036 | spec.md FR-023 / FR-014 |
| description | For a completed run with round-1 truncation, AC-002 asserts a 4-fact header while AC-020/FR-036 require a 5th element (truncation note) | AC-011/FR-021 count "exactly 2 content blocks" in the round-2 prompt while FR-023 mandates an answering instruction that FR-014's convention would count as a third element |
| severity | WARNING | WARNING |
| suggested_resolution | Scope AC-002 to non-truncated runs or reword to "4 base facts" (ISS-203) | Reword FR-021 to count 3 elements or define "content block" to exclude instructions; align AC-011 (ISS-201) |

Checks that found nothing: requirement_conflict — none (the FR-008/FR-028 call-count arithmetic is consistent: 2 logical calls, ≤ 4 subprocess invocations, matching NFR-001's 4-timeout bound); assumption_requirement_misalignment — none (A-001/A-002 unvalidated statuses are honestly mirrored by OQ-001/OQ-002 and the Limitations section; FR-010 claims only what temp-cwd guarantees); boundary_violation — none (Out of Scope mirrors boundaries.md's explicit harness NON-boundary; concurrency non-goal now stated); priority_inversion — none (all FRs are MVP; no cross-priority dependencies exist).

## Pre-Mortem Findings

| Risk | Likelihood | Impact | Affected Requirements |
|------|-----------|--------|----------------------|
| Prompt builder or AC-011 stub test written against the literal "2 content blocks" count, omitting or miscounting the round-2 answering instruction | MEDIUM | Round-2 output unusable on every run (exit-3 loop) or a false-passing isolation test | FR-021, FR-022, FR-023, AC-011 (ISS-201) |
| Model cites an out-of-range evidence line; renderer crashes or quotes the wrong line with no assigned behavior to test against | MEDIUM | Rework at build; report evidence silently wrong — the grounding rule's weakest joint | FR-024, FR-039, AC-009 (ISS-202) |
| OQ-001 (prompt delivery / output flags) left unresolved when HOW freezes the extraction design | MEDIUM | Extraction contract designed blind; systematic noise → exit-3 loop; acceptance fails | FR-026–FR-030, A-001 |
| Category enum drift between round-1 prompt taxonomy and validator | LOW-MEDIUM | Every run burns its single retry on a cosmetic mismatch | FR-015, FR-016 (ISS-206) |
| Under deadline pressure, `claude -p` invocation borrows the harness stream-json backend "because it already works" | LOW | Standalone contract broken (FR-045, A-003); test seam stops working | FR-043, FR-045 |

Most likely misimplemented requirement: FR-021 (counting ambiguity). Loosest acceptance criterion: AC-009 (passes even when a cited line number is out of range, because it only checks lines that were cited and resolvable). Missing requirement causing most rework: the ISS-202 render-time range behavior. First scope boundary violated under pressure: harness reuse (FR-045).

## Cross-Artifact Consistency

| Check | Status | Notes |
|-------|--------|-------|
| Entities in spec match mental-model | PASS | All 8 Key Entities present and aligned in mental-model.md; one attribute-level divergence (atomic write, ISS-204) flagged |
| Dependencies in spec match boundaries | PASS | claude CLI, spec read side, spec-dir write side, neutral temp dir, pytest stub, and the harness NON-boundary all consistent; no cycles |
| Terms match glossary | PASS | Spec's Glossary Additions extend without conflict; two naming residuals flagged (ISS-205 collapsed rendering, ISS-206 category tokens) |
| Scope aligns with boundaries | PASS | Out of Scope items map 1:1 to boundaries.md non-goals; concurrency and context-window limits now explicit |
| Assumptions match assumptions.md | PASS | A-001..A-012 statuses in the spec table match assumptions.md exactly (A-004 validated at ef2643c9, A-008 validated, rest unvalidated/adopted) |
| Open questions reference unknowns.md | PASS | OQ-001→U-001, OQ-002→U-002; Resolved-During-WHAT table accounts for U-003..U-010 individually |

## Checks Performed With No Findings (Rule 4 — no rubber-stamping)

- **LOC verification check:** no LOC claims citing single files or lacking a cloc command exist in spec.md or the WHAT-phase artifacts (the only size statement, A-005's "a few hundred lines", was already flagged in WHY1 and is tracked via ISS-209). Confidence: high.
- **Resolution evidence check:** the Resolved-During-WHAT table's 8 resolutions each point to concrete encoded FR text (verifiable in place), not technology names; WHY1 ISS-001/ISS-002 are correctly NOT claimed resolved — they remain open as OQ-001/OQ-002 with unvalidated assumption statuses. Confidence: high.
- **Flakiness management validation:** N/A at WHY2 by design — test-strategy.md/coverage-map.md are SENTINEL outputs that correctly do not exist yet.
- **Untestable requirements:** none found; every FR has a When/If trigger and a countable constraint, and the 8 per-requirement testability-0.0 rows are parser artifacts (each contains numeric constraints), not genuinely untestable requirements. Confidence: medium-high — the parser artifact judgment is mine, not Understanding's.
- **Missing actors:** none — single operator plus the model command subprocess; no schedulers, webhooks, or background jobs are implied anywhere in the design.
- **Confidence statement:** overall confidence 0.85 that no CRITICAL/HIGH issue was missed. The residual risk sits in OQ-001/OQ-002 — external-CLI behavior that no amount of spec reading can validate; those are correctly parked as pre-HOW spikes rather than spec defects.

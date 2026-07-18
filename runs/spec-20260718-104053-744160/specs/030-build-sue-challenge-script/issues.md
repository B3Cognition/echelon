# Issues — WHY3

## Summary
- **CRITICAL:** 1
- **HIGH:** 3
- **MEDIUM:** 1
- **LOW:** 5
- **Verdict:** FAIL

All 8 Understanding document-level quality gates pass (see quality-gates.md); the FAIL is issue-driven. The CRITICAL is a WHY3 automation-coverage protocol violation (missing acceptance record in state.json — a cheap, deterministic fix owned by COMMANDER). The 3 HIGHs are the WHY2 MEDIUMs that WHY2 explicitly warned would escalate if unaddressed — spec.md and mental-model.md received zero amendments between WHY2 and WHY3, so the escalation rule fires. Every required fix is small (two one-line spec rewordings, one one-word mental-model deletion, one dataclass type change, one state record); a re-validation after they land should PASS cleanly.

**WHY2 follow-up disposition (11 issues):** 6 substantively addressed at HOW — ISS-202 (out-of-range citations → ADR-007 `(not present in the specification)` render marker, contract-pinned and test-enumerated), ISS-206 (category enum tokens pinned as ADR-002 shared constants; FR-015 names declared display names), ISS-207 (timeout dump content assigned: partial output + `TIMEOUT after <T>s` line), ISS-208 (bounds assigned in data-model: `> 0` constraints — small test-enumeration residual carried as ISS-308), ISS-209 (A-005 size measurement encoded as T-S01 step 3), ISS-210 (decode disposition assigned: UTF-8 `errors="replace"`, run proceeds). 3 NOT addressed → escalated (ISS-302, ISS-303, ISS-304 below). 2 LOWs not addressed → carried at LOW (ISS-309, ISS-310).

## Issues

### ISS-301: Escalated coverage rows SC-001/AC-023 have no user-acceptance record in state.json
- **Severity:** CRITICAL
- **Type:** incompleteness
- **Description:** coverage-map.md classifies SC-001 and AC-023 (the manual live acceptance run) as coverage_type `escalate`. The WHY3 automation coverage check requires every escalated requirement to terminate in an explicit `deferred_risky_accepted` entry in state.json; state.json contains no such key (verified directly). SENTINEL's rationale — "user decision is recorded in the approved spec" — is an agent inferring acceptance, which is precisely what the recorded-acceptance rule exists to prevent. Requirement SC-001/AC-023 was escalated but no user acceptance is recorded in state.json.
- **Affected artifact:** coverage-map.md, state.json
- **Affected section:** coverage-map.md Escalations table; state.json (missing `deferred_risky_accepted`)
- **Evidence:** `state.json` top-level keys enumerated 2026-07-18: `deferred_risky_accepted` absent. coverage-map.md Escalations: "resolved — user decision is recorded in the approved spec (SC-001, AC-023) … no new approval required".
- **Recommendation:** COMMANDER records a `deferred_risky_accepted` entry for SC-001/AC-023 in state.json, citing the approved spec text (SC-001, AC-023, plan.md Final Phase) as the acceptance evidence — or surfaces the one-line confirmation to the user if autonomy mode requires it. This is a state-recording formality, not a re-decision: the substantive choice (single manual live gate with encoded tolerance) is genuinely spec-mandated. WHY3 cannot PASS until the record exists.
- **Responsible agent:** HOW (COMMANDER — deterministic state write)

### ISS-302: FR-021/AC-011 "exactly 2 content blocks" still contradicts FR-023's mandated instruction — spec unamended since WHY2
- **Severity:** HIGH — Previously raised in WHY2 as ISS-201 (MEDIUM), not addressed
- **Type:** inconsistency
- **Description:** FR-014 counts the round-1 instruction as one of its "exactly 2 elements"; FR-021/AC-011 count "exactly 2 content blocks" in the round-2 prompt while FR-023 mandates an answering instruction that FR-014's convention would count as a third element. WHY2 flagged this with the explicit warning that a literal AC-011 test would assert the wrong count. Since WHY2: the spec was NOT reworded; instead the counting convention ("a content block is a data payload; instructions are not content blocks") was pinned normatively in contracts/model-command-contract.md, and SENTINEL's tests adopt it. That mitigation is real — but plan.md (Risks row 3), test-strategy.md (Known Test-Enumeration Hazard), and coverage-map.md (Gap Analysis row 1) ALL still route the one-line rewording to CARTOGRAPHER, and plan.md's own precondition ("before phase3-sentinel") has already been missed. The authoritative artifact now contradicts the frozen build contract, and SPEC GUARD verifies code against spec.md, not contracts.
- **Affected artifact:** spec.md
- **Affected section:** FR-021 (line 163), AC-011 (line 45), FR-023, FR-014
- **Evidence:** spec.md line 163 verbatim on 2026-07-18: "exactly 2 content blocks: the line-numbered specification text (FR-018) plus the round-1 question identifiers with their question texts" — unchanged since WHY2. contracts/model-command-contract.md: "a **content block** is a data payload … Flagged for CARTOGRAPHER's FR-021/AC-011 wording alignment."
- **Recommendation:** CARTOGRAPHER applies the one-line rewording before build: either reword FR-021/AC-011 to count 3 elements including the FR-023 instruction, or add the contract's content-block definition to spec.md's Glossary Additions so the spec itself carries the convention its ACs are tested under.
- **Responsible agent:** WHAT (CARTOGRAPHER)

### ISS-303: AC-002 "exactly 4 facts" still conflicts with the truncation-note header — spec unamended since WHY2
- **Severity:** HIGH — Previously raised in WHY2 as ISS-203 (MEDIUM), not addressed
- **Type:** inconsistency
- **Description:** AC-002's Given clause covers any completed challenge run and asserts a header of "exactly 4 facts"; FR-036/AC-020 require a 5th header element (the truncation note) on truncated runs — an acceptance_criteria_conflict. Since WHY2 the spec was not touched; contracts/report-format.md pins "4 base facts; the truncation note is the only conditional addition", which resolves it for the renderer and tests, but the two ACs still assert conflicting header contents in the authoritative artifact.
- **Affected artifact:** spec.md
- **Affected section:** AC-002 (line 23), AC-020, FR-036
- **Evidence:** spec.md line 23 verbatim on 2026-07-18: "the report header states exactly 4 facts" — unchanged since WHY2, versus FR-036 "exactly 4 base facts — … — plus the FR-019 truncation note when truncation occurred".
- **Recommendation:** CARTOGRAPHER rewords AC-002's Then clause to "exactly 4 base facts" (mirroring FR-036) or scopes its Given clause to non-truncated runs. One line.
- **Responsible agent:** WHAT (CARTOGRAPHER)

### ISS-304: mental-model.md still asserts atomic report writes that spec U-010 explicitly declined
- **Severity:** HIGH — Previously raised in WHY2 as ISS-204 (MEDIUM) and in WHY1 as ISS-008 (LOW); not addressed across two passes
- **Type:** inconsistency
- **Description:** Spec decision U-010 (encoded in FR-034) is "plain overwrite … no atomicity or concurrency guarantee claimed in v1". mental-model.md's Challenge Report lifecycle still reads "written atomically at the end of a successful run". data-model.md explicitly declares the mental-model claim "superseded" — proof the squad knows the two artifacts contradict — yet the one-word source patch was never applied. This has now survived two escalation warnings; the persistence itself is the finding: base-artifact drift is being tolerated rather than repaired, and any future consumer reading mental-model.md without data-model.md's caveat inherits a false guarantee (e.g. deriving an atomic-rename test ADR-007 explicitly rejected).
- **Affected artifact:** mental-model.md
- **Affected section:** Challenge Report — Lifecycle (line 39)
- **Evidence:** mental-model.md line 39 verbatim on 2026-07-18: "written atomically at the end of a successful run; regenerable at will." spec.md U-010: "Plain overwrite of the report file; no atomicity or concurrency guarantee claimed in v1."
- **Recommendation:** Delete the word "atomically" (replace with "written by plain overwrite"). One word. Batch the ISS-309 collapsed-rendering patch into the same touch.
- **Responsible agent:** DISCOVER

### ISS-305: RunConfig types timeout_seconds as int while the test strategy depends on sub-second timeout values
- **Severity:** MEDIUM
- **Type:** inconsistency
- **Description:** data-model.md declares `timeout_seconds | int | default 300; > 0`. test-strategy.md's timeout-boundary row specifies "`--timeout` ≈ 0.2–0.5 s to keep suite fast", and tasks.md T-005/T-009/T-014 all rely on "sub-second `--timeout`" stubs (the < 30 s pre-commit target, SNT-008, depends on this). An integer-typed option cannot express 0.2–0.5: as written, either argparse rejects the test values or truncates them to 0 — which the `> 0` constraint then rejects. The two HOW artifacts are mutually unsatisfiable; this surfaces as immediate rework at T-005 (the highest-risk task in risk-matrix.md).
- **Affected artifact:** data-model.md, contracts/cli-contract.md
- **Affected section:** data-model.md Entity: RunConfig (`timeout_seconds` row); cli-contract.md `--timeout SECONDS` row; tasks.md T-005/T-009/T-014; test-strategy.md Boundary And Data Strategy (Timeout budget row)
- **Evidence:** data-model.md: "`timeout_seconds` | int | yes | default 300; > 0"; test-strategy.md: "sleep-mode stub; `--timeout` ≈ 0.2–0.5 s to keep suite fast".
- **Recommendation:** ARCHITECT changes the type to float (`argparse type=float`, constraint > 0, default 300.0) in data-model.md and cli-contract.md — one row each. Spec FR-004 ("defaulting to exactly 300 seconds") is unaffected. The alternative (integer seconds with ≥ 1 s test budgets) would violate the SNT-008 30-second suite target across the multi-case timeout matrix.
- **Responsible agent:** HOW (ARCHITECT)

### ISS-306: ADR-006 residual write-failure path exits 1, contradicting the cli-contract exit-1 guarantee
- **Severity:** LOW
- **Type:** inconsistency
- **Description:** contracts/cli-contract.md's exit table guarantees for code 1: "exactly 0 model calls launched". ADR-006's consequences note that a report-write failure occurring after the model calls (exotic ACL race bypassing the FR-006 pre-flight) "reports exit 1 with the diagnostic line" — an exit-1 outcome after 2 model calls, breaking the stated guarantee. coverage-map.md already documents the path as accepted and practically unreachable; the residual is the guarantee wording, not the behavior.
- **Affected artifact:** contracts/cli-contract.md, research.md (ADR-006)
- **Affected section:** cli-contract.md Exit codes table (code 1 Guarantees cell); ADR-006 Consequences
- **Evidence:** cli-contract.md code-1 guarantee "exactly 0 model calls launched (ERR-001/ERR-002)" vs ADR-006: "failure after model calls reports exit 1 with the diagnostic line".
- **Recommendation:** Scope the code-1 guarantee to pre-flight failures ("pre-flight failures exit 1 before any model call; the practically-unreachable post-flight write failure also maps to 1") — one cell edit whenever cli-contract.md is next touched. No test change needed.
- **Responsible agent:** HOW (ARCHITECT)

### ISS-307: spec.md assumption/open-question statuses are stale against the executed HOW spikes
- **Severity:** LOW
- **Type:** inconsistency
- **Description:** research.md resolved OQ-001 and OQ-002 with Grade-A direct evidence (claude CLI 2.1.214 spike, 2026-07-18) — genuine resolutions with protocol, observations, and failure modes, not name-only (resolution-evidence check PASS). spec.md still lists both as open ("under investigation") and keeps A-001/A-002 at "unvalidated (… spike before HOW)". The evidence direction supports the spec's design, so nothing is wrong substantively — the statuses are simply stale.
- **Affected artifact:** spec.md
- **Affected section:** Open Questions table (OQ-001, OQ-002); Assumptions in Effect (A-001, A-002); Limitations (Residual context exposure)
- **Evidence:** research.md "OQ-001 / OQ-002 Evidence (spike executed at HOW, 2026-07-18)" vs spec.md OQ table "should-resolve-before-HOW" rows still open.
- **Recommendation:** When CARTOGRAPHER applies ISS-302/ISS-303, refresh the two OQ rows to "resolved at HOW — see research.md" and A-001/A-002 statuses to "validated at HOW (claude CLI 2.1.214)" / "confirmed residual, documented limitation". Batch — do not make this a separate touch.
- **Responsible agent:** WHAT (CARTOGRAPHER, batched)

### ISS-308: No enumerated tests for non-positive --questions/--timeout values despite the data-model bounds
- **Severity:** LOW
- **Type:** incompleteness (residual of WHY2 ISS-208, which is otherwise addressed)
- **Description:** data-model.md assigns `> 0` constraints to `max_questions` and `timeout_seconds`, resolving WHY2 ISS-208's missing bounds. But tasks.md T-002's test list (defaults, overrides, quoting, zero-word value, disclosure count) and coverage-map.md's T-ARG rows enumerate no case for `--questions 0/-1` or `--timeout 0/-1`, so the new constraints have no named verification.
- **Affected artifact:** tasks.md, coverage-map.md
- **Affected section:** T-002 Test Tasks; coverage-map FR-002/FR-004 rows
- **Evidence:** T-002 test enumeration contains no non-positive-value vectors; data-model.md RunConfig constrains both fields `> 0`.
- **Recommendation:** IMPLEMENTER adds two parametrized argv vectors (non-positive N, non-positive timeout → exit-1 argument-error class) inside the existing T-002 argument-handling group; no new task needed.
- **Responsible agent:** HOW (IMPLEMENTER at T-002)

### ISS-309: Base-artifact report definitions still omit the collapsed audit rendering
- **Severity:** LOW — Previously raised in WHY2 as ISS-205, not addressed
- **Type:** inconsistency
- **Description:** glossary.md and mental-model.md "Challenge report" definitions still describe the audit appendix without the collapsed property that FR-038/AC-008 (spec, authoritative) and ADR-007 (`<details>` block) mandate. Not escalated: the authoritative artifacts are correct and test-enumerated (T-RPT-07); this is base-artifact hygiene.
- **Affected artifact:** glossary.md, mental-model.md
- **Affected section:** Challenge report definitions
- **Evidence:** grep for "collapsed" in glossary.md/mental-model.md returns no hits; spec.md FR-038 and report-format.md both mandate it.
- **Recommendation:** Batch into the ISS-304 DISCOVER patch.
- **Responsible agent:** DISCOVER

### ISS-310: FR-010 still lacks the outside-the-repository location constraint that AC-012 tests
- **Severity:** LOW — Previously raised in WHY2 as ISS-211, not addressed
- **Type:** inconsistency
- **Description:** AC-012 requires the recorded cwd to be "outside the repository"; FR-010 carries no location constraint. ADR-004 claims mkdtemp in the system temp location is "outside the repository by construction" — untrue under a TMPDIR override pointing into the repo tree. Mitigation is adequate (T-SEAM-04 controls the test environment and asserts the location), so this stays LOW, but the FR should carry the constraint its AC verifies.
- **Affected artifact:** spec.md, research.md (ADR-004)
- **Affected section:** FR-010, AC-012; ADR-004 Decision
- **Evidence:** FR-010: "exactly 1 newly created neutral temporary directory" — no location clause; AC-012: "outside the repository".
- **Recommendation:** Append "outside the challenged specification's repository tree" to FR-010 when CARTOGRAPHER applies ISS-302/ISS-303 (batch).
- **Responsible agent:** WHAT (CARTOGRAPHER, batched)

## Per-Requirement Failures

Spec.md is unchanged since WHY2; the per-requirement profile is identical (re-verified from `/tmp/u_perreq.json`, 83 requirements). Document-level gates all pass. The actionable subset remains: 8 requirements at per-requirement testability 0.00 (AC-015, AC-020, FR-017, FR-019, FR-025, FR-033, FR-040, NFR-004 — parser artifacts; each contains numeric constraints), 6 readability rows below 0.55 (FR-044 0.31, FR-016 0.44, FR-015 0.49, FR-010 0.51, AC-011 0.53, AC-012 0.54), 4 cognitive rows below 0.65 (AC-017/AC-023 0.63, SC-001 0.64, FR-010 0.64), and the structure rows ≤ 0.35 (FR-016 0.15, AC-018 0.18, AC-011 0.23, SC-003 0.23, FR-022 0.25, ERR-001 0.33). Granularity note stands: per-requirement depth/structure are document-level metrics single bullets cannot satisfy; only the listed rows are worth touching, and all are advisory.

## EARS Pattern Gaps

None — 0 of 83 requirements unclassified (event_driven 71, ubiquitous 8, unwanted 3, optional 1).

## Contradiction Detection (Step 8 — systematic sweep)

Artifacts scanned: 19 (spec.md, glossary.md, mental-model.md, mental-model-code.md, boundaries.md, assumptions.md, unknowns.md, plan.md, research.md, data-model.md, contracts/cli-contract.md, contracts/internal-interfaces.md, contracts/model-command-contract.md, contracts/report-format.md, tasks.md, test-strategy.md, coverage-map.md, critical-path.md, risk-matrix.md) plus reasoning-journal.jsonl and state.json. Contradiction types checked: requirement_conflict, assumption_requirement_misalignment, boundary_violation, priority_inversion, acceptance_criteria_conflict. **Contradictions found: 5 (3 BLOCKING via WHY3 escalation, 2 WARNING).**

| # | contradiction_type | artifact_a | artifact_b | description | severity | suggested_resolution |
|---|--------------------|------------|------------|-------------|----------|----------------------|
| 1 | acceptance_criteria_conflict | spec.md AC-011 / FR-021 | spec.md FR-023 / FR-014; contracts/model-command-contract.md counting convention | "Exactly 2 content blocks" vs the mandated answering instruction; spec contradicts its own convention and the frozen contract | BLOCKING (ISS-302) | One-line FR-021/AC-011 reword or glossary definition of "content block" |
| 2 | acceptance_criteria_conflict | spec.md AC-002 | spec.md AC-020 / FR-036 | 4-fact header vs 5th truncation-note element on truncated runs | BLOCKING (ISS-303) | Reword AC-002 to "4 base facts" or scope to non-truncated runs |
| 3 | requirement_conflict (artifact-level) | mental-model.md Challenge Report lifecycle | spec.md U-010 / FR-034; data-model.md | "Written atomically" vs the recorded plain-overwrite decision | BLOCKING (ISS-304) | Delete "atomically" from mental-model.md |
| 4 | requirement_conflict (artifact-level) | data-model.md RunConfig `timeout_seconds: int` | test-strategy.md / tasks.md sub-second `--timeout` (0.2–0.5 s) | Integer type cannot express the sub-second budgets the timeout tests require | WARNING (ISS-305, MEDIUM) | Type the option float in data-model.md + cli-contract.md |
| 5 | requirement_conflict (artifact-level) | contracts/cli-contract.md exit-1 guarantee "0 model calls" | research.md ADR-006 post-flight write-failure → exit 1 | Practically-unreachable residual path breaks the stated exit-1 invariant | WARNING (ISS-306, LOW) | Scope the guarantee wording to pre-flight failures |

Checks that found nothing: assumption_requirement_misalignment — none blocking (A-001/A-002 statuses are stale rather than misaligned, ISS-307; the evidence direction supports the requirements); boundary_violation — none (plan/contracts honour the harness NON-boundary; FR-045 gate + import-scan test hold the line); priority_inversion — none (all FRs MVP; task chain is linear with in-degree ≤ 1, verified in dependencies.md); requirement_conflict within spec.md proper — none beyond rows 1–2 (call-count arithmetic FR-008/FR-028/NFR-001 consistent: 2 logical calls, ≤ 4 invocations, 4-timeout bound).

## Pre-Mortem Findings

| Risk | Likelihood | Impact | Affected Requirements |
|------|-----------|--------|----------------------|
| SPEC GUARD or a literal-minded test reads AC-011/AC-002 counting words from spec.md instead of the contract convention → false FAIL or wrong assertion at build/verify | MEDIUM | Build-phase churn; erosion of spec authority (agents learn to prefer contracts over spec) | FR-021, AC-011, AC-002 (ISS-302/ISS-303) |
| T-005/T-009 timeout tests written against int-typed `--timeout` → argparse rejects 0.2–0.5 s values; suite either fails or balloons past the 30 s target | MEDIUM | Immediate rework on the plan's highest-risk task | FR-004, FR-011, FR-013 (ISS-305) |
| FINALIZE reached with the SC-001/AC-023 escalation still unrecorded → gate friction or, worse, silent waiver of the only live validation | LOW-MEDIUM | Governance gap on the single live acceptance gate | SC-001, AC-023 (ISS-301) |
| mental-model.md atomicity claim consumed by a future maintainer or SUE tier without data-model.md's supersession note | LOW | Test asserting behavior ADR-007 explicitly rejected | FR-034, U-010 (ISS-304) |
| claude CLI drift from the 2.1.214 spike baseline before the acceptance run | LOW-MEDIUM | Extraction retries burn; `.sue-debug` diagnosis needed | FR-026–FR-030 (accepted, mitigated by ADR-005; version pinned) |

Most likely misimplemented requirement: FR-004's timeout option (type contradiction, ISS-305). Loosest acceptance criterion: AC-002 (asserts a count the truncated-run header violates). Missing record causing most friction: the ISS-301 acceptance entry. First scope boundary violated under pressure: still harness reuse (FR-045) — but the T-013 AST import-scan tripwire is now designed, downgrading this from WHY2's assessment.

## Cross-Artifact Consistency

| Check | Status | Notes |
|-------|--------|-------|
| Entities in spec match mental-model | FAIL | ISS-304: mental-model.md atomic-write lifecycle actively contradicts spec U-010/FR-034 (known since WHY1, still unpatched); ISS-309 collapsed-rendering omission. All 8 Key Entities otherwise map 1:1 into data-model.md, which explicitly follows the spec |
| Dependencies in spec match boundaries | PASS | claude CLI, read/write sides, temp-cwd, pytest stub, harness NON-boundary all consistent across boundaries.md, plan.md, contracts; no cycles (dependencies.md verified) |
| Terms match glossary | PASS | Contract counting convention ("content block") is defined in model-command-contract.md but absent from spec/glossary — tracked as the ISS-302 fix, not a new term conflict |
| Scope aligns with boundaries | PASS | Out of Scope ↔ boundaries.md non-goals 1:1; plan adds no scope (UI-004 no-expansion honoured: ADR-004 explicitly rejected `--safe-mode` for v1) |
| Assumptions match assumptions.md | PASS with note | Statuses internally consistent but stale against research.md's executed spikes (ISS-307): A-001/A-002 remain "unvalidated" after Grade-A validation/confirmation |
| Open questions reference unknowns.md | PASS with note | OQ-001→U-001, OQ-002→U-002 intact; both now resolved in research.md while spec rows stay open (ISS-307, batched refresh) |

## WHY3 Automation Coverage Check (BLOCKING)

coverage-map.md exists and maps all 83 requirement rows. Zero rows carry `manual` or `none` coverage; zero rows carry `deferred-automation`. Two rows (SC-001, AC-023) carry `escalate`; state.json has no `deferred_risky_accepted` entry → **CRITICAL ISS-301 raised; PASS is barred until the record exists.** The escalation's substance is sound (spec-mandated manual gate with encoded tolerance); only the acceptance record is missing.

## Checks Performed With No Findings (Rule 4 — no rubber-stamping)

- **LOC verification check:** no LOC claims citing single files or lacking a cloc command in any scanned artifact; ADR-001's "~700–900 lines" and ADR-005's "~150 lines" are forward estimates, not measured claims. Confidence: high.
- **Resolution evidence check:** research.md's OQ-001/OQ-002 resolutions carry direct observations (pinned CLI version, byte-level output, debug-log contents), invocation protocol, and failure-mode analysis — genuine Grade-A resolutions, not name-only. The 8 Resolved-During-WHAT rows re-verified unchanged. No name-only resolution found. Confidence: high.
- **Flakiness Management validation (WHY3):** test-strategy.md includes integration/e2e-surface tests and its Flakiness Management section covers all 5 mandated concerns with concrete values (detection: 5-run pre-merge loop; quarantine: skip-marker + tracked issue; taxonomy: timing-margin/state-leak with fixes; stability targets: <5% suite, 100% critical journeys; cadence: weekly with COMMANDER escalation). Format is a table rather than 5 subsections — substance complete; no issue raised. Confidence: high.
- **Untestable requirements:** none; coverage-map.md maps every FR/AC/NFR/ERR/SC to enumerated tests or the recorded manual gate; the per-requirement testability-0.0 rows remain parser artifacts. Confidence: medium-high.
- **Missing actors:** none — single operator + model subprocess; no schedulers, webhooks, or background jobs anywhere in spec or plan.
- **Journal audit:** no low-confidence insights driving high-impact decisions (only two sub-0.6 entries, both TRACKER prediction records, a different mechanism).
- **Confidence statement:** overall confidence 0.9 that no additional CRITICAL/HIGH issue was missed. The finding density at WHY3 (1 new MEDIUM, 3 new LOWs across ~19 artifacts) is consistent with a mature artifact set rather than insufficient analysis; the escalations are mechanical applications of the iteration rule to verified-unchanged text.

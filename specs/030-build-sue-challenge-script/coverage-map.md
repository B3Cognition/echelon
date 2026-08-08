# Coverage Map — SUE Challenge Script

- Spec: 030-build-sue-challenge-script
- Sentinel: speckit-echelon-sentinel (SENTINEL)
- Date: 2026-07-18

Test case IDs join to `test-architecture.md` naming conventions. All tests live in `tests/unit/test_sue_challenge.py`, marked `unit`, fully offline (SC-002). `T-META-01` is the CI property that the suite runs green with no network and no `claude` on PATH. Zero rows carry `manual`; the two `escalate` rows are the spec-mandated live acceptance gate whose approval is already recorded in spec.md (SC-001/AC-023) and plan.md (Final Phase).

## Coverage Table

| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |
|----------------|--------------|-----------|-------------------|---------------|----------|--------------|
| FR-001 | T-ARG-01 | unit | automated | automated | parse_args accepts exactly 1 positional; 2 positionals / 0 positionals rejected to exit-1 class | — |
| FR-002 | T-ARG-01 | unit | automated | automated | `--questions` default 15 asserted on parsed RunConfig | — |
| FR-003 | T-ARG-01 | unit | automated | automated | `--claude-cmd` default `"claude"` asserted | — |
| FR-004 | T-ARG-01 | unit | automated | automated | `--timeout` default 300 asserted | — |
| FR-005 | T-EXC-01 | integration | automated | automated | missing + chmod-000 spec → exit 1, stub recording file shows 0 calls | — |
| FR-006 | T-EXC-02 | integration | automated | automated | read-only spec dir → exit 1, 0 recorded calls | — |
| FR-007 | T-ARG-03 | unit | automated | automated | quoted command string shlex-split; word 1 fed to which; zero-word value → exit-1 argument error | — |
| FR-008 | T-SEAM-01 | integration | automated | automated | happy-path stub run records exactly 2 invocations | — |
| FR-009 | T-SEAM-05 | integration | automated | automated | recording file count still 2 after report+summary complete | — |
| FR-010 | T-SEAM-04 | integration | automated | automated | cwd-recording stub: each call's cwd matches `sue-challenge-*` prefix, differs per call, is outside the repo root, and did not pre-exist | — |
| FR-011 | T-EXC-06 | integration | automated | automated | sleeping stub + sub-second timeout → classified parse failure, retry issued | — |
| FR-012 | T-EXC-03 | integration | automated | automated | nonexistent executable → exit 2; stderr contains exactly 1 message with an installation pointer; no report file | — |
| FR-013 | T-EXC-07 | integration | automated | automated | attempt 1 sleeps past budget, attempt 2 replies fast → run succeeds; per-attempt durations from recording timestamps show fresh budget | — |
| FR-014 | T-PRM-02 | unit | automated | automated | round-1 prompt contains numbered spec text + generation instruction, nothing else | — |
| FR-015 | T-PRM-02 | unit | automated | automated | instruction names cap N and all 5 category tokens imported from module constants | — |
| FR-016 | T-VAL-01, T-VAL-02, T-VAL-04, T-VAL-12 | unit | automated | automated | valid object passes; each missing/mistyped field fails; id regex enforced; unknown extra keys ignored | — |
| FR-017 | T-VAL-03 | unit | automated | automated | duplicate round-1 ids → ParseFailure naming the duplicate | — |
| FR-018 | T-PRM-01 | unit | automated | automated | numbered_text yields `1: …` first line; N-th line prefix matches file line N | — |
| FR-019 | T-VAL-06 + T-RPT-02 | unit | automated | automated | N+1 questions → first N kept in order, truncated flag set; note rendered only when flag true | — |
| FR-020 | T-VAL-05 + T-SEAM-06 | unit + integration | automated | automated | empty list validates; end-to-end zero-question run makes 1 call, exits 0, report says 0 questions | — |
| FR-021 | T-PRM-03 + T-PRM-06 | unit + integration | automated | automated | round-2 builder receives only (id, question) pairs; recorded live prompt contains spec text + id/question array | — |
| FR-022 | T-PRM-03 + T-PRM-06 | unit + integration | automated | automated | recorded round-2 prompt contains 0 category tokens, 0 targets, 0 line-reference arrays, 0 round-1 reasoning (counting convention per model-command-contract.md) | — |
| FR-023 | T-PRM-03 | unit | automated | automated | round-2 instruction names spec-text-only rule + the 3 verdict tokens from module constants | — |
| FR-024 | T-VAL-07 | unit | automated | automated | valid answers pass; each per-field violation fails | — |
| FR-025 | T-VAL-08, T-VAL-09, T-VAL-10 | unit | automated | automated | missing / duplicate / unknown id each → ParseFailure whose reason names every offending id | — |
| FR-026 | T-EXT-01..04 | unit | automated | automated | clean, fenced, prose-wrapped, multi-object envelopes each yield exactly 1 object | — |
| FR-027 | T-EXT-05 | unit | automated | automated | zero-object input (prose only; JSON array only) → ParseFailure | — |
| FR-028 | T-PRM-04 + T-EXC-05 | unit + integration | automated | automated | retry prompt = original + corrective naming failure.reason, 0 echoed prior-output lines; invalid-then-valid replay run records exactly 2 invocations for the round and exits 0 | — |
| FR-029 | T-PRM-05 + T-EXC-06 | unit + integration | automated | automated | timeout retry prompt byte-equals the original (0 appended text) | — |
| FR-030 | T-EXC-04 | integration | automated | automated | invalid-invalid replay → exit 3; `.sue-debug/round{R}-attempt{A}-{stdout,stderr}.txt` present for both attempts; no report | — |
| FR-031 | T-EXC-08 | integration | automated | automated | round-2 double failure: recording shows round-1 called exactly once | — |
| FR-032 | T-RNK-01 | unit | automated | automated | mixed verdicts partition into exactly 2 groups with correct membership | — |
| FR-033 | T-RNK-02 | unit | automated | automated | all CONTRADICTED before all UNANSWERABLE; round-1 order stable within class; ranks dense from 1 | — |
| FR-034 | T-SEAM-02 | integration | automated | automated | two consecutive runs → exactly 1 `socratic-challenge.md` in spec dir, content = second run's | — |
| FR-035 | T-RPT-03 | unit | automated | automated | rendered body has header, Findings, Audit appendix in order and nothing else | — |
| FR-036 | T-RPT-01 + T-RPT-02 | unit | automated | automated | header states exactly the 4 base facts; truncation note present only when truncated | — |
| FR-037 | T-RPT-04 | unit | automated | automated | each finding entry carries verdict, question, target, evidence | — |
| FR-038 | T-RPT-07 | unit | automated | automated | exactly 1 `<details>` block; every ANSWERED question inside with quoted answering lines | — |
| FR-039 | T-RPT-05 + T-RPT-06 | unit | automated | automated | each cited number quotes exactly the 1-based file line; UNANSWERABLE entries state the named gap; out-of-range renders `(not present in the specification)` marker | — |
| FR-040 | T-RPT-11 + T-SEAM-01 | unit + integration | automated | automated | summary states per-class counts + top 3 in rank order; printed to stdout after report write; exit 0 | — |
| FR-041 | T-RPT-08 | unit | automated | automated | all-ANSWERED input → findings section states 0 findings; appendix holds all questions | — |
| FR-042 | T-SEAM-03 | integration | automated | automated | sha256 of spec fixture identical before/after runs ending 0, 1, 2, and 3 | — |
| FR-043 | T-SEAM-01 | integration | automated | automated | entire seam suite substitutes the stub via `--claude-cmd`; 0 live calls by construction | — |
| FR-044 | T-META-01 + this map | meta | automated | automated | all 7 behavior groups have enumerated cases (T-ARG/T-PRM/T-EXT/T-VAL/T-RNK/T-RPT/T-EXC); suite runs offline | — |
| FR-045 | T-SEAM-07 | integration | automated | automated | import-scan: all imports stdlib; no project package in `sys.modules` after load; no config/state file reads (strace-free proxy: no such paths opened by pure runs — asserted via absence of orchestration reads in code review gate + import scan) | CODE REVIEWER gate (plan Phase 5) corroborates |
| NFR-001 | T-SEAM-08 | integration | automated | automated | worst-case run (both rounds retry) records exactly 4 invocations; each attempt bounded by injected sub-second timeout; structural bound ≤ 4×timeout + local work | — |
| NFR-002 | T-SEAM-07 + T-META-01 | integration + meta | automated | automated | stdlib-only import assertion; CI runs suite on fresh checkout with no extra installs | — |
| NFR-003 | T-ARG-02 | unit | automated | automated | `--help` text contains exactly 1 egress-disclosure statement | — |
| NFR-004 | T-RPT-10 | unit | automated | automated | double render of identical validated inputs → byte-identical bodies with run-date line excluded | — |
| NFR-005 | T-EXC-09 (via `run_main` helper on every non-zero test) | integration | automated | automated | every exit-1/2/3 test asserts exactly 1 stderr line naming the failure class | — |
| ERR-001 | T-EXC-01 | integration | automated | automated | same evidence as FR-005 | — |
| ERR-002 | T-EXC-02 | integration | automated | automated | same evidence as FR-006 | — |
| ERR-003 | T-EXC-03 | integration | automated | automated | same evidence as FR-012 | — |
| ERR-004 | T-EXC-04 | integration | automated | automated | same evidence as FR-030 | — |
| ERR-005 | T-EXC-06 | integration | automated | automated | timeout → 1 retry → second failure exits 3 | — |
| AC-001 | T-SEAM-01 | integration | automated | automated | exactly 2 recorded calls; report in spec dir; exit 0 | — |
| AC-002 | T-RPT-01 | unit | automated | automated | header 4-fact golden assertion | — |
| AC-003 | T-SEAM-02 | integration | automated | automated | rerun leaves exactly 1 report holding new content | — |
| AC-004 | T-RNK-02 | unit | automated | automated | mixed-verdict ordering per FR-033 | — |
| AC-005 | T-RPT-11 + T-SEAM-01 | unit + integration | automated | automated | stdout summary counts + top 3 | — |
| AC-006 | T-SEAM-06 | integration | automated | automated | valid empty list → round 2 skipped (1 recorded call), 0-question report, exit 0 | — |
| AC-007 | T-RPT-08 + end-to-end all-ANSWERED replay in T-SEAM-01 parametrization | unit + integration | automated | automated | 0-findings statement; full audit appendix; exit 0 | — |
| AC-008 | T-RPT-07 | unit | automated | automated | ANSWERED question in exactly 1 `<details>` section with quoted lines | — |
| AC-009 | T-RPT-05 | unit | automated | automated | 1 quoted spec line per cited number, read from fixture file | — |
| AC-010 | T-SEAM-03 | integration | automated | automated | spec hash unchanged across all exit codes | — |
| AC-011 | T-PRM-06 | integration | automated | automated | prompt-recording stub: round-2 prompt = spec payload + id/question payload; 0 round-1 categories/targets/line tags/reasoning (contract counting convention) | — |
| AC-012 | T-SEAM-04 | integration | automated | automated | recorded cwd is a fresh `sue-challenge-*` temp dir outside the repo for every invocation | — |
| AC-013 | T-EXC-01 | integration | automated | automated | exit 1, 0 model calls | — |
| AC-014 | T-EXC-03 | integration | automated | automated | exit 2, 1 installation-pointer message, 0 reports | — |
| AC-015 | T-EXC-04 | integration | automated | automated | exit 3, raw output in `.sue-debug/`, 0 reports | — |
| AC-016 | T-EXC-05 | integration | automated | automated | invalid-then-valid replay: exactly 2 invocations that round, exit 0 | — |
| AC-017 | T-EXC-06 | integration | automated | automated | timeout → parse-failure classification, 1 retry, second failure exit 3 (sub-second budget keeps test fast) | — |
| AC-018 | T-VAL-08..10 + T-EXC-05 | unit + integration | automated | automated | missing/duplicate/unknown id each classified parse failure consuming exactly 1 retry | — |
| AC-019 | T-EXC-02 | integration | automated | automated | read-only dir → exit 1, 0 model calls | — |
| AC-020 | T-VAL-06 + T-RPT-02 | unit | automated | automated | first-N truncation + exactly 1 header note | — |
| AC-021 | T-SEAM-01 | integration | automated | automated | full stubbed end-to-end, 0 live calls | — |
| AC-022 | T-META-01 | meta (CI) | automated | automated | suite green with no network and no `claude` installed (CI job property; locally reproducible) | — |
| AC-023 | — | live acceptance | escalate | escalate | spec-mandated manual live run at FINALIZE (plan.md Final Phase); tolerance ≥ 1 of 3 known issues within ≤ 3 attempts; A-004 anchor freeze first | decision already recorded in spec.md — no further user input needed; FINALIZE owns execution |
| SC-001 | — | live acceptance | escalate | escalate | same gate as AC-023 | same — spec-approved live gate |
| SC-002 | T-META-01 | meta (CI) | automated | automated | offline suite property | — |
| SC-003 | T-EXC-01..04, T-EXC-09 | integration | automated | automated | full exit-code matrix: each class reproduces its code + exactly 1 diagnostic line | — |
| SC-004 | T-SEAM-08 | integration | automated | automated | ≤ 4 invocations structural bound with per-call timeout enforcement observed under sub-second budgets | — |
| SC-005 | T-SEAM-07 + T-META-01 | integration + meta | automated | automated | stdlib-only + zero-install suite run on fresh checkout | — |

## Gap Analysis

| Requirement ID | Gap | Risk | Required Action | Owner |
|----------------|-----|------|-----------------|-------|
| AC-011 / FR-021 | spec.md wording "exactly 2 content blocks" not yet reworded per ISS-201/ISS-203; literal block-counting tests would assert an ill-defined count | tests could encode the wrong count if written literally | tests assert payload presence + zero round-1 leakage per the counting convention pinned in `contracts/model-command-contract.md`; COMMANDER should still route the one-line rewording to CARTOGRAPHER (plan.md risk row 3) — not blocking | COMMANDER → CARTOGRAPHER |
| FR-045 (config/state-read half) | the import-scan test proves no project imports; "reads 0 orchestration config or state files" is additionally guarded by review, since a runtime file-open audit is not practical in-suite | low — stdlib-only single file makes hidden reads visible in review | CODE REVIEWER gate at plan Phase 5 checks for config/state path literals | CODE REVIEWER |
| A-004 (acceptance anchors) | the 3 named spec-029 known issues were validated at base commit ef2643c9 and may drift before FINALIZE | live gate could fail for stale-anchor reasons, not tool reasons | re-verify or freeze anchors as Final-Phase work item 1 (already in plan.md) before any live attempt | FINALIZE operator |
| — (report-write failure after model calls) | no AC covers a write failure that bypasses the FR-006 pre-flight (exotic ACL race); ADR-006 notes the path reports exit 1 | very low — pre-flight makes it practically unreachable | accepted; no test enumerated (would require ACL manipulation beyond portable tmp_path capabilities) — documented here for transparency | SENTINEL (accepted) |

No acceptance criterion is untestable; nothing routes back to WHAT.

## Escalations

| Requirement ID | Reason Automation Is Infeasible | Options For User | Status |
|----------------|---------------------------------|------------------|--------|
| SC-001 / AC-023 | Requires a live, nondeterministic model call, which SC-002 explicitly forbids inside the automated suite; the spec itself defines this as the single manual live acceptance run with an encoded tolerance (≥ 1 of 3 named issues, ≤ 3 attempts) | (a) accept as spec-designed manual FINALIZE gate — **already chosen in spec.md/plan.md**; (b) add a recorded-replay harness in a later SUE tier | resolved — user decision is recorded in the approved spec (SC-001, AC-023) and plan (Final Phase); no new approval required |

## Browser App Gates

| Gate | Required | Coverage Evidence |
|------|----------|-------------------|
| Playwright E2E critical journeys | no | is_browser_app = false (stdlib CLI tool; see test-strategy.md Stack Detection) |
| Smoke serving check | no | nothing is served; the stub-seam end-to-end run (T-SEAM-01) is the equivalent "does it actually run" smoke gate |
| Visual validation task | no | no UI surface exists |

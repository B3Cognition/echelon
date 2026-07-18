# Planning Risk Matrix — SUE Challenge Script

## Metadata

- Spec: 030-build-sue-challenge-script (runs/spec-20260718-104053-744160/specs/030-build-sue-challenge-script/spec.md)
- Orchestrator: speckit-echelon-orchestrator (ORCHESTRATOR)
- Mode: consensus
- Date: 2026-07-18

Scoring: Probability × Impact, each Low=1 / Medium=2 / High=3, score 1–9. Mitigation
sources: plan.md Risks, research.md ADRs, test-strategy.md, implementability-report.md
(ASSESS2), issues.md (WHY3). Consensus deltas: T-005's int-timeout rework trigger
(ISS-305) is defused by the T-002 clarification; the ISS-201/ISS-203 wording risk is
now WHY3-escalated (ISS-302/ISS-303, HIGH); one governance risk added (ISS-301).

## High-Risk Tasks

Every task with score >= 6.

| Task | Probability | Impact | Score | Mitigation |
|------|-------------|--------|-------|------------|
| T-005 subprocess runner | Medium | High | 6 | Invocation shape frozen by contracts/model-command-contract.md with Grade-A spike evidence (claude 2.1.214, ADR-003); recording stubs prove cwd/argv/stdin before any dependent task builds on it; sub-second timeout tests keep the failure mode visible in CI. Consensus: the ISS-305 int-typed `--timeout` contradiction (WHY3's "most likely misimplemented requirement") is defused upstream — T-002 now implements float-seconds parsing, so the sub-second budgets T-005's tests require are expressible before this task starts |
| T-009 retry loop + exit-3 path | Medium | High | 6 | Typed CallOutcome state machine (ADR-006) instead of exception flow; replay-sequence stubs cover invalid→valid, invalid→invalid, sleep→sleep before implementation (TDD); dump naming pinned by report-format.md so drift fails a test, not a user |
| T-S01 manual live acceptance | Medium | High | 6 | Tolerance already encoded in the criterion (≥1 of 3 issues, ≤3 attempts, AC-023); A-004 anchor re-verify/freeze is step 1 of the task; failure after 3 attempts routes to COMMANDER — never silently waived; `.sue-debug/` gives raw evidence for diagnosis |

## Medium/Low-Risk Tasks

| Task | Probability | Impact | Score | Notes |
|------|-------------|--------|-------|-------|
| T-006 extraction | Medium | Medium | 4 | claude CLI output-shape drift lands here; staged tolerant extractor (ADR-005) plus 6-class fixture matrix bound the damage; version pinned in research.md keeps drift diagnosable |
| T-012 pipeline wiring | Low | High | 3 | Interface mismatches surface here; mitigated by the frozen internal-interfaces.md signatures every prior task tests against |
| T-011 renderers | Low | Medium | 2 | Golden-test brittleness on wording; report-format.md is the single wording source; NFR-004 byte-diff test catches nondeterminism |
| T-003 pre-flight spine | Low | Medium | 2 | argparse exit-2 remap (U-007) is the only subtlety; explicit test asserts argument errors never exit 2 |
| T-014 hardening + flakiness gate | Low | Medium | 2 | Timeout-margin flakiness is the expected class; sleep set to 3× budget per test-strategy.md taxonomy |
| T-001, T-002, T-004, T-007, T-008, T-010, T-013 | Low | Low–Medium | 1–2 | Pure functions or fixed surfaces with exhaustive cheap unit tests |

## Systemic Risks

| Risk Type | Description | Probability | Impact | Mitigation |
|-----------|-------------|-------------|--------|------------|
| Technology | claude CLI version drift changes `-p` stdout shape (validated on 2.1.214 only) — hits T-005/T-006 extraction and, at worst, the exit-3 loop | Medium | High | Staged tolerant extractor (ADR-005); version + flags pinned in research.md; `.sue-debug/` preserves raw evidence; stub seam keeps CI immune |
| Integration | Operator-scope ambient context biases the blind reading (OQ-002 residual, evidence-confirmed) — silent bias, no crash | Medium | Medium | Documented limitation with Grade-A evidence (ADR-004); usage/README offers `--claude-cmd "claude --safe-mode"` as operator opt-in; human reviewer is the designed backstop |
| Knowledge | Counting wordings still unfixed in spec.md — WHY3 escalated them to HIGH (ISS-302/ISS-303, formerly ISS-201/ISS-203); literal test enumeration or SPEC GUARD verification against spec.md would assert wrong counts (e.g. AC-011 "2 content blocks", AC-002 "4 facts" on truncated runs) | Medium | Medium | Counting convention normatively pinned in contracts/model-command-contract.md (content block = data payload); T-004/T-011/T-014 test descriptions already adopt it, so the build is insulated; the one-line CARTOGRAPHER rewordings remain a WHY3 blocking requirement COMMANDER must route before SPEC GUARD verification |
| Governance | SC-001/AC-023 escalation has no `deferred_risky_accepted` record in state.json (WHY3 CRITICAL ISS-301) — FINALIZE reached without the record produces gate friction or a silently waived live validation | Medium | Medium | Deterministic COMMANDER state write citing the approved spec text (SC-001/AC-023, plan.md Final Phase) — a recording formality, not a re-decision; T-S01's content is unaffected; WHY3 PASS is barred until it lands, which forces resolution before build sign-off |
| Scope | Standalone-contract erosion under pressure (harness stream-json reuse creeping in) — breaks FR-045 and the stub seam | Low | High | T-013 AST import-scan test is a permanent tripwire; CODE REVIEWER zero-coupling gate at polish; constitution Principle V alignment recorded in plan.md |
| Scope | Silent trimming of fidelity items (collapsed audit appendix FR-038, egress disclosure NFR-003) — the items DISCOVER once dropped | Low | Medium | Both are explicit acceptance criteria on T-011/T-002 with dedicated tests; UI-004 no-trimming intent journaled by TRACKER |

## Risk Summary

| Rating | Count | Notes |
|--------|-------|-------|
| High (score ≥ 6) | 3 | T-005, T-009, T-S01 — all clustered on the model boundary and its failure paths, matching the testability deficiency (negative-space) SENTINEL weighted the pyramid toward |
| Medium (3–5) | 2 | T-006, T-012 |
| Low (1–2) | 10 | Pure-function and fixed-surface tasks |

# Critical Path — SUE Challenge Script

## Metadata

- Spec: 030-build-sue-challenge-script (runs/spec-20260718-104053-744160/specs/030-build-sue-challenge-script/spec.md)
- Orchestrator: speckit-echelon-orchestrator (ORCHESTRATOR)
- Mode: consensus
- Date: 2026-07-18

## Effort Basis (GATEKEEPER inputs — no new estimates)

Per Rule 3, ORCHESTRATOR does not estimate effort. All per-task figures below are a
proportional decomposition of GATEKEEPER's estimates.md totals: most-likely 10 h
(0.25 person-weeks). At consensus, GATEKEEPER's implementability-report.md tightened
the interval to 4–18 h (0.10–0.45 person-weeks, confidence medium) — the first-pass
worst case ("extraction contract needs redesign after the OQ-001 spike") is defused by
the executed spike. Per-task shares are unchanged and sum exactly to the 10 h
most-likely figure; the manual acceptance gate (T-S01) sits in the acceptance-run
overhead GATEKEEPER noted separately in prioritization.md and is operator-paced, not
developer effort.

## Consensus Re-Evaluation (PLAN2)

ASSESS2 scored all 15 tasks READY; zero tasks were added, split, or re-sequenced, and
no specialist output required a new task (SENTINEL's test strategy is already embedded
in the per-task Test contracts; no SECURITY/PERFORMANCE specialist artifacts exist for
this run). The critical path is therefore **unchanged**: the same linear chain
T-001→…→T-014→T-S01. The only task-content deltas (ISS-308 bounds vectors and the
ISS-305 sub-second timeout clarification, both on T-002) add test vectors inside an
existing 0.5 h share and do not move the path.

## Minimum Timeline

| Metric | Value | Notes |
|--------|-------|-------|
| Critical path effort | 10 h most-likely (4–18 h consensus interval) | = the entire build chain T-001→T-014; single-file deliverable serializes everything |
| Critical path task count | 14 build tasks (+ 1 manual gate T-S01) | every build task is on the critical path |
| Parallelizable task count | 0 | all tasks mutate `scripts/sue_challenge.py` and/or `tests/unit/test_sue_challenge.py` — shared mutable state everywhere |

The critical path IS the task list: with one implementation file, one test file, and a
TDD ordering constraint (constitution hard gate), no task can start before its
predecessor finishes. This is a deliberate consequence of ADR-001 (single-file script),
not a planning failure — at 10 h most-likely total, parallelization overhead would
exceed its savings.

## Critical Path

| Order | Task | Effort share (of 10 h) | Cumulative | Dependency Reason |
|-------|------|--------|------------|-------------------|
| 1 | T-001 skeleton: constants + dataclasses | 0.5 h | 0.5 h | Everything imports the shared constants (ISS-206 three-way contract anchor) |
| 2 | T-002 parse_args + egress disclosure | 0.5 h | 1.0 h | RunConfig consumed by every later stage; frozen CLI surface first |
| 3 | T-003 preflight, load_spec, fail(), main spine | 1.0 h | 2.0 h | Exit-code spine must exist before any model-call path is testable |
| 4 | T-004 numbered_text + prompt builders | 1.0 h | 3.0 h | Prompts are input to the runner tests (recording stubs assert prompt content) |
| 5 | T-005 isolated subprocess runner | 1.25 h | 4.25 h | The single external boundary; retry loop builds on CallOutcome |
| 6 | T-006 staged JSON extraction | 0.5 h | 4.75 h | Validators consume extracted objects |
| 7 | T-007 round-1 validation + truncation | 0.75 h | 5.5 h | Round-2 bijection validates against post-truncation ids |
| 8 | T-008 round-2 validation + bijection | 0.5 h | 6.0 h | execute_round needs both validators |
| 9 | T-009 retry loop + debug dump + exit-3 | 1.25 h | 7.25 h | Completes the untrusted-output state machine (ADR-006) |
| 10 | T-010 partition + ranking | 0.25 h | 7.5 h | Renderer consumes ranked findings |
| 11 | T-011 report + summary renderers | 1.25 h | 8.75 h | main wiring needs the renderers |
| 12 | T-012 main pipeline wiring, end-to-end | 0.5 h | 9.25 h | First point the full product exists; unblocks the gates |
| 13 | T-013 standalone gate (import scan) | 0.25 h | 9.5 h | Gate over the finished script |
| 14 | T-014 coverage completion + hardening | 0.5 h | 10.0 h | Terminal build gate: SC-003 matrix, NFR bounds, flakiness loop |
| 15 | T-S01 manual live acceptance (FINALIZE) | operator-paced | — | Spec-mandated SC-001 gate; outside developer effort, after merge-quality build |

## Bottleneck Tasks

| Task | Effort | Dependents | Why Bottleneck |
|------|--------|------------|----------------|
| T-005 runner | 1.25 h | 9 downstream tasks | Largest single risk surface (subprocess, isolation, timeout); every model-path behavior depends on CallOutcome semantics; claude CLI drift lands here first |
| T-009 retry loop | 1.25 h | 5 downstream tasks | The exit-3 state machine gates all failure-path acceptance criteria (AC-015–AC-018); errors here invalidate the SC-003 matrix |
| T-011 renderers | 1.25 h | 3 downstream tasks | The product payload; golden tests are the largest test mass; blocks end-to-end wiring |
| T-012 wiring | 0.5 h | 2 gates + T-S01 | First integration point — any interface mismatch among the 11 prior tasks surfaces here |

## Float Analysis

| Task | Float | Notes |
|------|-------|-------|
| T-001…T-014 | 0 | Linear chain: every build task is critical; any slip moves the end date 1:1 |
| T-S01 | operator-scheduled | Only float in the plan: the FINALIZE gate can run any time after T-014, provided the A-004 anchor freeze happens before the first attempt |

Logical (not schedulable) float: T-004, T-006, T-007, T-008, T-010, T-011 are pure
functions whose *logic* depends only on T-001 constants — if the chain ever needs
re-sequencing (e.g. a blocker in T-005), these can proceed out of order at the cost of
merge conflicts in the two shared files. Recorded as a contingency, not a plan.

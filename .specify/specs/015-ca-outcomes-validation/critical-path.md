# Critical Path — Spec 015: Cognitive Architecture Outcomes Validation
**Agent**: ORCHESTRATOR | **Squad Run**: squad-1775154996 | **Date**: 2026-04-02
**Phase**: plan

---

## Critical Path: MVP Track

The MVP consists of five requirements (REQ-015-001, -002, -006, -008, -004) and the following tasks: TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-009, TASK-010, TASK-012.

### Dependency Graph

```
Day 0
  ├── TASK-001 (REQ-015-001 — Proof Status Table)         [Quick, ~3h]
  ├── TASK-002 (REQ-015-002 — Novelty Search Record)      [Quick, ~1h]
  ├── TASK-003 (REQ-015-006 — NS-003 Experiment Design)   [Medium, ~2d]
  ├── TASK-004 (REQ-015-008 — U-CA-004 Spec)             [Medium, ~2d]
  ├── TASK-005 (REQ-015-004 — Scope Violation Baseline)   [Medium, ~1-2d]
  └── TASK-009 (ISS-001 Architecture Ambiguity)           [Quick, ~2h]

Day 0–1 (after TASK-001 completes)
  └── TASK-010 (Final Proof Status Review)               [Quick, ~2h]

Day 2–4 (after TASK-001, -002, -003, -004, -005, -010)
  └── TASK-012 (Finalization and Delivery)               [Quick, ~2h]
```

### Critical Path Sequence

The critical path runs through the two Medium-effort MVP tasks in parallel:

**Path A (longest MVP dependency chain):**
```
TASK-003 or TASK-004 [~2d] → TASK-012 [~2h]
Total: ~2.25 days
```

**Path B (parallel, does not extend total):**
```
TASK-001 [~3h] → TASK-010 [~2h] → TASK-012 [~2h]
Total: ~1 day
```

**Path C (parallel, does not extend total):**
```
TASK-002 [~1h] → TASK-012 [~2h]
Total: ~0.5 days
```

**Path D (parallel, does not extend total):**
```
TASK-005 [~1-2d] → TASK-012 [~2h]
Total: ~1.5-2.25 days
```

The critical path is determined by whichever of TASK-003 or TASK-004 completes last. Both are Medium-effort (1-2 days) with no dependencies. If executed by separate agents in parallel, the critical path is 2 days of task execution plus ~2 hours of finalization.

**MVP Calendar Estimate: 3 days with parallel execution, 4-5 days with sequential execution.**

---

## Post-MVP Track (Baseline Measurement Tasks)

The three baseline tasks and NOVEL-004 calibration run on a separate track, partially in parallel with the MVP track.

```
Day 0 (start immediately, runs in background)
  └── TASK-006 (REQ-015-003 — Token Logging Instrumentation)
        [Quick for instrumentation + 1-3d for 3 instrumented runs to complete]

Day 0–2 (can start in parallel with TASK-005)
  └── TASK-007 (REQ-015-005 — Contradiction Scan)
        [Medium, ~1-2d; shares artifact corpus with TASK-005]

After TASK-006 completes (Day 3–5 depending on run-collection gate)
  └── TASK-008 (REQ-015-007 — NOVEL-004 Calibration)
        [Medium, ~1-2d; uses symbolic break-even if TASK-006 still incomplete]
```

### Post-MVP Calendar Estimate

- TASK-006: instrumentation Quick (~3h) + pipeline run-collection gate (1-3 days of wall time for 3 spec runs) = total 1-3 days
- TASK-007: 1-2 days, parallel with TASK-005
- TASK-008: 1-2 days, starts after TASK-006 (or in symbolic break-even mode at any point)
- TASK-011: Risk Register — Quick (~1h), can run any time

**Post-MVP completion estimate: 3-5 days after MVP delivery, depending on run-collection gate for TASK-006.**

---

## Full Spec Completion Estimate

| Track | Tasks | Calendar Time |
|-------|-------|---------------|
| MVP (parallel execution) | TASK-001 through -005, -009, -010, -012 | 3 days |
| MVP (sequential execution) | TASK-001 through -005, -009, -010, -012 | 4-5 days |
| Post-MVP baseline track | TASK-006, -007, -008, -011 | 3-5 days after MVP |
| Full spec (parallel MVP + parallel post-MVP) | All 12 tasks | 5-7 days total |

---

## Parallelization Recommendations

1. **Day 0, parallel start**: TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-009 can all begin simultaneously. Assign TASK-003 and TASK-004 to separate agents — they are the longest MVP tasks and are completely independent.

2. **TASK-001 priority**: Although Quick, TASK-001 should be the first task assigned because TASK-010 depends on it and TASK-012 transitively depends on TASK-010. Completing TASK-001 early eliminates this dependency bottleneck.

3. **TASK-007 can start alongside TASK-005**: Both use the same artifact corpus (runs 008-014). TASK-005 determines which 3-5 runs are selected; TASK-007 can begin scanning the full available corpus immediately and subset results once TASK-005 confirms the annotated run set.

4. **TASK-008 can proceed with symbolic break-even**: Do not wait for TASK-006 run-collection to complete before starting TASK-008. Begin with symbolic break-even form (AC-007-004 permits this); update to numeric form once TASK-006 produces data.

5. **TASK-009 is Quick and unblocking**: Resolve ISS-001 architecture ambiguity early (Day 0 or Day 1) so that TASK-004's CA overlay testing order recommendation is grounded in the confirmed granularity.

---

## Risk to Critical Path

| Risk | Probability | Impact on Critical Path | Mitigation |
|------|-------------|------------------------|-----------|
| TASK-003 or TASK-004 rubric/AC self-check requires revision | Medium | +0.5-1 day | Build AC self-check into each task's completion criterion; assign separate reviewers |
| TASK-006 run-collection gate delayed (fewer than 3 runs available in window) | Low | Post-MVP delay only; MVP not blocked | TASK-008 proceeds with symbolic break-even; TASK-011 notes the risk |
| TASK-005 fewer than 3 spec runs have complete DISCOVER+ASSESS outputs | Low | +0.5 day to expand corpus | Runs 008-014 confirmed as available in INVESTIGATOR artifacts |
| TASK-009 does not resolve ISS-001 definitively | Low | TASK-004 overlay testing order stated as provisional | Note open ISS-001 status in TASK-004 output per spec non-requirements |

---

## MVP Completion Gate

MVP is complete when all of the following are true:

1. TASK-001 complete: 17-row proof status table artifact exists with all AC-001-001 through -005 satisfied.
2. TASK-002 complete: Standalone novelty search record artifact exists with AC-002-001 through -005 satisfied.
3. TASK-003 complete: NS-003 experiment design document satisfies AC-006-001 through -007.
4. TASK-004 complete: U-CA-004 experiment specification satisfies AC-008-001 through -007.
5. TASK-005 complete: Scope violation baseline artifact satisfies AC-004-001 through -005.
6. TASK-010 complete: Proof status table cross-referenced against source files; no discrepancies remaining.
7. TASK-012 complete: All five MVP artifacts confirmed internally consistent; AC-SPEC-001 through -005 verified across the full artifact set.

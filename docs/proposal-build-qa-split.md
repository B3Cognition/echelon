# Proposal: Split Phase 4 into BUILD and QA

## Current State (v0.3.0)

```
Phase 4: BUILD (monolithic)
├── Per Task (sequential, blocking)
│   ├── IMPLEMENTER → writes code
│   ├── SPEC GUARD → spec compliance
│   ├── CODE REVIEWER → code quality
│   └── TEST GUARDIAN → test quality
├── Per Phase
│   ├── ENGINEERING MANAGER → orchestration
│   ├── INTEGRATOR → system integration
│   └── VISUAL VALIDATOR → visual check
└── Final
    └── VERIFICATION → backpropagation (100% coverage)
```

**Problem:** 4 sequential agents per task. Task T-005 waits for T-004's full review chain.

---

## Proposed State (v0.4.0)

```
Phase 4: BUILD (fast, parallelizable)
├── Per Task (parallel capable)
│   └── IMPLEMENTER → writes code + tests
├── Light Gate (automated, non-blocking between tasks)
│   ├── Build passes (tsc --noEmit)
│   ├── Tests pass (vitest run)
│   └── No lint errors
├── Phase Gate
│   ├── PROGRESS TRACKER → effort/drift check
│   └── ENGINEERING MANAGER → proceed to QA?
└── Output: all code written, all tests green

Phase 5: QA (thorough, batched)
├── Batch Review (can process multiple tasks)
│   ├── SPEC GUARD → spec compliance (all tasks)
│   ├── CODE REVIEWER → code quality (holistic)
│   └── TEST GUARDIAN → test quality (aggregate)
├── System Validation
│   ├── INTEGRATOR → full integration
│   └── VISUAL VALIDATOR → running product
├── Verification
│   └── VERIFICATION → backpropagation loop
├── Phase Gate
│   └── ENGINEERING MANAGER → rework or done?
└── Output: verified, production-ready code
```

---

## Phase 4: BUILD — Detailed

### Purpose

Produce working code that passes automated checks. Optimize for speed and parallelism.

### Agents Active

| Agent | Role | Runs |
|-------|------|------|
| IMPLEMENTER | Write code + tests (TDD) | Per task (parallelizable) |
| PROGRESS TRACKER | Track effort, detect drift | Continuous |
| ENGINEERING MANAGER | Phase gate decision | End of phase |
| CHANGE CONTROLLER | Handle spec changes | On demand |

### Per-Task Flow

```
Task assigned to IMPLEMENTER
    ↓
IMPLEMENTER writes code (TDD)
    ↓
Light Gate (automated):
  - tsc --noEmit passes
  - vitest run passes
  - eslint passes
    ↓
Task status: BUILD_COMPLETE
    ↓
Next task (can run in parallel with other IMPLEMENTERs)
```

### Light Gate Rules

The light gate is NOT a full review. It checks:

1. **Compiles** — `tsc --noEmit` exits 0
2. **Tests pass** — `vitest run` exits 0
3. **No lint errors** — `eslint` exits 0
4. **Files exist** — task's specified output files are present

It does NOT check:
- Spec compliance (QA does this)
- Code quality beyond lint (QA does this)
- Test quality/coverage (QA does this)
- Cross-task integration (QA does this)

### Phase Gate Criteria

BUILD phase ends when:

| Criterion | Check |
|-----------|-------|
| All tasks BUILD_COMPLETE | tasks.md status |
| No BLOCKED tasks | tasks.md status |
| Effort within 1.5x estimate | PROGRESS TRACKER |
| No unresolved change requests | CHANGE CONTROLLER |

### Parallelization Model

Tasks can run in parallel if:
- No dependency relationship in tasks.md
- Different file paths (no write conflicts)

```
Example: 10 tasks, 3 parallel workers

Worker 1: T-001 → T-004 → T-007 → T-010
Worker 2: T-002 → T-005 → T-008
Worker 3: T-003 → T-006 → T-009

Total time: ~4 task-cycles instead of 10
```

### Output Artifacts

- Source files in specified paths
- Test files co-located or in test/
- tasks.md updated with BUILD_COMPLETE status
- build-phase-report.md (timing, effort, issues)

---

## Phase 5: QA — Detailed

### Purpose

Verify that BUILD output meets spec, quality standards, and is production-ready. Optimize for thoroughness.

### Agents Active

| Agent | Role | Runs |
|-------|------|------|
| SPEC GUARD | Spec compliance | Batch (all completed tasks) |
| CODE REVIEWER | Code quality | Holistic review |
| TEST GUARDIAN | Test quality | Aggregate assessment |
| INTEGRATOR | System integration | Full system |
| VISUAL VALIDATOR | Visual verification | Running product |
| VERIFICATION | Backpropagation | Full spec coverage |
| ENGINEERING MANAGER | Rework decisions | After verification |

### QA Flow

```
BUILD phase complete
    ↓
┌─────────────────────────────────────┐
│ Batch Review (can run in parallel)  │
├─────────────────────────────────────┤
│ SPEC GUARD ──────┐                  │
│ CODE REVIEWER ───┼──► Review Report │
│ TEST GUARDIAN ───┘                  │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ System Validation (sequential)      │
├─────────────────────────────────────┤
│ INTEGRATOR → integration-report.md  │
│ VISUAL VALIDATOR → visual-report.md │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Verification (backpropagation)      │
├─────────────────────────────────────┤
│ VERIFICATION → gap-report.md        │
│              → coverage score       │
└─────────────────────────────────────┘
    ↓
Coverage = 100%? ──No──► Rework Loop
    │
   Yes
    ↓
QA COMPLETE
```

### Batch Review Benefits

Instead of reviewing each task in isolation:

**Before (per-task):**
```
CODE REVIEWER sees: T-001 files only
- Cannot detect: T-001 pattern differs from T-003
- Cannot detect: T-002 duplicates logic from T-005
```

**After (batch):**
```
CODE REVIEWER sees: all BUILD output
- Can detect: inconsistent patterns across tasks
- Can detect: duplication across tasks
- Can detect: architectural drift
- Can suggest: cross-task refactoring
```

### SPEC GUARD Batch Mode

SPEC GUARD reviews all tasks against full spec:

```markdown
## Batch Spec Compliance Report

### Traceability Matrix (Complete)
| Requirement | Task | Code Location | Status |
|-------------|------|---------------|--------|
| FR-001 | T-001 | src/auth.ts:23 | IMPLEMENTED |
| FR-002 | T-003 | src/api.ts:45 | IMPLEMENTED |
| FR-003 | T-005 | — | MISSING |

### Cross-Task Issues
- FR-007 partially implemented in T-002 and T-004 (split implementation)
- FR-012 acceptance criteria not tested (test exists but doesn't verify criterion)

### Scope Creep (Aggregate)
- src/utils/helper.ts added by T-006 — not traced to any requirement
```

### CODE REVIEWER Holistic Mode

CODE REVIEWER sees full codebase:

```markdown
## Holistic Code Review

### Pattern Consistency
| Pattern | Tasks Using | Deviation |
|---------|-------------|-----------|
| Error handling | T-001, T-002, T-004 | T-003 uses different approach |
| Naming convention | T-001-T-005 | T-006 uses camelCase instead of kebab |

### Cross-Task Issues
| Issue | Severity | Tasks Affected | Recommendation |
|-------|----------|----------------|----------------|
| Duplicate validation logic | MEDIUM | T-002, T-005 | Extract to shared util |
| Inconsistent error types | HIGH | T-003 | Align with T-001 pattern |

### Architecture Observations
- Data flow is clean
- Dependency direction correct
- No circular imports detected
```

### Rework Loop

When VERIFICATION finds gaps:

```
VERIFICATION: coverage = 87% (13 gaps found)
    ↓
ENGINEERING MANAGER creates rework tasks:
  - RW-001: Implement FR-003 (not implemented)
  - RW-002: Fix FR-007 (partial)
  - RW-003: Add tests for FR-012
    ↓
Rework tasks go back to BUILD phase (light process)
    ↓
QA re-runs (VERIFICATION only, unless rework touched reviewed code)
    ↓
Coverage = 100%? Loop until yes (max 3 iterations)
```

### QA Complete Criteria

| Criterion | Agent | Required |
|-----------|-------|----------|
| All SPEC GUARD verdicts: PASS | SPEC GUARD | YES |
| CODE REVIEWER: APPROVED (no CHANGES_REQUESTED) | CODE REVIEWER | YES |
| TEST GUARDIAN: PASS | TEST GUARDIAN | YES |
| INTEGRATOR: PASS | INTEGRATOR | YES |
| VISUAL VALIDATOR: PASS | VISUAL VALIDATOR | YES |
| VERIFICATION coverage: 100% | VERIFICATION | YES |
| Gap report: zero open items | VERIFICATION | YES |

---

## Comparison: Before vs After

### Timing (10 tasks, 4 review agents)

**Before (sequential per-task):**
```
T-001: IMPL(1h) → SG(15m) → CR(20m) → TG(15m) = 1h50m
T-002: IMPL(1h) → SG(15m) → CR(20m) → TG(15m) = 1h50m
...
T-010: IMPL(1h) → SG(15m) → CR(20m) → TG(15m) = 1h50m

Total: 10 × 1h50m = 18h20m (sequential)
```

**After (parallel BUILD, batch QA):**
```
BUILD (3 parallel workers):
  Worker 1: T-001 → T-004 → T-007 → T-010 = 4h
  Worker 2: T-002 → T-005 → T-008         = 3h
  Worker 3: T-003 → T-006 → T-009         = 3h
  BUILD Total: 4h (wall clock)

QA (batch):
  SPEC GUARD (batch): 45m
  CODE REVIEWER (holistic): 1h
  TEST GUARDIAN (aggregate): 30m
  INTEGRATOR: 30m
  VERIFICATION: 1h
  QA Total: 3h45m

Total: 4h + 3h45m = 7h45m (vs 18h20m)
```

**Speedup: ~2.4x** (with rework cycles, still faster due to batch detection)

### Quality

| Aspect | Before | After |
|--------|--------|-------|
| Cross-task pattern issues | Caught late (VERIFICATION) | Caught early (batch CODE REVIEWER) |
| Duplicate code | Often missed | Detected in batch review |
| Spec gaps | Found after all tasks done | Same, but rework is batched |
| Integration issues | Found in INTEGRATOR | Same |

---

## Migration Path

### Phase 1: Add QA phase (non-breaking)

1. Keep current per-task gates but mark them "light"
2. Add explicit QA phase after all tasks complete
3. QA runs batch versions of same agents
4. Rework identified in QA, not per-task

### Phase 2: Optimize BUILD (performance)

1. Remove blocking per-task reviews (keep light gate only)
2. Enable parallel IMPLEMENTER execution
3. Tune light gate thresholds

### Phase 3: Tune QA (quality)

1. Add cross-task analysis to CODE REVIEWER
2. Add aggregate metrics to TEST GUARDIAN
3. Optimize VERIFICATION for incremental re-runs

---

## Configuration

Add to `squad-config.yml`:

```yaml
phases:
  build:
    parallel_workers: 3              # IMPLEMENTERs running concurrently
    light_gate:
      require_build: true            # tsc --noEmit
      require_tests: true            # vitest run
      require_lint: true             # eslint
      fail_on_warning: false         # lint warnings don't block

  qa:
    batch_review: true               # review all tasks together
    holistic_code_review: true       # CODE REVIEWER sees full codebase
    verification_max_iterations: 3   # backpropagation loop limit
    visual_validation: true          # run VISUAL VALIDATOR
```

---

## Open Questions

1. **Rework routing**: Should rework tasks go through full BUILD → QA, or just BUILD → VERIFICATION?
2. **Partial QA**: If only 2 tasks are reworked, does QA re-run on all tasks or just the 2?
3. **Human checkpoint**: Should there be a human gate between BUILD and QA?
4. **Specialist triggering**: When do GUARDIAN, BENCHMARK, etc. run? BUILD or QA?

---

## Recommendation

Implement Phase 1 (add QA phase) in v0.4.0. Measure:
- Time savings from batch review
- Quality improvement from holistic CODE REVIEWER
- Rework cycle count

Then decide on Phase 2/3 optimizations based on data.

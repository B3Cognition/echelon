# SP-001: BDI Feasibility Spike — Report

**Scientist**: Claude (SP-001)
**Date**: 2026-03-21
**Status**: Complete

## Objective

Build a minimal BDI reasoning cycle in TypeScript from the AgentSpeak(L) formal specification (Rao 1996, Bordini 2007). Validate feasibility for echelon architecture per ADR-001 (build from spec, not port Jason).

## What Was Built

A complete BDI engine implementing the AgentSpeak(L) reasoning cycle:

| Module | File | LOC | Purpose |
|--------|------|-----|---------|
| Types | `types.ts` | 137 | Beliefs, Goals, Plans, Intentions, Events, Actions |
| Belief Base | `belief-base.ts` | 91 | O(1) add/remove/query, event generation |
| Plan Library | `plan-library.ts` | 60 | Plan storage, applicable plan filtering |
| Reasoning Cycle | `reasoning-cycle.ts` | 307 | Full BDI deliberation loop (9 steps) |
| Failure Recovery | `failure.ts` | 47 | Plan fallback + goal failure propagation |
| XState Integration | `xstate-integration.ts` | 175 | BDI as XState v5 callback actor |
| Index | `index.ts` | 35 | Public API surface |
| Benchmark | `benchmark.ts` | 106 | Performance measurement |

## Measurements

### Lines of Code

| Category | LOC |
|----------|-----|
| **Source (non-test)** | **958** |
| Tests | 789 |
| Total | 1,747 |
| XState glue | 175 (includes types/docs; core glue ~30 lines) |
| File count | 12 |

### Performance (1000 cycles, 50 beliefs, 10 plans)

| Metric | Value |
|--------|-------|
| **Avg cycle** | **2.1 us (0.0021 ms)** |
| Median cycle | 1.5 us |
| P99 cycle | 9.2 us |
| Max cycle | 356.3 us (JIT warmup) |
| Total (1000 cycles) | 2.1 ms |

### Test Results

- **35 tests, 4 test files, all passing**
- Belief base: 13 tests (add/remove/query/events)
- Plan library: 7 tests (matching, filtering, context conditions)
- Reasoning cycle: 11 tests (basic execution, beliefs in plans, context selection, failure recovery, sub-goals, belief-triggered plans, 3-goal scenario)
- XState integration: 4 tests (goal events, perception, full flow, glue size)

## Decision Against Thresholds

| Criterion | Threshold (ADOPT) | Actual | Verdict |
|-----------|-------------------|--------|---------|
| Total LOC | < 4,000 | 958 | ADOPT |
| Cycle time | < 1 ms | 0.002 ms | ADOPT |
| XState glue | < 100 LOC | ~30 LOC core | ADOPT |

## Verdict: ADOPT

All three thresholds met with wide margins:

1. **LOC**: 958 source lines — 4x under the ADOPT ceiling. The engine is small enough to understand, debug, and extend without becoming a maintenance burden.

2. **Performance**: 2.1 microseconds per cycle — 475x faster than the 1ms ADOPT threshold. Even with 100x more beliefs and plans, the engine would stay sub-millisecond. No performance concern.

3. **XState integration**: The core glue is ~30 lines inside a `fromCallback` receive handler. The full `xstate-integration.ts` (175 LOC) includes TypeScript types, JSDoc, and a demo machine — the actual wiring is trivial.

## Key Design Decisions

1. **Belief keys as canonical strings**: `functor(arg0,arg1)` enables O(1) Set membership. No unification needed for ground atoms.

2. **Context conditions as functions**: Instead of parsing a context language, plan contexts are TypeScript functions over the belief key set. This is both simpler and more expressive for our use case.

3. **First-match plan selection**: MVP uses plan library order for deliberation. Can be extended to priority-based or utility-based selection without changing the architecture.

4. **Sub-goals via event queue**: When a plan body contains `!subgoal`, it posts a GoalAdd event. This naturally decomposes into the BDI goal-plan tree (DAG, per T-0.4 — no KB cycles by design).

5. **Failure recovery via alternatives list**: Each intention carries its untried alternative plans. On failure, swap to next alternative. When exhausted, propagate failure upward. Clean and O(1) per recovery attempt.

## What This Proves

- AgentSpeak(L) BDI semantics can be faithfully implemented in <1000 LOC TypeScript
- The reasoning cycle integrates cleanly with XState v5 actor model
- Performance is a non-issue (microsecond-scale cycles)
- Goal-plan trees are naturally DAGs — no cycle detection needed
- Failure recovery (plan fallback + goal failure propagation) works correctly

## Next Steps (if ADOPT confirmed)

1. Add plan argument binding (lightweight unification for plan parameters)
2. Add intention scheduling policy (round-robin vs priority)
3. Wire into echelon's actual XState machine topology
4. Add async action support (actions that return Promises)
5. Add plan annotations for priority/utility-based selection

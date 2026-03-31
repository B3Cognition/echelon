# SP-002: Temporal NEVER Rule Spike Report

**Date**: 2026-03-21
**Status**: Complete
**Verdict**: ADOPT

## Objective

Validate that temporal NEVER rules (specifically "never re-attempt a failed plan within 300 seconds") can be enforced with sub-5ms latency, zero false negatives, and fail-safe defaults.

## Architecture

```
┌─────────────────────────────────────────────────┐
│           Enforcement Actor (XState v5)         │
│                                                 │
│  PLAN_ATTEMPT_REQUESTED ──► Evaluate Rules      │
│                              │                  │
│                   ┌──────────┼──────────┐       │
│                   │          │          │       │
│              Escape Hatch  Rules    Fail-Safe   │
│              (belief hash) Engine   (ADR-004)   │
│                   │          │          │       │
│                   └──────────┼──────────┘       │
│                              │                  │
│                     Temporal Store               │
│                   (append-only log)              │
│                                                 │
│  PLAN_FAILED ──► Record fact + belief hash      │
│  Result ──► ALLOW | DENY                        │
└─────────────────────────────────────────────────┘
```

### Components

| File | Purpose |
|------|---------|
| `temporal-store.ts` | Datahike-style append-only fact store with `query()`, `asOf()`, `since()` |
| `rule-engine.ts` | Rule evaluation with 4-class taxonomy, fail-safe error handling, timeout detection |
| `escape-hatch.ts` | Belief-change detection via DJB2 hash — allows re-attempt when circumstances changed |
| `failure-modes.ts` | ADR-004 fail-safe wrappers: store crash, rule crash, timeout all => DENY |
| `enforcement-actor.ts` | XState v5 machine: idle/evaluating states, integrates all components |

## Test Results

**46 tests, all passing.**

| Suite | Tests | Coverage |
|-------|-------|----------|
| Temporal Store | 13 | assert, query, since, asOf, wildcards, clear |
| Rule Engine | 9 | ALLOW/DENY timing, multi-agent isolation, short-circuit |
| Escape Hatch | 9 | Hash consistency, belief-change detection, window expiry |
| Failure Modes | 5 | Store throws => DENY, rule crashes => DENY, timeout => DENY |
| Enforcement Actor | 10 | Full lifecycle, multi-agent, belief escape, XState integration |

## Performance Measurements

All measurements on Apple Silicon (M-series), Node.js, single-threaded.

### Latency

| Scenario | Median | P99 | Max |
|----------|--------|-----|-----|
| Store query (1000 facts) | 4.4 us | 10 us | — |
| Rule evaluation (isolated) | 1.0 us | 1.3 us | — |
| End-to-end, 1 agent | 9.4 us | 70 us | 772 us |
| End-to-end, 10 agents | 7.9 us | 19 us | 80 us |
| End-to-end, 100 agents | 13 us | 49 us | 367 us |

**All scenarios are well under the 5ms ADOPT threshold.** Even at P99 with 100 simulated agents, latency is 0.049ms — two orders of magnitude below the threshold.

### Memory

At 10,000 facts across 100 agents, the store is lightweight. Each fact is a small JS object (~5 fields). Estimated overhead is under 1MB for 10,000 facts based on object structure (heap measurement is unreliable without `--expose-gc`).

## Decision Against Thresholds

| Criterion | Threshold | Result | Status |
|-----------|-----------|--------|--------|
| Latency at 10 agents | < 5ms | 0.008ms median | PASS |
| Latency at 100 agents | < 20ms | 0.013ms median | PASS |
| False negatives | 0 | 0 (46/46 tests) | PASS |
| Fail-safe on error | DENY | Verified (3 modes) | PASS |

## Key Design Decisions

### 1. Monotonic Clock (performance.now)
Wall-clock (`Date.now()`) is susceptible to NTP jumps and manual adjustments. Using `performance.now()` guarantees monotonically increasing timestamps, eliminating clock-skew failure modes. The clock is injected via interface for testability.

### 2. Append-Only Fact Log
Facts are never modified or deleted — only appended. This mirrors Datahike's immutable temporal model and ensures that historical queries (`asOf`, `since`) are always consistent. Cleanup of old facts can be done as a background sweep without affecting correctness.

### 3. Belief-Change Escape Hatch
A pure time-window NEVER rule is too rigid. If the environment changes (e.g., a door that was locked is now unlocked), the agent should be allowed to retry. We hash the belief subset at failure time and compare on re-attempt. DJB2 hash is sufficient for prototype; production could use SHA-256.

### 4. Fail-Safe Default (ADR-004)
Every failure path returns DENY:
- Store query throws => DENY with diagnostic
- Rule condition throws => DENY with diagnostic
- Evaluation exceeds 50ms => DENY with timeout reason
- No pending request => DENY

### 5. XState v5 Actor
The enforcement logic is encapsulated in an XState machine with two states (idle, evaluating). This aligns with the echelon architecture where all agent coordination flows through state machines. The machine processes events synchronously — rule evaluation is fast enough that async is unnecessary.

## Limitations and Future Work

1. **Linear scan**: `query()` does a linear scan of all facts. For >100K facts, add an index (entity+attribute => fact[]). Current performance is fine for anticipated scale.

2. **No persistence**: In-memory only. For production, back with Datahike or SQLite with WAL for crash recovery.

3. **Single-process**: No distributed enforcement. For multi-process, the temporal store would need to be behind a shared service or use CRDTs.

4. **Belief hash granularity**: Currently hashes ALL beliefs. May want to specify which belief subset is relevant per rule.

5. **Cleanup**: Old facts accumulate. Add a periodic sweep that removes facts older than `2 * windowMs`.

## Verdict: ADOPT

The temporal NEVER rule mechanism meets all ADOPT criteria:
- **Latency**: Sub-100 microsecond median, sub-1ms worst case — far below the 5ms threshold
- **Correctness**: Zero false negatives across 46 test cases covering all edge cases
- **Fail-safe**: All error paths verified to return DENY per ADR-004
- **Escape hatch**: Belief-change mechanism prevents false positives without compromising safety

Recommend integrating into the echelon rule layer as the standard enforcement pattern for all temporal NEVER rules.

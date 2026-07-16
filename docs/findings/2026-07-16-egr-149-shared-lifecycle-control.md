# EGR-149 Shared Lifecycle Control Abstraction

**Review date:** 2026-07-16
**Priority:** P2
**Status:** open
**Horizon:** mid-term refactor after the first-class RE lifecycle stabilizes

## Summary

Echelon exposes the same operator interaction model across three independent
long-running workflows:

- spec `run` / `continue` / `resume`,
- delivery `run` / `continue` / `resume`,
- RE `run` / `continue` / `resume` after the approved first-class RE lifecycle
  change.

Each lifecycle needs safe current-run resolution, state classification,
no-input continuation, typed human-answer capture, reset behavior, blocker
guidance, and terminal summaries. Those semantics are conceptually shared, but
their implementations are or will be lifecycle-specific.

Immediately generalizing the existing two mature controllers while introducing
RE would expand a cost-reduction change into a broad, high-risk refactor. The
correct near-term design is independent controllers with consistent public
semantics. Once the third implementation is real and tested, the duplicated
control-plane behavior should be grounded and extracted.

## Evidence

- `src/echelon/cli.py` contains spec run, continue, resume, active-run
  selection, recovery classification, and escalation handling.
- `src/echelon/cli_app.py` separately declares and forwards the typed spec and
  delivery command surfaces.
- `src/harness/coordinator.py`, `ralph.py`, state helpers, and delivery CLI
  routes own delivery-specific continuation and human-blocker semantics.
- The approved design in
  `docs/superpowers/specs/2026-07-16-first-class-re-lifecycle-design.md`
  intentionally adds a sibling RE coordinator rather than coupling RE to the
  spec controller.
- All three workflows require the same top-level classification: terminal,
  retryable without input, blocked on typed input, recoverable after a bounded
  override, or invalid/corrupt state.

## Required Refactor

After the RE lifecycle has production evidence, derive a small shared
control-plane abstraction from the three concrete implementations. It should
cover only invariant orchestration mechanics:

1. Safe active-run marker resolution and run-kind validation.
2. A typed lifecycle-state classification result.
3. Dispatch of `run`, `continue`, and `resume` actions from that classification.
4. Structured human escalation validation and answer capture.
5. Stable terminal/error summary contracts.
6. Common tests that every lifecycle implementation must satisfy.

Lifecycle-specific work must remain behind adapters:

- spec phase graph, artifact publication, checkpoints, and feature targeting,
- RE fingerprint planning, extraction quality debt, and RE publication,
- delivery strategies, Docker verification, PR review, and landing.

The shared abstraction must not become a generic state machine that erases
domain-specific invariants or forces the three state schemas to become one.

## Sequencing

1. Implement and stabilize the first-class RE lifecycle.
2. Compare real spec, RE, and delivery transition tables and blocker classes.
3. Identify behavior proven identical in all three implementations.
4. Extract the smallest shared interfaces and conformance tests.
5. Migrate one lifecycle at a time, preserving CLI output and persisted-state
   compatibility.

## Candidate Files

- `src/echelon/cli.py`
- `src/echelon/cli_app.py`
- new `src/harness/lifecycle_control.py` or equivalent
- spec state and escalation helpers under `src/harness/`
- `src/harness/coordinator.py`
- first-class RE lifecycle coordinator/state helpers
- focused conformance tests under `tests/unit/`

## Acceptance Criteria

- Spec, RE, and delivery pass one shared run/continue/resume conformance suite.
- Current-run resolution is safe and run-kind-specific for all three.
- Typed human questions and no-input blockers cannot be confused.
- Persisted state remains backward compatible or has an explicit migration.
- Lifecycle-specific planners, controllers, and terminal actions remain
  isolated behind narrow adapters.
- CLI output and exit-code behavior do not regress during migration.

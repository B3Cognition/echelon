# Controller State Contracts Second Fix Wave Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every critical and important final re-review finding with one
immutable routing snapshot, deterministic local-reference cycle rejection, one
complete store-owned transaction namespace, fully canonical agent results, and
a typed fail-closed construction/recovery boundary.

**Architecture:** `SquadStateStore` captures an immutable routing snapshot
under its shared lock immediately after phase execution and before any
controller enrichment. That receipt is the only state source through
enrichment, transition evaluation, COMMANDER prompting, decision sealing, and
recovery; the existing exclusive advance lock performs the final CAS. A
central transaction-namespace module separates externally supplied updates
from store-owned effects. `PreparedPhaseResult` stores a field-by-field
canonical result receipt rather than a copy of an untrusted dataclass.

**Tech Stack:** Python 3.11, jsonschema Draft 2020-12, pytest, Echelon
`SquadController`/`SquadStateStore`/`PreparedPhaseResult`.

## Global Constraints

- Capture exactly one routing snapshot per phase result or recovery attempt.
- Never hold a state-store lock while calling COMMANDER.
- Never reload workflow state to evaluate, seal, or recover a routing decision.
- Reject the final write when phase, revision, or previous-dispatch identity
  differs from the snapshot.
- Do not emit stale conflict diagnostics or any product, timing, checkpoint, or
  advance side effect after decision construction fails.
- Reject all externally supplied store-owned transaction keys, including
  manual-run, identity, status, diagnostic, and history fields.
- Do not invoke arbitrary copy, representation, conversion, mapping, or path
  protocols while detaching an untrusted `SquadAgentResult`.
- Preserve valid unchanged-state self-loops and current transition
  action/effect semantics.

---

### Task 1: Deterministic Local `$ref` Cycles and Central Transaction Namespace

**Files:**
- Modify: `src/harness/controller_state_contracts.py`
- Create: `src/harness/state_transaction_namespace.py`
- Modify: `src/harness/prepared_phase_result.py`
- Modify: `src/harness/squad_state.py`
- Modify: `tests/kernel/test_controller_state_contracts.py`
- Modify: `tests/kernel/test_prepared_phase_result.py`
- Modify: `tests/kernel/test_squad_state.py`

**Interfaces:**
- Produces:
  - `STORE_OWNED_TRANSACTION_KEYS: frozenset[str]`
  - `reject_store_owned_updates(updates, *, owner, error_factory)`
  - deterministic local `$ref` graph validation before validator construction
- Consumes: existing strict registry loader and prepared-result factories.

- [x] Add RED tests for direct and indirect local-reference cycles, a valid
  acyclic chain, and an exhaustive provider/controller/judgment ownership
  matrix covering phase, revision, dispatch, completion, manual-run, skip,
  status, diagnostic, and history identities.
- [x] Run the focused tests and record the expected failures.
- [x] Implement a sorted local-reference dependency graph and DFS cycle check.
  Error text must include a stable pointer chain such as
  `#/$defs/a -> #/$defs/b -> #/$defs/a`.
- [x] Define the complete store-owned namespace once and import it at every
  external update boundary. Keep internal transaction effects in a distinct
  trusted channel rather than weakening the external checks.
- [x] Run the focused tests and commit the schema/namespace slice.

### Task 2: Canonical `SquadAgentResult` Receipt

**Files:**
- Modify: `src/harness/prepared_phase_result.py`
- Modify: `tests/kernel/test_prepared_phase_result.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces:
  - exact-type, bounded field validation for every `SquadAgentResult` field
  - a frozen internal canonical result representation
  - field-by-field safe reconstruction from that canonical representation
- Consumes: the central transaction namespace from Task 1.

- [x] Add RED tests whose `raw_output`, `duration_ms`, boolean flags, token
  details, and provider metadata contain hostile subclasses or objects with
  exploding `__deepcopy__`, `__repr__`, conversion, or mapping hooks.
- [x] Assert rejection is typed, redacted, bounded, and occurs before routing;
  mutate every accepted source field after preparation and assert the sealed
  result is unchanged.
- [x] Run the focused tests and record the expected failures.
- [x] Replace generic dataclass `deepcopy`/`replace` storage with exact
  field-by-field canonicalization. Permit only documented exact scalar and
  bounded container forms; reconstruct a fresh `SquadAgentResult` without
  consulting the original object.
- [x] Make attestation hash the canonical representation only and remove
  arbitrary mapping/object/repr fallbacks from the attestation path.
- [x] Run the focused tests and commit the canonical-receipt slice.

### Task 3: One Immutable Routing Snapshot

**Files:**
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/kernel/test_squad_state.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_squad_phase_checkpoints.py`

**Interfaces:**
- Produces:
  - `RoutingStateSnapshot` containing detached state, phase, revision, and
    previous-dispatch digest
  - `SquadStateStore.capture_routing_snapshot(...)`
  - snapshot-bound `prepare_routing_decision(...)`
- Consumes: canonical prepared results and the store-owned namespace.

- [x] Add RED regressions that mutate state between snapshot evaluation and
  sealing, advance recovery state while COMMANDER runs, and exercise a valid
  unchanged-state self-loop.
- [x] Assert stale attempts create no decision, diagnostic, product update,
  advance, successful timing, or checkpoint side effect.
- [x] Run the focused tests and record the expected failures.
- [x] Capture the snapshot once, immediately after the executor result and
  before enrichment. Thread it through preparation, WHY coordination,
  transition evaluation, COMMANDER prompt construction, sealing, and advance.
- [x] Change state reads in those paths to detached snapshot reads. Pass the
  snapshot to the final exclusive-lock CAS and require exact phase, revision,
  and previous-dispatch equality.
- [x] For COMMANDER usage accounting, stage usage in controller memory while a
  routing snapshot is active and merge it only through the successful
  transaction. On construction failure, merge it only with a snapshot-matching
  failure mutation; on a stale snapshot, use a separate accounting-only atomic
  mutation that cannot rebase or bless the route.
- [x] Run the focused tests and commit the routing-snapshot slice.

### Task 4: Typed Construction and Recovery Failure Boundary

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_squad_phase_checkpoints.py`

**Interfaces:**
- Produces:
  - one redacted routing-construction failure handler for ordinary, manual,
    skip, and recovery paths
  - revision-aware compare-and-set diagnostic merge
- Consumes: `RoutingStateSnapshot` from Task 3.

- [x] Add RED tests for transition sealing and recovery synthesis/sealing
  conflicts, including concurrent same-phase revision changes.
- [x] Assert the boundary catches both
  `ControllerStateContractViolation` and `StateAdvanceError`, emits only a
  stable redacted diagnostic when its snapshot still matches, and emits
  nothing when stale.
- [x] Assert product-input mutation is ordered after successful decision
  construction and that failed construction records no timing/checkpoint or
  advance side effects.
- [x] Run the focused tests and record the expected failures.
- [x] Route ordinary, manual, skip, and recovery construction through the same
  typed handler. Make diagnostic merge compare phase, revision, and dispatch
  digest under lock.
- [x] Construct and seal the decision before product-input effects, then apply
  the already-sealed decision using the existing action/effect ordering.
- [x] Run the focused tests and commit the failure-boundary slice.

### Task 5: Report and Verification

**Files:**
- Append: `.superpowers/sdd/final-fix-report.md`
- Modify only if required by behavior changes:
  `docs/superpowers/specs/2026-07-23-controller-state-contracts-design.md`

- [x] Run focused boundary suites:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_controller_state_contracts.py \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_squad_state.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py
```

- [x] Run static and compile checks:

```bash
.venv/bin/ruff check src/harness tests/kernel tests/integration tests/unit
.venv/bin/python -m compileall -q src tests
```

- [x] Run workflow dry-run validation using the repository's existing dry-run
  test target or command documented by the first-wave report.
- [x] Run the full test suite and capture exact pass/skip/deselection counts.
- [x] Append a dedicated second-wave report mapping every finding to tests,
  implementation, and verification evidence.
- [x] Commit documentation/report changes, confirm `git status --short` is
  empty, and return commits, tests, remaining concerns, and report location.

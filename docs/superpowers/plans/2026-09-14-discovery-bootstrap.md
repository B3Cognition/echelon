# Discovery Bootstrap Checkpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for approved inline execution; obtain independent read-only review before the checkpoint commit.

**Goal:** Durably select and recover fresh managed discovery enrollment before reservations or model dispatch.

**Architecture:** Extend the existing SquadStateStore with protected bootstrap metadata and three narrow transitions. An inactive bootstrap helper captures sources through an existing sealed inspection transaction and calls the existing source/genesis registration APIs. The existing execution leases remain caller-owned; the legacy admission guard rejects pending bootstrap metadata.

**Tech Stack:** Python, pytest, SquadStateStore, captured source manifests and existing SQLite identity authority.

**Spec:** `docs/superpowers/specs/2026-09-14-managed-discovery-integration-design.md` (approved); continues `2026-09-14-discovery-reservation-binding.md`.

## Global Constraints

- No provider execution, reservation allocation, candidate publication, completion, public selector or default activation.
- Existing initialized workspace authority is required; bootstrap enrolls a fresh spec, never initializes/reconstructs a missing workspace registry.
- Source capture, registration retry IDs and the selected operation are saved before registration. Original empty selected spec and exact retained namespace are required.
- Existing Phase A and selected-run leases must surround bootstrap, as they will at the Squad integration owner. This helper does not create a second controller or nested lease loop.
- No change to Claude/Codex, neutral prose, modes, legacy build, AGENTS.md/CLAUDE.md or the stopped game workspace.
- No live calls, installation, migration, push or merge.
- This slice captures only the selected fresh spec tree. Runtime admission still must establish the absence of unsupported RE/external-memory domains and bind additional context before any provider dispatch.

## Task 1 — Protected selection in the existing state owner

**Files:** Create `src/harness/discovery_bootstrap_state.py`, `tests/unit/test_discovery_bootstrap.py`; modify `src/harness/squad_state.py` and `src/harness/element_identity_legacy_guard.py`.

**Interfaces:** A closed `managed_discovery_bootstrap` record has integer version 1, `selection` and nullable canonical `source_manifest`. Selection binds exact spec/run/operation, project/run paths, namespace UUIDs, spec-relative path and sealed capture marker. Source-context, source-registration and genesis-registration IDs derive deterministically from that immutable selection. Pure validators enforce the record and its association with ordinary state and final `managed_identity` metadata.

State methods return confirmed durable state:

```python
state_store.prepare_discovery_bootstrap(selection)
state_store.capture_discovery_bootstrap(selection, manifest.payload)
state_store.complete_discovery_bootstrap(selection, genesis)
```

- [x] Add RED tests showing ordinary save cannot inject, remove or alter bootstrap metadata; state load rejects malformed/cross-run records; reset cannot silently lose a selected bootstrap; source capture is single-assignment; genesis completion requires exact selected namespace/source and captured manifest. Exact retries preserve state revision and unrelated counters/mode.
- [x] Implement pure validation and the three locked state transitions using `_save_unlocked` and `_confirm_durable_state_unlocked`. Protect the field in normal load/save paths, without putting registry/source I/O into the state owner.
- [x] Extend existing negative legacy admission to block the presence of bootstrap metadata, including malformed metadata and before registry enrollment. Add RED regression for this admission boundary.
- [x] Run new tests, existing managed state/legacy admission and SquadStateStore regressions.

## Task 2 — Recover registration through existing source and authority APIs

**Files:** Create `src/harness/discovery_bootstrap.py`; extend `tests/unit/test_discovery_bootstrap.py`.

**Interface:** `bootstrap_discovery(project_root, state_store, *, spec_id, run_id, operation_id, spec_path, capture_marker, create=False) -> dict[str, str]`. Explicit creation saves selection; resume requires existing matching metadata. The helper opens existing authority, reloads the exact sealed capture with `load_prepared_publication`, requires no publication operations, and captures only `(spec_path,)` through `inspect_sources`. Caller holds execution leases. Completed bootstrap recovery still checks the original empty source; later accepted discovery publication uses managed-context authentication, not bootstrap replay.

- [x] Add real temporary workspace fixtures with initialized Squad state, authority, empty spec, sealed empty transaction and actual execution leases. Observe missing helper RED before implementation.

```python
record = bootstrap_discovery(root, state_store, spec_id="game", run_id="first",
    operation_id="discovery", spec_path="specs/game", capture_marker=marker, create=True)
assert state_store.load()["managed_identity"] == record
assert store.managed_identity(spec_id="game") == record
```

- [x] Save capture before source registration, register source before genesis, then bind exact genesis through the state owner. Replay matching source/genesis writes after unknown completion; once state claims completion authenticate read-only instead of rebuilding missing receipts.
- [x] Inject interruptions before/after selection/capture/final state persistence and both real database registrations. Resume with the same selected IDs and assert exactly one retained source/genesis operation, no entities or reservations, unchanged source files/counters/mode, and legacy entry blocked from first saved selection.
- [x] Test changed source bytes/tree, nonempty/missing spec, wrong selected run/spec/operation/path/marker, registry replacement/loss, absent or corrupt bootstrap metadata, invalid pending state and source/genesis conflicts. All must block before allocation or dispatch; no filesystem reconstruction or guessed source maxima.
- [x] Feed the completed durable state into the existing reservation journal, proving genesis precedes real reservation and resume preserves exact IDs. This is component composition, not real Squad activation.

## Task 3 — Review, verification and commit

- [x] Independent read-only review of the diff against this checkpoint and parent design; fix demonstrated defects with RED regressions.
- [x] Run bootstrap/reservation/managed/source/legacy/state/durable-writer regressions and `git diff --check`. Record exact receipts and limitations in this plan and existing convergence/deferred records.
- [x] Commit on the existing worktree branch. Keep provider-turn recovery/accounting and Squad publication/admission as remaining work; do not close or merge the branch.

## Checkpoint receipts

Baseline reservation/managed-context checks passed **103 tests in 9.79s**.
The initial 18 REDs demonstrated missing owned transitions and unprotected
generic state writes/loads. After implementation they passed. The next 21 REDs
identified the missing bootstrap helper; the real enrollment/recovery path then
passed those tests. Additional state/source/authority and real Squad entry cases
expanded the final bootstrap suite to **63 tests**.

Independent read-only review found one Important defect: completing state inside
`inspect_sources` preceded its mandatory post-yield validation. Two RED tests
injected source drift after each real database registration and reproduced a
false completed state. Completion now follows successful inspection exit. These
tests confirm captured state survives the failure, no completion is recorded,
source drift remains blocking and restoring the test source permits exact
idempotent recovery without changing database rows. The reviewer rechecked the
fix and reported no remaining findings.

Final affected batch: **848 tests passed in 34.08s**:

```sh
python -m pytest tests/unit/test_discovery_bootstrap.py tests/unit/test_discovery_reservations.py tests/unit/test_element_identity_managed.py tests/unit/test_element_identity_managed_context.py tests/unit/test_element_identity_source_store.py tests/unit/test_element_identity_state.py tests/unit/test_element_identity_legacy_guard.py tests/unit/test_durable_json.py tests/unit/test_controller_lock_order.py tests/kernel/test_squad_state.py -q
```

Existing negative runtime and cross-owner regressions: **397 tests passed in
184.31s**:

```sh
python -m pytest tests/unit/test_squad_identity_exclusion.py tests/unit/test_managed_spec_memory_exclusion.py tests/unit/test_managed_projection_write_exclusion.py tests/unit/test_managed_retarget_rewind_exclusion.py -q
```

`git diff --check` passed. During test expansion, misplaced assertions from the
preceding test caused six failures; their placement was corrected, with no
production change. The final real Squad entry tests use the actual workflow
graph and prove pending selection blocks both entry points in all three modes.
Positive discovery runtime, provider recovery and full dependency-domain admission
remain deliberately outside this inactive checkpoint.

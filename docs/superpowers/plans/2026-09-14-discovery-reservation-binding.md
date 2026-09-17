# Discovery Reservation Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the user's selected inline execution. Obtain an independent read-only review before committing this checkpoint.

**Goal:** Retain exact proposal-key/subject/ID associations through allocation crashes and subsequent discovery proposals, without activating discovery.

**Architecture:** A selected-run reservation journal uses the existing durable writer and existing SQLite allocator. It authenticates an already registered managed genesis and retained source context; it neither enrolls a spec nor edits Squad state. A narrow read-only reservation lookup verifies completed receipts without recreating missing authority.

**Tech Stack:** Python, pytest, existing SQLite identity authority and descriptor-safe durable file helpers.

**Spec:** `docs/superpowers/specs/2026-09-14-managed-discovery-integration-design.md`.

## Global Constraints

- U/A creation and same-subject revision only; six-digit minimum and no ordinal digit cap.
- No second allocator, provider-specific prose, placeholder substitution or Markdown renumbering.
- No runtime activation, enrollment, provider calls, publication or completion in this checkpoint.
- No edits to AGENTS.md, CLAUDE.md, legacy build, modes/defaults or the stopped smoke workspace.
- No installation, migration, push or merge.
- Caller must hold existing execution leases and durably select this operation before initialization. Resume explicitly requires its journal; missing recovery material never initializes itself.
- This journal retains associations, not provider attempts or semantic approval. The following provider checkpoint must persist attempts before dispatch and bind these receipts to its own selected operation. Three proposal receipts are a defensive upper bound, not a substitute for that attempt budget.

## Task 1 — Read retained reservations without allocation

**Files:** Modify `src/harness/element_identity_store.py`; create `tests/unit/test_discovery_reservations.py`.

**Interface:** `IdentityStore.reservation(*, spec_id: str, kind: str, operation_id: str, count: int) -> tuple[str, ...] | None`. Return `None` only when both exact operation and range are absent; conflicting arguments, orphan rows and damaged counters fail. Reuse existing transaction, digest, high-water and reservation validators.

- [x] Add real-store tests for absence without allocation, matching retained ranges, argument conflicts and missing/corrupt rows. Snapshot SQLite rows before/after reads. Test wide ordinals through the existing decimal-string allocator.

```python
assert store.reservation(spec_id="game", kind="U", operation_id="r", count=1) is None
assert store.reserve(spec_id="game", kind="U", operation_id="r", count=1) == ("U-000001",)
assert store.reservation(spec_id="game", kind="U", operation_id="r", count=1) == ("U-000001",)
```

- [x] Run `python -m pytest tests/unit/test_discovery_reservations.py -q`; observe the missing read API failure before implementing.
- [x] Implement the bounded read, using `PRAGMA query_only=ON`; never call `reserve` from this read.
- [x] Run the new suite and `tests/unit/test_element_identity_store.py`.

## Task 2 — Persist intent and exact associations

**Files:** Create `src/harness/discovery_reservations.py`; extend `tests/unit/test_discovery_reservations.py`.

**Interface:** `DiscoveryReservationJournal(run_dir)` is a context manager owning its no-follow run-local lock. `select(store, *, spec_id, run_id, operation_id, managed_identity, create=False)` authenticates genesis/source and loads an exact selection; explicit creation requires no existing journal. `bind(assignment, reply) -> tuple[DiscoveryReservation, ...]` returns only the current proposal's mappings after all results are durable. It exposes no publication or provider API.

- [x] Add RED cases using real managed genesis, source manifests and SQLite. Assert the first mapping produces `A-000001` and sorted `U-000001`/`U-000002`, survives reopen, and leaves entity/history state unchanged. Inject interruption immediately before/after actual allocator commit and before/after durable mapping writes. Assert resume preserves the same mapping and next ordinal.
- [x] Implement strict bounded checksummed JSON with existing `write_text_atomic`, selected-directory identity checks and compare-before-replace. Save canonical validated proposal plus per-kind intent before any allocator call. Each intent binds selected operation, proposal digest and sorted unseen keys; derive a stable retry operation ID from those values. Save exact results before returning.

```python
with DiscoveryReservationJournal(run) as journal:
    journal.select(store, spec_id="game", run_id="first", operation_id="discovery",
                   managed_identity=genesis, create=True)
    mappings = journal.bind(assignment, proposal)
assert mappings[0].key == "camera"
```

- [x] Add RED recovery/admission cases: missing journal, changed selected spec/run/operation/genesis/source, wrong assignment, malformed JSON/checksum/schema, symlink/hardlink/replaced directory, conflicting proposal for an existing dispatch, incomplete earlier reservation, forged completed mapping and missing completed database receipt. Failed admission must not allocate.
- [x] Add RED repair-association cases: reordered proposal replay; a new dispatch reuses unchanged keys; changed subject/kind/caption rejects; a removed then reintroduced key retains its ID; new keys allocate only new ranges; a fourth distinct proposal blocks. Neither reorder nor input-hash changes erase retained associations.
- [x] Run all new tests and existing semantic/candidate/managed/store/durable writer suites. Feed recovered mappings into the actual candidate translator and coherent preview; assert no accepted source/history publication.

## Task 3 — Review and checkpoint

- [x] Independently review diff against this plan and approved design. Fix demonstrated defects with RED regressions.
- [x] Run affected suites and `git diff --check`; record exact results in this plan and convergence boundary.
- [x] Commit the tested checkpoint on the existing branch. Do not push, merge or finish the development branch.

## Remaining approved connections

Managed bootstrap/selected state, bounded provider-turn receipts/accounting and semantic execution follow this reservation checkpoint. Guarded Squad publication/completion and targeted repair integration follow those. This plan implements only the reservation boundary of the approved durable checkpoint, not the entire runtime design.

## Verification and review receipts

The missing read API produced 14 RED failures before its implementation. The
first journal batch then produced 21 missing-module failures with those 14 tests
passing. The completed new suite passed 63 tests in 6.49s. This includes actual
source-head advancement through existing guarded publication; its initial test
setup incorrectly held the inspection lock during publication, was interrupted,
and was corrected to the existing inspect-then-publish sequence. No production
publication behavior was changed.

The final affected batch passed **613 tests in 41.45s**:

```sh
python -m pytest tests/unit/test_discovery_reservations.py tests/unit/test_element_identity_store.py tests/unit/test_element_identity_managed.py tests/unit/test_element_identity_managed_context.py tests/unit/test_discovery_semantics.py tests/unit/test_discovery_candidate.py tests/unit/test_discovery_identity_candidate.py tests/unit/test_element_identity_candidate_preview.py tests/unit/test_identity_graph_publication_composition.py tests/unit/test_durable_json.py -q
```

Independent read-only review reported no Critical/Important/Minor defects and
independently passed 155 reservation/store tests plus all four subsequently
added source-head/missing-database/empty-proposal cases. `git diff --check` passed.
No provider calls, bootstrap, controller activation or accepted publication were
performed outside temporary test fixtures. The existing branch/worktree remains
in place for the next durable integration slice.

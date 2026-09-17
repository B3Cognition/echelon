# Identity lifecycle transaction composition implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow the existing lifecycle writer and reference/issue binding writers to participate in one caller-owned transaction without duplicating persistence rules or changing public lifecycle behavior.

**Architecture:** Move the existing lifecycle persistence operation into its existing connection-owned lifecycle module; keep the public API as its validated transaction owner. This is the small prerequisite for atomic historical reconciliation and publication finalization, not a new publication path or a claim that either integration exists.

**Tech Stack:** Existing Python/SQLite lifecycle and binding modules; real-transaction pytest tests. No dependency/schema changes.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- Failed or abandoned reservations leave gaps; numbers are never recycled.
- A stable ID does not authorize arbitrary subject changes: updates require the controller's edit scope and semantic review.
- Historical evidence is retained, not relabeled as proof of the new content.
- No allocation/import changes, schema change, publication path, provider routing, automatic historical reconciliation or activation in this task.

---

### Task 1: shared connection-owned lifecycle persistence

**Files:** Modify `src/harness/element_identity_lifecycle_store.py` and `src/harness/element_identity_store.py`; create `tests/unit/test_element_identity_transaction_composition.py`; add a short integration-boundary note to `docs/element-identity-storage.md`. The new test module has `pytestmark = pytest.mark.unit`. Do not modify schema, allocator/import algorithms, binding algorithms, candidate rules or controller/publication code.

**Interfaces:**

```python
# harness.element_identity_lifecycle_store
def apply_changes(connection, store, spec_id, operation_id, changes):
    """Apply a validated lifecycle operation in the caller's active transaction."""
```

Return the existing `tuple[dict, ...]` lifecycle receipt with exactly unchanged keys, ordering, lineage associations and digest representation. This is an internal connection-owned operation, not a new public store API. Require an already active transaction (`connection.in_transaction`); reject a connection without one before any SQL write. Never open another connection, begin/commit/rollback a transaction, run provider/filesystem work, or call public store methods. Validate spec/operation identifiers using the existing validator, and normalize/revalidate through `lifecycle.request` inside this function so direct internal callers cannot bind an unrelated payload to changes. Reuse the existing high-water checks, `_operation`, `_receipt`, `plan_changes`, `_lineage`, and canonical JSON/digest helpers. Do not write a second lifecycle algorithm or planner.

Move, rather than duplicate, the existing `IdentityStore.apply_lifecycle` SQL insertion/receipt body into this helper. Keep exact idempotency: same operation ID/method/spec/request returns its original authenticated receipt before re-planning against now-advanced heads. Different arguments or method reuse reject atomically. Counter/history corruption checks still run before honoring a retry as they do today. Keep entity/revision/head/lineage insert ordering and receipt serialization unchanged.

The caller owns an authenticated authority transaction and must let any helper or downstream binding failure abort that whole transaction; it must not swallow an error and commit partial rows. Do not add independent savepoint/rollback ownership inside this helper. Document this internal integration contract alongside the no-nested-public-API boundary.

The public wrapper retains its `_public` exception boundary and validates identifiers and snapshots `lifecycle.request(changes)[0]` before opening the existing single write transaction, then delegates to the helper. Calling the same pure request validator again inside the internal helper is intentional boundary validation, not copied validation logic. It prevents a direct transaction composer from bypassing the contract while preserving the public invalid-input-before-transaction behavior. Public preview and both candidate checks remain read-only and continue sharing `plan_changes`.

**First regression, before production edits:**

```python
def test_lifecycle_and_reference_binding_rollback_together(tmp_path):
    from contextlib import closing
    import hashlib
    import sqlite3
    import pytest
    from harness import element_identity_binding_store as binding_store
    from harness import element_identity_bindings as bindings
    from harness import element_identity_lifecycle_store as lifecycle_store
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    create = ElementCreate(label, "Scene", "Scene body", "reserve")
    claim = bindings.ReferenceClaim("evidence.md", hashlib.sha256(b"source").hexdigest(),
                                    "span:0:6", label, "1", "evidence")
    database = tmp_path / ".echelon/identity/registry.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        before = tuple(connection.iterdump())
    with pytest.raises(RuntimeError, match="injected after both effects"):
        with store._transaction(write=True) as connection:
            lifecycle_store.apply_changes(connection, store, "demo", "create", (create,))
            rows = binding_store.record(connection, store, "reference_claims", "demo", "bind",
                                         bindings.request((claim,), bindings.ReferenceClaim))
            assert rows[0]["target_revision"] == "1"
            assert connection.in_transaction
            raise RuntimeError("injected after both effects")
    with closing(sqlite3.connect(database)) as connection:
        assert tuple(connection.iterdump()) == before
    assert store.lookup(spec_id="demo", element_id=label) is None
    assert store.high_water(spec_id="demo", kind="FR") == "1"
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_identity_transaction_composition.py -q`, retain actual missing-helper RED before the extraction. The test must fail at the missing helper, not before reaching a real initialized authority/reservation.
- [ ] Extract the single lifecycle persistence path and delegate from the existing public wrapper as specified. Keep imports safe for a fresh interpreter and the existing module import cycle; do not move unrelated store helpers.
- [ ] Add real caller-owned transaction tests for successful lifecycle-plus-reference and lifecycle-plus-issue-occurrence commit; inspect both through the existing public readers after commit, compare all immutable receipts, and run explicit audit successfully. Assert no writer commits early by checking `connection.in_transaction` and a separate already-open read connection cannot observe uncommitted effects. Caller rollback and a downstream binding validation failure must preserve the full SQL prestate, including operation/receipt tables; reserved gaps remain reserved.
- [ ] Cover multiple lifecycle operations in one caller transaction using distinct globally bound operation IDs, followed by bindings to the corresponding materialized revisions. Retry each original operation after later revisions/retirement and confirm the exact original receipt without extra rows. Conflicting method/spec/payload reuse rejects; stale revisions, illegal subject changes, duplicate labels and damaged counters keep their existing failures and full transaction rollback.
- [ ] Prove `apply_changes` rejects an autocommit connection before creating operation rows. Prove a query-only transaction cannot write. Use real SQLite transaction tracing or narrowly wrapped connection creation to assert the helper does not open a nested store transaction or commit/rollback; do not replace planner/store success with mocks. Include public invalid-input validation before transaction entry as a compatibility check.
- [ ] Run the new tests with `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_preview.py`, `tests/unit/test_element_identity_bindings.py`, `tests/unit/test_element_identity_admin.py`, `tests/unit/test_discovery_identity_candidate.py`, `tests/unit/test_definition_identity_candidate.py`, and `tests/unit/test_issue_identity_candidate.py`, using the checkout virtualenv Python above. Do not run the repository-wide or million-record suite; allocation/import/index paths are unchanged by this extraction.
- [ ] Self-review original versus extracted SQL/receipt semantics, run `git diff --check`, and document that transaction composition does not itself authenticate historical sources, semantic decisions, canonical files or graph completion. Commit only task files and retain complete commands/RED/GREEN evidence and concerns in the ignored task report.

## Following work

Atomic authenticated historical reconciliation and durable publication intent/finalization must call these existing connection-owned writers from their own short authority transaction. They still need explicit source bindings, conflict decisions, pending-write protection, canonical promotion recovery, semantic review and required graph/completion receipts. This refactor does not authorize partial integration or a live workflow.

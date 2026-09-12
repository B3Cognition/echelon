# Durable element identity allocation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the durable allocation foundation of phase 2, independently testable before producer integration.

**Architecture:** One explicit workspace-owned SQLite authority with transactional counters, idempotent reservations, immutable imported identities, and safe backups. The store is a library, not an alternate workflow controller; lifecycle, artifact promotion and producer routing integrate in subsequent plans.

**Tech Stack:** Python standard library sqlite3, hashlib, json, uuid, pathlib; pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- New labels use a minimum width of six decimal digits.
- Six is a minimum display width, not a storage width or maximum value.
- Persist counters as decimal strings and use Python integer arithmetic; IDs travel as strings.
- Never recycle a reservation, reset counters on reopen/rewind, or regenerate a missing established ledger from current document maxima.
- Preserve legacy labels and reserve their numeric ordinals; opaque composite IDs are not heuristically renumbered.
- No dependencies, global installation, stopped smoke-run mutation, main-branch edits, or automatic feature activation.
- Workdir is the existing delivery-controller-contract worktree. Test interpreter is `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python`.

## Task 1: transactional allocation authority

**Files:**
- Create `src/harness/element_identity_store.py`.
- Create `tests/unit/test_element_identity_store.py` and `tests/integration/test_element_identity_store.py`.
- Create `docs/element-identity-storage.md` documenting the library's authority, restore boundaries, and the fact that it is not yet wired into producers.
- Consume `src/kernel/element_ids.py` from numeric compatibility; do not modify unrelated producers in this task.

**Interfaces:**
- `IdentityStoreError(ValueError)` is the fail-closed public error.
- `IdentityStore.initialize(workspace: Path) -> IdentityStore`: explicitly create a fresh authority at `.echelon/identity`, fail if any existing authority state exists. Create an authority marker with version, workspace UUID and epoch UUID, plus `registry.sqlite3`; protect sensitive state with owner-only file permissions. An incomplete initialization blocks subsequent opens/initialization instead of silently starting over.
- `IdentityStore.open(workspace: Path) -> IdentityStore`: require both marker and database; use SQLite `mode=rw` to prevent implicit creation. Validate schema version, marker/database identity match, and required schema. Reject symlinked authority components and unreadable or malformed state. Do not scan every entity on each open.
- `reserve(*, spec_id: str, kind: str, operation_id: str, count: int) -> tuple[str, ...]`: one transaction, idempotent on the full argument set; operation IDs are unique within the authority and conflicting reuse fails. Kinds initially supported: AC, FR, NFR, ISS, U, A, T. Reject blank identifiers, bool/noninteger/nonpositive counts, and invalid kinds. Return controller-reserved IDs in increasing order. No arbitrary numeric ordinal ceiling.
- `import_identities(*, spec_id: str, operation_id: str, definitions: Sequence[tuple[str, str]]) -> None`: each pair is exact legacy label and immutable subject string. Import is atomic and retry-safe, establishes subject bindings and raises the type high-water marks. An existing label with a different subject or an equivalent numeric ordinal under different padding fails; same exact definition can be reused by a subsequent import. Duplicate labels within one request fail. Reject a numeric import whose ordinal falls in an existing reservation even if it has not yet been materialized. Subject-changing lifecycle operations are not supported by this task.
- `lookup(*, spec_id: str, element_id: str) -> dict | None`: return a copied identity record, including exact original label and subject. Reserved IDs are not created entities.
- `high_water(*, spec_id: str, kind: str) -> str`: canonical decimal high-water value; zero before allocation/import.
- `backup(destination: Path) -> None`: SQLite online backup plus bound authority metadata in a fresh dedicated backup directory, no overwrite. Include all allocations and imported identity state; use a completed manifest with database digest to distinguish complete backup from crash debris. Use a consistent database snapshot and bound identity, never separate unsynchronized table exports.
- `IdentityStore.restore(workspace: Path, backup: Path) -> IdentityStore`: verify completed backup, digest, schema and authority identity before creating an empty destination authority; no merge or overwrite. Restores exact workspace identity/epoch and reservations. A destination with existing marker or database fails. Document that independently advancing restored copies must not be merged as one allocation authority.

Connections should be short-lived per operation or explicitly closed; avoid process-global connections so separate processes use the same authority correctly. Use `BEGIN IMMEDIATE`, a bounded busy timeout, parameterized statements, rollback on failures, and durable SQLite settings. Counter text must be canonical positive/zero decimal, never SQLite CAST or floating point. Reservation rows may store contiguous ranges plus request digests instead of one row per reserved ID; collision checks must remain indexed by namespace/type. Imported entities have an indexed numeric ordinal where applicable, represented without precision loss. Restrict lexical forms to recognized kind prefixes while preserving legacy composite suffixes as opaque identities.

- [ ] Write tests before implementation. Public examples and literal expectations:

```python
store = IdentityStore.initialize(tmp_path)
assert store.reserve(spec_id="001-demo", kind="AC", operation_id="dispatch-1", count=2) == ("AC-000001", "AC-000002")
reopened = IdentityStore.open(tmp_path)
assert reopened.reserve(spec_id="001-demo", kind="AC", operation_id="dispatch-1", count=2) == ("AC-000001", "AC-000002")
assert reopened.reserve(spec_id="001-demo", kind="AC", operation_id="dispatch-2", count=1) == ("AC-000003",)
```

Test conflicting operation reuse across count, kind and spec; independently scoped counters; preserved FR-001 import followed by FR-000002 allocation; conflicting FR-000001 import; changed imported subject; abandoned reservation; opaque legacy labels; rollback of a mixed valid/conflicting import; delete or corrupt a known database and prove open does not reset; missing marker; mismatched marker/database; symlink escapes; backup/restore retains reservation retry and high-water history; malformed backups cannot create a destination authority.

- [ ] Run RED and record failing behavior. New API import failures establish missing module only; add behavior assertions for all contracts before green implementation.

- [ ] Implement the public interfaces with a small indexed schema. Store reservation operation digests and bound full arguments; reconstruct results from stored range so retry needs no new IDs. A representative transaction is:

```python
connection.execute("BEGIN IMMEDIATE")
existing = connection.execute("SELECT digest, first_ordinal, count FROM reservations WHERE operation_id = ?", (operation_id,)).fetchone()
# Validate existing digest and return its range, or advance the namespace counter
# and insert a reservation within the same transaction before committing.
```

The statement is a transaction pattern, not permission to omit validation or durability. Factor path checks and schema validation rather than repeating them at each API boundary. Translate sqlite and filesystem errors to IdentityStoreError with actionable context and no credentials.

- [ ] Run real multiprocessing contention tests (separate processes reserve distinct batches; union has no duplicates), process termination after a committed reservation followed by retry, and a numeric boundary test importing AC-999999 before allocating AC-1000000. Also test an ordinal larger than signed 64-bit to prove the TEXT storage contract.
- [ ] Add a marked integration capacity test that imports a million distinct identities in bounded batches and then allocates without scanning the table. Assert correctness and use SQLite query plans for the indexed lookup; record measured elapsed time and storage size without brittle timing thresholds. Keep this large test out of the default unit suite.
- [ ] Run all new unit and integration tests plus `tests/unit/test_element_ids.py`; record exact commands and results. Self-review backup atomicity, marker integrity, rollback, path safety and transaction ownership. Commit only task files and write the full report for independent review.

## Following work

This store intentionally does not activate identity-managed specs. The following plan adds content revisions, retire/replace/split/merge lineage, reference and publication receipts, then integrates producer-facing reservations and targeted repair. Until that integration exists, ordinary authoring remains legacy and no live smoke retry is warranted.

# Revision-bound reference and issue occurrence implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Retain reference claims and review occurrences against exact historical entity revisions without treating either as semantic verification.

**Architecture:** Add immutable claim records to the existing SQLite authority and reuse its global operation IDs, transactions, lifecycle reads, backup and explicit migration. A reference claim records source provenance and the target revision assessed by its author; a current revision match is not a passing review. Issue occurrences point to a durable ISS entity revision while preserving the existing fingerprint guard. This foundation remains inactive until controller publication binds and authorizes these records.

**Tech Stack:** Python standard library, existing SQLite authority, existing `issue_identity.issue_fingerprint`, pytest. No new dependency or allocator.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Preserve exact published labels, historical content, and lifecycle lineage. Never rebind retained evidence to the current revision automatically.
- A stored reference claim is not semantic verification. A current target-revision match alone must not expose a `verified` or `passed` verdict.
- Issue identity does not replace the existing fingerprint-based resolution guard. Changed evidence or repair obligations cannot inherit a closed resolution from a stable display label alone.
- Use the existing workspace authority and global operation-ID namespace. No separate JSON ledger, counter, or controller.
- No canonical publication, graph/memory writes, provider routing, or live activation in this foundation task.

---

### Task 1: immutable source claims and persistent issue occurrences

**Files:** Create `src/harness/element_identity_bindings.py` for immutable request types and pure validation; extend `src/harness/element_identity_schema.py` for additive schema 3 and exact schema 1/2 upgrade recognition; extend `src/harness/element_identity_store.py` with transaction-owned record/read/audit APIs, factoring connection-owned binding queries into `src/harness/element_identity_binding_store.py` to avoid another large mixed responsibility inside the store. Create `tests/unit/test_element_identity_bindings.py`, freeze reviewed schema 2 as `tests/fixtures/element_identity/authority-v2.sql`, and extend `docs/element-identity-storage.md`. Preserve `issue_identity.py` unchanged.

**Public request types:**

```python
@dataclass(frozen=True, slots=True)
class ReferenceClaim:
    source_path: str
    source_sha256: str
    source_anchor: str
    target_id: str
    target_revision: str | None
    relation: str

@dataclass(frozen=True, slots=True)
class IssueOccurrence:
    issue_id: str
    issue_revision: str
    report_id: str
    report_sha256: str
    display_id: str
    title: str
    body: str
```

`source_path` is canonical spec-relative POSIX syntax without traversal, absolute paths, backslashes, NUL or empty segments. `source_sha256` and `report_sha256` are lowercase 64-digit SHA256 strings. `source_anchor` is a nonblank immutable controller-supplied locator inside those exact source bytes; the store must not resolve it against a live file or infer a new anchor after edits. `relation` is exactly `reference`, `requires`, `depends`, or `evidence`. IDs use the existing store's supported exact labels. Revisions use positive canonical decimal strings and the shared unbounded numeric helpers. `None` explicitly means an unassessed/legacy reference, never the current revision. `report_id` is a nonblank immutable report provenance ID. Issue and display IDs must be ISS labels; a historical display label may differ from the bound durable issue ID only because the caller explicitly supplied that mapping. Reject malformed types, booleans masquerading as numbers, extra fields and mutable nested containers before mutation.

**Public store APIs:**

```python
record_reference_claims(
    *, spec_id: str, operation_id: str, claims: Sequence[ReferenceClaim]
) -> tuple[dict, ...]

reference_claims(
    *, spec_id: str, source_path: str, source_sha256: str
) -> tuple[dict, ...]

record_issue_occurrences(
    *, spec_id: str, operation_id: str, occurrences: Sequence[IssueOccurrence]
) -> tuple[dict, ...]

issue_occurrences(*, spec_id: str, issue_id: str) -> tuple[dict, ...]
```

Record APIs return immutable-in-storage, detached-copy receipts keyed by `operation_id` and canonical decimal `entry_index` starting at `"1"`. Return the original recorded fields and fingerprint (for an occurrence), not a recomputed current-state verdict. Repeating identical arguments returns the original receipt after later revisions and restart. Conflicting reuse with reserve/import/lifecycle/another binding method fails. Empty batches or repeated identical claims/occurrences within a batch fail before effect; the complete operation is atomic. A new operation may retain a separately assessed reference to a different revision, but it must not replace or delete the old claim. Authorization to reassess belongs to the future controller boundary, not this record API.

Read APIs return deterministic order `(operation_id, numeric entry_index)`, not a claimed chronological ordering. Reference reads retain every original field and add `target_status` and `target_revision_matches_current`. The latter is true only if the claim has a non-null revision, it equals the current target head revision, and that head is active. It is false for unassessed, stale, retired, or superseded targets. Do not return `verified`, `passed`, or another semantic-gate verdict. Issue occurrence reads retain historical content and fingerprint, including after retirement or a later issue revision. All returned nested structures are detached from storage.

**Storage and integrity:**

1. Record APIs use one existing store-owned write transaction and globally bound operation request. Helpers receive the caller-owned SQLite connection and never open files, commit, reserve IDs or open another transaction.
2. Every target entity must already exist in the same spec. A non-null reference revision must exist as an assessed historical revision, including a terminal lifecycle revision when the reference records that historical state. Current-revision-match metadata still requires an active current head; pointing to a terminal revision cannot certify an active obligation. Unbound references may be retained without fabricated content or a guessed current revision. Validate referenced namespace counter integrity and lifecycle head/revision bindings using the existing store checks.
3. Every occurrence binds an existing ISS entity and exact historical active revision. Require `title` to equal that revision's immutable subject and `body` to equal that revision's exact retained content. Compute `issue_fingerprint(title, body)` with the existing helper; never accept a caller-supplied fingerprint as authority. Preserve report ID/hash and historical display label separately from the durable issue ID. No heuristic matching or automatic ISS allocation.
4. Store immutable claim/occurrence records and bound operation receipts with indexed source lookup and issue lookup. Rows bind their full canonical payload hash so damaged source/revision/fingerprint fields reject. Foreign-key and operation-method/spec bindings must be validated as well. Detect missing record/receipt associations in full audits and reject; do not reconstruct them from current Markdown.
5. Source hashes/anchors are declared provenance, not proof that the caller holds or has reviewed a source file. The later publication transaction must authenticate staged bytes and reviewer provenance. Document this boundary; these APIs must not read a mutable file to manufacture authority.
6. Add database schema 3 under the unchanged marker/user_version format 1. Freeze actual reviewed schema 2 DDL before changing it. Ordinary `open` on recognized schema 1 or 2 explains explicit upgrade is required and does not mutate. Explicit upgrade audits old state, then adds only required tables/indexes and updates schema metadata under one caller-owned transaction. Schema 1 first gains the existing imported/null lifecycle heads; neither older version gains fabricated claims or occurrences. Preserve all exact identities and retry bindings.
7. Explicit restore accepts exact recognized schema 1/2/3 backups, audits their appropriate records before destination claim, and upgrades only the new destination. Unknown/malformed schemas reject before creation. Current-schema audits must include the shared entity label/kind/ordinal/subject check fixed in `779ed4ae`; preserve legacy-only overlap semantics and all retained reservation-history checks.
8. Backup/restore preserves claims, original receipts, report provenance and fingerprints. Source backups are unchanged. Failed migration rolls back DDL, data and schema metadata together. Routine claim reads and writes use indexed target/source/operation access; full historical scans belong only to explicit audit/upgrade/restore.

**Step 1 — behavioral RED:** Write a real-storage test like this before implementation, importing the new interface inside the test so a missing module is a test failure rather than the only collection evidence.

```python
def test_old_evidence_is_not_rebound_after_requirement_revision(tmp_path):
    import hashlib
    from harness.element_identity_bindings import ReferenceClaim
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="001-game", kind="AC", operation_id="allocate", count=1)
    store.apply_lifecycle(spec_id="001-game", operation_id="create", changes=(
        ElementCreate("AC-000001", "Player movement", "Moves with WASD.", "allocate"),
    ))
    source_hash = hashlib.sha256(b"Movement observation E1").hexdigest()
    claim = ReferenceClaim("evidence-grades.md", source_hash, "E1",
                           "AC-000001", "1", "evidence")
    original = store.record_reference_claims(
        spec_id="001-game", operation_id="assess-one", claims=(claim,))
    store.apply_lifecycle(spec_id="001-game", operation_id="revise", changes=(
        ElementRevision("AC-000001", "1", "Player movement", "Moves with arrows."),
    ))
    saved = store.reference_claims(spec_id="001-game", source_path="evidence-grades.md",
                                   source_sha256=source_hash)
    assert saved[0]["target_revision"] == "1"
    assert saved[0]["target_revision_matches_current"] is False
    assert "verified" not in saved[0] and "passed" not in saved[0]
    assert store.record_reference_claims(
        spec_id="001-game", operation_id="assess-one", claims=(claim,)) == original
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_identity_bindings.py -q`; retain behavioral RED.
- [ ] Add tests before corresponding behavior for unassessed claims, wrong/missing namespace or revision, terminal current targets with valid historical claims (including an explicitly referenced terminal revision, never marked current-active), reassessment retaining both revisions, atomic rollback on last invalid entry, conflicting/retried operation IDs, detached results, and numeric entry ordering.
- [ ] Add real ISS creation/revision tests: same durable issue retains multiple report occurrences; fingerprint changes for changed repair/evidence; old resolution does not certify the new fingerprint through `matching_issue_resolution`. Explicitly mapped legacy display labels retain provenance without merging two distinct occurrences or allocating an ISS implicitly.
- [ ] Add real corruption and migration tests using frozen schema 2 and existing frozen schema 1: damaged revision/source/fingerprint/receipt/operation binding, missing association rows, current and older restore before destination claim, interrupted upgrade rollback, current no-op upgrade and old operation retries. Assert complete prestate on rejected writes.

**Step 2 — implement incrementally:** Pure validated types feed connection-owned record handlers. Serialize a canonical ordered payload with method/spec/operation binding, validate all referenced entities/revisions, insert every row and its receipt in the same transaction, and return detached receipt copies. Read paths authenticate original records before calculating current revision-match metadata; they never update records while reading. Keep numeric counters and existing lifecycle behavior unchanged.

```python
# Store ownership pattern, not a second transaction owner:
with self._transaction(write=True) as connection:
    # Pure request validation precedes this boundary. Existing store helpers
    # validate operation conflicts, namespace claims and historical revisions.
    receipt = binding_store.record_claims(connection, self, spec_id, operation_id, claims)
return receipt
```

- [ ] Document inactive scope, provenance versus verification, exact request/receipt fields and schema upgrade behavior.

**Step 3 — GREEN and review:**

- [ ] Run new binding tests plus `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_store.py`, `tests/unit/test_element_ids.py`, `tests/unit/test_issue_identity.py`, and the store's real-process integration tests excluding the million-record capacity case unless a routine allocation/import/index path changed. Inspect the exact capacity test name/marker before selecting; do not accidentally rerun all unrelated integration tests.
- [ ] Add query-plan assertions for the new indexed reads using real populated temporary records. If a routine allocation/index/import path changed, run and report the capacity case too.
- [ ] Run `git diff --check`, self-review the focused diff, and commit only task files. Report exact RED/GREEN commands/output, migration choice and remaining controller/publication gap.

## Following work

These immutable claims are necessary history, not a publication gate. Candidate scope/identity/reference validation, history-aware import tools, durable publication intents and completion receipts, graph/memory projection, managed producer integration, bounded repair and offline/live verification remain required. No code in this plan may claim that merely recording a source hash or having a current revision proves semantic correctness.

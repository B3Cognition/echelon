# Element identity lifecycle implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Status:** Ready for execution against the reviewed allocation-store checkpoint `5fab792b`. The approved durable-identity design is the binding authority.

**Goal:** Complete the lifecycle portion of the durable-authority foundation without activating it in authoring or bypassing existing squad publication.

**Architecture:** Extend the same SQLite authority with immutable content revisions and explicit lineage. Allocations remain separate from materialized entities. All mutations in a controller operation are atomic and retry-safe. This is an inactive library layer; artifact adapters and durable publication integration come next.

**Tech Stack:** Python standard library dataclasses, SQLite, hashlib, JSON, pathlib; existing pytest and multiprocessing tests. No dependencies added.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Preserve exact published labels and numeric reservations. Never derive a new counter from surviving active rows.
- Content revisions are not new entity IDs. Revision counters are decimal strings backed by Python integer arithmetic, without fixed-width truncation.
- A revision cannot change the immutable subject binding. Semantic continuity review and allowed edit scope remain required at the future publication boundary; a caller supplying the same subject string is not itself proof that rewritten prose has the same meaning.
- Retirement and replacement preserve historical content, references, and lineage. They never free an ID.
- Do not add provider routing, graph writes, or canonical file publication in this foundation task.

## Task 1: transactional revisions and lifecycle lineage

**Files:** Extend `src/harness/element_identity_store.py`; create `src/harness/element_identity_lifecycle.py` for immutable operation types and pure payload validation and `src/harness/element_identity_schema.py` for canonical allocation/lifecycle DDL and explicit transactional migration helpers; create `tests/unit/test_element_identity_lifecycle.py` and a frozen allocation-only schema fixture at `tests/fixtures/element_identity/authority-v1.sql`; extend `tests/integration/test_element_identity_store.py` and `docs/element-identity-storage.md` only where covering the added lifecycle storage. Keep unrelated producers unchanged. Schema helpers operate on a caller-owned connection, never independently commit, initialize authority, or change filesystem state.

**Public operation types:** frozen dataclasses with strictly validated fields, no arbitrary extra fields:

- `ElementCreate(element_id: str, subject: str, content: str, reservation_operation_id: str)`.
- `ElementAdopt(element_id: str, subject: str, content: str)` for attaching the first assessed content to an already imported legacy subject. It does not allocate or change that subject.
- `ElementRevision(element_id: str, expected_revision: str, subject: str, content: str)`.
- `ElementRetirement(element_id: str, expected_revision: str, reason: str)`.
- `ElementTransition(kind: str, predecessors: tuple[tuple[str, str], ...], successors: tuple[ElementCreate, ...], reason: str)`, where each predecessor pair is exact ID and expected revision; kind is `replace`, `split`, or `merge`.

**Store interfaces:**

- `IdentityStore.upgrade(workspace: Path) -> IdentityStore`: explicitly and transactionally upgrade a recognized allocation-only authority; retry on the current schema is a validated no-op. Never initialize missing state or guess at unknown schemas. Keep marker format/version and authority UUIDs unchanged; use separately versioned database-schema metadata.
- `apply_lifecycle(*, spec_id: str, operation_id: str, changes: Sequence[LifecycleChange]) -> tuple[dict, ...]`: one SQLite transaction and one globally bound operation request. Repeating the same operation returns its original receipt even after later edits; conflicting reuse with reserve/import/lifecycle arguments fails. The receipt identifies changed exact IDs, resulting revisions/statuses, and lineage without relying on caller object identity.
- `lookup` retains the allocation store's existing exact-label/subject fields and adds `status`, `revision`, `content`, and `content_sha256`. Imported-but-unbound records must be distinguishable from active assessed content. Do not change the six-digit allocator or existing numeric alias semantics.
- `read_revision(*, spec_id: str, element_id: str, revision: str) -> dict | None`: immutable historical content, subject, lifecycle status, and content digest at the requested decimal revision.
- `lineage(*, spec_id: str, element_id: str) -> tuple[dict, ...]`: direct predecessor/successor links with the specific predecessor revisions and creating lifecycle operation; not recursive history traversal.

**Storage and semantics:**

1. Use the same operation-ID authority and short transaction/connection discipline as allocation. Do not add an independent counter, JSON ledger, or database.
2. Fresh materialization consumes only a matching reservation for that spec/type/ordinal. It uses the exact controller-issued label; padding aliases, unknown reservations, and already used or imported IDs fail. A batch may consume part of a reservation; unused IDs stay reserved forever.
3. Legacy imports made through the allocation-only API have a subject but no assessed content. Represent that honestly with lifecycle status `imported`, and `None` for current revision/content/digest. `ElementAdopt` binds content once while keeping the original subject and ID; it must not fabricate historical content from a subject caption.
4. First assessed content revision is `"1"`. Revision updates require an active entity, an exact current revision precondition, and the unchanged immutable subject. Preserve prior content and revision rows. Store canonical decimal revisions as text, including beyond signed 64-bit. Verify content digests and revision/head bindings when reading or using them; damaged state must not silently certify content or be repaired from current text.
5. Retirement requires an active entity and exact current revision, records a reason and terminal lifecycle revision, and retains its prior content. Retired/superseded entities cannot be silently revised or recreated. A status change is not a new entity ID.
6. Replace is one predecessor to one new successor; split is one to at least two; merge is at least two to one. Reject duplicate inputs, overlapping predecessor/successor labels, malformed cardinality, missing reservations, and stale predecessor revisions before any effect commits. Successors can use their explicitly bound supported type reservations; a future consumer must reject operations it cannot represent before publication.
7. Record all predecessor revision bindings and the transition reason atomically with terminal predecessor status and new successor content. No dangling lineage or half-completed split/merge is permitted.
8. Reject multiple changes to the same existing entity within one batch rather than making semantics depend on list order. Validate every request before advancing any record. Rollback must include materialization, revisions, lineage, counters, and operation receipts.
9. Existing backup/restore must carry all lifecycle tables and operation receipts. Determine the smallest explicit schema upgrade after inspecting the reviewed store; missing/corrupt storage still blocks. Do not silently reinterpret old import records as assessed content. Record the schema-upgrade decision in the implementation ledger before coding it.

**Migration design to verify against the final reviewed allocation schema:** Keep the existing authority marker format at version 1, and record database `schema_version` separately in metadata. Recognize the exact reviewed allocation schema and metadata as the sole older format, not arbitrary schema variants. The explicit upgrade must validate old authority and counter/history consistency, then make the entire schema/data change under one `BEGIN IMMEDIATE` transaction. Preserve canonical DDL and use named-column imports; a canonical table rebuild is permitted where SQLite's rewritten ALTER TABLE text would undermine exact-schema validation. Import records become unbound, without fabricated content revisions. `open` on an older schema must explain that explicit upgrade is needed, never mutate on read. Explicit `restore` may accept a recognized allocation-only backup, verify its full digest/authority/history before claiming the fresh destination, and upgrade that restored destination before returning it; unknown versions fail before destination creation. Existing UUID, epoch, reservations, operation retry bindings, exact labels, and immutable subjects remain unchanged. Tests must exercise interrupted/rolled-back upgrade, idempotent upgrade, and both current and allocation-only backup restoration.

**Test checkpoints (TDD):**

- [ ] Establish the public behavior with real storage before implementation:

```python
from harness.element_identity_store import IdentityStore
from harness.element_identity_lifecycle import ElementCreate, ElementRevision

def test_revision_keeps_id_and_prior_content(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    assert store.reserve(spec_id="001-game", kind="AC", operation_id="allocate", count=1) == ("AC-000001",)
    store.apply_lifecycle(spec_id="001-game", operation_id="create", changes=(
        ElementCreate("AC-000001", "Player movement", "Moves with WASD.", "allocate"),
    ))
    first = store.lookup(spec_id="001-game", element_id="AC-000001")
    assert first["revision"] == "1"
    store.apply_lifecycle(spec_id="001-game", operation_id="revise", changes=(
        ElementRevision("AC-000001", "1", "Player movement", "Moves with WASD and arrow keys."),
    ))
    assert store.lookup(spec_id="001-game", element_id="AC-000001")["revision"] == "2"
    assert store.read_revision(spec_id="001-game", element_id="AC-000001", revision="1")["content"] == "Moves with WASD."
    assert store.high_water(spec_id="001-game", kind="AC") == "1"
```

Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_identity_lifecycle.py -q` and capture RED. Add the remaining behavioral assertions below before their implementation, then implement types, schema migration and atomic handlers incrementally. Use the existing `self._transaction(write=True)` owner: validate every involved namespace against retained claims, check/bind the operation digest and return its original receipt on retry, validate all current revisions/subjects/states/reservations, and only then apply every lifecycle row and persist the result receipt. A failed condition rolls back the entire transaction.

- [ ] Create a reserved AC, revise its body with the same subject, read both immutable revisions, and prove allocation high-water is unchanged by revision.
- [ ] Reject subject replacement under revise, stale revisions, unreserved creation, padding aliases, reuse of retired IDs, and conflicting operation-ID reuse. Assert the entire prestate remains unchanged after rejection.
- [ ] Import FR-001, prove it has no invented assessed content, adopt exact subject/content, retry adoption, and reject conflicting second adoption.
- [ ] Retire an element, reopen the store, allocate the next ID, and verify its historical revisions remain readable.
- [ ] Replace, split, and merge using real reservations; verify lineage points to the original assessed predecessor revisions. A failure in the last successor must roll back every earlier mutation.
- [ ] Retry a successful lifecycle operation after an unrelated later revision and require the original durable receipt, without repeating any effect.
- [ ] Corrupt a stored revision digest or head binding in a temporary fixture and require fail-closed reads/mutations; verify no automatic reconstruction from subject or latest artifact text.
- [ ] Use separate processes to race two revisions from the same baseline: exactly one commits and the other fails stale; no lost update.
- [ ] Backup/restore retains historical revisions, status, lineage, and retry receipts; missing or malformed lifecycle schema blocks instead of dropping history.
- [ ] Run focused lifecycle, allocation-store, formatter, and real-process tests. Run the existing marked capacity test only if schema/index/lookup changes could affect its contract; do not repeat unrelated whole-unit suites.
- [ ] Final verification command: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_identity_lifecycle.py tests/unit/test_element_identity_store.py tests/unit/test_element_ids.py tests/integration/test_element_identity_store.py -q -s`. The schema changes in this task warrant the existing capacity test. Record measured times/size and require indexed lookups. Run `git diff --check`.
- [ ] Commit only task files and supply RED/GREEN evidence plus a schema/migration note for independent review.

## Following phase

Typed artifact adapters, revision-bound evidence, issue occurrences, publication intents/receipts, graph/memory history, managed-spec producer integration, and bounded discovery repair remain required before this feature can be activated. Library lifecycle tests alone do not prove arbitrary Markdown edits preserve semantic identity.

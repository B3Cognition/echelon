# Read-only lifecycle proposal validation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the publication validator check an entire proposed lifecycle batch against one coherent registry snapshot without persisting proposed revisions or inventing a second implementation of lifecycle rules.

**Architecture:** Extract the existing pre-write lifecycle planning loop into a connection-owned helper shared by preview and application. The public preview is explicitly advisory: it returns projected heads and the heads they depend on; publication must revalidate under its durable intent/CAS boundary. This checkpoint remains inactive and cannot authorize canonical file promotion.

**Tech Stack:** Python standard library, existing SQLite authority and lifecycle types, pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing labels, immutable subjects, revision history, terminal states, reservation ownership and lifecycle lineage remain unchanged.
- Use one harness-owned workspace authority. Helpers receive the store-owned connection and never open another connection, allocate IDs, commit or write files.
- Preview is not a durable authorization, semantic review, or publication receipt. It must not mutate operations, entities, revisions, counters, claims, occurrences or receipts.
- No canonical publication, graph/memory writes, provider routing, or live activation in this task.
- Do not duplicate the lifecycle validation algorithm or replace the existing transaction owner.

---

### Task 1: shared lifecycle planning and read-only preview

**Files:** Create `src/harness/element_identity_lifecycle_store.py` for the connection-owned batch planner. Extend `src/harness/element_identity_store.py` to call it from existing application and the new preview API. Create `tests/unit/test_element_identity_preview.py`; extend `docs/element-identity-storage.md`. No schema or frozen-fixture changes.

**Consumes:** Existing exact `ElementCreate`, `ElementAdopt`, `ElementRevision`, `ElementRetirement`, `ElementTransition`, `lifecycle.request`, store `_creation`, `_existing_change`, `_high_water`, `_head` and `_transaction`. Read the actual post-binding store before editing; preserve binding APIs and migration behavior.

**Produces:**

```python
IdentityStore.preview_lifecycle(
    *, spec_id: str, changes: Sequence[lifecycle.LifecycleChange]
) -> tuple[dict, ...]
```

Each returned detached record has exactly `element_id`, `expected_status`, `expected_revision`, `subject`, `content`, `content_sha256`, `revision`, `status`. The expected fields are the actual current head's status/revision in the read snapshot, both `None` for a new reserved identity, and `imported`/`None` for an adoption. The remaining fields describe the proposed head. Revision strings use the existing unbounded decimal helpers. Order is exactly the current application's planned-row order: input order, predecessor order, then successor order. Terminal projections retain predecessor content and digest. This is a current-prestate preview, not operation replay; it has no operation ID and never creates an operation record. Repeating a stale proposal after a successful application rejects rather than implying that the earlier preview still authorizes a write.

**Shared planner boundary:**

```python
# Connection-owned helper; imports lifecycle from harness.element_identity_lifecycle.
def plan_changes(connection, store, spec_id, changes):
    changes, _, labels = lifecycle.request(changes)
    for kind in {label.split("-", 1)[0] for label in labels}:
        store._high_water(connection, spec_id, kind)
    planned, links = [], []
    for change in changes:
        if type(change) is lifecycle.ElementCreate:
            planned.append(store._creation(connection, spec_id, change))
        elif type(change) is lifecycle.ElementAdopt:
            planned.append(store._existing_change(
                connection, spec_id, change.element_id, None,
                subject=change.subject, content=change.content, adopt=True))
        elif type(change) is lifecycle.ElementRevision:
            planned.append(store._existing_change(
                connection, spec_id, change.element_id, change.expected_revision,
                subject=change.subject, content=change.content))
        elif type(change) is lifecycle.ElementRetirement:
            planned.append(store._existing_change(
                connection, spec_id, change.element_id, change.expected_revision,
                status="retired", reason=change.reason))
        else:
            for label, expected in change.predecessors:
                planned.append(store._existing_change(
                    connection, spec_id, label, expected,
                    status="superseded", reason=change.reason))
            for successor in change.successors:
                planned.append(store._creation(connection, spec_id, successor))
            links.extend(
                (spec_id, label, expected, successor.element_id, "1", change.kind, change.reason)
                for label, expected in change.predecessors
                for successor in change.successors)
    return planned, links

# Existing apply_lifecycle still owns global request binding and persistence.
with self._transaction(write=True) as connection:
    # Existing namespace validation and idempotent-operation branch stay here.
    planned, links = lifecycle_store.plan_changes(connection, self, spec_id, changes)
    # Existing insertion loop uses these rows; append the real operation_id
    # when persisting each lineage tuple. Preserve original retry receipts.

# Preview owns only one read transaction and computes no mutable-store effects.
with self._transaction() as connection:
    planned, links = lifecycle_store.plan_changes(connection, self, spec_id, changes)
    # Return detached projected fields and validated current expected heads.
```

The helper must carry the existing namespace high-water integrity checks so both callers reject detectable authority contradictions. Keep global operation conflict/retry handling in application; do not call its inserting `_operation` helper during preview. Avoid unrelated lifecycle/store refactors. Projecting heads does not need to publish fake lineage receipts or expose a fabricated operation ID.

- [ ] Write a real-storage behavioral test before implementation, importing the new behavior inside the test body so missing behavior is a failure, not only collection failure:

```python
def test_preview_does_not_materialize_reserved_identity(tmp_path):
    import hashlib
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="001-game", kind="U", operation_id="reserve", count=1)
    proposal = ElementCreate(label, "Collision margin", "Question body", "reserve")
    projected, = store.preview_lifecycle(spec_id="001-game", changes=(proposal,))
    assert projected == {
        "element_id": label, "expected_status": None, "expected_revision": None,
        "subject": "Collision margin", "content": "Question body",
        "content_sha256": hashlib.sha256(b"Question body").hexdigest(),
        "revision": "1", "status": "active",
    }
    assert store.lookup(spec_id="001-game", element_id=label) is None
    assert store.high_water(spec_id="001-game", kind="U") == "1"
    store.apply_lifecycle(spec_id="001-game", operation_id="create", changes=(proposal,))
    actual = store.lookup(spec_id="001-game", element_id=label)
    assert {key: actual[key] for key in projected if not key.startswith("expected_")} == {
        key: value for key, value in projected.items() if not key.startswith("expected_")
    }
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_identity_preview.py -q` and retain expected behavioral RED.
- [ ] Add tests before corresponding behavior for adoption, revision, retirement, replacement, split and merge. Compare every projected head to the actual head produced by applying the identical proposal, including terminal content retention. Compare the complete SQLite logical prestate before and after successful/rejected previews, not only the current head.
- [ ] Add rejected-preview tests for stale revisions, subject changes, unreserved/padding-alias creations, reused/terminal identities, duplicated IDs, wrong cardinality and a last invalid successor. The entire prestate and original operation receipts remain unchanged.
- [ ] Add a two-connection test: after preview, another store handle revises the same entity; applying the old proposal rejects, while the earlier detached preview stays unchanged. No preview-to-apply transaction reservation is claimed.
- [ ] Extract the existing pre-write planner and add preview incrementally. Run the focused tests to GREEN; self-review specifically that application and preview call the same planner and that no public store method is nested inside either transaction.
- [ ] Run `tests/unit/test_element_identity_preview.py`, `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_bindings.py`, `tests/unit/test_element_identity_store.py` and the store's process integration suite excluding its million-record import case. Routine allocation/import/index paths must remain unchanged; if they change, include that capacity case and explain why the extra change was needed.
- [ ] Document the exact response and the advisory/CAS boundary. Run `git diff --check`, self-review and commit only task files. Report exact RED/GREEN commands and outputs, preserved retry behavior, and remaining candidate/publication work.

## Coverage boundary

This implements only the common read-only lifecycle preflight needed by candidate validation. Parsing and checking staged artifacts, edit-scope enforcement, authenticating evidence bytes and semantic assessments, durable publication intents/recovery, graph/memory consumers, all managed producers, bounded repair, offline smoke replay and rollout remain separate required checkpoints. A successful preview must never be called an accepted or published candidate.

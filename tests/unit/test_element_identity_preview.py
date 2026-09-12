"""Real-storage contracts for read-only lifecycle previews."""

import hashlib
import sqlite3

import pytest


pytestmark = pytest.mark.unit


def logical_state(workspace):
    with sqlite3.connect(workspace / ".echelon/identity/registry.sqlite3") as connection:
        return tuple(connection.iterdump())


def assert_matches_applied_heads(store, spec_id, projected):
    proposed_keys = tuple(key for key in projected[0] if not key.startswith("expected_"))
    for projection in projected:
        actual = store.lookup(spec_id=spec_id, element_id=projection["element_id"])
        assert {key: actual[key] for key in proposed_keys} == {
            key: projection[key] for key in proposed_keys
        }


def active_store(workspace, *, count=6):
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(workspace)
    store.reserve(spec_id="demo", kind="AC", operation_id="reserve", count=count)
    store.apply_lifecycle(spec_id="demo", operation_id="seed", changes=(
        ElementCreate("AC-000001", "First", "First body.", "reserve"),
        ElementCreate("AC-000002", "Second", "Second body.", "reserve"),
    ))
    return store


def test_preview_does_not_materialize_reserved_identity(tmp_path):
    import hashlib
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="001-game", kind="U", operation_id="reserve", count=1)
    proposal = ElementCreate(label, "Collision margin", "Question body", "reserve")
    before = logical_state(tmp_path)
    projected, = store.preview_lifecycle(spec_id="001-game", changes=(proposal,))
    assert logical_state(tmp_path) == before
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


def test_preview_adoption_matches_applied_head_without_writes(tmp_path):
    from harness.element_identity_lifecycle import ElementAdopt
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    store.import_identities(
        spec_id="demo", operation_id="import", definitions=(("FR-legacy", "Legacy requirement"),),
    )
    proposal = ElementAdopt("FR-legacy", "Legacy requirement", "Assessed legacy body.")
    before = logical_state(tmp_path)
    projected = store.preview_lifecycle(spec_id="demo", changes=(proposal,))
    assert logical_state(tmp_path) == before
    assert projected == ({
        "element_id": "FR-legacy",
        "expected_status": "imported",
        "expected_revision": None,
        "subject": "Legacy requirement",
        "content": "Assessed legacy body.",
        "content_sha256": hashlib.sha256(b"Assessed legacy body.").hexdigest(),
        "revision": "1",
        "status": "active",
    },)
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=(proposal,))
    assert_matches_applied_heads(store, "demo", projected)


@pytest.mark.parametrize("case", ["revision", "retirement"])
def test_preview_existing_change_matches_applied_head_and_retains_terminal_content(tmp_path, case):
    from harness.element_identity_lifecycle import ElementRetirement, ElementRevision

    store = active_store(tmp_path)
    proposal = (
        ElementRevision("AC-000001", "1", "First", "Revised body.")
        if case == "revision"
        else ElementRetirement("AC-000001", "1", "No longer needed")
    )
    before = logical_state(tmp_path)
    projected = store.preview_lifecycle(spec_id="demo", changes=(proposal,))
    assert logical_state(tmp_path) == before
    expected_content = "Revised body." if case == "revision" else "First body."
    assert projected == ({
        "element_id": "AC-000001",
        "expected_status": "active",
        "expected_revision": "1",
        "subject": "First",
        "content": expected_content,
        "content_sha256": hashlib.sha256(expected_content.encode()).hexdigest(),
        "revision": "2",
        "status": "active" if case == "revision" else "retired",
    },)
    store.apply_lifecycle(spec_id="demo", operation_id=case, changes=(proposal,))
    assert_matches_applied_heads(store, "demo", projected)


@pytest.mark.parametrize("kind", ["replace", "split", "merge"])
def test_preview_transition_matches_applied_heads_in_predecessor_successor_order(tmp_path, kind):
    from harness.element_identity_lifecycle import ElementCreate, ElementTransition

    store = active_store(tmp_path)
    predecessors = (("AC-000001", "1"),)
    if kind == "merge":
        predecessors += (("AC-000002", "1"),)
    successor_labels = ("AC-000003", "AC-000004") if kind == "split" else ("AC-000003",)
    successors = tuple(
        ElementCreate(label, f"Successor {label}", f"Body for {label}.", "reserve")
        for label in successor_labels
    )
    proposal = ElementTransition(kind, predecessors, successors, "Reviewed transition")
    before = logical_state(tmp_path)
    projected = store.preview_lifecycle(spec_id="demo", changes=(proposal,))
    assert logical_state(tmp_path) == before
    assert tuple(row["element_id"] for row in projected) == tuple(
        label for label, _ in predecessors
    ) + successor_labels
    predecessor_content = {"AC-000001": "First body.", "AC-000002": "Second body."}
    for row in projected[:len(predecessors)]:
        assert (row["expected_status"], row["expected_revision"]) == ("active", "1")
        assert (row["status"], row["revision"], row["content"]) == (
            "superseded", "2", predecessor_content[row["element_id"]],
        )
        assert row["content_sha256"] == hashlib.sha256(row["content"].encode()).hexdigest()
    for row in projected[len(predecessors):]:
        assert (row["expected_status"], row["expected_revision"]) == (None, None)
        assert (row["status"], row["revision"]) == ("active", "1")
    store.apply_lifecycle(spec_id="demo", operation_id=kind, changes=(proposal,))
    assert_matches_applied_heads(store, "demo", projected)


def test_preview_preserves_batch_input_then_transition_row_order(tmp_path):
    from harness.element_identity_lifecycle import (
        ElementAdopt, ElementCreate, ElementRevision, ElementTransition,
    )

    store = active_store(tmp_path)
    store.import_identities(
        spec_id="demo", operation_id="import", definitions=(("FR-legacy", "Legacy"),),
    )
    changes = (
        ElementRevision("AC-000001", "1", "First", "Edited first."),
        ElementAdopt("FR-legacy", "Legacy", "Assessed legacy."),
        ElementTransition(
            "replace", (("AC-000002", "1"),),
            (ElementCreate("AC-000003", "Third", "Third body.", "reserve"),),
            "Replacement",
        ),
    )
    before = logical_state(tmp_path)
    projected = store.preview_lifecycle(spec_id="demo", changes=changes)
    assert tuple(row["element_id"] for row in projected) == (
        "AC-000001", "FR-legacy", "AC-000002", "AC-000003",
    )
    assert logical_state(tmp_path) == before
    store.apply_lifecycle(spec_id="demo", operation_id="batch", changes=changes)
    assert_matches_applied_heads(store, "demo", projected)


def invalid_preview_case(workspace, case):
    from harness.element_identity_lifecycle import (
        ElementCreate, ElementRevision, ElementRetirement, ElementTransition,
    )

    store = active_store(workspace)
    if case == "stale":
        changes = (ElementRevision("AC-000001", "2", "First", "Body"),)
    elif case == "subject":
        changes = (ElementRevision("AC-000001", "1", "Changed", "Body"),)
    elif case == "unreserved":
        changes = (ElementCreate("AC-000007", "Seventh", "Body", "reserve"),)
    elif case == "padding_alias":
        changes = (ElementCreate("AC-03", "Third", "Body", "reserve"),)
    elif case == "reused":
        changes = (ElementCreate("AC-000001", "First", "Body", "reserve"),)
    elif case == "terminal":
        terminal = ElementRetirement("AC-000001", "1", "Done")
        store.apply_lifecycle(spec_id="demo", operation_id="retire", changes=(terminal,))
        changes = (ElementRevision("AC-000001", "2", "First", "Changed"),)
    elif case == "duplicate":
        change = ElementRevision("AC-000001", "1", "First", "Body")
        changes = (change, change)
    elif case == "wrong_cardinality":
        successor = ElementCreate("AC-000003", "Third", "Body", "reserve")
        malformed = object.__new__(ElementTransition)
        object.__setattr__(malformed, "kind", "split")
        object.__setattr__(malformed, "predecessors", (("AC-000001", "1"),))
        object.__setattr__(malformed, "successors", (successor,))
        object.__setattr__(malformed, "reason", "Bad split")
        changes = (malformed,)
    else:
        successor = ElementCreate("AC-000003", "Third", "Body", "reserve")
        invalid_last = ElementCreate("FR-000001", "Missing", "Body", "missing-reservation")
        changes = (ElementTransition(
            "split", (("AC-000001", "1"),), (successor, invalid_last), "Bad successor",
        ),)
    return store, changes


@pytest.mark.parametrize("case", [
    "stale", "subject", "unreserved", "padding_alias", "reused", "terminal",
    "duplicate", "wrong_cardinality", "last_invalid_successor",
])
def test_rejected_preview_preserves_complete_logical_prestate(tmp_path, case):
    from harness.element_identity_store import IdentityStoreError

    store, changes = invalid_preview_case(tmp_path, case)
    before = logical_state(tmp_path)
    with pytest.raises((IdentityStoreError, ValueError)):
        store.preview_lifecycle(spec_id="demo", changes=changes)
    assert logical_state(tmp_path) == before


def test_preview_rejects_counter_below_retained_claim_without_repair(tmp_path):
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_store import IdentityStore, IdentityStoreError

    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="demo", kind="U", operation_id="reserve", count=1)
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        connection.execute("UPDATE counters SET high_water='0'")
    before = logical_state(tmp_path)
    with pytest.raises(IdentityStoreError, match="counter"):
        store.preview_lifecycle(
            spec_id="demo", changes=(ElementCreate("U-000001", "Question", "Body", "reserve"),),
        )
    assert logical_state(tmp_path) == before


def test_detached_preview_does_not_authorize_stale_apply_between_store_handles(tmp_path):
    from harness.element_identity_lifecycle import ElementRevision
    from harness.element_identity_store import IdentityStore, IdentityStoreError

    first = active_store(tmp_path)
    second = IdentityStore.open(tmp_path)
    proposal = ElementRevision("AC-000001", "1", "First", "Proposed body.")
    projected = first.preview_lifecycle(spec_id="demo", changes=(proposal,))
    detached_copy = tuple(dict(row) for row in projected)
    second.apply_lifecycle(spec_id="demo", operation_id="other", changes=(
        ElementRevision("AC-000001", "1", "First", "Concurrent body."),
    ))
    before_rejection = logical_state(tmp_path)
    with pytest.raises(IdentityStoreError, match="stale"):
        first.apply_lifecycle(spec_id="demo", operation_id="stale", changes=(proposal,))
    assert logical_state(tmp_path) == before_rejection
    assert projected == detached_copy
    assert projected[0]["expected_revision"] == "1"
    assert first.lookup(spec_id="demo", element_id="AC-000001")["content"] == "Concurrent body."


def test_preview_revision_arithmetic_is_unbounded_decimal_text(tmp_path):
    from harness.element_identity_lifecycle import ElementRevision

    store = active_store(tmp_path)
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        connection.execute("UPDATE revisions SET revision='9223372036854775808' WHERE element_id='AC-000001'")
        connection.execute("UPDATE lifecycle_heads SET revision='9223372036854775808' WHERE element_id='AC-000001'")
    proposal = ElementRevision(
        "AC-000001", "9223372036854775808", "First", "Beyond signed SQLite integer.",
    )
    before = logical_state(tmp_path)
    projected, = store.preview_lifecycle(spec_id="demo", changes=(proposal,))
    assert projected["expected_revision"] == "9223372036854775808"
    assert projected["revision"] == "9223372036854775809"
    assert logical_state(tmp_path) == before

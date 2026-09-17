"""Restoration selects old content without undoing identity knowledge."""
import json
from dataclasses import replace

import pytest

from harness.element_identity_lifecycle import ElementCreate, ElementRevision, ElementRetirement
from harness.element_identity_store import IdentityStore


@pytest.fixture
def candidates(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="game", kind="FR", operation_id="allocate", count=2)
    store.apply_lifecycle(spec_id="game", operation_id="a", changes=(
        ElementCreate("FR-000001", "Movement", "Move in scene", "allocate"),))
    a = store.identity_history(spec_id="game")
    store.apply_lifecycle(spec_id="game", operation_id="b", changes=(
        ElementRevision("FR-000001", "1", "Movement", "Move using arrows"),
        ElementCreate("FR-000002", "Lighting", "Light the scene", "allocate")))
    b = store.identity_history(spec_id="game")
    return store, a, b


def test_restoration_plans_forward_content_and_membership_then_repeated_return(candidates):
    from harness.discovery_restoration import requirement_restoration_changes
    store, a, b = candidates
    changes = requirement_restoration_changes(store, spec_id="game", selected_history=a, snapshot_id="a")
    assert [(item.element_id, item.expected_revision, item.present, item.source_revision) for item in changes] == [
        ("FR-000001", "2", True, "1"), ("FR-000002", "1", False, None)]
    assert store.identity_history(spec_id="game") == b
    store.apply_lifecycle(spec_id="game", operation_id="restore-a", changes=changes)
    assert requirement_restoration_changes(store, spec_id="game", selected_history=a, snapshot_id="a-again") == ()
    changes = requirement_restoration_changes(store, spec_id="game", selected_history=b, snapshot_id="b")
    store.apply_lifecycle(spec_id="game", operation_id="restore-b", changes=changes)
    assert store.lookup(spec_id="game", element_id="FR-000001")["revision"] == "4"
    assert store.lookup(spec_id="game", element_id="FR-000002")["revision"] == "3"
    assert store.lookup(spec_id="game", element_id="FR-000002")["present"] is True
    assert store.reserve(spec_id="game", kind="FR", operation_id="next", count=1) == ("FR-000003",)


def test_selected_absent_requirement_stays_absent_without_new_history(candidates):
    from harness.discovery_restoration import requirement_restoration_changes
    store, a, b = candidates
    store.apply_lifecycle(spec_id="game", operation_id="restore-a",
        changes=requirement_restoration_changes(store, spec_id="game", selected_history=a, snapshot_id="a"))
    absent = store.identity_history(spec_id="game")
    store.apply_lifecycle(spec_id="game", operation_id="restore-b",
        changes=requirement_restoration_changes(store, spec_id="game", selected_history=b, snapshot_id="b"))
    changes = requirement_restoration_changes(store, spec_id="game", selected_history=absent, snapshot_id="absent")
    assert next(change for change in changes if change.element_id == "FR-000002").present is False


def test_restoration_does_not_rewind_issue_history(candidates):
    from harness.discovery_restoration import requirement_restoration_changes
    store, a, _ = candidates
    store.reserve(spec_id="game", kind="ISS", operation_id="issue-reserve", count=1)
    store.apply_lifecycle(spec_id="game", operation_id="issue", changes=(
        ElementCreate("ISS-000001", "Issue", "New evidence", "issue-reserve"),))
    changes = requirement_restoration_changes(store, spec_id="game", selected_history=a, snapshot_id="a")
    assert all(not change.element_id.startswith("ISS-") for change in changes)


def test_retained_plan_replays_original_forward_revisions_after_apply(candidates):
    from harness import discovery_restoration
    store, a, b = candidates
    planner = getattr(discovery_restoration, "_requirement_restoration_changes", None)
    assert callable(planner), "Recovery needs a plan derived from captured history, not the mutable head"
    changes = planner(current_history=b, selected_history=a, snapshot_id="candidate-a")
    store.apply_lifecycle(spec_id="game", operation_id="restore-a", changes=changes)
    after = store.identity_history(spec_id="game")
    replay = planner(current_history=b, selected_history=a, snapshot_id="candidate-a")
    assert [(item.element_id, item.expected_revision, item.present, item.source_revision) for item in replay] == [
        ("FR-000001", "2", True, "1"), ("FR-000002", "1", False, None)]
    store.apply_lifecycle(spec_id="game", operation_id="restore-a", changes=replay)
    assert store.identity_history(spec_id="game") == after


def test_retained_plan_rejects_damaged_captured_history(candidates):
    from harness import discovery_restoration
    _, a, b = candidates
    planner = getattr(discovery_restoration, "_requirement_restoration_changes", None)
    assert callable(planner), "Recovery must validate captured history before deriving changes"
    with pytest.raises(ValueError):
        planner(current_history=replace(b, sha256="0" * 64), selected_history=a, snapshot_id="candidate-a")


def test_restoration_rejects_terminal_identity_revival(candidates):
    from harness.discovery_restoration import requirement_restoration_changes
    store, _, b = candidates
    store.apply_lifecycle(spec_id="game", operation_id="retire", changes=(
        ElementRetirement("FR-000002", "1", "Permanently removed"),))
    before = store.identity_history(spec_id="game")
    with pytest.raises(ValueError):
        requirement_restoration_changes(store, spec_id="game", selected_history=b, snapshot_id="b")
    assert store.identity_history(spec_id="game") == before


@pytest.mark.parametrize("damage", ["digest", "authority", "revision"])
def test_restoration_requires_selected_history_to_be_retained(candidates, damage):
    from harness.discovery_restoration import requirement_restoration_changes
    from harness.element_identity_snapshot import canonical_snapshot
    store, a, _ = candidates
    value = json.loads(a.payload)
    if damage == "digest": selected = replace(a, sha256="a" * 64)
    else:
        if damage == "authority": value["epoch_uuid"] = "wrong-authority"
        if damage == "revision": value["revisions"][0]["content"] = "Invented history"
        selected = canonical_snapshot(value)
    before = store.identity_history(spec_id="game")
    with pytest.raises(ValueError):
        requirement_restoration_changes(store, spec_id="game", selected_history=selected, snapshot_id="a")
    assert store.identity_history(spec_id="game") == before

"""Historical WHY1 answers follow their accepted Tracker, never today's active one."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_discovery_turns import case, enrolled
from tests.unit.test_synthesis_refresh_selection import retained


def source(digit):
    return dict(dispatch_id=digit * 32, completion_intent_sha256="1" * 64,
        completion_receipts_sha256="2" * 64, completed_publication_binding_sha256="3" * 64)


def resolved(digit, question, answer, producer="tracker"):
    from tests.unit.test_blocked_decision import _v2_decision
    decision = {**_v2_decision(), "id": "dec-" + digit * 8, "status": "resolved",
        "source_phase": "phase1-" + producer, "producer_id": "phase1-" + producer,
        "question": question, "answer_text": answer, "resolved_by": "user",
        "resolved_at": "2026-07-28T10:01:00+00:00"}
    return dict(decision=decision, completion=dict(schema_version=1, decision_id=decision["id"],
        completion_id=digit * 32, intent_sha256="1" * 64, receipts_sha256="2" * 64,
        publication_binding_sha256="3" * 64))


def row(digit, producer="tracker", *, predecessor=None, resolution=None):
    from tests.unit.test_discovery_operation import binding, result
    operation_id = producer + "-" + digit * 32
    paths = ["user-intent.md", "stakeholder-model.md"] if producer == "tracker" else ["assumption-review.md", "issues.md", "unknowns.md"]
    operation = dict(schema_version=1, binding={**binding(), "operation_id": operation_id,
        "artifact_paths": paths, "unowned_writable_paths": paths,
        "intent": dict(kind="track" if producer == "tracker" else "challenge", request="Create an isometric game")},
        attempts=[dict(number=1, result=result("accepted"))])
    return dict(source=source(digit), predecessor=predecessor, resolution=resolution, operation=operation, turns=None)


@pytest.fixture
def history(enrolled):
    # Structurally valid state-only fixture. Real proof authentication is tested
    # separately; these records confer no publication authority.
    state = enrolled[1].load()
    first, parent, later = ("tracker-" + digit * 32 for digit in ("a", "b", "c"))
    why = "why1-" + "d" * 32
    state["managed_tracker_rounds"] = dict(schema_version=1, active=later, rounds={
        first: row("a"), parent: row("b", predecessor=first,
            resolution=resolved("b", "Which controls?", "Arrow keys")),
        later: row("c", predecessor=parent, resolution=resolved("c", "Which camera?", "Isometric"))})
    state["managed_why1_rounds"] = dict(schema_version=1, active=why, rounds={
        why: {**row("d", "why1"), "tracker_parent": parent}})
    return state, why, parent, later


def test_pinned_why1_does_not_absorb_later_tracker_answers(history):
    from harness.tracker_clarification import previous_records
    state, why, parent, later = history
    before = deepcopy(state)
    records = previous_records(state, why, "why1")
    assert [(item.question, item.answer) for item in records] == [("Which controls?", "Arrow keys")]
    assert len(previous_records(state, later)) == 2
    assert state == before


@pytest.mark.parametrize("damage", ["missing", "unaccepted", "nonroot", "tracker_field"])
def test_tracker_parent_must_name_retained_accepted_tracker_at_why1_root(history, damage):
    from harness.discovery_producer import tracker_rounds
    state, why, parent, later = history
    root = state["managed_why1_rounds"]["rounds"][why]
    producer = "why1"
    if damage == "missing": root["tracker_parent"] = "tracker-" + "f" * 32
    elif damage == "unaccepted": state["managed_tracker_rounds"]["rounds"][parent]["operation"]["attempts"] = []
    elif damage == "nonroot":
        child = "why1-" + "e" * 32
        state["managed_why1_rounds"]["active"] = child
        state["managed_why1_rounds"]["rounds"][child] = {**row("e", "why1", predecessor=why,
            resolution=resolved("e", "Audience?", "Single player", "why1")), "tracker_parent": parent}
    else:
        state["managed_tracker_rounds"]["rounds"][later]["tracker_parent"] = parent
        producer = "tracker"
    with pytest.raises(ValueError): tracker_rounds(state, producer)


def test_generic_save_cannot_change_or_delete_parent(history, enrolled):
    from harness.squad_state import StateAdvanceError
    state, why, parent, later = history
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    original = store.load()
    for replacement in (None, later):
        changed = deepcopy(original)
        root = changed["managed_why1_rounds"]["rounds"][why]
        if replacement is None: del root["tracker_parent"]
        else: root["tracker_parent"] = replacement
        with pytest.raises(StateAdvanceError): store.save(changed)
        assert store.load() == original


def test_first_why1_selection_pins_the_accepted_tracker(history, enrolled):
    state, why, parent, later = history
    del state["managed_why1_rounds"]
    state.update(phase="phase1-why1", status="running", mode="greenfield",
        last_dispatch={**source("d"), "phase_id": "phase1-tracker", "post_dispatch_complete": True})
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    saved = store.prepare_why1_round(source("d"))
    assert saved["managed_why1_rounds"]["rounds"][why]["tracker_parent"] == later
    assert store.prepare_why1_round(source("d")) == saved


def test_legacy_parent_pin_is_once_bound_with_full_state_cas(history, enrolled):
    from harness.squad_state import StateAdvanceError, SquadStateStore
    state, why, parent, later = history
    del state["managed_why1_rounds"]["rounds"][why]["tracker_parent"]
    state.update(phase="phase1-why1", status="running", mode="greenfield")
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    before = store.load()
    stale = deepcopy(before)
    stale["state_revision"] += 1
    with pytest.raises(StateAdvanceError):
        store.pin_why1_tracker_parent(why, parent, source=source("d"), expected_state=stale)
    with pytest.raises(StateAdvanceError):
        store.pin_why1_tracker_parent(why, parent, source=source("f"), expected_state=before)
    saved = store.pin_why1_tracker_parent(why, parent, source=source("d"), expected_state=before)
    expected = deepcopy(before["managed_why1_rounds"])
    expected["rounds"][why]["tracker_parent"] = parent
    assert saved["managed_why1_rounds"] == expected
    for key in ("managed_tracker_rounds", "phase_dispatch_counts", "token_usage", "last_dispatch"):
        assert saved.get(key) == before.get(key)
    reopened = SquadStateStore(store.squad_dir)
    assert reopened.pin_why1_tracker_parent(why, parent, source=source("d"), expected_state=saved) == saved
    with pytest.raises(StateAdvanceError):
        reopened.pin_why1_tracker_parent(why, later, source=source("d"), expected_state=saved)
    assert store.load() == saved


@pytest.fixture
def refresh_history(history, retained):
    state, why, parent, later = history
    state["managed_tracker_rounds"]["active"] = parent
    del state["managed_tracker_rounds"]["rounds"][later]
    state["managed_discovery_repairs"] = retained[0]["managed_discovery_repairs"]
    unit, = state["managed_discovery_repairs"]["units"]
    repair = state["managed_discovery_repairs"]["units"][unit]
    answered = "why1-" + "e" * 32
    state["managed_why1_rounds"]["rounds"][answered] = row("e", "why1", predecessor=why,
        resolution=resolved("e", "Which audience?", "Single player", "why1"))
    # The retained repair fixture uses b as repair completion and c as requester.
    # Use another valid repair completion here to avoid the existing Tracker ID.
    repair_source = source("f")
    for producer, predecessor, predecessor_source in (("tracker", parent, source("9")),
            ("why1", answered, repair["selection"]["source"])):
        rounds = state["managed_" + producer + "_rounds"]
        operation_id = producer + "-" + "f" * 32
        rounds["active"] = operation_id
        rounds["rounds"][operation_id] = dict(source=repair_source, predecessor=predecessor,
            resolution=None, operation=None, turns=None, refresh=dict(repair_unit=unit,
                repair_source=repair_source, predecessor_source=predecessor_source))
    return state, why, parent, answered


def test_tracker_refresh_carries_why1_answers_without_duplicating_old_tracker(refresh_history):
    from harness.tracker_clarification import previous_records
    state, why, parent, answered = refresh_history
    records = previous_records(state, state["managed_tracker_rounds"]["active"])
    assert [(item.question, item.answer) for item in records] == [
        ("Which controls?", "Arrow keys"), ("Which audience?", "Single player")]
    assert [(item.question, item.answer) for item in previous_records(state, answered, "why1")] == [
        ("Which controls?", "Arrow keys"), ("Which audience?", "Single player")]
    # A subsequent answer appends to the exact existing human receipt/policy.
    from harness.clarification_candidate import ClarificationRecord, prepare_clarification_candidate
    first = prepare_clarification_candidate(decision=ClarificationRecord("dec-bbbbbbbb", "Which controls?", "Arrow keys"),
        previous=(), receipt_before=None, policy_before=None, artifacts={})
    second = prepare_clarification_candidate(decision=ClarificationRecord("dec-eeeeeeee", "Which audience?", "Single player"),
        previous=first.decisions, receipt_before=first.receipt_text, policy_before=first.policy_text, artifacts={})
    third = prepare_clarification_candidate(decision=ClarificationRecord("dec-99999999", "Which camera?", "Isometric"),
        previous=records, receipt_before=second.receipt_text, policy_before=second.policy_text, artifacts={})
    assert [(item.question, item.answer) for item in third.decisions] == [
        ("Which controls?", "Arrow keys"), ("Which audience?", "Single player"), ("Which camera?", "Isometric")]
    rounds = state["managed_tracker_rounds"]
    operation_id = "tracker-" + "9" * 32
    rounds["rounds"][operation_id] = row("9", predecessor=rounds["active"],
        resolution=resolved("9", "Which camera?", "Isometric"))
    rounds["active"] = operation_id
    assert [(item.question, item.answer) for item in previous_records(state, operation_id)] == [
        ("Which controls?", "Arrow keys"), ("Which audience?", "Single player"), ("Which camera?", "Isometric")]
    assert len(previous_records(state, answered, "why1")) == 2


def test_cross_producer_history_cycle_fails_closed(refresh_history):
    from harness.tracker_clarification import previous_records
    state, why, parent, answered = refresh_history
    rounds = state["managed_tracker_rounds"]
    operation_id = "tracker-" + "9" * 32
    rounds["rounds"][operation_id] = row("9", predecessor=rounds["active"],
        resolution=resolved("9", "Which camera?", "Isometric"))
    rounds["active"] = operation_id
    state["managed_why1_rounds"]["rounds"][why]["tracker_parent"] = operation_id
    with pytest.raises(ValueError, match="invalid clarification ancestry"):
        previous_records(state, operation_id)


def test_tracker_refresh_history_requires_requesting_why1_association(refresh_history):
    from harness.tracker_clarification import previous_records
    state, why, parent, answered = refresh_history
    rounds = state["managed_why1_rounds"]
    del rounds["rounds"][rounds["active"]]
    rounds["active"] = answered
    with pytest.raises(ValueError): previous_records(state, state["managed_tracker_rounds"]["active"])


def test_parent_admission_cannot_invent_a_released_repair(enrolled):
    from harness.discovery_repair_admission import pin_why1_tracker_history
    before = enrolled[1].load()
    with pytest.raises(ValueError): pin_why1_tracker_history(enrolled[0], enrolled[1])
    assert enrolled[1].load() == before


def test_parent_pin_must_match_the_proven_tracker_not_just_any_accepted_one(history):
    from types import SimpleNamespace
    from harness.discovery_completion import _require_why1_tracker_parent
    state, why, parent, later = history
    child = SimpleNamespace(producer="why1", clarification=False,
        recovery=dict(operation=dict(binding=dict(operation_id=why))))
    def binding(operation_id, producer="tracker"):
        return SimpleNamespace(producer=producer, clarification=False,
            recovery=dict(operation=dict(binding=dict(operation_id=operation_id))))
    _require_why1_tracker_parent(state, child, binding(parent))
    with pytest.raises(ValueError): _require_why1_tracker_parent(state, child, binding(later))
    with pytest.raises(ValueError): _require_why1_tracker_parent(state, child, binding(parent, "why1"))
    # Existing proof formats without the optional root association stay readable.
    del state["managed_why1_rounds"]["rounds"][why]["tracker_parent"]
    _require_why1_tracker_parent(state, child, binding(parent))

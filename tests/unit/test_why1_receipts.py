"""WHY1 journals retain exact report assignments and allocator receipts."""
from dataclasses import replace
import json

import pytest

from tests.unit.test_discovery_turns import case, enrolled

from harness.discovery_receipts import DiscoveryReceiptFile
from harness.discovery_reservations import DiscoveryReservationJournal
from harness.discovery_turns import _assignment, _validate, _usage
from tests.unit.test_discovery_reservations import managed, database_rows, Interrupted
from tests.unit.test_why1_candidate import assignment, reply, routing


@pytest.mark.parametrize("damage", ["foreign_round", "two_roots", "generic_save", "unaccepted_parent"])
def test_why1_round_selection_requires_its_existing_state_owner(enrolled, damage):
    from copy import deepcopy
    from harness.discovery_producer import tracker_rounds
    from harness.squad_state import StateAdvanceError
    store = enrolled[1]
    before = store.load()
    source = dict(dispatch_id="a" * 32, completion_intent_sha256="1" * 64,
        completion_receipts_sha256="2" * 64, completed_publication_binding_sha256="3" * 64)
    operation_id = "why1-" + "a" * 32
    row = dict(source=source, resolution=None, predecessor=None, operation=None, turns=None)
    state = deepcopy(before)
    state["managed_why1_rounds"] = dict(schema_version=1, active=operation_id, rounds={operation_id: row})
    if damage == "generic_save":
        with pytest.raises(StateAdvanceError):
            store.save(state)
    elif damage == "unaccepted_parent":
        with pytest.raises(StateAdvanceError):
            store.prepare_why1_round(source)
    else:
        rounds = state["managed_why1_rounds"]
        if damage == "foreign_round":
            rounds["active"] = "tracker-" + "a" * 32
            rounds["rounds"] = {rounds["active"]: row}
        else:
            extra = deepcopy(row)
            extra["source"]["dispatch_id"] = "b" * 32
            rounds["rounds"]["why1-" + "b" * 32] = extra
        with pytest.raises(ValueError):
            tracker_rounds(state, "why1")
    assert store.load() == before


def select(journal, case, operation, create=False):
    journal.select(case[2], spec_id="game", run_id="first", operation_id=operation,
        managed_identity=case[3], create=create)


@pytest.mark.parametrize("step", ["propose", "author", "review"])
def test_why1_saved_turn_retains_routing_and_usage(step):
    bound = assignment(step, verdict="FAIL")
    restored = _assignment(json.loads(json.dumps(bound.identity())))
    assert restored == bound
    record = dict(schema_version=1, binding={}, token_budget=100, dispatch_limit=9, steps=[dict(
        assignment=bound.identity(), input_sha256="a" * 64, deadline=1, records=[dict(
            prompt_sha256="b" * 64, reply=reply(bound, verdict="FAIL"), read=None, token_usage=7, error=None, accepted=True)])])
    _validate(record)
    assert _usage(record) == dict(tokens=7, known=True, dispatches=1)


def test_why1_two_rounds_retain_separate_reservations(managed):
    originals = []
    for number, digit in enumerate(("a", "b"), 1):
        bound = replace(assignment(), operation_id="why1-" + digit * 32)
        value = reply(bound)
        value["new_subjects"].append(dict(key="question", kind="U", subject="Controls", caption="Controls"))
        with DiscoveryReservationJournal(managed[1], producer="why1", round_operation_id=bound.operation_id) as journal:
            select(journal, managed, bound.operation_id, True)
            allocated = journal.bind(bound, value)
            assert [(row.key, row.element_id) for row in allocated] == [("audience", f"ISS-{number:06d}"), ("question", f"U-{number:06d}")]
            originals.append((journal.path, journal.path.read_bytes(), bound, value, allocated))
    before = database_rows(managed[0])
    for path, raw, bound, value, allocated in originals:
        with DiscoveryReservationJournal(managed[1], producer="why1", round_operation_id=bound.operation_id) as journal:
            select(journal, managed, bound.operation_id)
            assert journal.bind(bound, value, replay_only=True) == allocated
        assert path.read_bytes() == raw
    assert database_rows(managed[0]) == before


@pytest.mark.parametrize("kind", ["U", "ISS"])
@pytest.mark.parametrize("when", ["before", "after"])
def test_why1_allocator_interruption_reuses_exact_reservation(managed, monkeypatch, kind, when):
    bound = assignment(kind=kind)
    value = reply(bound, kind=kind)
    original = managed[2].reserve
    def interrupt(**kwargs):
        if when == "before": raise Interrupted()
        original(**kwargs)
        raise Interrupted()
    with DiscoveryReservationJournal(managed[1], producer="why1", round_operation_id=bound.operation_id) as journal:
        select(journal, managed, bound.operation_id, True)
        with monkeypatch.context() as patch:
            patch.setattr(managed[2], "reserve", interrupt)
            with pytest.raises(Interrupted): journal.bind(bound, value)
    with DiscoveryReservationJournal(managed[1], producer="why1", round_operation_id=bound.operation_id) as journal:
        select(journal, managed, bound.operation_id)
        assert [row.element_id for row in journal.bind(bound, value)] == [kind + "-000001"]
    assert managed[2].reserve(spec_id="game", kind=kind, operation_id="next", count=1) == (kind + "-000002",)


@pytest.mark.parametrize("producer,operation", [("why1", None), ("why1", "tracker-" + "a" * 32), ("tracker", "why1-" + "a" * 32), ("why1", "../escape")])
def test_why1_receipts_cannot_use_another_producer_namespace(tmp_path, producer, operation):
    with pytest.raises(ValueError):
        DiscoveryReceiptFile(tmp_path, "discovery-turns", producer=producer, round_operation_id=operation)
    assert list(tmp_path.iterdir()) == []

"""WHY1 re-review binds the exact accepted Tracker and its human history."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tests.unit.test_tracker_refresh_input import case, enrolled, retained, after_synthesis
from tests.unit.test_refresh_activation import activation_state
from tests.unit.test_why1_tracker_parent import source, row, resolved


@pytest.fixture
def after_tracker(after_synthesis):
    state = activation_state(after_synthesis)
    rounds = state["managed_tracker_rounds"]
    target = rounds["rounds"][rounds["active"]]
    target["operation"] = row("b")["operation"]
    state["phase_dispatch_counts"]["phase1-tracker"] = 2
    state["last_dispatch"] = {**source("f"), "phase_id": "phase1-tracker", "post_dispatch_complete": True}
    return state, dict(source=source("f"), dependencies=dict(
        before_sha256="1" * 64, after_sha256="2" * 64, changed=["identity"]))


def test_why1_input_and_tracker_history_are_bound_once(after_tracker, enrolled):
    from harness.discovery_producer import tracker_round, tracker_input_source
    from harness.squad_state import StateAdvanceError, SquadStateStore
    state, bound = after_tracker
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    before = store.load()
    saved = store.bind_refresh_input("why1", bound, expected_state=before)
    current = tracker_round(saved, producer="why1")
    assert current["tracker_parent"] == "tracker-" + "b" * 32
    assert tracker_input_source(saved, producer="why1") == source("f")
    assert current["source"] == source("b")
    for key in ("phase", "last_dispatch", "phase_dispatch_counts", "token_usage", "managed_tracker_rounds"):
        assert saved.get(key) == before.get(key)
    assert SquadStateStore(store.squad_dir).bind_refresh_input("why1", bound, expected_state=saved) == saved
    with pytest.raises(StateAdvanceError): store.bind_refresh_input("why1", bound, expected_state=before)
    for field in ("execution_input", "tracker_parent"):
        edited = deepcopy(saved)
        del edited["managed_why1_rounds"]["rounds"][edited["managed_why1_rounds"]["active"]][field]
        with pytest.raises(StateAdvanceError): store.save(edited)
    assert store.load() == saved


@pytest.mark.parametrize("changed", [True, False])
def test_why1_bound_refresh_can_execute_without_replacing_original(after_tracker, enrolled, changed):
    from harness.discovery_operation_state import operation_from_state
    state, bound = after_tracker
    if not changed:
        bound["dependencies"].update(after_sha256="1" * 64, changed=[])
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    saved = store.bind_refresh_input("why1", bound, expected_state=store.load())
    binding = row("b", "why1")["operation"]["binding"]
    begun = store.advance_discovery_operation(binding, "prepare", producer="why1")
    assert operation_from_state(begun, "why1")["binding"] == binding
    assert begun["managed_why1_rounds"]["rounds"]["why1-" + "d" * 32] == saved["managed_why1_rounds"]["rounds"]["why1-" + "d" * 32]
    assert store.advance_discovery_operation(binding, "prepare", producer="why1") == begun


def test_refresh_parent_requires_exact_nonclarification_tracker(after_tracker):
    from harness.discovery_completion import _require_refresh_parent
    state, bound = after_tracker
    refresh = state["managed_why1_rounds"]["rounds"][state["managed_why1_rounds"]["active"]]["refresh"]
    child = SimpleNamespace(recovery=dict(version=11, refresh=refresh, execution_input=bound,
        tracker_parent="tracker-" + "b" * 32))
    parent = SimpleNamespace(producer="tracker", clarification=False,
        recovery=dict(operation=dict(binding=dict(operation_id="tracker-" + "b" * 32))))
    _require_refresh_parent(child, parent, source("f"))
    for altered in (SimpleNamespace(**{**vars(parent), "clarification": True}),
            SimpleNamespace(**{**vars(parent), "producer": "why1"}),
            SimpleNamespace(**{**vars(parent), "recovery": dict(operation=dict(binding=dict(operation_id="tracker-" + "d" * 32)))})):
        with pytest.raises(ValueError): _require_refresh_parent(child, altered, source("f"))


def test_bound_why1_history_includes_new_tracker_answer_without_changing_old(after_tracker, enrolled):
    from harness.tracker_clarification import previous_records
    state, bound = after_tracker
    rounds = state["managed_tracker_rounds"]
    later = "tracker-" + "9" * 32
    rounds["rounds"][later] = row("9", predecessor=rounds["active"],
        resolution=resolved("9", "Which lighting?", "Daylight"))
    rounds["active"] = later
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    saved = store.bind_refresh_input("why1", bound, expected_state=store.load())
    active = saved["managed_why1_rounds"]["active"]
    assert [(item.question, item.answer) for item in previous_records(saved, active, "why1")] == [("Which lighting?", "Daylight")]
    assert previous_records(saved, "why1-" + "d" * 32, "why1") == ()


@pytest.mark.parametrize("producer", ["tracker", "why1"])
def test_old_answer_does_not_select_a_new_refresh_clarification(after_tracker, enrolled, producer, monkeypatch):
    from tests.unit.test_discovery_completion import controller
    from tests.unit.test_discovery_normal_entry import selection, FullDiscoveryExecutor
    state, bound = after_tracker
    store = enrolled[1]
    if producer == "why1":
        rounds = state["managed_why1_rounds"]
        rounds["rounds"][rounds["active"]].update(execution_input=bound, tracker_parent="tracker-" + "b" * 32)
    else:
        state["last_dispatch"] = {**source("e"), "phase_id": "phase1-synthesizer", "post_dispatch_complete": True}
        rounds = state["managed_tracker_rounds"]
        rounds["rounds"][rounds["active"]]["operation"] = None
    state["phase"] = "phase1-" + producer
    old = resolved("8", "Earlier question", "Earlier answer", producer)
    state.update(blocked_decision=old["decision"], last_human_input_completion=old["completion"])
    # Isolate continuation selection before the existing dispatch guard. Real
    # admission, receipt and history are covered by the full recovery test.
    state["phase_dispatch_counts"][state["phase"]] = 100
    store._path.write_text(json.dumps(state))
    before = store.load()
    executor = FullDiscoveryExecutor()
    runner = controller(enrolled, executor)
    monkeypatch.setattr(runner, "_prepare_managed_repair_refresh", lambda selected: None)
    result = runner._run_managed_discovery_locked({**selection(enrolled), "through_phase": "phase1-why1"})
    assert result.summary == "phase_dispatch_limit", result
    assert store.load() == before and executor.calls == []

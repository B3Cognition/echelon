"""Refresh phase selection preserves durable source and accounting ownership."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_tracker_refresh_input import case, enrolled, after_synthesis, retained
from tests.unit.test_why1_tracker_parent import row, source


def activation_state(after_synthesis):
    state, bound = after_synthesis
    rounds = state["managed_tracker_rounds"]
    rounds["rounds"][rounds["active"]]["execution_input"] = bound
    previous = row("d", "why1")
    previous["tracker_parent"] = "tracker-" + "d" * 32
    state["managed_why1_rounds"] = dict(schema_version=1, active="why1-" + "b" * 32,
        rounds={"why1-" + "d" * 32: previous, "why1-" + "b" * 32: dict(
            source=source("b"), resolution=None, predecessor="why1-" + "d" * 32,
            operation=None, turns=None, refresh={**rounds["rounds"][rounds["active"]]["refresh"],
                "predecessor_source": source("c")})})
    previous["operation"]["binding"]["operation_id"] = "why1-" + "d" * 32
    return state


@pytest.mark.parametrize("producer", ["synthesizer", "tracker"])
@pytest.mark.parametrize("changed", [True, False])
def test_refresh_activation_is_exact_cas_and_does_not_charge(after_synthesis, enrolled, producer, changed):
    from harness.squad_state import StateAdvanceError, SquadStateStore
    state = activation_state(after_synthesis)
    if not changed:
        rounds = state["managed_" + producer + "_rounds"]
        rounds["rounds"][rounds["active"]]["execution_input"]["dependencies"].update(after_sha256="1" * 64, changed=[])
    if producer == "synthesizer":
        rounds = state["managed_synthesizer_rounds"]
        rounds["rounds"][rounds["active"]]["operation"] = None
        state["phase_dispatch_counts"]["phase1-synthesizer"] = 1
        state["last_dispatch"] = {**source("b"), "phase_id": "phase1-discover", "post_dispatch_complete": True}
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    before = store.load()
    stale = deepcopy(before)
    stale["state_revision"] += 1
    with pytest.raises(StateAdvanceError): store.activate_refresh_round(producer, expected_state=stale)
    saved = store.activate_refresh_round(producer, expected_state=before)
    expected = {**before, "phase": "phase1-" + producer, "state_revision": saved["state_revision"],
        "updated_at": saved["updated_at"]}
    assert saved == expected
    assert SquadStateStore(store.squad_dir).activate_refresh_round(producer, expected_state=saved) == saved


@pytest.mark.parametrize("damage", ["unbound", "source", "pending", "cancelled", "history", "phase", "parent_phase"])
def test_refresh_activation_cannot_bypass_admission(after_synthesis, enrolled, damage):
    from harness.squad_state import StateAdvanceError
    state = activation_state(after_synthesis)
    rounds = state["managed_tracker_rounds"]
    target = rounds["rounds"][rounds["active"]]
    if damage == "unbound": del target["execution_input"]
    elif damage == "source": state["last_dispatch"].update(source("f"))
    elif damage == "pending": state["pending_controller_completion"] = {}
    elif damage == "cancelled": state["cancel_requested"] = True
    elif damage == "phase": state["phase"] = "phase1-discover"
    elif damage == "parent_phase": state["last_dispatch"]["phase_id"] = "phase1-discover"
    else: del state["managed_why1_rounds"]
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    with pytest.raises(StateAdvanceError): store.activate_refresh_round("tracker", expected_state=store.load())


def test_active_operation_retries_but_cannot_be_reactivated(after_synthesis, enrolled):
    from harness.squad_state import StateAdvanceError
    state = activation_state(after_synthesis)
    state["phase"] = "phase1-tracker"
    rounds = state["managed_tracker_rounds"]
    target = rounds["rounds"][rounds["active"]]
    target["operation"] = deepcopy(rounds["rounds"][target["predecessor"]]["operation"])
    target["operation"]["binding"]["operation_id"] = rounds["active"]
    target["operation"]["attempts"] = []
    state["phase_dispatch_counts"]["phase1-tracker"] = 2
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    saved = store.load()
    assert store.activate_refresh_round("tracker", expected_state=saved) == saved
    store.save({**saved, "phase": "phase1-why1"})
    before = store.load()
    with pytest.raises(StateAdvanceError): store.activate_refresh_round("tracker", expected_state=before)
    assert store.load() == before


def test_controller_applies_cumulative_synthesis_refresh_cap(after_synthesis, enrolled):
    from tests.unit.test_discovery_completion import controller
    from tests.unit.test_discovery_normal_entry import selection, FullDiscoveryExecutor
    state = activation_state(after_synthesis)
    rounds = state["managed_synthesizer_rounds"]
    rounds["rounds"][rounds["active"]]["operation"] = None
    state["phase"] = "phase1-synthesizer"
    # This exercises the dispatch guard directly, not retained-count admission.
    # Full controller tests separately prove admitted history and actual routing.
    state["phase_dispatch_counts"]["phase1-synthesizer"] = 5
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    before = store.load()
    executor = FullDiscoveryExecutor()
    result = controller(enrolled, executor)._run_managed_discovery_locked({**selection(enrolled), "through_phase": "phase1-why1"})
    assert result.summary == "phase_dispatch_limit", result
    assert store.load() == before and executor.calls == []

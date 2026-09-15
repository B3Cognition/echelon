"""Tracker's actual parent is the accepted refreshed Synthesis, not repair origin."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_synthesis_refresh_selection import case, enrolled, retained
from tests.unit.test_why1_tracker_parent import row, source


@pytest.fixture
def after_synthesis(retained):
    # State-only fixture: retained proof authentication has separate real tests.
    state, _, synthesis_id = retained
    synthesis = state["managed_synthesizer_rounds"]["rounds"][synthesis_id]
    dependencies = dict(before_sha256="1" * 64, after_sha256="2" * 64, changed=["identity"])
    synthesis["execution_input"] = dict(source=synthesis["source"], dependencies=dependencies)
    synthesis["operation"] = deepcopy(state["managed_synthesizer_operation"])
    synthesis["operation"]["binding"]["operation_id"] = synthesis_id
    original_id, refresh_id = "tracker-" + "d" * 32, "tracker-" + "b" * 32
    state["managed_tracker_rounds"] = dict(schema_version=1, active=refresh_id, rounds={
        original_id: row("d"), refresh_id: dict(source=synthesis["source"], resolution=None,
            predecessor=original_id, operation=None, turns=None, refresh={**synthesis["refresh"],
                "predecessor_source": source("c")})})
    state.update(phase="phase1-why1", status="running", mode="greenfield",
        last_dispatch={**source("e"), "phase_id": "phase1-synthesizer", "post_dispatch_complete": True})
    state["phase_dispatch_counts"].update({"phase1-synthesizer": 2, "phase1-tracker": 1})
    return state, dict(source=source("e"), dependencies=deepcopy(dependencies))


def test_tracker_actual_input_does_not_fall_back_to_repair_origin(after_synthesis):
    from harness.discovery_producer import tracker_input_source
    state, bound = after_synthesis
    rounds = state["managed_tracker_rounds"]
    with pytest.raises(ValueError): tracker_input_source(state)
    rounds["rounds"][rounds["active"]]["execution_input"] = bound
    assert tracker_input_source(state) == source("e")
    assert rounds["rounds"][rounds["active"]]["source"] == source("b")


def test_tracker_input_owner_binds_once_without_rewriting_history(after_synthesis, enrolled):
    from harness.squad_state import StateAdvanceError, SquadStateStore
    state, bound = after_synthesis
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    before = store.load()
    stale = deepcopy(before)
    stale["state_revision"] += 1
    with pytest.raises(StateAdvanceError):
        store.bind_refresh_input("tracker", bound, expected_state=stale)
    saved = store.bind_refresh_input("tracker", bound, expected_state=before)
    expected = deepcopy(before)
    rounds = expected["managed_tracker_rounds"]
    rounds["rounds"][rounds["active"]]["execution_input"] = bound
    expected["state_revision"] = saved["state_revision"]
    expected["updated_at"] = saved["updated_at"]
    assert saved == expected
    assert SquadStateStore(store.squad_dir).bind_refresh_input("tracker", bound, expected_state=saved) == saved
    for changed in (dict(source=source("f"), dependencies=bound["dependencies"]),
            dict(source=source("b"), dependencies=bound["dependencies"])):
        with pytest.raises(StateAdvanceError): store.bind_refresh_input("tracker", changed, expected_state=saved)
    for delete in (False, True):
        edited = deepcopy(saved)
        target = edited["managed_tracker_rounds"]["rounds"][rounds["active"]]
        if delete: del target["execution_input"]
        else: target["execution_input"]["source"] = source("f")
        with pytest.raises(StateAdvanceError): store.save(edited)
    assert store.load() == saved


@pytest.mark.parametrize("damage", ["repair_head", "unaccepted_synthesis", "different_completion"])
def test_tracker_input_cannot_bypass_accepted_synthesis(after_synthesis, enrolled, damage):
    from harness.squad_state import StateAdvanceError
    state, bound = after_synthesis
    synthesis_rounds = state["managed_synthesizer_rounds"]
    synthesis = synthesis_rounds["rounds"][synthesis_rounds["active"]]
    if damage == "repair_head":
        state["last_dispatch"] = {**source("b"), "phase_id": "phase1-discover", "post_dispatch_complete": True}
        bound["source"] = source("b")
    elif damage == "unaccepted_synthesis": synthesis["operation"]["attempts"] = []
    else: bound["source"] = source("f")
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    with pytest.raises(StateAdvanceError):
        store.bind_refresh_input("tracker", bound, expected_state=state)


@pytest.mark.parametrize("changed", [True, False])
def test_tracker_refresh_retains_round_attempt_limit_and_charges_once(after_synthesis, enrolled, changed):
    from harness.discovery_operation_state import operation_from_state
    from harness.squad_state import StateAdvanceError
    state, bound = after_synthesis
    if not changed:
        bound["dependencies"].update(after_sha256="1" * 64, changed=[])
    rounds = state["managed_tracker_rounds"]
    target = rounds["rounds"][rounds["active"]]
    target["execution_input"] = bound
    previous = deepcopy(rounds["rounds"][target["predecessor"]])
    binding = {**previous["operation"]["binding"], "operation_id": rounds["active"]}
    state["phase"] = "phase1-tracker"
    store = enrolled[1]
    store._path.write_text(json.dumps(state))
    saved = store.advance_discovery_operation(binding, "prepare", producer="tracker")
    assert saved["phase_dispatch_counts"]["phase1-tracker"] == 2
    assert store.advance_discovery_operation(binding, "prepare", producer="tracker") == saved
    for attempt in range(1, 4):
        saved = store.advance_discovery_operation(binding, "begin", producer="tracker")
        assert len(operation_from_state(saved, "tracker")["attempts"]) == attempt
        saved = store.advance_discovery_operation(binding, "finish", result=dict(status="rejected",
            candidate_sha256=str(attempt) * 64, findings_sha256="c" * 64), producer="tracker")
    with pytest.raises(StateAdvanceError): store.advance_discovery_operation(binding, "begin", producer="tracker")
    assert saved["managed_tracker_rounds"]["rounds"][target["predecessor"]] == previous


@pytest.mark.parametrize("damage", ["unbound", "wrong_phase"])
def test_unadmitted_tracker_refresh_cannot_start(after_synthesis, damage):
    from harness.discovery_operation_state import advance_operation
    state, bound = after_synthesis
    rounds = state["managed_tracker_rounds"]
    target = rounds["rounds"][rounds["active"]]
    target["execution_input"] = bound
    binding = {**rounds["rounds"][target["predecessor"]]["operation"]["binding"], "operation_id": rounds["active"]}
    state["phase"] = "phase1-tracker"
    if damage == "unbound": del target["execution_input"]
    else: state["phase"] = "phase1-why1"
    with pytest.raises(ValueError): advance_operation(state, binding, "prepare", producer="tracker")


def test_refresh_proof_parent_requires_the_same_repair_and_actual_source(after_synthesis):
    from types import SimpleNamespace
    from harness.discovery_completion import _require_refresh_parent
    state, bound = after_synthesis
    row = state["managed_tracker_rounds"]["rounds"][state["managed_tracker_rounds"]["active"]]
    child = SimpleNamespace(recovery=dict(version=10, refresh=row["refresh"], execution_input=bound))
    parent = SimpleNamespace(producer="synthesizer", repair_unit=None,
        recovery=dict(version=9, refresh=deepcopy(row["refresh"])))
    _require_refresh_parent(child, parent, source("e"))
    for damage in ("repair", "version", "producer", "origin", "actual_input"):
        altered = deepcopy(parent)
        actual = source("e")
        if damage == "repair": altered.recovery["refresh"]["repair_unit"] = "0" * 64
        elif damage == "version": altered.recovery["version"] = 3
        elif damage == "producer": altered.producer = "tracker"
        elif damage == "origin": altered.recovery["refresh"]["repair_source"] = source("f")
        else: actual = source("b")
        with pytest.raises(ValueError): _require_refresh_parent(child, altered, actual)

"""Refresh execution retains original Synthesis and consumes a bound repair input."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_synthesis_refresh_selection import case, enrolled, retained


def selected(retained, *, changed=True):
    state, _, refresh = retained
    row = state["managed_synthesizer_rounds"]["rounds"][refresh]
    row["execution_input"] = dict(source=deepcopy(row["source"]), dependencies=dict(
        before_sha256="a" * 64, after_sha256=("b" if changed else "a") * 64,
        changed=["identity"] if changed else []))
    state["phase"] = "phase1-synthesizer"
    binding = {**state["managed_synthesizer_operation"]["binding"], "operation_id": refresh}
    return state, binding


def test_bound_refresh_uses_round_attempts_without_changing_original(retained):
    from harness.discovery_operation_state import advance_operation, operation_from_state
    state, binding = selected(retained)
    original = deepcopy(state["managed_synthesizer_operation"])
    state = advance_operation(state, binding, "prepare", producer="synthesizer")
    for attempt in range(1, 4):
        state = advance_operation(state, binding, "begin", producer="synthesizer")
        assert len(operation_from_state(state, "synthesizer")["attempts"]) == attempt
        state = advance_operation(state, binding, "finish", dict(status="rejected",
            candidate_sha256=str(attempt) * 64, findings_sha256="c" * 64), producer="synthesizer")
    assert state["managed_synthesizer_operation"] == original
    with pytest.raises(ValueError): advance_operation(state, binding, "begin", producer="synthesizer")


@pytest.mark.parametrize("damage", ["unbound", "unchanged", "wrong_phase"])
def test_unadmitted_refresh_cannot_start_attempts(retained, damage):
    from harness.discovery_operation_state import advance_operation
    state, binding = selected(retained, changed=damage != "unchanged")
    if damage == "unbound":
        del state["managed_synthesizer_rounds"]["rounds"][binding["operation_id"]]["execution_input"]
    if damage == "wrong_phase": state["phase"] = "phase1-why1"
    before = deepcopy(state)
    with pytest.raises(ValueError): advance_operation(state, binding, "prepare", producer="synthesizer")
    assert state == before


def test_state_owner_keeps_original_immutable_and_charges_refresh_once(retained, enrolled):
    from harness.squad_state import StateAdvanceError, SquadStateStore
    state, binding = selected(retained)
    store = enrolled[1]
    # Seed a structurally valid state for the state-owner test only. The separate
    # real-publication case must establish and authenticate all these records.
    store._path.write_text(json.dumps(state))
    original = store.load()
    saved = store.advance_discovery_operation(binding, "prepare", producer="synthesizer")
    assert saved["phase_dispatch_counts"]["phase1-synthesizer"] == 2
    assert store.advance_discovery_operation(binding, "prepare", producer="synthesizer") == saved
    marker = dict(schema_version=1, operation_id=binding["operation_id"], binding_sha256="f" * 64)
    saved = store.prepare_discovery_turns(marker, producer="synthesizer")
    assert SquadStateStore(store.squad_dir).prepare_discovery_turns(marker, producer="synthesizer") == saved
    for suffix in ("source", "operation", "turns"):
        key = "managed_synthesizer_" + suffix
        assert saved[key] == original[key]
        damaged = deepcopy(saved)
        del damaged[key]
        with pytest.raises(StateAdvanceError): store.save(damaged)
    damaged = deepcopy(saved)
    del damaged["managed_synthesizer_rounds"]["rounds"][binding["operation_id"]]["execution_input"]
    with pytest.raises(StateAdvanceError): store.save(damaged)
    assert store.load() == saved


def test_refresh_input_reader_never_falls_back_to_original_discovery(retained):
    from harness.discovery_producer import synthesis_input_source
    state, original, _ = retained
    with pytest.raises(ValueError): synthesis_input_source(state)
    state, binding = selected(retained)
    row = state["managed_synthesizer_rounds"]["rounds"][binding["operation_id"]]
    assert synthesis_input_source(state) == row["execution_input"]["source"]
    assert synthesis_input_source(state, original) == state["managed_synthesizer_source"]
    assert synthesis_input_source(state) != synthesis_input_source(state, original)

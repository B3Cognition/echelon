"""Strategy state/receipt shape tests do not confer released gate authority."""
from copy import deepcopy
import json

import pytest

from harness.discovery_operation_state import operation_from_state
from harness.discovery_producer import tracker_round, tracker_rounds
from harness.discovery_receipts import DiscoveryReceiptFile, receipt_round_operation_id
from harness.squad_state import StateAdvanceError
from tests.unit.test_discovery_turns import case, enrolled
from tests.unit.test_why1_tracker_parent import source


@pytest.fixture
def gate(enrolled):
    _, store, _, _ = enrolled
    state = store.load()
    state.update(phase="phase2-strategic-overview", feasibility_verdict="PASS",
        last_dispatch={**source("a"), "phase_id": "phase2-feasibility-structural", "post_dispatch_complete": True})
    store._path.write_text(json.dumps(state))
    return enrolled


def binding():
    return dict(operation_id="strategy-" + "a" * 32, spec_id="game", run_id="first",
        input_tree="inputs", artifact_paths=["strategic-overview.md"], editable_revisions=[],
        unowned_writable_paths=["strategic-overview.md"], intent=dict(kind="strategize", request="Map approved scope risks"), fingerprint="b" * 64)


def test_strategy_selection_and_components_require_owner_and_full_cas(gate):
    _, store, _, _ = gate
    before = store.load()
    selected = store.prepare_spec_round("strategy", source("a"), expected_state=before)
    assert store.prepare_spec_round("strategy", source("a"), expected_state=selected) == selected
    assert tracker_round(selected, producer="strategy") == dict(source=source("a"), resolution=None,
        predecessor=None, operation=None, turns=None)
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("strategy", source("a"), expected_state=before)
    saved = store.advance_discovery_operation(binding(), "prepare", producer="strategy")
    assert operation_from_state(saved, "strategy")["binding"] == binding()
    assert saved["phase_dispatch_counts"]["phase2-strategic-overview"] == 1
    assert store.advance_discovery_operation(binding(), "prepare", producer="strategy") == saved
    for damage in ("drop", "source", "operation", "turns", "resolution", "predecessor"):
        changed = deepcopy(saved)
        rounds = changed["managed_strategy_rounds"]
        row = rounds["rounds"][rounds["active"]]
        if damage == "drop": del changed["managed_strategy_rounds"]
        elif damage == "source": row["source"] = source("b")
        elif damage == "operation": row["operation"] = None
        elif damage == "turns": row["turns"] = {}
        elif damage == "resolution": row["resolution"] = {}
        else: row["predecessor"] = rounds["active"]
        with pytest.raises(StateAdvanceError): store.save(changed)
    assert store.load() == saved
    assert receipt_round_operation_id("strategy", binding()["operation_id"]) == binding()["operation_id"]
    assert DiscoveryReceiptFile(store.squad_dir, "discovery-turns", producer="strategy",
        round_operation_id=binding()["operation_id"]).path != DiscoveryReceiptFile(store.squad_dir,
            "discovery-reservations", producer="strategy", round_operation_id=binding()["operation_id"]).path


@pytest.mark.parametrize("damage", ["phase", "parent", "unfinished", "cancelled", "blocked", "source", "pending"])
def test_strategy_selection_refuses_unsettled_or_detached_parent(gate, damage):
    _, store, _, _ = gate
    state = store.load()
    if damage == "phase": state["phase"] = "phase2-tracker-alignment"
    elif damage == "parent": state["last_dispatch"]["phase_id"] = "phase2-decide"
    elif damage == "unfinished": state["last_dispatch"]["post_dispatch_complete"] = False
    elif damage == "cancelled": state["cancel_requested"] = True
    elif damage == "blocked": state["status"] = "blocked"
    elif damage == "source": state["last_dispatch"].update(source("b"))
    else: state["_spec_step_publication_plan"] = {}
    store._path.write_text(json.dumps(state))
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("strategy", source("a"), expected_state=state)
    assert store.load() == state


@pytest.mark.parametrize("operation", [None, "strategy-../escape", "feasibility-" + "a" * 32])
def test_strategy_receipts_refuse_missing_or_foreign_round(gate, operation):
    with pytest.raises(ValueError):
        DiscoveryReceiptFile(gate[1].squad_dir, "discovery-turns", producer="strategy", round_operation_id=operation)

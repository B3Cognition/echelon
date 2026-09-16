"""Retained requirement/review selections use the existing state and turn owners."""
from copy import deepcopy

import pytest

from tests.unit.test_discovery_turns import case, enrolled
from tests.unit.test_why1_tracker_parent import source


@pytest.mark.parametrize("damage", [None, "source", "parent", "decision_owner", "handler", "missing_pair", "constitution"])
def test_what_retains_requesting_review_answer_without_owning_it(enrolled, damage):
    from tests.unit.test_why1_tracker_parent import row, resolved
    from harness.discovery_producer import tracker_rounds
    from harness.discovery_spec import clarification_source
    state = enrolled[1].load()
    first, parent, answer = "what-" + "a" * 32, "why2-" + "b" * 32, "what-" + "c" * 32
    state["managed_why2_rounds"] = dict(schema_version=1, active=parent, rounds={parent: row("b", "why2")})
    association = resolved("c", "Is deployment required?", "No deployment.", "why2")
    current = dict(source=clarification_source(association["completion"]), resolution=None,
        predecessor=first, operation=None, turns=None, review_resolution=association, review_parent=parent)
    state["managed_what_rounds"] = dict(schema_version=1, active=answer, rounds={first: row("a", "what"), answer: current})
    if damage == "source": current["source"] = source("f")
    elif damage == "parent": current["review_parent"] = "why2-" + "f" * 32
    elif damage == "decision_owner": association["decision"]["source_phase"] = "phase1-what"
    elif damage == "handler": association["decision"]["resolution_handler"] = "reset_why_fail_count"
    elif damage == "missing_pair": del current["review_parent"]
    elif damage == "constitution": current["constitution_parent"] = "constitution-refresh-" + "d" * 32
    before = deepcopy(state)
    if damage is None:
        actual = tracker_rounds(state, "what")["rounds"][answer]
        assert actual["resolution"] is None and actual["review_resolution"] == association
    else:
        with pytest.raises(ValueError):
            tracker_rounds(state, "what")
    assert state == before


@pytest.mark.parametrize("producer,parent", [("what", "constitution"), ("why2", "understanding")])
def test_spec_round_selection_is_cas_protected_and_charges_operation_once(enrolled, producer, parent):
    from harness.squad_state import StateAdvanceError
    from harness.discovery_producer import tracker_round
    from harness.discovery_operation_state import operation_from_state
    root, store, _, _ = enrolled
    state = store.load()
    state.update(phase="phase1-" + producer, last_dispatch={**source("a"), "phase_id": "phase1-" + parent,
        "post_dispatch_complete": True})
    store.save(state)
    before = store.load()
    selected = store.prepare_spec_round(producer, source("a"), expected_state=before)
    assert store.prepare_spec_round(producer, source("a"), expected_state=selected) == selected
    assert selected["phase_dispatch_counts"] == before["phase_dispatch_counts"]
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round(producer, source("a"), expected_state=before)
    paths = ["spec.md", "requirements-overview.md"] if producer == "what" else ["quality-gates.md", "issues.md"]
    binding = dict(operation_id=producer + "-" + "a" * 32, spec_id="game", run_id="first", input_tree="inputs",
        artifact_paths=paths, editable_revisions=[], unowned_writable_paths=paths,
        intent=dict(kind="specify" if producer == "what" else "validate", request="Create a game"), fingerprint="b" * 64)
    prepared = store.advance_discovery_operation(binding, "prepare", producer=producer)
    assert operation_from_state(prepared, producer)["binding"] == binding
    assert prepared["phase_dispatch_counts"]["phase1-" + producer] == 1
    assert store.advance_discovery_operation(binding, "prepare", producer=producer) == prepared
    assert tracker_round(prepared, producer=producer)["source"] == source("a")
    for mutate in ("drop", "source", "operation", "active"):
        changed = deepcopy(prepared)
        rounds = changed["managed_" + producer + "_rounds"]
        if mutate == "drop":
            del changed["managed_" + producer + "_rounds"]
        elif mutate == "source":
            rounds["rounds"][rounds["active"]]["source"] = source("b")
        elif mutate == "operation":
            rounds["rounds"][rounds["active"]]["operation"] = None
        else:
            rounds["active"] = producer + "-" + "b" * 32
        with pytest.raises(StateAdvanceError):
            store.save(changed)


@pytest.mark.parametrize("producer,parent", [("what", "why1"), ("why2", "what")])
def test_spec_round_rejects_skipping_required_parent(enrolled, producer, parent):
    from harness.squad_state import StateAdvanceError
    _, store, _, _ = enrolled
    state = store.load()
    state.update(phase="phase1-" + producer, last_dispatch={**source("a"), "phase_id": "phase1-" + parent,
        "post_dispatch_complete": True})
    store.save(state)
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round(producer, source("a"), expected_state=store.load())


def test_new_what_round_retains_accepted_predecessor_and_private_receipt_namespace(enrolled):
    from harness.discovery_receipts import DiscoveryReceiptFile, receipt_round_operation_id
    from harness.squad_state import StateAdvanceError
    _, store, _, _ = enrolled
    state = store.load()
    state.update(phase="phase1-what", last_dispatch={**source("a"), "phase_id": "phase1-constitution", "post_dispatch_complete": True})
    store.save(state)
    store.prepare_spec_round("what", source("a"), expected_state=store.load())
    binding = dict(operation_id="what-" + "a" * 32, spec_id="game", run_id="first", input_tree="inputs",
        artifact_paths=["spec.md", "requirements-overview.md"], editable_revisions=[],
        unowned_writable_paths=["spec.md", "requirements-overview.md"],
        intent=dict(kind="specify", request="Create a game"), fingerprint="b" * 64)
    store.advance_discovery_operation(binding, "prepare", producer="what")
    state = store.load()
    state["last_dispatch"] = {**source("b"), "phase_id": "phase1-why2", "post_dispatch_complete": True}
    store.save(state)
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("what", source("b"), expected_state=store.load())
    store.advance_discovery_operation(binding, "begin", producer="what")
    store.advance_discovery_operation(binding, "finish", producer="what",
        result=dict(status="accepted", candidate_sha256="c" * 64, findings_sha256="d" * 64))
    previous = store.load()["managed_what_rounds"]
    next_state = store.prepare_spec_round("what", source("b"), expected_state=store.load())
    rounds = next_state["managed_what_rounds"]
    assert rounds["rounds"][previous["active"]] == previous["rounds"][previous["active"]]
    assert rounds["rounds"][rounds["active"]]["predecessor"] == previous["active"]
    first = DiscoveryReceiptFile(store.squad_dir, "discovery-turns", producer="what",
        round_operation_id=receipt_round_operation_id("what", previous["active"]))
    second = DiscoveryReceiptFile(store.squad_dir, "discovery-turns", producer="what",
        round_operation_id=receipt_round_operation_id("what", rounds["active"]))
    assert first.path != second.path

"""Derivation selections retain exact parents in the existing round owner."""
from copy import deepcopy

import pytest

from harness.discovery_producer import tracker_round
from harness.discovery_operation_state import operation_from_state
from harness.discovery_receipts import DiscoveryReceiptFile, receipt_round_operation_id
from harness.squad_state import StateAdvanceError
from tests.unit.test_discovery_turns import case, enrolled
from tests.unit.test_why1_tracker_parent import source


def select_parent(store, letter="a", parent="phase1-why2"):
    state = store.load()
    state.update(phase="phase1-lexicon-derive", last_dispatch={**source(letter),
        "phase_id": parent, "post_dispatch_complete": True})
    store.save(state)
    return store.load()


def binding(letter="a"):
    return dict(operation_id="lexicon-" + letter * 32, spec_id="game", run_id="first",
        input_tree="inputs", artifact_paths=["requirements.lexicon.md"], editable_revisions=[],
        unowned_writable_paths=["requirements.lexicon.md"],
        intent=dict(kind="derive", request="Translate the approved specification"), fingerprint="b" * 64)


def test_lexicon_selection_is_cas_protected_and_dispatch_charged_once(enrolled):
    _, store, _, _ = enrolled
    before = select_parent(store)
    selected = store.prepare_spec_round("lexicon", source("a"), expected_state=before)
    assert store.prepare_spec_round("lexicon", source("a"), expected_state=selected) == selected
    assert selected["phase_dispatch_counts"] == before["phase_dispatch_counts"]
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("lexicon", source("a"), expected_state=before)
    prepared = store.advance_discovery_operation(binding(), "prepare", producer="lexicon")
    assert operation_from_state(prepared, "lexicon")["binding"] == binding()
    assert prepared["phase_dispatch_counts"]["phase1-lexicon-derive"] == 1
    assert store.advance_discovery_operation(binding(), "prepare", producer="lexicon") == prepared
    assert tracker_round(prepared, producer="lexicon")["source"] == source("a")
    for mutation in ("drop", "source", "operation", "active"):
        changed = deepcopy(prepared)
        rounds = changed["managed_lexicon_rounds"]
        if mutation == "drop": del changed["managed_lexicon_rounds"]
        elif mutation == "source": rounds["rounds"][rounds["active"]]["source"] = source("b")
        elif mutation == "operation": rounds["rounds"][rounds["active"]]["operation"] = None
        else: rounds["active"] = "lexicon-" + "b" * 32
        with pytest.raises(StateAdvanceError):
            store.save(changed)
    assert store.load() == prepared


def test_lexicon_repair_requires_accepted_predecessor_and_private_receipts(enrolled):
    _, store, _, _ = enrolled
    before = select_parent(store)
    store.prepare_spec_round("lexicon", source("a"), expected_state=before)
    store.advance_discovery_operation(binding(), "prepare", producer="lexicon")
    select_parent(store, "b", "phase1-lexicon")
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("lexicon", source("b"), expected_state=store.load())
    store.advance_discovery_operation(binding(), "begin", producer="lexicon")
    store.advance_discovery_operation(binding(), "finish", producer="lexicon",
        result=dict(status="accepted", candidate_sha256="c" * 64, findings_sha256="d" * 64))
    previous = store.load()["managed_lexicon_rounds"]
    updated = store.prepare_spec_round("lexicon", source("b"), expected_state=store.load())
    rounds = updated["managed_lexicon_rounds"]
    assert rounds["rounds"][previous["active"]] == previous["rounds"][previous["active"]]
    assert rounds["rounds"][rounds["active"]]["predecessor"] == previous["active"]
    first = DiscoveryReceiptFile(store.squad_dir, "discovery-turns", producer="lexicon",
        round_operation_id=receipt_round_operation_id("lexicon", previous["active"]))
    second = DiscoveryReceiptFile(store.squad_dir, "discovery-turns", producer="lexicon",
        round_operation_id=receipt_round_operation_id("lexicon", rounds["active"]))
    assert first.path != second.path


@pytest.mark.parametrize("parent", ["phase1-what", "phase1-understanding", "phase1-lexicon"])
def test_initial_lexicon_round_cannot_skip_released_why2(enrolled, parent):
    _, store, _, _ = enrolled
    before = select_parent(store, parent=parent)
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("lexicon", source("a"), expected_state=before)
    assert store.load() == before
    # A valid selection also has to work, excluding an unsupported-producer
    # refusal as the explanation for the negative assertion.
    before = select_parent(store)
    accepted = store.prepare_spec_round("lexicon", source("a"), expected_state=before)
    assert tracker_round(accepted, producer="lexicon")["source"] == source("a")


def test_lexicon_debt_round_shape_keeps_exact_resolution_receipt(enrolled, tmp_path):
    from tests.unit.test_phase1_quality_debt import _debt_fixture
    from harness.discovery_spec import clarification_source
    debt_state, _, _, _ = _debt_fixture(tmp_path / "debt")
    _, store, _, _ = enrolled
    before = select_parent(store)
    decision = debt_state["spec_quality_debt_authorization"]["resolved_decision"]
    receipt = dict(schema_version=1, decision_id=decision["id"], completion_id="b" * 32,
        intent_sha256="c" * 64, receipts_sha256="d" * 64, publication_binding_sha256="e" * 64)
    operation = "lexicon-" + receipt["completion_id"]
    before["managed_lexicon_rounds"] = dict(schema_version=1, active=operation, rounds={operation:
        dict(source=clarification_source(receipt), resolution=dict(decision=decision, completion=receipt),
            predecessor=None, operation=None, turns=None)})
    row = tracker_round(before, producer="lexicon")
    assert row["source"] == clarification_source(receipt)
    assert row["resolution"] == dict(decision=decision, completion=receipt)
    assert row["predecessor"] is None


def test_checkpoint_selects_debt_head_after_checkpoint_replaces_active_decision(monkeypatch, tmp_path):
    from harness.discovery_spec import current_spec_source, clarification_source
    from harness.element_identity_store import IdentityStore
    from types import SimpleNamespace
    receipt = dict(schema_version=1, decision_id="debt-choice", completion_id="b" * 32,
        intent_sha256="c" * 64, receipts_sha256="d" * 64, publication_binding_sha256="e" * 64)
    head = "discovery-completion-" + receipt["completion_id"]
    monkeypatch.setattr(IdentityStore, "open", lambda root: SimpleNamespace(
        check_managed_context=lambda **kwargs: dict(source_context=dict(operation_id=head))))
    state = dict(last_dispatch={**source("a"), "phase_id": "phase1-why2"},
        blocked_decision=dict(id="checkpoint-choice", status="awaiting_human", source_phase="checkpoint-assess"),
        last_human_input_completion=receipt, managed_identity=dict(spec_id="game"), run_id="first",
        spec_quality_debt_authorization=dict(resolution_completion=dict(completion_id=receipt["completion_id"]),
            resolved_decision=dict(id=receipt["decision_id"])))
    assert current_spec_source(tmp_path, state, "checkpoint") == clarification_source(receipt)
    head = "discovery-completion-" + "a" * 32
    assert current_spec_source(tmp_path, state, "checkpoint") == source("a")

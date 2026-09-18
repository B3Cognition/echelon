"""Alignment state/receipt shape tests do not confer released gate authority."""
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
    state.update(phase="phase2-tracker-alignment", feasibility_verdict="PASS",
        last_dispatch={**source("a"), "phase_id": "phase2-strategic-overview", "post_dispatch_complete": True})
    store._path.write_text(json.dumps(state))
    return enrolled


def binding():
    return dict(operation_id="alignment-" + "a" * 32, spec_id="game", run_id="first",
        input_tree="inputs", artifact_paths=["intent-alignment-check.md"], editable_revisions=[],
        unowned_writable_paths=["intent-alignment-check.md"], intent=dict(kind="align", request="Map approved scope risks"), fingerprint="b" * 64)


def test_alignment_selection_and_components_require_owner_and_full_cas(gate):
    _, store, _, _ = gate
    before = store.load()
    selected = store.prepare_spec_round("alignment", source("a"), expected_state=before)
    assert store.prepare_spec_round("alignment", source("a"), expected_state=selected) == selected
    assert tracker_round(selected, producer="alignment") == dict(source=source("a"), resolution=None,
        predecessor=None, operation=None, turns=None)
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("alignment", source("a"), expected_state=before)
    saved = store.advance_discovery_operation(binding(), "prepare", producer="alignment")
    assert operation_from_state(saved, "alignment")["binding"] == binding()
    assert saved["phase_dispatch_counts"]["phase2-tracker-alignment"] == 1
    assert store.advance_discovery_operation(binding(), "prepare", producer="alignment") == saved
    for damage in ("drop", "source", "operation", "turns", "resolution", "predecessor"):
        changed = deepcopy(saved)
        rounds = changed["managed_alignment_rounds"]
        row = rounds["rounds"][rounds["active"]]
        if damage == "drop": del changed["managed_alignment_rounds"]
        elif damage == "source": row["source"] = source("b")
        elif damage == "operation": row["operation"] = None
        elif damage == "turns": row["turns"] = {}
        elif damage == "resolution": row["resolution"] = {}
        else: row["predecessor"] = rounds["active"]
        with pytest.raises(StateAdvanceError): store.save(changed)
    assert store.load() == saved
    assert receipt_round_operation_id("alignment", binding()["operation_id"]) == binding()["operation_id"]
    assert DiscoveryReceiptFile(store.squad_dir, "discovery-turns", producer="alignment",
        round_operation_id=binding()["operation_id"]).path != DiscoveryReceiptFile(store.squad_dir,
            "discovery-reservations", producer="alignment", round_operation_id=binding()["operation_id"]).path


@pytest.mark.parametrize("damage", ["phase", "parent", "unfinished", "cancelled", "blocked", "source", "pending"])
def test_alignment_selection_refuses_unsettled_or_detached_parent(gate, damage):
    _, store, _, _ = gate
    state = store.load()
    if damage == "phase": state["phase"] = "phase3-specialists"
    elif damage == "parent": state["last_dispatch"]["phase_id"] = "phase2-decide"
    elif damage == "unfinished": state["last_dispatch"]["post_dispatch_complete"] = False
    elif damage == "cancelled": state["cancel_requested"] = True
    elif damage == "blocked": state["status"] = "blocked"
    elif damage == "source": state["last_dispatch"].update(source("b"))
    else: state["pending_external_publication"] = {}
    store._path.write_text(json.dumps(state))
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("alignment", source("a"), expected_state=state)
    assert store.load() == state


@pytest.mark.parametrize("operation", [None, "alignment-../escape", "feasibility-" + "a" * 32])
def test_alignment_receipts_refuse_missing_or_foreign_round(gate, operation):
    with pytest.raises(ValueError):
        DiscoveryReceiptFile(gate[1].squad_dir, "discovery-turns", producer="alignment", round_operation_id=operation)


def test_alignment_repair_retains_accepted_predecessor_and_native_budget(gate, monkeypatch):
    root, store, _, _ = gate
    store.prepare_spec_round("alignment", source("a"), expected_state=store.load())
    store.advance_discovery_operation(binding(), "prepare", producer="alignment")
    state = store.load()
    state.update(iteration=2, intent_alignment_check_structural_attempts=1,
        feasibility_structural_attempts=2,
        last_dispatch={**source("b"), "phase_id": "phase2-intent-alignment-structural",
            "post_dispatch_complete": True})
    store.save(state)
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("alignment", source("b"), expected_state=store.load())
    store.advance_discovery_operation(binding(), "begin", producer="alignment")
    store.advance_discovery_operation(binding(), "finish", producer="alignment",
        result=dict(status="accepted", candidate_sha256="c" * 64, findings_sha256="d" * 64))
    before = store.load()
    selected = store.prepare_spec_round("alignment", source("b"), expected_state=before)
    row = tracker_round(selected, producer="alignment")
    assert row == dict(source=source("b"), resolution=None, predecessor=binding()["operation_id"],
        operation=None, turns=None)
    assert selected["managed_alignment_rounds"]["rounds"][binding()["operation_id"]] == before[
        "managed_alignment_rounds"]["rounds"][binding()["operation_id"]]
    for key in ("iteration", "intent_alignment_check_structural_attempts", "feasibility_structural_attempts",
            "phase_dispatch_counts"):
        assert selected[key] == before[key]
    assert store.prepare_spec_round("alignment", source("b"), expected_state=selected) == selected
    for damage in ("predecessor", "resolution", "historical"):
        changed = deepcopy(selected)
        rounds = changed["managed_alignment_rounds"]
        current = rounds["rounds"][rounds["active"]]
        if damage == "predecessor": current["predecessor"] = None
        elif damage == "resolution": current["resolution"] = {}
        else: rounds["rounds"][binding()["operation_id"]]["operation"] = None
        with pytest.raises(StateAdvanceError): store.save(changed)
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("alignment", source("a"), expected_state=selected)
    from harness.discovery_assessment import require_alignment_parent
    from harness.element_identity_store import IdentityStore
    def unexpected_lookup(*args, **kwargs):
        raise AssertionError("Inactive alignment must be refused before reading identity authority")
    monkeypatch.setattr(IdentityStore, "open", unexpected_lookup)
    with pytest.raises(ValueError):
        require_alignment_parent(root, store.squad_dir, selected, source("a"))
    assert store.load() == selected


def test_answer_round_retains_native_resolution_and_accepted_question(gate):
    """State shape/CAS only; released-answer authority is tested separately."""
    from pathlib import Path
    from harness.blocked_decision import build_blocked_decision_v3
    from harness.phase_graph import PhaseGraph
    from harness.human_input import AppliedHumanInputResolution
    from harness.squad_state import build_human_input_resolution_postimage
    from harness.discovery_spec import clarification_source
    _, store, _, _ = gate
    store.prepare_spec_round("alignment", source("a"), expected_state=store.load())
    for event in ("prepare", "begin", "finish"):
        store.advance_discovery_operation(binding(), event, producer="alignment", **(dict(
            result=dict(status="accepted", candidate_sha256="c" * 64, findings_sha256="d" * 64)) if event == "finish" else {}))
    registry = PhaseGraph(Path(__file__).resolve().parents[2] / "runtime/workflow/definition.yaml").human_input_policy_registry()
    request = registry.prepare(source_kind="provider_escalation", producer_id="phase2-tracker-alignment",
        phase_id="phase2-tracker-alignment", reason_code="human_clarification_required",
        question="Which movement controls?", recommended_answer="Use arrows", risk_level="low", source_state_revision=1)
    question = build_blocked_decision_v3(prepared=request, decision_id="dec-answer-round",
        status="awaiting_human", autonomy_mode="guided", created_at="2026-09-18T10:00:00+00:00")
    decision = build_human_input_resolution_postimage(question, AppliedHumanInputResolution(None, "Use WASD", "user"),
        resolved_at="2026-09-18T12:00:00+00:00")
    receipt = dict(schema_version=1, decision_id=decision["id"], completion_id="b" * 32,
        intent_sha256="1" * 64, receipts_sha256="2" * 64, publication_binding_sha256="3" * 64)
    state = store.load()
    state.update(blocked_decision=decision, last_human_input_completion=receipt,
        last_dispatch={**source("c"), "phase_id": "phase2-tracker-alignment", "post_dispatch_complete": True})
    store._path.write_text(json.dumps(state))
    selected = store.prepare_spec_round("alignment", clarification_source(receipt), expected_state=state)
    row = tracker_round(selected, producer="alignment")
    assert row == dict(source=source("b"), resolution=dict(decision=decision, completion=receipt),
        predecessor=binding()["operation_id"], operation=None, turns=None)
    assert store.prepare_spec_round("alignment", source("b"), expected_state=selected) == selected
    for damage in ("answer", "receipt", "source", "predecessor"):
        changed = deepcopy(selected)
        current = changed["managed_alignment_rounds"]["rounds"]["alignment-" + "b" * 32]
        if damage == "answer": current["resolution"]["decision"]["answer_text"] = "Changed answer"
        elif damage == "receipt": current["resolution"]["completion"]["intent_sha256"] = "0" * 64
        elif damage == "source": current["source"] = source("d")
        else: current["predecessor"] = None
        with pytest.raises(StateAdvanceError): store.save(changed)
    assert store.load() == selected

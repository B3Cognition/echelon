"""Automatic changed-input refresh uses real routing and retained proof owners."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from tests.unit.test_synthesis_refresh_publication import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, selection,
    install_why1, RefreshExecutor,
)
from tests.unit.test_discovery_completion import controller as full_controller


def controller(prepared, executor):
    """Isolate refresh ordering after authenticated WHY1 input, before re-review.

    test_why1_refresh_execution exercises the unmodified controller beyond this
    boundary. No source, publication or dependency check is replaced here.
    """
    from types import MethodType
    ctrl = full_controller(prepared, executor)
    advance = ctrl._prepare_managed_repair_refresh
    def stop_before_rereview(self, selected):
        result = advance(selected)
        state = self._state_store.load()
        if (result is None and state.get("phase") == "phase1-why1"
                and state.get("managed_discovery_repairs") is not None
                and (state.get("last_dispatch") or {}).get("phase_id") == "phase1-tracker"):
            return self._managed_discovery_stop("managed_repair_refresh_complete")
        return result
    ctrl._prepare_managed_repair_refresh = MethodType(stop_before_rereview, ctrl)
    return ctrl


@pytest.mark.parametrize("provider,mode", [("codex", "semi"), ("claude", "banzai")])
def test_controller_orders_changed_refresh_and_stops_before_why1(checkpoint_case, provider, mode):
    from harness.discovery_completion import released_discovery_input_projectors
    from harness.discovery_producer import SOURCE_FIELDS, tracker_round
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = mode
    store.save(state)
    install_why1(checkpoint_case)
    executor = RefreshExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected,
        create_managed_discovery=True).phase == "phase1-discover"
    original = store.load()
    receipts = {path: path.read_bytes() for path in store.squad_dir.glob("*turns*.json")}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.phase == "phase1-why1" and result.summary == "managed_repair_refresh_complete", result
    saved = store.load()
    assert saved["token_usage"] == 147 and len(executor.calls) == 21
    assert saved["phase_dispatch_counts"] == {**original["phase_dispatch_counts"],
        "phase1-discover": 2, "phase1-synthesizer": 2, "phase1-tracker": 2}
    synthesis, tracker = (tracker_round(saved, producer=name) for name in ("synthesizer", "tracker"))
    assert synthesis["execution_input"]["source"] == synthesis["refresh"]["repair_source"]
    assert tracker["execution_input"]["source"] != tracker["refresh"]["repair_source"]
    assert tracker["refresh"]["repair_source"] == synthesis["refresh"]["repair_source"]
    for producer in ("tracker", "why1"):
        for key, previous in original["managed_" + producer + "_rounds"]["rounds"].items():
            assert saved["managed_" + producer + "_rounds"]["rounds"][key] == previous
    for key in ("managed_synthesizer_source", "managed_synthesizer_operation", "managed_synthesizer_turns"):
        assert saved[key] == original[key]
    assert all(path.read_bytes() == raw for path, raw in receipts.items())
    assert tracker_round(saved, producer="why1")["operation"] is None
    released_discovery_input_projectors(root, store.squad_dir, saved,
        source={key: saved["last_dispatch"][key] for key in SOURCE_FIELDS})
    history = identity.identity_history(spec_id="game")
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).summary == result.summary
    assert store.load() == saved and len(executor.calls) == 21
    assert identity.identity_history(spec_id="game") == history
    for target in (root / "specs/game/issues.md", root / "specs/game/user-intent.md",
            root / ".echelon/runtime/templates/user-intent-template.md",
            store.squad_dir / "context/current-feature-context.md"):
        raw = target.read_bytes()
        try:
            target.write_bytes(raw + b"Changed after completed refresh\n")
            result = controller(checkpoint_case, executor).run(managed_discovery=selected)
            assert result.summary == "managed_review_repair_requires_reconciliation", result
            assert store.load() == saved and len(executor.calls) == 21
            assert identity.identity_history(spec_id="game") == history
        finally:
            target.write_bytes(raw)


def test_automatic_refresh_recovers_selection_publication_and_human_answer(checkpoint_case, monkeypatch):
    from harness.element_identity_store import IdentityStore
    from harness.discovery_producer import tracker_round
    from harness.tracker_clarification import previous_records
    from tests.unit.test_discovery_turns import Interrupted
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why1(checkpoint_case)
    executor = RefreshExecutor("claude")
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected,
        create_managed_discovery=True).phase == "phase1-discover"
    activate = store.activate_refresh_round
    def interrupted_selection(*args, **kwargs):
        activate(*args, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(store, "activate_refresh_round", interrupted_selection)
        with pytest.raises(Interrupted): controller(checkpoint_case, executor).run(managed_discovery=selected)
    selected_state = store.load()
    assert selected_state["phase"] == "phase1-synthesizer"
    assert selected_state["token_usage"] == 105 and len(executor.calls) == 15
    assert tracker_round(selected_state, producer="synthesizer")["operation"] is None
    target = root / "specs/game/issues.md"
    raw = target.read_bytes()
    try:
        target.write_bytes(raw + b"Changed after automatic phase selection\n")
        result = controller(checkpoint_case, executor).run(managed_discovery=selected)
        assert result.status == "blocked" and len(executor.calls) == 15
        assert store.load() == selected_state
    finally:
        target.write_bytes(raw)
    apply = IdentityStore.apply_identity_publication
    def interrupted_publication(*args, **kwargs):
        apply(*args, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", interrupted_publication)
        with pytest.raises(Interrupted): controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert len(executor.calls) == 18
    provider_turn = executor.run_inspection_turn
    def ask_once(*args, **kwargs):
        response = provider_turn(*args, **kwargs)
        reply = json.loads(response.stdout)
        evidence = json.dumps(executor.calls[-1]["context"]["evidence"])
        if reply.get("producer") == "tracker" and reply["step"] == "author" and "**Question:** Which lighting style?" not in evidence:
            reply["routing"] = dict(verdict="STOP_AND_ASK", question="Which lighting style?",
                recommended_answer=None, risk_level=None)
        return replace(response, stdout=json.dumps(reply))
    monkeypatch.setattr(executor, "run_inspection_turn", ask_once)
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.summary == "human_clarification_required" and result.phase == "phase1-tracker", result
    assert len(executor.calls) == 21 and store.load()["token_usage"] == 147
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", interrupted_publication)
        with pytest.raises(Interrupted): controller(checkpoint_case, executor).resume_with_human_input("Daylight")
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.summary == "managed_repair_refresh_complete" and result.phase == "phase1-why1", result
    saved = store.load()
    assert len(executor.calls) == 24 and saved["token_usage"] == 168
    assert saved["phase_dispatch_counts"]["phase1-tracker"] == 3
    assert [(item.question, item.answer) for item in previous_records(saved, saved["managed_tracker_rounds"]["active"])] == [
        ("Which lighting style?", "Daylight")]
    assert tracker_round(saved, producer="why1")["operation"] is None
    history = identity.identity_history(spec_id="game")
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).summary == result.summary
    assert store.load() == saved and len(executor.calls) == 24
    assert identity.identity_history(spec_id="game") == history

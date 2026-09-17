"""Pin legacy human ancestry from real retained proofs without rewriting them."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_repair_refresh_inputs import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, controller,
    selection, install_why1, RepairExecutor, select_refresh,
)


def pin(root, store):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_repair_admission import pin_why1_tracker_history
    with PhaseAExecutionLock.acquire(root, "test-human-history-pin"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-human-history-pin"):
            return pin_why1_tracker_history(root, store)


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_legacy_parent_is_authenticated_and_old_human_proofs_stay_replayable(checkpoint_case, provider, monkeypatch):
    from harness.discovery_producer import tracker_rounds
    from harness.squad_completion import CompletionError, validate_retained_completion_proof
    from harness.discovery_completion import decode_binding
    from harness.tracker_clarification import previous_records
    from harness.squad_state import StateAdvanceError, SquadStateStore
    from tests.unit.test_why1_tracker_parent import source, resolved
    root, store, identity, _ = checkpoint_case
    initial = store.load()
    initial["autonomy_mode"] = "guided"
    if provider == "codex":
        for key in ("spec_dir", "checkpoint_policy_version", "phase_completion_outcomes"):
            initial.pop(key)
    store.save(initial)
    install_why1(checkpoint_case)
    executor = RepairExecutor(provider)
    executor.clarification = True
    executor.why_verdict = "STOP_AND_ASK"
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    ctrl = controller(checkpoint_case, executor)
    assert ctrl.run(managed_discovery=request, create_managed_discovery=True).phase == "phase1-tracker"
    assert ctrl.resume_with_human_input("Use arrow keys")
    assert ctrl.run(managed_discovery=request).phase == "phase1-why1"
    assert ctrl.resume_with_human_input("Single player")
    executor.why_verdict = "FAIL"
    assert ctrl.run(managed_discovery=request).phase == "phase1-discover"
    assert ctrl.run(managed_discovery=request).summary == "managed_repair_dependency_refresh_not_supported"
    current = store.load()
    why_rounds = tracker_rounds(current, "why1")
    why_root, = (key for key, row in why_rounds["rounds"].items() if row["predecessor"] is None)
    parent = tracker_rounds(current)["active"]
    assert why_rounds["rounds"][why_root]["tracker_parent"] == parent
    # Simulate a pre-pin legacy root. The new metadata is absent from old proof
    # encodings; no operation, receipt or retained database proof is changed.
    del current["managed_why1_rounds"]["rounds"][why_root]["tracker_parent"]
    store._path.write_text(json.dumps(current))
    before = store.load()
    human_proofs = []
    for producer in ("tracker", "why1"):
        for row in tracker_rounds(before, producer)["rounds"].values():
            if row["resolution"] is not None:
                completion_id = row["resolution"]["completion"]["completion_id"]
                operation_id = "discovery-completion-" + completion_id
                retained = identity.identity_publication(spec_id="game", operation_id=operation_id)
                human_proofs.append((operation_id, retained))
    assert len(human_proofs) == 2
    receipts = {path: path.read_bytes() for path in store.squad_dir.glob("*.json")
        if "turns" in path.name or "reservations" in path.name}
    staged = {path: path.read_bytes() for path in store.staging_dir.iterdir() if path.is_file()}
    old_history = identity.identity_history(spec_id="game")
    original_pin = store.pin_why1_tracker_parent
    def race(*args, **kwargs):
        store.save(store.load())
        return original_pin(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(store, "pin_why1_tracker_parent", race)
        with pytest.raises(StateAdvanceError): pin(root, store)
    assert "tracker_parent" not in store.load()["managed_why1_rounds"]["rounds"][why_root]
    saved = pin(root, store)
    assert saved["managed_why1_rounds"]["rounds"][why_root]["tracker_parent"] == parent
    assert pin(root, SquadStateStore(store.squad_dir)) == saved
    from harness.element_identity_store import IdentityStore
    original_publication = IdentityStore.identity_publication
    parent_publication_id = "discovery-completion-" + why_rounds["rounds"][why_root]["source"]["dispatch_id"]
    def damaged_parent(self, *args, **kwargs):
        value = original_publication(self, *args, **kwargs)
        if kwargs.get("operation_id") == parent_publication_id:
            return {**value, "completion_payload": "{}"}
        return value
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "identity_publication", damaged_parent)
        with pytest.raises(ValueError): pin(root, store)
    assert store.load() == saved
    for operation_id, retained in human_proofs:
        assert identity.identity_publication(spec_id="game", operation_id=operation_id) == retained
    assert identity.identity_history(spec_id="game") == old_history
    assert all(path.read_bytes() == raw for path, raw in receipts.items())
    assert all(path.read_bytes() == raw for path, raw in staged.items())
    # Start historical traversal at the first WHY1 result, before its v7 human
    # completion. A forged accepted pin cannot hide behind v7 answer comparison:
    # only the authenticated WHY1→Tracker link can reject this substitution.
    from harness.discovery_completion import _released_discovery_projections
    initial_why1_source = why_rounds["rounds"][why_rounds["active"]]["source"]
    _released_discovery_projections(root, store.squad_dir, saved, source=initial_why1_source, historical=True)
    forged = deepcopy(saved)
    other_parent, = (key for key, row in tracker_rounds(saved)["rounds"].items() if row["predecessor"] is None)
    assert other_parent != parent
    forged["managed_why1_rounds"]["rounds"][why_root]["tracker_parent"] = other_parent
    with pytest.raises(CompletionError) as rejected:
        _released_discovery_projections(root, store.squad_dir, forged, source=initial_why1_source, historical=True)
    assert rejected.value.code == "intent_mismatch"
    # Reader-only future selection: historical proof decoding must not consult
    # this later Tracker answer. It is not an authorized new publication.
    later = deepcopy(saved)
    rounds = later["managed_tracker_rounds"]
    later_id = "tracker-" + "9" * 32
    following = deepcopy(rounds["rounds"][parent])
    following.update(source=source("9"), predecessor=parent,
        resolution=resolved("9", "Which camera?", "Isometric"))
    following["operation"]["binding"]["operation_id"] = later_id
    following["turns"] = None
    rounds["active"] = later_id
    rounds["rounds"][later_id] = following
    for operation_id, retained in human_proofs:
        proof = json.loads(retained["completion_payload"])
        marker, intent, _ = validate_retained_completion_proof(proof["completion"], proof["proof"]["intent"], proof["proof"]["receipts"])
        decoded = decode_binding(intent.publication, completion_id=marker.completion_id, state=later)
        assert decoded.clarification
    assert [(item.question, item.answer) for item in previous_records(later, why_rounds["active"], "why1")] == [
        ("Which movement controls?", "Use arrow keys"), ("Which audience?", "Single player")]
    # Reauthentication remains mandatory on retry, despite an existing pin.
    target = root / "specs/game/issues.md"
    raw = target.read_bytes()
    try:
        target.write_bytes(raw + b"Changed after pin\n")
        with pytest.raises(ValueError): pin(root, store)
    finally:
        target.write_bytes(raw)
    for producer in ("synthesizer", "tracker", "why1"):
        select_refresh(root, store, producer)
    history = previous_records(store.load(), tracker_rounds(store.load())["active"])
    assert [(item.question, item.answer) for item in history] == [
        ("Which movement controls?", "Use arrow keys"), ("Which audience?", "Single player")]
    assert len(executor.calls) == 21 and store.load()["token_usage"] == 147
    assert controller(checkpoint_case, executor).run(managed_discovery=request).summary == "managed_repair_dependency_refresh_not_supported"

"""Refresh associations retain history but cannot start dependency execution."""
from copy import deepcopy

import pytest

from tests.unit.test_discovery_repair_execution import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, controller,
    selection, install_why1, RepairExecutor,
)


def select_refresh(root, store, producer):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_repair_admission import prepare_repair_refresh_round
    with PhaseAExecutionLock.acquire(root, "test-refresh-admission"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-refresh-admission"):
            return prepare_repair_refresh_round(root, store, producer)


def test_released_repair_retains_refresh_rounds_without_execution(checkpoint_case):
    from harness.discovery_producer import tracker_round, producer_component
    from harness.squad_state import SquadStateStore, StateAdvanceError
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = RepairExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True).phase == "phase1-discover"
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).summary == "managed_repair_dependency_refresh_not_supported"
    original = store.load()
    history = identity.identity_history(spec_id="game")
    receipts = {path: path.read_bytes() for path in store.squad_dir.glob("*turns*.json")}
    for producer in ("synthesizer", "tracker", "why1"):
        saved = select_refresh(root, store, producer)
        row = tracker_round(saved, producer=producer)
        assert row["operation"] is None and row["turns"] is None and row["resolution"] is None
        assert row["source"]["dispatch_id"] == original["last_dispatch"]["dispatch_id"]
        unit, = original["managed_discovery_repairs"]["units"]
        assert row["refresh"]["repair_unit"] == unit
        assert row["refresh"]["repair_source"] == row["source"]
        assert row["refresh"]["predecessor_source"]["dispatch_id"] != row["source"]["dispatch_id"]
        if producer == "synthesizer":
            prior = original["managed_synthesizer_operation"]
        else:
            prior = tracker_round(original, producer=producer)["operation"]
        assert row["predecessor"] == prior["binding"]["operation_id"]
        assert producer_component(saved, producer, "operation", operation_id=row["predecessor"]) == prior
        assert select_refresh(root, SquadStateStore(store.squad_dir), producer) == saved
        for key in ("managed_discovery_operation", "managed_discovery_repairs", "managed_synthesizer_source",
                "managed_synthesizer_operation", "managed_synthesizer_turns", "phase_dispatch_counts", "token_usage", "last_dispatch"):
            assert saved[key] == original[key]
        for previous_producer in ("tracker", "why1"):
            key = "managed_" + previous_producer + "_rounds"
            assert all(saved[key]["rounds"][key_id] == value for key_id, value in original[key]["rounds"].items())
        for damage in ("delete", "source", "predecessor", "repair", "activate_operation"):
            changed = deepcopy(saved)
            rounds = changed["managed_" + producer + "_rounds"]
            active = rounds["rounds"][rounds["active"]]
            if damage == "delete": del changed["managed_" + producer + "_rounds"]
            elif damage == "source": active["source"]["completion_intent_sha256"] = "0" * 64
            elif damage == "predecessor": active["predecessor"] = rounds["active"]
            elif damage == "repair": active["refresh"]["repair_unit"] = "0" * 64
            else: active["operation"] = deepcopy(prior)
            with pytest.raises(StateAdvanceError): store.save(changed)
            assert store.load() == saved
        with pytest.raises(StateAdvanceError):
            store.prepare_refresh_round(producer, row["source"], row["refresh"], expected_state=original)
        assert store.load() == saved
        binding = {**prior["binding"], "operation_id": producer + "-" + row["source"]["dispatch_id"]}
        with pytest.raises(StateAdvanceError):
            store.advance_discovery_operation(binding, "prepare", producer=producer)
        assert store.load() == saved
    assert identity.identity_history(spec_id="game") == history
    assert all(path.read_bytes() == content for path, content in receipts.items())
    saved = store.load()
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).summary == "managed_repair_dependency_refresh_not_supported"
    assert len(executor.calls) == 15 and store.load() == saved
    for target in (root / "specs/game/unknowns.md", store.squad_dir / "context/current-feature-context.md",
            root / ".echelon/runtime/templates/unknowns-template.md"):
        before = target.read_bytes()
        try:
            target.write_bytes(before + b"Changed after repair publication\n")
            with pytest.raises(ValueError): select_refresh(root, store, "why1")
            assert store.load() == saved
        finally:
            target.write_bytes(before)
    with pytest.raises(ValueError): select_refresh(root, store, "discovery")
    assert store.load() == saved


def test_refresh_owner_requires_accepted_repair_and_exact_state(enrolled):
    from harness.squad_state import StateAdvanceError
    _, store, _, _ = enrolled
    before = store.load()
    source = dict(dispatch_id="a" * 32, completion_intent_sha256="b" * 64,
        completion_receipts_sha256="c" * 64, completed_publication_binding_sha256="d" * 64)
    refresh = dict(repair_unit="e" * 64, repair_source=source, predecessor_source=source)
    with pytest.raises(StateAdvanceError):
        store.prepare_refresh_round("why1", source, refresh, expected_state=before)
    assert store.load() == before


def test_refresh_preserves_tracker_and_why1_clarification_history(checkpoint_case):
    from harness.discovery_producer import tracker_round
    from harness.tracker_clarification import previous_records
    root, store, identity, _ = checkpoint_case
    state = store.load()
    state["autonomy_mode"] = "guided"
    store.save(state)
    install_why1(checkpoint_case)
    executor = RepairExecutor("claude")
    executor.clarification = True
    executor.why_verdict = "STOP_AND_ASK"
    selected = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    ctrl = controller(checkpoint_case, executor)
    assert ctrl.run(managed_discovery=selected, create_managed_discovery=True).phase == "phase1-tracker"
    assert ctrl.resume_with_human_input("Use arrow keys")
    assert ctrl.run(managed_discovery=selected).phase == "phase1-why1"
    assert store.load()["blocked_decision"]["question"] == "Which audience?"
    assert ctrl.resume_with_human_input("Single player")
    executor.why_verdict = "FAIL"
    assert ctrl.run(managed_discovery=selected).phase == "phase1-discover"
    result = ctrl.run(managed_discovery=selected)
    assert result.summary == "managed_repair_dependency_refresh_not_supported", result
    original = store.load()
    prior_id = tracker_round(original, producer="why1")["operation"]["binding"]["operation_id"]
    records = previous_records(original, prior_id, "why1")
    assert [(row.question, row.answer) for row in records] == [
        ("Which movement controls?", "Use arrow keys"), ("Which audience?", "Single player")]
    for producer in ("synthesizer", "tracker", "why1"):
        saved = select_refresh(root, store, producer)
        assert previous_records(saved, prior_id, "why1") == records
        if producer == "why1":
            assert previous_records(saved, saved["managed_why1_rounds"]["active"], "why1") == records
        assert select_refresh(root, store, producer) == saved
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).summary == "managed_repair_dependency_refresh_not_supported"
    assert len(executor.calls) == 21 and store.load()["token_usage"] == 147

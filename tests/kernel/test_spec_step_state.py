"""Atomic state ownership for durable Phase A spec steps."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.spec_step import (
    SpecStepEffectReceipt,
    append_spec_step_receipt,
    prepare_spec_step,
)
from harness.squad_state import StateAdvanceError, SquadStateStore


STEP_ID = "a" * 32


def _store(tmp_path: Path) -> SquadStateStore:
    store = SquadStateStore(tmp_path / "run")
    store.initialize("run", "greenfield", "request", 0, "phase1")
    return store


def _prepared(store: SquadStateStore, *, effects: tuple[str, ...] = ()):
    snapshot = store.capture_routing_snapshot(expected_phase="phase1")
    final_state = snapshot.state
    final_state["phase"] = "phase2"
    final_state["last_dispatch"] = {
        "dispatch_id": STEP_ID,
        "phase_id": "phase1",
        "next_phase": "phase2",
        "completed_at": "2026-09-24T00:00:00+00:00",
    }
    prepared = prepare_spec_step(
        store.squad_dir,
        step_id=STEP_ID,
        origin="routed",
        expected_state_revision=snapshot.state_revision,
        expected_previous_dispatch_sha256=snapshot.previous_dispatch_sha256,
        route={"from_phase": "phase1", "to_phase": "phase2", "manual": False},
        effects=effects,
        publication=None,
        final_state=final_state,
        provenance={"prepared_result_sha256": "d" * 64},
    )
    return snapshot, prepared


def test_begin_spec_step_persists_only_marker_against_exact_snapshot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot, prepared = _prepared(store, effects=("journal",))

    store.begin_spec_step(prepared, snapshot=snapshot)

    state = store.load()
    assert state["phase"] == "phase1"
    assert state["pending_spec_step"] == prepared.marker.to_dict()


def test_begin_spec_step_rejects_stale_revision(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot, prepared = _prepared(store)
    changed = store.load()
    changed["token_usage"] = 1
    store.save(changed)

    with pytest.raises(StateAdvanceError, match="changed"):
        store.begin_spec_step(prepared, snapshot=snapshot)


def test_begin_spec_step_adopts_saved_then_raised_postimage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot, prepared = _prepared(store)
    original = store._save_unlocked

    def save_then_raise(state, **kwargs):
        original(state, **kwargs)
        raise OSError("ambiguous save")

    with patch.object(store, "_save_unlocked", side_effect=save_then_raise):
        store.begin_spec_step(prepared, snapshot=snapshot)

    assert store.load()["pending_spec_step"] == prepared.marker.to_dict()


def test_record_spec_step_failure_replaces_one_bounded_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot, prepared = _prepared(store, effects=("journal",))
    store.begin_spec_step(prepared, snapshot=snapshot)

    store.record_spec_step_failure(prepared.marker, effect="journal", code="effect_io")
    once = store.load()["pending_spec_step"]
    store.record_spec_step_failure(once, effect="journal", code="effect_io")

    failure = store.load()["pending_spec_step"]["failure"]
    assert failure == {
        "effect": "journal",
        "code": "effect_io",
        "attempts": 2,
        "resume_status": "running",
    }


def test_record_spec_step_failure_rejects_wrong_marker(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot, prepared = _prepared(store, effects=("journal",))
    store.begin_spec_step(prepared, snapshot=snapshot)
    wrong = prepared.marker.to_dict()
    wrong["step_id"] = "b" * 32

    with pytest.raises(StateAdvanceError, match="marker"):
        store.record_spec_step_failure(wrong, effect="journal", code="effect_io")


def test_advance_spec_step_accepts_exact_one_ahead_marker(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot, prepared = _prepared(store, effects=("journal", "timing"))
    store.begin_spec_step(prepared, snapshot=snapshot)
    advanced = append_spec_step_receipt(
        prepared,
        SpecStepEffectReceipt(STEP_ID, "journal", "e" * 64, {"written": True}),
    )

    store.advance_spec_step(prepared.marker, advanced.marker)

    assert store.load()["pending_spec_step"] == advanced.marker.to_dict()


def test_advance_spec_step_adopts_saved_then_raised_marker(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot, prepared = _prepared(store, effects=("journal", "timing"))
    store.begin_spec_step(prepared, snapshot=snapshot)
    advanced = append_spec_step_receipt(
        prepared,
        SpecStepEffectReceipt(STEP_ID, "journal", "e" * 64, {"written": True}),
    )
    original = store._save_unlocked

    def save_then_raise(state, **kwargs):
        original(state, **kwargs)
        raise OSError("ambiguous save")

    with patch.object(store, "_save_unlocked", side_effect=save_then_raise):
        store.advance_spec_step(prepared.marker, advanced.marker)

    assert store.load()["pending_spec_step"] == advanced.marker.to_dict()


def test_advance_spec_step_rejects_receipt_digest_reuse(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot, prepared = _prepared(store, effects=("journal", "timing"))
    store.begin_spec_step(prepared, snapshot=snapshot)
    advanced = append_spec_step_receipt(
        prepared,
        SpecStepEffectReceipt(STEP_ID, "journal", "e" * 64, {"written": True}),
    )
    invalid = advanced.marker.to_dict()
    invalid["receipts_sha256"] = prepared.marker.receipts_sha256

    with pytest.raises(StateAdvanceError, match="receipt"):
        store.advance_spec_step(prepared.marker, invalid)


def test_complete_spec_step_installs_postimage_and_clears_marker(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot, prepared = _prepared(store)
    store.begin_spec_step(prepared, snapshot=snapshot)

    receipt = store.complete_spec_step(prepared)

    state = store.load()
    assert state["phase"] == "phase2"
    assert "pending_spec_step" not in state
    assert state["last_dispatch"]["dispatch_id"] == prepared.marker.step_id
    assert receipt.dispatch_id == prepared.marker.step_id


def test_complete_spec_step_adopts_saved_then_raised_and_repeated_call(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot, prepared = _prepared(store)
    store.begin_spec_step(prepared, snapshot=snapshot)
    original = store._save_unlocked

    def save_then_raise(state, **kwargs):
        original(state, **kwargs)
        raise OSError("ambiguous save")

    with patch.object(store, "_save_unlocked", side_effect=save_then_raise):
        first = store.complete_spec_step(prepared)
    revision = store.load()["state_revision"]
    second = store.complete_spec_step(prepared)

    assert first.dispatch_id == second.dispatch_id == STEP_ID
    assert store.load()["state_revision"] == revision


def test_generic_save_cannot_remove_pending_spec_step(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot, prepared = _prepared(store)
    store.begin_spec_step(prepared, snapshot=snapshot)
    state = store.load()
    state.pop("pending_spec_step")

    with pytest.raises(StateAdvanceError, match="pending spec step"):
        store.save(state)

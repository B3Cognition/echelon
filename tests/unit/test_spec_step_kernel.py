"""Recovery boundaries for the single Phase A spec-step drain."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.spec_step import SpecStepEffectReceipt, prepare_spec_step
from harness.spec_step_kernel import (
    SpecStepEffectError,
    drain_pending_spec_step,
)
from harness.squad_state import SquadStateStore


STEP_ID = "a" * 32


@dataclass
class StepFixture:
    store: SquadStateStore
    squad_dir: Path


class RecordingApplier:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def apply(self, prepared, state):
        effect = prepared.marker.cursor
        self.calls.append(effect)
        return SpecStepEffectReceipt(
            prepared.marker.step_id,
            effect,
            (str(len(self.calls)) * 64)[:64],
            {"state_revision": state["state_revision"]},
        )


def _fixture(tmp_path: Path, effects: tuple[str, ...] = ("journal",)) -> StepFixture:
    squad_dir = tmp_path / "run"
    store = SquadStateStore(squad_dir)
    store.initialize("run", "greenfield", "request", 0, "phase1")
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
        squad_dir,
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
    store.begin_spec_step(prepared, snapshot=snapshot)
    return StepFixture(store, squad_dir)


def test_drain_without_pending_marker_is_a_noop(tmp_path: Path) -> None:
    store = SquadStateStore(tmp_path / "run")
    store.initialize("run", "greenfield", "request", 0, "phase1")
    calls: list[str] = []

    outcome = drain_pending_spec_step(store, store.squad_dir, RecordingApplier(calls))

    assert not outcome.recovered
    assert calls == []


def test_recovery_never_reapplies_a_receipted_effect(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    calls: list[str] = []
    applier = RecordingApplier(calls)

    first = drain_pending_spec_step(fixture.store, fixture.squad_dir, applier)
    second = drain_pending_spec_step(fixture.store, fixture.squad_dir, applier)

    assert first.recovered
    assert not second.recovered
    assert calls == ["journal"]


def test_drain_applies_every_declared_cursor_once(tmp_path: Path) -> None:
    effects = ("journal", "timing", "checkpoint", "quality", "context", "mining", "retarget")
    fixture = _fixture(tmp_path, effects)
    calls: list[str] = []

    outcome = drain_pending_spec_step(
        fixture.store,
        fixture.squad_dir,
        RecordingApplier(calls),
    )

    assert outcome.recovered
    assert calls == list(effects)
    assert "pending_spec_step" not in fixture.store.load()


def test_retry_after_apply_before_receipt_verifies_external_postimage(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    external_writes: list[str] = []

    class VerifyingApplier(RecordingApplier):
        def apply(self, prepared, state):
            self.calls.append(prepared.marker.cursor)
            if not external_writes:
                external_writes.append("journal")
                raise OSError("crash after external write")
            return SpecStepEffectReceipt(STEP_ID, "journal", "e" * 64, {"verified": True})

    calls: list[str] = []
    with pytest.raises(OSError, match="crash after external write"):
        drain_pending_spec_step(fixture.store, fixture.squad_dir, VerifyingApplier(calls))

    drain_pending_spec_step(fixture.store, fixture.squad_dir, VerifyingApplier(calls))
    assert calls == ["journal", "journal"]
    assert external_writes == ["journal"]


def test_retry_adopts_receipt_written_before_state_advance(tmp_path: Path, monkeypatch) -> None:
    fixture = _fixture(tmp_path)
    calls: list[str] = []
    original = fixture.store.advance_spec_step
    attempts = 0

    def fail_before_advance(current, advanced):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("crash before marker advance")
        return original(current, advanced)

    monkeypatch.setattr(fixture.store, "advance_spec_step", fail_before_advance)
    with pytest.raises(OSError, match="crash before marker advance"):
        drain_pending_spec_step(fixture.store, fixture.squad_dir, RecordingApplier(calls))
    drain_pending_spec_step(fixture.store, fixture.squad_dir, RecordingApplier(calls))

    assert calls == ["journal"]


def test_fully_receipted_commit_failure_retries_only_commit(tmp_path: Path, monkeypatch) -> None:
    fixture = _fixture(tmp_path)
    calls: list[str] = []
    original = fixture.store.complete_spec_step
    attempts = 0

    def fail_once(prepared):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("commit unavailable")
        return original(prepared)

    monkeypatch.setattr(fixture.store, "complete_spec_step", fail_once)
    with pytest.raises(OSError, match="commit unavailable"):
        drain_pending_spec_step(fixture.store, fixture.squad_dir, RecordingApplier(calls))
    outcome = drain_pending_spec_step(
        fixture.store,
        fixture.squad_dir,
        RecordingApplier(calls),
    )

    assert outcome.recovered
    assert calls == ["journal"]
    assert attempts == 2


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_corrupt_stage_records_one_bounded_failure(
    tmp_path: Path,
    damage: str,
) -> None:
    fixture = _fixture(tmp_path)
    root = fixture.squad_dir / ".spec-step-outbox" / STEP_ID
    if damage == "missing":
        shutil.rmtree(root)
    else:
        (root / "intent.json").write_text("{}\n", encoding="utf-8")

    outcome = drain_pending_spec_step(
        fixture.store,
        fixture.squad_dir,
        RecordingApplier([]),
    )

    assert outcome.blocked
    failure = fixture.store.load()["pending_spec_step"]["failure"]
    assert failure["attempts"] == 1
    assert failure["effect"] == "journal"


def test_bounded_effect_failure_is_recorded_without_advancing(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    class FailingApplier:
        def apply(self, prepared, state):
            raise SpecStepEffectError("target_drift")

    outcome = drain_pending_spec_step(
        fixture.store,
        fixture.squad_dir,
        FailingApplier(),
    )

    assert outcome.blocked
    marker = fixture.store.load()["pending_spec_step"]
    assert marker["cursor"] == "journal"
    assert marker["failure"]["code"] == "target_drift"

from pathlib import Path
import json

from harness.phase_checkpoints import (
    CheckpointLedger,
    PhaseCheckpoint,
    load_checkpoint_ledger,
    record_checkpoint_metadata,
    resolve_checkpoint,
)


def test_checkpoint_ledger_round_trips_under_spec_dir(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    checkpoint = PhaseCheckpoint(
        id="phase3-plan",
        spec_id="001-demo",
        phase="phase3-plan",
        next_phase="phase3-consensus",
        commit="abc123",
        metadata_commit="",
        source="auto",
        run_id="squad-1",
        created_at="2026-07-04T12:00:00Z",
    )

    record_checkpoint_metadata(spec_dir, checkpoint)
    ledger = load_checkpoint_ledger(spec_dir)

    assert ledger.spec_id == "001-demo"
    assert ledger.checkpoints[0] == checkpoint
    assert json.loads((spec_dir / ".echelon/checkpoints.json").read_text())["spec_id"] == "001-demo"


def test_resolve_checkpoint_by_phase_uses_latest_matching_entry(tmp_path: Path) -> None:
    ledger = CheckpointLedger(
        spec_id="001-demo",
        checkpoints=[
            PhaseCheckpoint("phase3-plan", "001-demo", "phase3-plan", "phase3-consensus", "old", "", "auto", "run1", "2026-07-04T01:00:00Z"),
            PhaseCheckpoint("phase3-plan-2", "001-demo", "phase3-plan", "phase3-consensus", "new", "", "auto", "run2", "2026-07-04T02:00:00Z"),
        ],
    )

    assert resolve_checkpoint(ledger, "phase3-plan").commit == "new"
    assert resolve_checkpoint(ledger, "checkpoint:phase3-plan-2").commit == "new"

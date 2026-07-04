from pathlib import Path

from echelon.checkpoint_cli import run_checkpoint_command
from harness.phase_checkpoints import PhaseCheckpoint, record_checkpoint_metadata


def test_checkpoint_list_requires_spec_when_no_active_spec(tmp_path: Path, capsys) -> None:
    run_checkpoint_command(["list"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "No active spec resolved" in out
    assert "echelon checkpoint list --spec 001" in out


def test_checkpoint_list_prints_spec_scoped_ledger(tmp_path: Path, capsys) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint(
            id="phase3-plan",
            spec_id="001-demo",
            phase="phase3-plan",
            next_phase="phase3-consensus",
            commit="abcdef123456",
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-04T12:00:00Z",
        ),
    )

    run_checkpoint_command(["list", "--spec", "001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "CHECKPOINTS - spec 001-demo" in out
    assert "phase3-plan" in out
    assert "abcdef1" in out

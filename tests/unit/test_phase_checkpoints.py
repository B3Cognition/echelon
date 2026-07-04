from pathlib import Path
import json
import subprocess

from harness.phase_checkpoints import (
    CheckpointLedger,
    PhaseCheckpoint,
    create_phase_checkpoint,
    load_checkpoint_ledger,
    record_phase_checkpoint,
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

    record_phase_checkpoint(spec_dir, checkpoint)
    ledger = load_checkpoint_ledger(spec_dir)

    assert ledger.spec_id == "001-demo"
    assert ledger.checkpoints[0] == checkpoint
    assert json.loads((spec_dir / ".echelon/checkpoints.json").read_text())["spec_id"] == "001-demo"


def test_record_phase_checkpoint_rejects_wrong_spec_id(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    try:
        record_phase_checkpoint(
            spec_dir,
            PhaseCheckpoint(
                id="phase3-plan",
                spec_id="002-other",
                phase="phase3-plan",
                next_phase="phase3-consensus",
                commit="abc123",
                metadata_commit="",
                source="auto",
                run_id="squad-1",
                created_at="2026-07-04T12:00:00Z",
            ),
        )
    except ValueError as exc:
        assert "does not match spec directory" in str(exc)
    else:
        raise AssertionError("wrong spec_id should fail")


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


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_create_phase_checkpoint_commits_artifacts_and_records_sha(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    checkpoint = create_phase_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase3-plan",
        next_phase="phase3-consensus",
        run_id="squad-1",
    )

    assert checkpoint is not None
    assert checkpoint.phase == "phase3-plan"
    assert checkpoint.commit == _git(repo, "rev-parse", "HEAD")
    assert "Co-authored-by: Echelon" in _git(repo, "log", "-1", "--format=%B")
    assert load_checkpoint_ledger(spec_dir).checkpoints[-1].commit == checkpoint.commit

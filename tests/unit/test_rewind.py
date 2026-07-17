from pathlib import Path
import subprocess

import pytest

from echelon.rewind import RewindError, prepare_rewind
from harness.phase_checkpoints import PhaseCheckpoint, record_checkpoint_metadata


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo_with_checkpoint(tmp_path: Path) -> tuple[Path, Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "001-demo")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "checkpoint")
    checkpoint = _git(repo, "rev-parse", "HEAD")
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint(
            "phase3-plan",
            "001-demo",
            "phase3-plan",
            "phase3-consensus",
            checkpoint,
            "",
            "auto",
            "squad-1",
            "2026-07-04T12:00:00Z",
        ),
    )
    (spec_dir / "spec.md").write_text("v2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "later")
    later = _git(repo, "rev-parse", "HEAD")
    return repo, spec_dir, checkpoint, later


def test_rewind_requires_confirmation_when_branch_has_later_commits(tmp_path: Path) -> None:
    repo, _spec_dir, checkpoint, later = _repo_with_checkpoint(tmp_path)

    result = prepare_rewind(project_root=repo, spec="001", target="phase3-plan", confirm=False)

    assert not result.applied
    assert result.from_commit == later
    assert result.to_commit == checkpoint
    assert "echelon spec rewind phase3-plan --confirm" in result.message


def test_rewind_creates_backup_ref_and_resets_branch_when_confirmed(tmp_path: Path) -> None:
    repo, _spec_dir, checkpoint, later = _repo_with_checkpoint(tmp_path)

    result = prepare_rewind(project_root=repo, spec="001", target="phase3-plan", confirm=True)

    assert result.applied
    assert _git(repo, "rev-parse", "HEAD") == checkpoint
    assert _git(repo, "rev-parse", result.backup_ref) == later


def test_rewind_refuses_dirty_worktree(tmp_path: Path) -> None:
    repo, spec_dir, _checkpoint, _later = _repo_with_checkpoint(tmp_path)
    (spec_dir / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(RewindError, match="dirty worktree"):
        prepare_rewind(project_root=repo, spec="001", target="phase3-plan", confirm=True)


def test_rewind_missing_checkpoint_reports_available_targets(tmp_path: Path) -> None:
    repo, _spec_dir, _checkpoint, _later = _repo_with_checkpoint(tmp_path)

    with pytest.raises(RewindError) as exc:
        prepare_rewind(project_root=repo, spec="001", target="phase2-decide", confirm=False)

    message = str(exc.value)
    assert "checkpoint not found for spec 001-demo: phase2-decide" in message
    assert "Available checkpoints: phase3-plan" in message


def test_rewind_uses_explicit_run_local_spec_directory(tmp_path: Path) -> None:
    repo, root_spec_dir, checkpoint, later = _repo_with_checkpoint(tmp_path)
    ledger = root_spec_dir / ".echelon" / "checkpoints.json"
    run_spec_dir = repo / "runs" / "spec-1" / "specs" / root_spec_dir.name
    run_spec_dir.mkdir(parents=True)
    (run_spec_dir / ".echelon").mkdir()
    (run_spec_dir / ".echelon" / "checkpoints.json").write_text(
        ledger.read_text(encoding="utf-8"), encoding="utf-8"
    )
    ledger.unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "move ledger to run context")
    later = _git(repo, "rev-parse", "HEAD")

    result = prepare_rewind(
        project_root=repo,
        spec="001",
        spec_dir=run_spec_dir,
        target="phase3-plan",
        confirm=False,
    )

    assert not result.applied
    assert result.from_commit == later
    assert result.to_commit == checkpoint

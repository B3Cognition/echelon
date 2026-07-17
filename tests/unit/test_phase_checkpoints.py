from pathlib import Path
import json
import subprocess

import pytest

from harness.phase_checkpoints import (
    CheckpointLedger,
    PhaseCheckpointError,
    PhaseCheckpoint,
    commit_manual_checkpoint,
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


def _checkpoint_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "runs").mkdir()
    (repo / "runs" / ".gitignore").write_text(
        "**/.echelon/checkpoints.json\n*/state.json\n.current*\n",
        encoding="utf-8",
    )
    spec_dir = repo / "runs" / "spec-run" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    (repo / "README.md").write_text("# Repository\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo, spec_dir


def test_create_phase_checkpoint_commits_artifacts_and_records_sha(tmp_path: Path) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)

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


def test_create_phase_checkpoint_commits_only_active_spec_path(tmp_path: Path) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "src/staged.txt")
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    (repo / "scratch.txt").write_text("scratch\n", encoding="utf-8")

    checkpoint = create_phase_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase3-plan",
        next_phase="phase3-consensus",
        run_id="spec-run",
    )

    assert _git(repo, "show", "--format=", "--name-only", "HEAD").splitlines() == [
        "runs/spec-run/specs/001-demo/tasks.md"
    ]
    assert _git(repo, "diff", "--cached", "--name-only") == "src/staged.txt"
    status = _git(repo, "status", "--short")
    assert "README.md" in status
    assert "scratch.txt" in status
    assert checkpoint.commit == _git(repo, "rev-parse", "HEAD")


def test_create_phase_checkpoint_records_clean_head_without_new_commit(tmp_path: Path) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    head_before = _git(repo, "rev-parse", "HEAD")
    count_before = _git(repo, "rev-list", "--count", "HEAD")

    checkpoint = create_phase_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase2-decide",
        next_phase="phase3-how",
        run_id="spec-run",
    )

    assert checkpoint.commit == head_before
    assert _git(repo, "rev-list", "--count", "HEAD") == count_before
    assert load_checkpoint_ledger(spec_dir).checkpoints[-1] == checkpoint


def test_create_phase_checkpoint_commits_owned_spec_when_runs_are_ignored(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "ignored-runs-repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / ".gitignore").write_text("/runs/\n", encoding="utf-8")
    (repo / "README.md").write_text("# Repository\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "README.md")
    _git(repo, "commit", "-m", "base")
    spec_dir = repo / "runs" / "spec-run" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Ignored but owned\n", encoding="utf-8")

    checkpoint = create_phase_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase1-what",
        next_phase="phase1-why2",
        run_id="spec-run",
    )

    assert _git(repo, "show", "--format=", "--name-only", "HEAD").splitlines() == [
        "runs/spec-run/specs/001-demo/spec.md"
    ]
    assert checkpoint.commit == _git(repo, "rev-parse", "HEAD")


def test_create_phase_checkpoint_rejects_spec_dir_outside_project(tmp_path: Path) -> None:
    repo, _spec_dir = _checkpoint_repo(tmp_path)
    outside = tmp_path / "outside" / "001-demo"
    outside.mkdir(parents=True)
    (outside / "spec.md").write_text("# Outside\n", encoding="utf-8")
    position_before = (
        _git(repo, "branch", "--show-current"),
        _git(repo, "rev-parse", "HEAD"),
        _git(repo, "diff", "--cached", "--name-only"),
    )

    with pytest.raises(PhaseCheckpointError, match="inside the project root"):
        create_phase_checkpoint(
            project_root=repo,
            spec_dir=outside,
            phase="phase1-what",
            next_phase="phase1-why2",
            run_id="spec-run",
            spec_id="001-demo",
        )

    assert (
        _git(repo, "branch", "--show-current"),
        _git(repo, "rev-parse", "HEAD"),
        _git(repo, "diff", "--cached", "--name-only"),
    ) == position_before
    assert not (outside / ".echelon" / "checkpoints.json").exists()


def test_commit_manual_checkpoint_commits_only_active_spec_path(tmp_path: Path) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    (spec_dir / "tasks.md").write_text("# Manual tasks\n", encoding="utf-8")
    (repo / "unrelated.txt").write_text("unrelated staged\n", encoding="utf-8")
    _git(repo, "add", "unrelated.txt")

    checkpoint = commit_manual_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase3-plan",
        run_id="spec-run",
        message="docs: manual spec checkpoint",
    )

    assert _git(repo, "show", "--format=", "--name-only", "HEAD").splitlines() == [
        "runs/spec-run/specs/001-demo/tasks.md"
    ]
    assert _git(repo, "diff", "--cached", "--name-only") == "unrelated.txt"
    assert checkpoint.commit == _git(repo, "rev-parse", "HEAD")

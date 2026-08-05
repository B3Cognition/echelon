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
    config = repo / ".echelon" / "config.yml"
    config.parent.mkdir()
    config.write_text("lexicon_gate: warn\n", encoding="utf-8")
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


def _repo_at_retarget_checkpoint(tmp_path: Path) -> tuple[Path, Path, str, str]:
    repo, spec_dir, checkpoint, _later = _repo_with_checkpoint(tmp_path)
    _git(repo, "reset", "--hard", checkpoint)
    history = spec_dir / "retarget-history.json"
    history.write_text('{"status":"prepared"}\n', encoding="utf-8")
    _git(repo, "add", "specs/001-demo/retarget-history.json")
    _git(repo, "commit", "-m", "retarget checkpoint")
    retarget_checkpoint = _git(repo, "rev-parse", "HEAD")
    checkpoint_id = "retarget-preflight-retarget-test"
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint(
            checkpoint_id,
            "001-demo",
            "retarget",
            "phase0-constitution",
            retarget_checkpoint,
            retarget_checkpoint,
            "retarget-preflight",
            "squad-base",
            "2026-08-05T00:00:00Z",
        ),
    )
    return repo, spec_dir, retarget_checkpoint, checkpoint_id


def test_rewind_requires_confirmation_when_branch_has_later_commits(tmp_path: Path) -> None:
    repo, _spec_dir, checkpoint, later = _repo_with_checkpoint(tmp_path)

    result = prepare_rewind(project_root=repo, spec="001", target="phase3-plan", confirm=False)

    assert not result.applied
    assert result.from_commit == later
    assert result.to_commit == checkpoint
    assert "echelon spec rewind phase3-plan --confirm" in result.message


def test_rewind_preview_selects_checkpoint_commit_and_preserves_confirmation_selector(
    tmp_path: Path,
) -> None:
    repo, _spec_dir, checkpoint, later = _repo_with_checkpoint(tmp_path)

    result = prepare_rewind(
        project_root=repo,
        spec="001",
        target="phase3-plan",
        checkpoint_commit=checkpoint[:8],
        confirm=False,
    )

    assert not result.applied
    assert result.from_commit == later
    assert result.to_commit == checkpoint
    assert (
        f"echelon spec rewind phase3-plan --commit {checkpoint[:8]} --confirm"
        in result.message
    )


def test_rewind_preview_preserves_checkpoint_id_target_in_confirmation(
    tmp_path: Path,
) -> None:
    repo, spec_dir, checkpoint, _later = _repo_with_checkpoint(tmp_path)
    explicit_id = "user-accepted-phase3-plan-20260726-050000"
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint(
            explicit_id,
            "001-demo",
            "phase3-plan",
            "phase3-consensus",
            checkpoint,
            "",
            "user-accepted",
            "squad-1",
            "2026-07-26T05:00:00Z",
        ),
    )

    result = prepare_rewind(
        project_root=repo,
        spec="001",
        target=explicit_id,
        checkpoint_commit=checkpoint[:8],
        confirm=False,
    )

    assert (
        f"echelon spec rewind {explicit_id} "
        f"--commit {checkpoint[:8]} --confirm"
        in result.message
    )


def test_rewind_creates_backup_ref_and_resets_branch_when_confirmed(tmp_path: Path) -> None:
    repo, _spec_dir, checkpoint, later = _repo_with_checkpoint(tmp_path)

    result = prepare_rewind(project_root=repo, spec="001", target="phase3-plan", confirm=True)

    assert result.applied
    assert _git(repo, "rev-parse", "HEAD") == checkpoint
    assert _git(repo, "rev-parse", result.backup_ref) == later


def test_rewind_refuses_dirty_active_spec_worktree(tmp_path: Path) -> None:
    repo, spec_dir, _checkpoint, _later = _repo_with_checkpoint(tmp_path)
    (spec_dir / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(RewindError, match="dirty active spec paths"):
        prepare_rewind(project_root=repo, spec="001", target="phase3-plan", confirm=True)


def test_rewind_preserves_dirty_workspace_config_outside_the_active_spec(
    tmp_path: Path,
) -> None:
    repo, _spec_dir, checkpoint, _later = _repo_with_checkpoint(tmp_path)
    config = repo / ".echelon" / "config.yml"
    config.write_text("lexicon_gate: block\n", encoding="utf-8")

    result = prepare_rewind(
        project_root=repo,
        spec="001",
        target="phase3-plan",
        confirm=True,
    )

    assert result.applied
    assert _git(repo, "rev-parse", "HEAD") == checkpoint
    assert config.read_text(encoding="utf-8") == "lexicon_gate: block\n"
    assert ".echelon/config.yml" in _git(repo, "status", "--short")


def test_rewind_refuses_dirty_files_owned_by_the_active_spec(tmp_path: Path) -> None:
    repo, spec_dir, _checkpoint, _later = _repo_with_checkpoint(tmp_path)
    (spec_dir / "spec.md").write_text("uncommitted spec edit\n", encoding="utf-8")

    with pytest.raises(RewindError, match="dirty active spec paths"):
        prepare_rewind(project_root=repo, spec="001", target="phase3-plan", confirm=True)


def test_retarget_retry_discards_only_enumerated_recovery_owned_dirty_paths(
    tmp_path: Path,
) -> None:
    repo, spec_dir, checkpoint, _later = _repo_with_checkpoint(tmp_path)
    history = spec_dir / "retarget-history.json"
    history.write_text('{"failed":true}\n', encoding="utf-8")

    result = prepare_rewind(
        project_root=repo,
        spec="001",
        target="phase3-plan",
        confirm=True,
        discard_active_spec_dirty_paths=frozenset({"retarget-history.json"}),
    )

    assert result.applied
    assert _git(repo, "rev-parse", "HEAD") == checkpoint
    assert not history.exists()


def test_retarget_retry_still_rejects_unowned_active_spec_dirt(
    tmp_path: Path,
) -> None:
    repo, spec_dir, _checkpoint, _later = _repo_with_checkpoint(tmp_path)
    (spec_dir / "retarget-history.json").write_text(
        '{"failed":true}\n', encoding="utf-8"
    )
    (spec_dir / "spec.md").write_text("user edit\n", encoding="utf-8")

    with pytest.raises(RewindError, match="dirty active spec paths"):
        prepare_rewind(
            project_root=repo,
            spec="001",
            target="phase3-plan",
            confirm=True,
            discard_active_spec_dirty_paths=frozenset({"retarget-history.json"}),
        )


def test_same_head_retarget_retry_discards_tracked_and_untracked_after_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.rewind as rewind

    repo, spec_dir, checkpoint, checkpoint_id = _repo_at_retarget_checkpoint(
        tmp_path
    )
    history = spec_dir / "retarget-history.json"
    report = spec_dir / "mempalace-mine.json"
    history.write_text('{"status":"failed"}\n', encoding="utf-8")
    report.write_text('{"stale":true}\n', encoding="utf-8")
    original_discard = rewind._discard_recovery_dirty_paths
    events: list[str] = []

    def discard_after_backup(project_root: Path, paths: tuple[str, ...]) -> None:
        refs = _git(
            repo,
            "for-each-ref",
            "--format=%(objectname)",
            "refs/heads/echelon/backup",
        )
        assert checkpoint in refs.splitlines()
        events.append("backup-before-discard")
        original_discard(project_root, paths)

    monkeypatch.setattr(rewind, "_discard_recovery_dirty_paths", discard_after_backup)

    result = prepare_rewind(
        project_root=repo,
        spec="001",
        target=checkpoint_id,
        confirm=True,
        discard_active_spec_dirty_paths=frozenset(
            {"retarget-history.json", "mempalace-mine.json"}
        ),
    )

    assert result.applied
    assert result.backup_ref
    assert _git(repo, "rev-parse", result.backup_ref) == checkpoint
    assert history.read_text(encoding="utf-8") == '{"status":"prepared"}\n'
    assert not report.exists()
    assert events == ["backup-before-discard"]


def test_same_head_retarget_preview_is_byte_for_byte_nonmutating(
    tmp_path: Path,
) -> None:
    repo, spec_dir, checkpoint, checkpoint_id = _repo_at_retarget_checkpoint(
        tmp_path
    )
    history = spec_dir / "retarget-history.json"
    report = spec_dir / "mempalace-mine.json"
    history.write_text('{"status":"failed"}\n', encoding="utf-8")
    report.write_text('{"stale":true}\n', encoding="utf-8")
    before = (
        _git(repo, "rev-parse", "HEAD"),
        _git(repo, "status", "--porcelain=v1", "--untracked-files=all"),
        _git(repo, "for-each-ref", "--format=%(refname):%(objectname)"),
        history.read_bytes(),
        report.read_bytes(),
    )

    result = prepare_rewind(
        project_root=repo,
        spec="001",
        target=checkpoint_id,
        confirm=False,
        discard_active_spec_dirty_paths=frozenset(
            {"retarget-history.json", "mempalace-mine.json"}
        ),
    )
    after = (
        _git(repo, "rev-parse", "HEAD"),
        _git(repo, "status", "--porcelain=v1", "--untracked-files=all"),
        _git(repo, "for-each-ref", "--format=%(refname):%(objectname)"),
        history.read_bytes(),
        report.read_bytes(),
    )

    assert not result.applied
    assert before == after
    assert result.from_commit == checkpoint == result.to_commit


def test_same_head_retarget_retry_rejects_unowned_spec_dirt(
    tmp_path: Path,
) -> None:
    repo, spec_dir, _checkpoint, checkpoint_id = _repo_at_retarget_checkpoint(
        tmp_path
    )
    (spec_dir / "retarget-history.json").write_text(
        '{"status":"failed"}\n', encoding="utf-8"
    )
    (spec_dir / "spec.md").write_text("user edit\n", encoding="utf-8")

    with pytest.raises(RewindError, match="dirty active spec paths"):
        prepare_rewind(
            project_root=repo,
            spec="001",
            target=checkpoint_id,
            confirm=True,
            discard_active_spec_dirty_paths=frozenset({"retarget-history.json"}),
        )


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

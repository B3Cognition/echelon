from pathlib import Path
import json
import subprocess

import pytest

from echelon.checkpoint_cli import run_checkpoint_command
from harness.phase_checkpoints import PhaseCheckpoint, record_checkpoint_metadata


def test_checkpoint_list_requires_spec_when_no_active_spec(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        run_checkpoint_command(["list"], project_root=tmp_path)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "No active spec resolved" in err
    assert "echelon spec checkpoint list --spec 001" in err


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


def test_checkpoint_list_explains_ledger_order_and_marks_latest_phase_occurrence(
    tmp_path: Path,
    capsys,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    checkpoints = [
        PhaseCheckpoint(
            id="phase1-what",
            spec_id="001-demo",
            phase="phase1-what",
            next_phase="phase1-understanding",
            commit="1111111" + ("a" * 33),
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-26T03:00:00+00:00",
            completion_id="1" * 32,
        ),
        PhaseCheckpoint(
            id="phase1-lexicon",
            spec_id="001-demo",
            phase="phase1-lexicon",
            next_phase="checkpoint-assess",
            commit="2222222" + ("b" * 33),
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-26T02:00:00Z",
            completion_id="2" * 32,
        ),
        PhaseCheckpoint(
            id="phase1-what",
            spec_id="001-demo",
            phase="phase1-what",
            next_phase="phase1-understanding",
            commit="3333333" + ("c" * 33),
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-26T01:00:00Z",
            completion_id="3" * 32,
        ),
    ]
    for checkpoint in checkpoints:
        record_checkpoint_metadata(spec_dir, checkpoint)

    run_checkpoint_command(["list", "--spec", "001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "Order: oldest -> newest (ledger order)" in out
    assert "phase-only rewind selects the last matching row" in out
    assert "CREATED UTC" in out
    assert "LATEST" in out
    assert "2026-07-26 03:00:00" in out
    assert out.index("1111111") < out.index("2222222") < out.index("3333333")
    lines = out.splitlines()
    first_what = next(line for line in lines if "1111111" in line)
    lexicon = next(line for line in lines if "2222222" in line)
    last_what = next(line for line in lines if "3333333" in line)
    assert " yes " not in first_what
    assert " yes " in lexicon
    assert " yes " in last_what


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo_with_spec(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "001-demo")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo, spec_dir


def test_checkpoint_accept_refuses_dirty_files(tmp_path: Path) -> None:
    from harness.phase_checkpoints import accept_checkpoint_baseline

    repo, spec_dir = _repo_with_spec(tmp_path)
    (spec_dir / "tasks.md").write_text("# Dirty Tasks\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="dirty worktree"):
        accept_checkpoint_baseline(
            project_root=repo,
            spec_dir=spec_dir,
            phase="phase3-plan",
            run_id="squad-1",
        )


def test_checkpoint_accept_moves_ledger_without_creating_commit(tmp_path: Path) -> None:
    from harness.phase_checkpoints import accept_checkpoint_baseline

    repo, spec_dir = _repo_with_spec(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")

    checkpoint = accept_checkpoint_baseline(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase3-plan",
        run_id="squad-1",
        boundary_completion_id="a" * 32,
    )

    assert _git(repo, "rev-parse", "HEAD") == head
    assert checkpoint.commit == head
    assert checkpoint.boundary_completion_id == "a" * 32


def test_checkpoint_commit_writes_echelon_trailers(tmp_path: Path) -> None:
    from harness.phase_checkpoints import commit_manual_checkpoint

    repo, spec_dir = _repo_with_spec(tmp_path)
    (spec_dir / "tasks.md").write_text("# Manual Tasks\n", encoding="utf-8")

    checkpoint = commit_manual_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase3-plan",
        run_id="squad-1",
        message="docs: accept manual Phase A checkpoint",
        boundary_completion_id="a" * 32,
    )

    body = _git(repo, "log", "-1", "--format=%B")
    assert checkpoint.source == "user-committed"
    assert "Co-authored-by: Echelon <echelon@b3cognition.dev>" in body
    assert "Echelon-Action: user-committed-checkpoint" in body
    assert "Echelon-Spec: 001-demo" in body
    assert "Echelon-Completion: " + ("a" * 32) in body
    assert "Echelon-Checkpoint-Source: user-committed" in body
    assert checkpoint.boundary_completion_id == "a" * 32


def test_checkpoint_accept_binds_latest_executed_phase_completion(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _repo_with_spec(tmp_path)
    run_dir = repo / "runs" / "spec-20260820-000000"
    run_dir.mkdir(parents=True)
    (repo / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "checkpoint_policy_version": 2,
                "spec_id": "001-demo",
                "spec_dir": "specs/001-demo",
                "phase_completion_outcomes": [
                    {
                        "completion_id": "a" * 32,
                        "phase": "phase3-plan",
                        "outcome": "executed",
                    },
                    {
                        "completion_id": "b" * 32,
                        "phase": "phase3-plan",
                        "outcome": "executed",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "runs")
    _git(repo, "commit", "-m", "test: add run state")

    run_checkpoint_command(
        ["accept", "--phase", "phase3-plan", "--run-id", run_dir.name],
        project_root=repo,
    )

    checkpoint = json.loads(
        (spec_dir / ".echelon" / "checkpoints.json").read_text(encoding="utf-8")
    )["checkpoints"][-1]
    assert checkpoint["source"] == "user-accepted"
    assert checkpoint["boundary_completion_id"] == "b" * 32


def test_checkpoint_list_uses_active_spec_from_run_state(tmp_path: Path, capsys) -> None:
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
    run_dir = tmp_path / "runs" / "spec-20260704-120000"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps({"spec_dir": "runs/spec-20260704-120000/specs/001-demo"}),
        encoding="utf-8",
    )

    run_checkpoint_command(["list"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "CHECKPOINTS - spec 001-demo" in out
    assert "phase3-plan" in out


def test_checkpoint_list_spec_prefers_matching_active_staging_spec(
    tmp_path: Path,
    capsys,
) -> None:
    stale_spec_dir = tmp_path / "specs" / "001-old-feature"
    stale_spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        stale_spec_dir,
        PhaseCheckpoint(
            id="phase3-plan",
            spec_id="001-old-feature",
            phase="phase3-plan",
            next_phase="phase3-consensus",
            commit="oldabcdef123",
            metadata_commit="",
            source="auto",
            run_id="old-run",
            created_at="2026-07-04T11:00:00Z",
        ),
    )
    active_spec_dir = tmp_path / "runs" / "spec-20260704-120000" / "staging"
    active_spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        active_spec_dir,
        PhaseCheckpoint(
            id="phase1-why1",
            spec_id="001-simple-notes",
            phase="phase1-why1",
            next_phase="phase1-why1",
            commit="newabcdef123",
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-04T12:00:00Z",
        ),
    )
    run_dir = active_spec_dir.parent
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "spec_id": "001-simple-notes",
                "spec_dir": "runs/spec-20260704-120000/staging",
            }
        ),
        encoding="utf-8",
    )

    run_checkpoint_command(["list", "--spec", "001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "CHECKPOINTS - spec 001-simple-notes" in out
    assert "phase1-why1" in out
    assert "oldabcd" not in out


def test_checkpoint_list_without_spec_uses_active_staging_spec(
    tmp_path: Path,
    capsys,
) -> None:
    active_spec_dir = tmp_path / "runs" / "spec-20260704-120000" / "staging"
    active_spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        active_spec_dir,
        PhaseCheckpoint(
            id="phase1-why1",
            spec_id="001-simple-notes",
            phase="phase1-why1",
            next_phase="phase1-why1",
            commit="newabcdef123",
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-04T12:00:00Z",
        ),
    )
    run_dir = active_spec_dir.parent
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "spec_id": "001-simple-notes",
                "spec_dir": "runs/spec-20260704-120000/staging",
            }
        ),
        encoding="utf-8",
    )

    run_checkpoint_command(["list"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "CHECKPOINTS - spec 001-simple-notes" in out
    assert "phase1-why1" in out


def test_checkpoint_list_prefers_existing_active_run_spec_over_published(
    tmp_path: Path,
    capsys,
) -> None:
    published_spec_dir = tmp_path / "specs" / "001-simple-notes"
    published_spec_dir.mkdir(parents=True)

    active_spec_dir = tmp_path / "runs" / "spec-20260704-120000" / "specs" / "001-simple-notes"
    active_spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        active_spec_dir,
        PhaseCheckpoint(
            id="phase3-sentinel",
            spec_id="001-simple-notes",
            phase="phase3-sentinel",
            next_phase="phase3-plan",
            commit="newabcdef123",
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-04T12:00:00Z",
        ),
    )
    run_dir = active_spec_dir.parents[1]
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "spec_id": "001-simple-notes",
                "spec_dir": "runs/spec-20260704-120000/specs/001-simple-notes",
                "published_spec_dir": "specs/001-simple-notes",
            }
        ),
        encoding="utf-8",
    )

    run_checkpoint_command(["list"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "CHECKPOINTS - spec 001-simple-notes" in out
    assert "phase3-sentinel" in out

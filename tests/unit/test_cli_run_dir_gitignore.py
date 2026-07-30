from __future__ import annotations

import subprocess
from pathlib import Path

from echelon.cli import _setup_run_dir
from harness.phase_checkpoints import create_phase_checkpoint


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Echelon Tests")
    _git(repo, "config", "user.email", "echelon@example.test")
    (repo / "README.md").write_text("# Repository\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_setup_run_dir_preserves_and_idempotently_extends_gitignore(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    runs_dir = project_root / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / ".gitignore").write_text("custom-local-entry\n", encoding="utf-8")

    _setup_run_dir(project_root, "spec-run-a")
    _setup_run_dir(project_root, "spec-run-b")

    lines = (runs_dir / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "custom-local-entry" in lines
    assert lines.count("**/.echelon/checkpoints.json") == 1
    assert lines.count("**/.echelon/checkpoints.lock") == 1
    assert lines.count("**/.echelon/.checkpoints.json.*.tmp") == 1
    assert lines.count("*/state.json") == 1
    assert lines.count("*/*.tmp") == 1
    assert lines.count(".current*") == 1


def test_setup_run_dir_keeps_checkpoint_ledger_out_of_git_status(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    run_dir = _setup_run_dir(repo, "spec-run")
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", "runs/.gitignore", "runs/spec-run/specs/001-demo/spec.md")
    _git(repo, "commit", "-m", "seed active spec")

    create_phase_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase1-what",
        next_phase="phase1-why2",
        run_id="spec-run",
    )

    ledger = "runs/spec-run/specs/001-demo/.echelon/checkpoints.json"
    assert _git(repo, "check-ignore", ledger) == ledger
    assert _git(repo, "status", "--short") == ""

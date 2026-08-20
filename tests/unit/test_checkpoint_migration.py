from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

import echelon.checkpoint_migration as migration_module
from echelon.checkpoint_migration import (
    LegacyCheckpointMigrationError,
    apply_legacy_checkpoint_migration,
    prepare_legacy_checkpoint_migration,
)
from echelon.spec_lifecycle import PhaseAExecutionLock, resolve_spec_run
from harness.phase_checkpoints import load_checkpoint_ledger


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _legacy_repo(tmp_path: Path) -> tuple[Path, Path, Path, object]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "001-demo")
    _git(repo, "config", "user.name", "Migration Test")
    _git(repo, "config", "user.email", "migration@example.test")
    run_dir = repo / "runs" / "spec-run-1"
    staging = run_dir / "staging"
    spec_dir = run_dir / "specs" / "001-demo"
    staging.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    state = {
        "run_id": "spec-run-1",
        "spec_id": "001-demo",
        "feature_branch": "001-demo",
        "spec_dir": spec_dir.relative_to(repo).as_posix(),
        "state_revision": 0,
        "completed_phases": ["phase1-discover", "phase1-synthesizer"],
        "phase": "phase1-why1",
        "status": "interrupted",
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (repo / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    _git(repo, "add", "README.md", "runs/spec-run-1/state.json", "runs/.current")
    _git(repo, "commit", "-m", "base")
    return repo, staging, spec_dir, resolve_spec_run(repo, run_dir.name)


def test_legacy_migration_preview_is_allowlisted_and_non_mutating(
    tmp_path: Path,
) -> None:
    repo, staging, spec_dir, run = _legacy_repo(tmp_path)
    (staging / "glossary.md").write_text("terms\n", encoding="utf-8")
    (staging / "user-intent.md").write_text("intent\n", encoding="utf-8")
    (staging / "state.json").write_text("{}\n", encoding="utf-8")
    (staging / "unknown.md").write_text("ignore\n", encoding="utf-8")
    head = _git(repo, "rev-parse", "HEAD")

    plan = prepare_legacy_checkpoint_migration(repo, run)

    assert [item.name for item in plan.files] == ["glossary.md", "user-intent.md"]
    assert plan.ignored == ("state.json", "unknown.md")
    assert plan.captured_head == head
    assert not (spec_dir / "glossary.md").exists()
    assert _git(repo, "rev-parse", "HEAD") == head


def test_legacy_migration_preview_rejects_allowlisted_symlink(
    tmp_path: Path,
) -> None:
    repo, staging, _, run = _legacy_repo(tmp_path)
    outside = repo / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    (staging / "glossary.md").symlink_to(outside)

    with pytest.raises(LegacyCheckpointMigrationError, match="regular file"):
        prepare_legacy_checkpoint_migration(repo, run)


def test_legacy_migration_preview_rejects_different_destination(
    tmp_path: Path,
) -> None:
    repo, staging, spec_dir, run = _legacy_repo(tmp_path)
    (staging / "glossary.md").write_text("source\n", encoding="utf-8")
    (spec_dir / "glossary.md").write_text("different\n", encoding="utf-8")

    with pytest.raises(LegacyCheckpointMigrationError, match="collision"):
        prepare_legacy_checkpoint_migration(repo, run)


def test_legacy_migration_is_blocked_by_live_phase_a_execution(
    tmp_path: Path,
) -> None:
    repo, staging, spec_dir, run = _legacy_repo(tmp_path)
    (staging / "glossary.md").write_text("terms\n", encoding="utf-8")

    with PhaseAExecutionLock.acquire(repo, "live-controller"):
        with pytest.raises(LegacyCheckpointMigrationError, match="live-controller"):
            prepare_legacy_checkpoint_migration(repo, run)

    assert not (spec_dir / "glossary.md").exists()


def test_legacy_migration_commits_and_promotes_state_idempotently(
    tmp_path: Path,
) -> None:
    repo, staging, spec_dir, run = _legacy_repo(tmp_path)
    (staging / "glossary.md").write_text("terms\n", encoding="utf-8")
    (staging / "user-intent.md").write_text("intent\n", encoding="utf-8")
    plan = prepare_legacy_checkpoint_migration(repo, run)

    checkpoint = apply_legacy_checkpoint_migration(repo, plan)
    replayed = apply_legacy_checkpoint_migration(repo, plan)

    assert replayed == checkpoint
    assert (spec_dir / "glossary.md").read_text(encoding="utf-8") == "terms\n"
    assert (staging / "glossary.md").read_text(encoding="utf-8") == "terms\n"
    state = json.loads((run.run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["checkpoint_policy_version"] == 2
    assert [row["phase"] for row in state["phase_completion_outcomes"]] == [
        "phase1-discover",
        "phase1-synthesizer",
    ]
    assert all(row["legacy"] is True for row in state["phase_completion_outcomes"])
    ledger = load_checkpoint_ledger(spec_dir)
    assert ledger.checkpoints == [checkpoint]
    assert checkpoint.source == "legacy-migration"
    assert checkpoint.rewind == "none"
    assert checkpoint.rewind_reason == "legacy-migration-boundary"
    assert checkpoint.boundary_completion_id == ""
    body = _git(repo, "show", "-s", "--format=%B", checkpoint.commit)
    assert "Co-authored-by: Echelon <echelon@b3cognition.dev>" in body
    assert "Echelon-Checkpoint-Source: legacy-migration" in body
    assert _git(repo, "rev-list", "--count", "HEAD") == "2"


def test_legacy_migration_recovers_commit_created_before_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, staging, spec_dir, run = _legacy_repo(tmp_path)
    (staging / "glossary.md").write_text("terms\n", encoding="utf-8")
    plan = prepare_legacy_checkpoint_migration(repo, run)
    real_create = migration_module.create_or_recover_completion_checkpoint

    def crash_after_commit(**kwargs):
        def fault(boundary: str) -> None:
            if boundary == "after_commit":
                raise RuntimeError("crash after commit")

        return real_create(**kwargs, fault_hook=fault)

    with monkeypatch.context() as scoped:
        scoped.setattr(
            migration_module,
            "create_or_recover_completion_checkpoint",
            crash_after_commit,
        )
        with pytest.raises(RuntimeError, match="crash after commit"):
            apply_legacy_checkpoint_migration(repo, plan)

    assert (spec_dir / "glossary.md").read_text(encoding="utf-8") == "terms\n"
    assert not load_checkpoint_ledger(spec_dir).checkpoints
    assert json.loads((run.run_dir / "state.json").read_text())["state_revision"] == 0

    checkpoint = apply_legacy_checkpoint_migration(repo, plan)

    assert checkpoint.source == "legacy-migration"
    assert len(load_checkpoint_ledger(spec_dir).checkpoints) == 1
    assert _git(repo, "rev-list", "--count", "HEAD") == "2"


def test_confirmed_legacy_migration_rechecks_execution_lease_before_mutation(
    tmp_path: Path,
) -> None:
    repo, staging, spec_dir, run = _legacy_repo(tmp_path)
    (staging / "glossary.md").write_text("terms\n", encoding="utf-8")
    plan = prepare_legacy_checkpoint_migration(repo, run)
    head = _git(repo, "rev-parse", "HEAD")

    with PhaseAExecutionLock.acquire(repo, "live-controller"):
        with pytest.raises(LegacyCheckpointMigrationError, match="live-controller"):
            apply_legacy_checkpoint_migration(repo, plan)

    assert _git(repo, "rev-parse", "HEAD") == head
    assert not (spec_dir / "glossary.md").exists()


def test_legacy_migration_restores_copied_files_when_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, staging, spec_dir, run = _legacy_repo(tmp_path)
    (staging / "glossary.md").write_text("terms\n", encoding="utf-8")
    plan = prepare_legacy_checkpoint_migration(repo, run)
    monkeypatch.setattr(
        migration_module,
        "create_or_recover_completion_checkpoint",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("commit failed")),
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        apply_legacy_checkpoint_migration(repo, plan)

    assert not (spec_dir / "glossary.md").exists()
    state = json.loads((run.run_dir / "state.json").read_text())
    assert "checkpoint_policy_version" not in state


def test_legacy_migration_commits_only_allowlisted_files_when_staging_is_spec_dir(
    tmp_path: Path,
) -> None:
    repo, staging, _, _ = _legacy_repo(tmp_path)
    state_path = staging.parent / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["spec_dir"] = staging.relative_to(repo).as_posix()
    state_path.write_text(json.dumps(state), encoding="utf-8")
    _git(repo, "add", state_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "test: use staging as spec")
    (staging / "glossary.md").write_text("terms\n", encoding="utf-8")
    (staging / "unknown.md").write_text("ignore\n", encoding="utf-8")
    run = resolve_spec_run(repo, "spec-run-1")

    checkpoint = apply_legacy_checkpoint_migration(
        repo,
        prepare_legacy_checkpoint_migration(repo, run),
    )

    committed = _git(
        repo,
        "show",
        "--format=",
        "--name-only",
        checkpoint.commit,
    ).splitlines()
    assert committed == ["runs/spec-run-1/staging/glossary.md"]
    assert "?? runs/spec-run-1/staging/unknown.md" in _git(repo, "status", "--short")

"""Real-Git tests for Echelon-owned fresh Phase A starts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from echelon.phase_a_start import PhaseAStartError, start_phase_a_spec


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Echelon Tests")
    _git(repo, "config", "user.email", "echelon@example.test")
    (repo / ".gitignore").write_text(
        "/.echelon/runtime/\n/runs/.current\n/runs/*/state.json\n"
        "/runs/*/specs/*/.echelon/checkpoints.json\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "README.md")
    _git(repo, "commit", "-m", "base")
    return repo


def _checkpoint_active_run(repo: Path) -> str:
    base = _git(repo, "rev-parse", "main^{commit}")
    _git(repo, "switch", "-c", "001-spec-a", base)
    run_dir = repo / "runs" / "run-a"
    spec_dir = run_dir / "specs" / "001-spec-a"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec A\n", encoding="utf-8")
    _git(repo, "add", str((spec_dir / "spec.md").relative_to(repo)))
    _git(repo, "commit", "-m", "checkpoint A")
    checkpoint = _git(repo, "rev-parse", "HEAD^{commit}")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "runtime-a",
                "spec_id": "001-spec-a",
                "feature_branch": "001-spec-a",
                "spec_dir": "runs/run-a/specs/001-spec-a",
                "published_spec_dir": "specs/001-spec-a",
            }
        ),
        encoding="utf-8",
    )
    ledger = spec_dir / ".echelon" / "checkpoints.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps(
            {
                "spec_id": "001-spec-a",
                "checkpoints": [
                    {
                        "id": "phase-a",
                        "spec_id": "001-spec-a",
                        "phase": "phase-a",
                        "next_phase": "phase-next",
                        "commit": checkpoint,
                        "metadata_commit": "",
                        "source": "auto",
                        "run_id": "runtime-a",
                        "created_at": "2026-07-17T12:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (repo / "runs" / ".current").write_text("run-a\n", encoding="utf-8")
    return base


def test_first_spec_starts_on_sibling_branch_and_selects_discoverable_run(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "main^{commit}")

    outcome = start_phase_a_spec(repo, "run-b", "Build audit logging")

    assert outcome.bootstrap.spec_id == "001-build-audit-logging"
    assert _git(repo, "branch", "--show-current") == outcome.bootstrap.feature_branch
    assert _git(repo, "rev-parse", "HEAD^{commit}") == base
    assert (repo / "runs" / ".current").read_text().strip() == "run-b"
    state = json.loads((outcome.run_dir / "state.json").read_text())
    assert state["status"] == "preparing"
    assert state["run_id"] == "run-b"
    assert state["feature_branch"] == outcome.bootstrap.feature_branch


def test_first_spec_refuses_unmanaged_nondefault_checkout(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "switch", "-c", "unmanaged-work")

    with pytest.raises(PhaseAStartError, match="requires the configured default branch"):
        start_phase_a_spec(repo, "run-b", "Build audit logging")

    assert _git(repo, "branch", "--show-current") == "unmanaged-work"
    assert not (repo / "runs" / ".current").exists()


def test_next_spec_ignores_prior_status_but_requires_checkpoint_and_uses_main(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    base = _checkpoint_active_run(repo)

    outcome = start_phase_a_spec(repo, "run-b", "Build search dashboard")

    assert outcome.source_checkpoint is not None
    assert outcome.source_checkpoint.checkpoint_id == "phase-a"
    assert outcome.bootstrap.spec_id == "002-build-search-dashboard"
    assert _git(repo, "branch", "--show-current") == "002-build-search-dashboard"
    assert _git(repo, "rev-parse", "HEAD^{commit}") == base
    assert (repo / "runs" / ".current").read_text().strip() == "run-b"


def test_next_spec_refuses_dirty_outgoing_run_by_default(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="dirty worktree"):
        start_phase_a_spec(repo, "run-b", "Build search dashboard")

    assert _git(repo, "branch", "--show-current") == "001-spec-a"
    assert (repo / "runs" / ".current").read_text().strip() == "run-a"
    assert not (repo / "runs" / "run-b").exists()


def test_next_spec_can_stash_dirty_outgoing_run(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    outcome = start_phase_a_spec(
        repo,
        "run-b",
        "Build search dashboard",
        dirty_action="stash",
    )

    assert outcome.stash_commit
    assert _git(repo, "status", "--short") == ""
    source_state = json.loads((repo / "runs" / "run-a" / "state.json").read_text())
    assert source_state["phase_a_stash"]["commit"] == outcome.stash_commit


def test_next_spec_requires_a_checkpoint_even_when_prior_status_is_nonfinal(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    ledger = repo / "runs" / "run-a" / "specs" / "001-spec-a" / ".echelon" / "checkpoints.json"
    ledger.unlink()

    with pytest.raises(PhaseAStartError, match="checkpoint"):
        start_phase_a_spec(repo, "run-b", "Build search dashboard")

    assert _git(repo, "branch", "--show-current") == "001-spec-a"
    assert (repo / "runs" / ".current").read_text().strip() == "run-a"


def test_next_spec_can_discard_dirty_changes_only_with_confirmation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="explicit confirmation"):
        start_phase_a_spec(
            repo,
            "run-b",
            "Build search dashboard",
            dirty_action="discard",
        )

    outcome = start_phase_a_spec(
        repo,
        "run-b",
        "Build search dashboard",
        dirty_action="discard",
        confirm_discard=True,
    )

    assert outcome.bootstrap.spec_id == "002-build-search-dashboard"
    assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"


def test_controller_preserves_prepared_git_identity_without_provider(tmp_path: Path) -> None:
    from harness.squad import SquadController
    from harness.squad_state import SquadStateStore

    class TerminalGraph:
        def entry_phase(self) -> str:
            return "DONE"

        def all_phase_ids(self) -> set[str]:
            return {"DONE"}

    repo = _repo(tmp_path)
    outcome = start_phase_a_spec(repo, "run-b", "Build audit logging")
    store = SquadStateStore(outcome.run_dir)
    controller = SquadController(
        provider=object(),
        state_store=store,
        phase_graph=TerminalGraph(),
        ext_dir=repo / "missing-extension",
        project_root=repo,
        squad_dir=outcome.run_dir,
    )

    result = controller.run(user_message="Build audit logging")

    state = store.load()
    assert result.status == "done"
    assert state["run_id"] == "run-b"
    assert state["spec_id"] == outcome.bootstrap.spec_id
    assert state["feature_branch"] == outcome.bootstrap.feature_branch
    assert state["phase_a_base_commit"] == outcome.bootstrap.default_commit

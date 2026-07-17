"""Real-Git tests for checkpoint-gated Phase A spec switching."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from echelon.git_helpers import GitHelperError
from echelon.spec_lifecycle import (
    PhaseAExecutionLock,
    load_spec_switch_intent,
    resolve_spec_run,
)
from echelon.spec_switch import (
    DirtySpecWorktreeError,
    SpecSwitchError,
    switch_spec,
    validate_spec_checkpoint,
)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def _write_run_state(
    repo: Path,
    run_name: str,
    *,
    run_id: str,
    spec_id: str,
    branch: str,
) -> Path:
    run_dir = repo / "runs" / run_name
    spec_dir = run_dir / "specs" / spec_id
    spec_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "spec_id": spec_id,
                "feature_branch": branch,
                "spec_dir": spec_dir.relative_to(repo).as_posix(),
                "published_spec_dir": f"specs/{spec_id}",
            }
        ),
        encoding="utf-8",
    )
    return spec_dir


def _write_ledger(
    spec_dir: Path,
    *,
    spec_id: str,
    checkpoints: list[dict[str, str]],
) -> None:
    path = spec_dir / ".echelon" / "checkpoints.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"spec_id": spec_id, "checkpoints": checkpoints}),
        encoding="utf-8",
    )


def _checkpoint(
    *,
    checkpoint_id: str,
    spec_id: str,
    run_id: str,
    commit: str,
) -> dict[str, str]:
    return {
        "id": checkpoint_id,
        "spec_id": spec_id,
        "phase": checkpoint_id,
        "next_phase": "phase-next",
        "commit": commit,
        "metadata_commit": "",
        "source": "auto",
        "run_id": run_id,
        "created_at": "2026-07-17T12:00:00+00:00",
    }


@pytest.fixture
def switch_repo(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Echelon Tests")
    (repo / ".gitignore").write_text(
        "/.echelon/runtime/\n"
        "/runs/.current\n"
        "/runs/*/state.json\n"
        "/runs/*/specs/*/.echelon/checkpoints.json\n",
        encoding="utf-8",
    )
    (repo / "shared.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "shared.txt")
    _git(repo, "commit", "-m", "base")

    _git(repo, "switch", "-c", "001-spec-a", "main")
    tracked_a = repo / "runs" / "run-a" / "specs" / "001-spec-a" / "spec.md"
    tracked_a.parent.mkdir(parents=True)
    tracked_a.write_text("# Spec A\n", encoding="utf-8")
    _git(repo, "add", tracked_a.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "checkpoint A")
    commit_a = _git(repo, "rev-parse", "HEAD^{commit}").stdout.strip()

    _git(repo, "switch", "main")
    _git(repo, "switch", "-c", "002-spec-b", "main")
    tracked_b = repo / "runs" / "run-b" / "specs" / "002-spec-b" / "spec.md"
    tracked_b.parent.mkdir(parents=True)
    tracked_b.write_text("# Spec B\n", encoding="utf-8")
    _git(repo, "add", tracked_b.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "checkpoint B")
    commit_b = _git(repo, "rev-parse", "HEAD^{commit}").stdout.strip()

    _git(repo, "switch", "001-spec-a")
    spec_a = _write_run_state(
        repo,
        "run-a",
        run_id="runtime-a",
        spec_id="001-spec-a",
        branch="001-spec-a",
    )
    spec_b = _write_run_state(
        repo,
        "run-b",
        run_id="runtime-b",
        spec_id="002-spec-b",
        branch="002-spec-b",
    )
    _write_ledger(
        spec_a,
        spec_id="001-spec-a",
        checkpoints=[
            _checkpoint(
                checkpoint_id="phase-a",
                spec_id="001-spec-a",
                run_id="runtime-a",
                commit=commit_a,
            ),
            _checkpoint(
                checkpoint_id="wrong-run-newer",
                spec_id="001-spec-a",
                run_id="different-runtime",
                commit=commit_b,
            ),
        ],
    )
    _write_ledger(
        spec_b,
        spec_id="002-spec-b",
        checkpoints=[
            _checkpoint(
                checkpoint_id="phase-b",
                spec_id="002-spec-b",
                run_id="runtime-b",
                commit=commit_b,
            )
        ],
    )
    (repo / "runs" / ".current").write_text("run-a\n", encoding="utf-8")
    return {
        "repo": repo,
        "spec_a": spec_a,
        "spec_b": spec_b,
        "commit_a": commit_a,
        "commit_b": commit_b,
    }


def test_validate_spec_checkpoint_selects_latest_matching_run_entry(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    run = resolve_spec_run(repo, "run-a")

    validated = validate_spec_checkpoint(repo, run)

    assert validated.checkpoint_id == "phase-a"
    assert validated.phase == "phase-a"
    assert validated.commit == switch_repo["commit_a"]
    assert validated.run == run


def test_validate_spec_checkpoint_rejects_missing_matching_checkpoint(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    spec_a = switch_repo["spec_a"]
    assert isinstance(repo, Path)
    assert isinstance(spec_a, Path)
    _write_ledger(spec_a, spec_id="001-spec-a", checkpoints=[])

    with pytest.raises(SpecSwitchError, match="no checkpoint"):
        validate_spec_checkpoint(repo, resolve_spec_run(repo, "run-a"))


def test_validate_spec_checkpoint_rejects_missing_commit(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    spec_a = switch_repo["spec_a"]
    assert isinstance(repo, Path)
    assert isinstance(spec_a, Path)
    _write_ledger(
        spec_a,
        spec_id="001-spec-a",
        checkpoints=[
            _checkpoint(
                checkpoint_id="missing",
                spec_id="001-spec-a",
                run_id="runtime-a",
                commit="0" * 40,
            )
        ],
    )

    with pytest.raises(SpecSwitchError, match="does not exist"):
        validate_spec_checkpoint(repo, resolve_spec_run(repo, "run-a"))


def test_validate_spec_checkpoint_rejects_commit_outside_feature_branch(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    spec_a = switch_repo["spec_a"]
    assert isinstance(repo, Path)
    assert isinstance(spec_a, Path)
    _write_ledger(
        spec_a,
        spec_id="001-spec-a",
        checkpoints=[
            _checkpoint(
                checkpoint_id="wrong-branch",
                spec_id="001-spec-a",
                run_id="runtime-a",
                commit=str(switch_repo["commit_b"]),
            )
        ],
    )

    with pytest.raises(SpecSwitchError, match="does not contain"):
        validate_spec_checkpoint(repo, resolve_spec_run(repo, "run-a"))


def test_clean_switch_changes_branch_then_active_pointer(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)

    outcome = switch_spec(repo, "002-spec-b")

    assert outcome.action == "switched"
    assert outcome.source.run_dir_name == "run-a"
    assert outcome.target.run_dir_name == "run-b"
    assert outcome.source_checkpoint.commit == switch_repo["commit_a"]
    assert outcome.target_checkpoint.commit == switch_repo["commit_b"]
    assert outcome.stash_commit == ""
    assert outcome.stash_restored is False
    assert _git(repo, "branch", "--show-current").stdout.strip() == "002-spec-b"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-b\n"
    assert load_spec_switch_intent(repo) is None


def test_switch_refuses_to_change_checkout_while_phase_a_is_executing(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)

    with PhaseAExecutionLock.acquire(repo, "active-controller"):
        with pytest.raises(SpecSwitchError, match="active-controller"):
            switch_spec(repo, "run-b")

    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-spec-a"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"


def test_switch_to_already_active_run_is_idempotent_even_when_dirty(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    switch_spec(repo, "run-b")
    (repo / "shared.txt").write_text("dirty but staying put\n", encoding="utf-8")

    outcome = switch_spec(repo, "runtime-b")

    assert outcome.action == "already_active"
    assert _git(repo, "branch", "--show-current").stdout.strip() == "002-spec-b"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-b\n"


def test_switch_requires_speckit_git_to_be_disabled(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    registry = repo / ".specify" / "extensions" / ".registry"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"extensions": {"git": {"enabled": True}}}),
        encoding="utf-8",
    )

    with pytest.raises(SpecSwitchError, match="sole Git authority"):
        switch_spec(repo, "run-b")

    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-spec-a"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"


def test_switch_rejects_detached_head_without_pointer_mutation(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    _git(repo, "checkout", "--detach", str(switch_repo["commit_a"]))

    with pytest.raises(SpecSwitchError, match="detached HEAD"):
        switch_spec(repo, "run-b")

    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"


def test_switch_rejects_branch_that_disagrees_with_active_pointer(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    _git(repo, "switch", "main")

    with pytest.raises(SpecSwitchError, match="active run branch"):
        switch_spec(repo, "run-b")

    assert _git(repo, "branch", "--show-current").stdout.strip() == "main"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"


def test_switch_rejects_missing_target_branch_without_pointer_mutation(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    _git(repo, "branch", "-D", "002-spec-b")

    with pytest.raises(SpecSwitchError, match="does not exist locally"):
        switch_spec(repo, "run-b")

    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-spec-a"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"


def test_checkout_failure_leaves_recoverable_intent_and_retry_completes(
    switch_repo: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    from echelon import spec_switch as spec_switch_module

    original_run_git = spec_switch_module.run_git

    def fail_target_switch(project_root: Path, *args: str, **kwargs):
        if args[:2] == ("switch", "002-spec-b"):
            raise GitHelperError("simulated checkout failure")
        return original_run_git(project_root, *args, **kwargs)

    monkeypatch.setattr(spec_switch_module, "run_git", fail_target_switch)

    with pytest.raises(SpecSwitchError, match="simulated checkout failure"):
        switch_spec(repo, "run-b")

    intent = load_spec_switch_intent(repo)
    assert intent is not None
    assert intent.stage == "prepared"
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-spec-a"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"

    monkeypatch.undo()
    outcome = switch_spec(repo, "run-b")

    assert outcome.action == "switched"
    assert load_spec_switch_intent(repo) is None
    assert _git(repo, "branch", "--show-current").stdout.strip() == "002-spec-b"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-b\n"


def test_dirty_refusal_reports_all_paths_without_mutation(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    state_a = repo / "runs" / "run-a" / "state.json"
    state_b = repo / "runs" / "run-b" / "state.json"
    before_states = (state_a.read_bytes(), state_b.read_bytes())
    before_head = _git(repo, "rev-parse", "HEAD^{commit}").stdout.strip()
    (repo / "shared.txt").write_text("unstaged change\n", encoding="utf-8")
    (repo / "staged.txt").write_text("staged change\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    untracked = repo / "untracked" / "note.txt"
    untracked.parent.mkdir()
    untracked.write_text("untracked change\n", encoding="utf-8")

    with pytest.raises(DirtySpecWorktreeError) as error:
        switch_spec(repo, "run-b")

    assert error.value.paths == ("shared.txt", "staged.txt", "untracked/note.txt")
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-spec-a"
    assert _git(repo, "rev-parse", "HEAD^{commit}").stdout.strip() == before_head
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"
    assert (state_a.read_bytes(), state_b.read_bytes()) == before_states


def test_managed_stash_records_commit_sha_and_switches_cleanly(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    (repo / "shared.txt").write_text("stashed tracked change\n", encoding="utf-8")
    (repo / "new.txt").write_text("stashed untracked change\n", encoding="utf-8")

    outcome = switch_spec(repo, "run-b", dirty_action="stash")

    stash_commit = _git(repo, "rev-parse", "refs/stash^{commit}").stdout.strip()
    state = json.loads((repo / "runs" / "run-a" / "state.json").read_text())
    record = state["phase_a_stash"]
    assert outcome.action == "switched"
    assert outcome.stash_commit == stash_commit
    assert outcome.stash_restored is False
    assert record == {
        "commit": stash_commit,
        "branch": "001-spec-a",
        "checkpoint_id": "phase-a",
        "checkpoint_commit": switch_repo["commit_a"],
        "created_at": record["created_at"],
    }
    assert record["created_at"]
    assert all("stash@" not in str(value) for value in record.values())
    assert _git(repo, "status", "--porcelain").stdout == ""
    assert _git(repo, "branch", "--show-current").stdout.strip() == "002-spec-b"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-b\n"


def test_returning_to_run_restores_and_drops_exact_managed_stash(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    (repo / "shared.txt").write_text("restore tracked change\n", encoding="utf-8")
    (repo / "new.txt").write_text("restore untracked change\n", encoding="utf-8")
    stashed = switch_spec(repo, "run-b", dirty_action="stash")

    outcome = switch_spec(repo, "run-a", restore_stash=True)

    state = json.loads((repo / "runs" / "run-a" / "state.json").read_text())
    stash_commits = _git(repo, "stash", "list", "--format=%H").stdout.splitlines()
    assert outcome.stash_restored is True
    assert outcome.stash_commit == ""
    assert outcome.restored_stash_commit == stashed.stash_commit
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "restore tracked change\n"
    assert (repo / "new.txt").read_text(encoding="utf-8") == "restore untracked change\n"
    assert "phase_a_stash" not in state
    assert stashed.stash_commit not in stash_commits
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-spec-a"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"


def test_failed_stash_restore_keeps_commit_and_run_record(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    (repo / "shared.txt").write_text("stashed side\n", encoding="utf-8")
    stashed = switch_spec(repo, "run-b", dirty_action="stash")
    switch_spec(repo, "run-a")
    (repo / "shared.txt").write_text("conflicting committed side\n", encoding="utf-8")
    _git(repo, "add", "shared.txt")
    _git(repo, "commit", "-m", "conflicting A change")

    with pytest.raises(SpecSwitchError, match="stash apply"):
        switch_spec(repo, "run-a", restore_stash=True)

    state = json.loads((repo / "runs" / "run-a" / "state.json").read_text())
    stash_commits = _git(repo, "stash", "list", "--format=%H").stdout.splitlines()
    assert state["phase_a_stash"]["commit"] == stashed.stash_commit
    assert stashed.stash_commit in stash_commits
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-spec-a"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"


def test_new_managed_stash_refuses_to_overwrite_existing_record(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    (repo / "shared.txt").write_text("first stash\n", encoding="utf-8")
    first = switch_spec(repo, "run-b", dirty_action="stash")
    switch_spec(repo, "run-a")
    (repo / "new-dirty.txt").write_text("second stash attempt\n", encoding="utf-8")

    with pytest.raises(SpecSwitchError, match="already has a managed stash"):
        switch_spec(repo, "run-b", dirty_action="stash")

    state = json.loads((repo / "runs" / "run-a" / "state.json").read_text())
    assert state["phase_a_stash"]["commit"] == first.stash_commit
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-spec-a"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"


def test_discard_requires_explicit_confirmation_without_mutation(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    before_head = _git(repo, "rev-parse", "HEAD^{commit}").stdout.strip()
    (repo / "shared.txt").write_text("must survive refused discard\n", encoding="utf-8")

    with pytest.raises(SpecSwitchError, match="confirmation"):
        switch_spec(repo, "run-b", dirty_action="discard")

    assert (repo / "shared.txt").read_text(encoding="utf-8") == "must survive refused discard\n"
    assert _git(repo, "rev-parse", "HEAD^{commit}").stdout.strip() == before_head
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-spec-a"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"


def test_confirmed_discard_resets_to_checkpoint_and_preserves_ignored_state(
    switch_repo: dict[str, object],
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    (repo / "shared.txt").write_text("discard tracked\n", encoding="utf-8")
    (repo / "staged.txt").write_text("discard staged\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    untracked = repo / "untracked" / "note.txt"
    untracked.parent.mkdir()
    untracked.write_text("discard untracked\n", encoding="utf-8")
    ignored = repo / ".echelon" / "runtime" / "keep.json"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("runtime survives\n", encoding="utf-8")

    outcome = switch_spec(
        repo,
        "run-b",
        dirty_action="discard",
        confirm_discard=True,
    )

    assert outcome.action == "switched"
    assert not (repo / "staged.txt").exists()
    assert not untracked.exists()
    assert ignored.read_text(encoding="utf-8") == "runtime survives\n"
    assert _git(repo, "branch", "--show-current").stdout.strip() == "002-spec-b"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-b\n"
    assert _git(repo, "status", "--porcelain").stdout == ""


def test_discard_git_failure_leaves_active_pointer_on_source(
    switch_repo: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    (repo / "shared.txt").write_text("dirty before failed reset\n", encoding="utf-8")
    from echelon import spec_switch as spec_switch_module

    original_run_git = spec_switch_module.run_git

    def fail_reset(project_root: Path, *args: str, **kwargs):
        if args and args[0] == "reset":
            raise GitHelperError("simulated discard reset failure")
        return original_run_git(project_root, *args, **kwargs)

    monkeypatch.setattr(spec_switch_module, "run_git", fail_reset)

    with pytest.raises(SpecSwitchError, match="simulated discard reset failure"):
        switch_spec(
            repo,
            "run-b",
            dirty_action="discard",
            confirm_discard=True,
        )

    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-spec-a"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "dirty before failed reset\n"


def test_git_status_failure_blocks_before_checkout_or_pointer_change(
    switch_repo: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = switch_repo["repo"]
    assert isinstance(repo, Path)
    from echelon import spec_switch as spec_switch_module

    original_run_git = spec_switch_module.run_git

    def fail_status(project_root: Path, *args: str, **kwargs):
        if args and args[0] == "status":
            return subprocess.CompletedProcess(
                ["git", *args],
                128,
                stdout="",
                stderr="simulated status failure",
            )
        return original_run_git(project_root, *args, **kwargs)

    monkeypatch.setattr(spec_switch_module, "run_git", fail_status)

    with pytest.raises(SpecSwitchError, match="inspect Git worktree"):
        switch_spec(repo, "run-b")

    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-spec-a"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-a\n"
    assert load_spec_switch_intent(repo) is None

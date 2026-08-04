from pathlib import Path
import json
import os
import subprocess

import pytest

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
import harness.phase_checkpoints as checkpoint_module
from harness.phase_checkpoints import (
    CheckpointLedger,
    PhaseCheckpointError,
    PhaseCheckpoint,
    commit_manual_checkpoint,
    commit_retarget_checkpoint,
    create_phase_checkpoint,
    load_checkpoint_ledger,
    record_phase_checkpoint,
    resolve_checkpoint,
)
from echelon.spec_retarget_history import (
    RetargetRecoveryProjection,
    append_prepared_revision,
    load_retarget_history,
    seal_retarget_checkpoint_parent,
)


COMPLETION_A = "a" * 32
COMPLETION_B = "b" * 32


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
    payload = json.loads(
        (spec_dir / ".echelon/checkpoints.json").read_text()
    )
    assert payload["spec_id"] == "001-demo"
    assert "completion_id" not in payload["checkpoints"][0]


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


def test_resolve_checkpoint_by_phase_and_commit_prefix_selects_older_entry() -> None:
    older = "12345678" + ("a" * 32)
    newer = "87654321" + ("b" * 32)
    ledger = CheckpointLedger(
        spec_id="001-demo",
        checkpoints=[
            PhaseCheckpoint(
                "phase1-what",
                "001-demo",
                "phase1-what",
                "phase1-understanding",
                older,
                "",
                "auto",
                "run1",
                "2026-07-04T01:00:00Z",
            ),
            PhaseCheckpoint(
                "phase1-what",
                "001-demo",
                "phase1-what",
                "phase1-understanding",
                newer,
                "",
                "auto",
                "run1",
                "2026-07-04T02:00:00Z",
            ),
        ],
    )

    assert (
        resolve_checkpoint(ledger, "phase1-what", commit=older[:8]).commit
        == older
    )


def test_resolve_checkpoint_commit_prefix_fails_when_missing_or_ambiguous() -> None:
    first = "abc11111" + ("a" * 32)
    second = "abc22222" + ("b" * 32)
    ledger = CheckpointLedger(
        spec_id="001-demo",
        checkpoints=[
            PhaseCheckpoint(
                "phase1-what",
                "001-demo",
                "phase1-what",
                "phase1-understanding",
                first,
                "",
                "auto",
                "run1",
                "2026-07-04T01:00:00Z",
            ),
            PhaseCheckpoint(
                "phase1-what",
                "001-demo",
                "phase1-what",
                "phase1-understanding",
                second,
                "",
                "auto",
                "run1",
                "2026-07-04T02:00:00Z",
            ),
        ],
    )

    with pytest.raises(KeyError, match="commit deadbeef not found"):
        resolve_checkpoint(ledger, "phase1-what", commit="deadbeef")
    with pytest.raises(ValueError, match="ambiguous checkpoint commit prefix abc"):
        resolve_checkpoint(ledger, "phase1-what", commit="abc")


def test_resolve_checkpoint_duplicate_exact_commit_uses_last_ledger_entry() -> None:
    commit = "12345678" + ("a" * 32)
    first = PhaseCheckpoint(
        "phase1-what",
        "001-demo",
        "phase1-what",
        "phase1-understanding",
        commit,
        "",
        "auto",
        "run1",
        "2026-07-04T01:00:00Z",
        "a" * 32,
    )
    last = PhaseCheckpoint(
        "phase1-what",
        "001-demo",
        "phase1-what",
        "phase1-understanding",
        commit,
        "",
        "auto",
        "run1",
        "2026-07-04T02:00:00Z",
        "b" * 32,
    )
    ledger = CheckpointLedger(spec_id="001-demo", checkpoints=[first, last])

    assert resolve_checkpoint(
        ledger,
        "phase1-what",
        commit=commit[:8],
    ) is last


def test_resolve_checkpoint_rejects_non_hex_commit_selector() -> None:
    ledger = CheckpointLedger(
        spec_id="001-demo",
        checkpoints=[
            PhaseCheckpoint(
                "phase1-what",
                "001-demo",
                "phase1-what",
                "phase1-understanding",
                "1" * 40,
                "",
                "auto",
                "run1",
                "2026-07-04T01:00:00Z",
            ),
        ],
    )

    with pytest.raises(ValueError, match="checkpoint commit must be hexadecimal"):
        resolve_checkpoint(ledger, "phase1-what", commit="not-a-commit")


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


def _retarget_checkpoint_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "retarget-repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Baseline\n", encoding="utf-8")
    (repo / "README.md").write_text("# Repository\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo, spec_dir


def _retarget_checkpoint_reftable_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "retarget-reftable-repo"
    repo.mkdir()
    initialized = subprocess.run(
        ["git", "init", "--ref-format=reftable", "-b", "main"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if initialized.returncode != 0:
        diagnostic = (initialized.stdout + initialized.stderr).lower()
        unsupported = (
            ("unknown option" in diagnostic and "ref-format" in diagnostic)
            or "unknown ref storage format" in diagnostic
            or "unsupported ref storage format" in diagnostic
        )
        if unsupported:
            pytest.skip("installed Git does not support reftable repositories")
        initialized.check_returncode()
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Baseline\n", encoding="utf-8")
    (repo / "README.md").write_text("# Repository\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo, spec_dir


def _prepared_retarget_revision(spec_dir: Path):
    return append_prepared_revision(
        spec_dir,
        operation_id="rt-abc",
        baseline_run_id="squad-base",
        replacement_run_id="squad-retarget",
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=RetargetRecoveryProjection(
            run_id="squad-base",
            status="done",
            phase="done",
            spec_status="planned",
            completed_phases=(),
            implementation_targets=("services/api",),
            ready_to_build=False,
        ),
    )


def _retarget_commit_message(revision) -> tuple[str, str]:
    checkpoint_id = f"retarget-preflight-{revision.revision_id}"
    return checkpoint_id, build_echelon_commit_message(
        f"checkpoint: prepare retarget {revision.revision_id}",
        EchelonCommitMetadata(
            origin="phase-a",
            action="retarget-preflight",
            spec_id="001-demo",
            run_id="squad-base",
            phase="retarget",
            next_phase="phase0-constitution",
            checkpoint_id=checkpoint_id,
            retarget_revision=revision.revision_id,
            baseline_run_id="squad-base",
            replacement_run_id="squad-retarget",
        ),
    )


def test_retarget_checkpoint_commits_prepared_ledger_and_exact_trailers(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = append_prepared_revision(
        spec_dir,
        operation_id="rt-abc",
        baseline_run_id="squad-base",
        replacement_run_id="squad-retarget",
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=RetargetRecoveryProjection(
            run_id="squad-base",
            status="done",
            phase="done",
            spec_status="planned",
            completed_phases=("phase4-document",),
            implementation_targets=("services/api",),
            ready_to_build=True,
        ),
    )
    (repo / "unrelated-staged.txt").write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "unrelated-staged.txt")
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    count_before = int(_git(repo, "rev-list", "--count", "HEAD"))

    checkpoint = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )

    assert int(_git(repo, "rev-list", "--count", "HEAD")) == count_before + 1
    assert checkpoint.source == "retarget-preflight"
    assert checkpoint.commit == _git(repo, "rev-parse", "HEAD^{commit}")
    message = _git(repo, "show", "-s", "--format=%B", checkpoint.commit)
    expected_trailers = (
        "Echelon-Action: retarget-preflight",
        f"Echelon-Checkpoint: {checkpoint.id}",
        f"Echelon-Retarget-Revision: {revision.revision_id}",
        "Echelon-Baseline-Run: squad-base",
        "Echelon-Replacement-Run: squad-retarget",
    )
    for trailer in expected_trailers:
        assert message.count(trailer) == 1
    ledger = _git(
        repo,
        "show",
        f"{checkpoint.commit}:specs/001-demo/retarget-history.json",
    )
    assert '"status": "prepared"' in ledger
    assert revision.revision_id in ledger
    assert _git(
        repo,
        "show",
        "--format=",
        "--name-only",
        checkpoint.commit,
    ).splitlines() == ["specs/001-demo/retarget-history.json"]
    assert _git(repo, "diff", "--cached", "--name-only") == "unrelated-staged.txt"
    assert "README.md" in _git(repo, "status", "--short")
    recorded = load_checkpoint_ledger(spec_dir).checkpoints[-1]
    assert recorded == checkpoint


def test_retarget_checkpoint_requires_latest_prepared_revision(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = append_prepared_revision(
        spec_dir,
        operation_id="rt-abc",
        baseline_run_id="squad-base",
        replacement_run_id="squad-retarget",
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=RetargetRecoveryProjection(
            run_id="squad-base",
            status="done",
            phase="done",
            spec_status="planned",
            completed_phases=(),
            implementation_targets=("services/api",),
            ready_to_build=False,
        ),
    )

    with pytest.raises(PhaseCheckpointError, match="baseline run"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="wrong-run",
            revision_id=revision.revision_id,
        )

    assert _git(repo, "rev-list", "--count", "HEAD") == "1"
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_retarget_checkpoint_recovers_commit_created_before_checkpoint_ledger(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = append_prepared_revision(
        spec_dir,
        operation_id="rt-abc",
        baseline_run_id="squad-base",
        replacement_run_id="squad-retarget",
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=RetargetRecoveryProjection(
            run_id="squad-base",
            status="done",
            phase="done",
            spec_status="planned",
            completed_phases=(),
            implementation_targets=("services/api",),
            ready_to_build=False,
        ),
    )
    created = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )
    count_after_commit = _git(repo, "rev-list", "--count", "--all")
    checkpoint_module.checkpoint_ledger_path(spec_dir).unlink()

    recovered = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )

    assert recovered == created
    assert _git(repo, "rev-list", "--count", "--all") == count_after_commit
    assert load_checkpoint_ledger(spec_dir).checkpoints == [created]


def test_retarget_checkpoint_seals_expected_parent_before_commit(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    expected_parent = _git(repo, "rev-parse", "HEAD^{commit}")
    revision = _prepared_retarget_revision(spec_dir)

    checkpoint = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )

    sealed = load_retarget_history(spec_dir).revisions[-1]
    committed = json.loads(
        _git(
            repo,
            "show",
            f"{checkpoint.commit}:specs/001-demo/retarget-history.json",
        )
    )
    assert sealed.checkpoint_parent == expected_parent
    assert committed["revisions"][-1]["checkpoint_parent"] == expected_parent
    assert _git(repo, "rev-parse", f"{checkpoint.commit}^") == expected_parent


def test_retarget_checkpoint_rejects_current_candidate_with_wrong_sealed_parent(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    expected_parent = _git(repo, "rev-parse", "HEAD^{commit}")
    revision = _prepared_retarget_revision(spec_dir)
    revision = seal_retarget_checkpoint_parent(
        spec_dir,
        revision.revision_id,
        checkpoint_parent=expected_parent,
    )
    _git(repo, "commit", "--allow-empty", "-m", "different parent")
    _checkpoint_id, message = _retarget_commit_message(revision)
    _git(repo, "add", "-f", "specs/001-demo/retarget-history.json")
    _git(repo, "commit", "-m", message)

    with pytest.raises(PhaseCheckpointError, match="expected parent"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_retarget_checkpoint_does_not_adopt_matching_off_branch_commit(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    first = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )
    ledger_bytes = (spec_dir / "retarget-history.json").read_bytes()
    parent = _git(repo, "rev-parse", f"{first.commit}^")
    _git(repo, "branch", "unrelated-ref", first.commit)
    checkpoint_module.checkpoint_ledger_path(spec_dir).unlink()
    _git(repo, "reset", "--hard", parent)
    _git(repo, "commit", "--allow-empty", "-m", "diverged current branch")
    (spec_dir / "retarget-history.json").write_bytes(ledger_bytes)

    with pytest.raises(PhaseCheckpointError, match="prestate"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert _git(repo, "rev-parse", "HEAD^{commit}") != first.commit
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_retarget_checkpoint_rejects_matching_current_head_with_unrelated_change(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    revision = seal_retarget_checkpoint_parent(
        spec_dir,
        revision.revision_id,
        checkpoint_parent=_git(repo, "rev-parse", "HEAD^{commit}"),
    )
    _checkpoint_id, message = _retarget_commit_message(revision)
    (repo / "unrelated.txt").write_text("not checkpoint-owned\n", encoding="utf-8")
    _git(repo, "add", "-f", "specs/001-demo/retarget-history.json")
    _git(repo, "add", "unrelated.txt")
    _git(repo, "commit", "-m", message)
    malicious_head = _git(repo, "rev-parse", "HEAD^{commit}")

    with pytest.raises(PhaseCheckpointError, match="scope"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert _git(repo, "rev-parse", "HEAD^{commit}") == malicious_head
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_retarget_checkpoint_blocks_head_move_before_recording(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    real_verify = checkpoint_module._verify_retarget_commit_tree
    attempted: list[subprocess.CompletedProcess[str]] = []

    def move_head_after_verification(*args, **kwargs) -> None:
        real_verify(*args, **kwargs)
        attempted.append(
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", "concurrent commit"],
                cwd=repo,
                check=False,
                capture_output=True,
                text=True,
            )
        )

    monkeypatch.setattr(
        checkpoint_module,
        "_verify_retarget_commit_tree",
        move_head_after_verification,
    )

    checkpoint = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )

    assert len(attempted) == 1
    assert attempted[0].returncode != 0
    assert checkpoint.commit == _git(repo, "rev-parse", "HEAD^{commit}")
    assert load_checkpoint_ledger(spec_dir).checkpoints == [checkpoint]


@pytest.mark.parametrize("head_kind", ["branch", "detached"])
def test_retarget_checkpoint_ref_lease_closes_verify_to_record_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    head_kind: str,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    parent = _git(repo, "rev-parse", "HEAD^{commit}")
    if head_kind == "detached":
        _git(repo, "checkout", "--detach", parent)
    revision = _prepared_retarget_revision(spec_dir)
    real_record = checkpoint_module._record_retarget_checkpoint_unlocked
    attempted: list[subprocess.CompletedProcess[str]] = []

    def attempt_ref_move(*args, **kwargs):
        attempted.append(
            subprocess.run(
                [
                    "git",
                    "update-ref",
                    "HEAD" if head_kind == "detached" else "refs/heads/main",
                    parent,
                ],
                cwd=repo,
                check=False,
                capture_output=True,
                text=True,
            )
        )
        return real_record(*args, **kwargs)

    monkeypatch.setattr(
        checkpoint_module,
        "_record_retarget_checkpoint_unlocked",
        attempt_ref_move,
    )

    checkpoint = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )

    assert len(attempted) == 1
    assert attempted[0].returncode != 0
    assert checkpoint.commit == _git(repo, "rev-parse", "HEAD^{commit}")
    assert load_checkpoint_ledger(spec_dir).checkpoints == [checkpoint]


def test_retarget_checkpoint_ref_lease_supports_packed_nested_branch(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    _git(repo, "checkout", "-b", "nested/checkpoint")
    _git(repo, "pack-refs", "--all", "--prune")
    ref_directory_value = _git(
        repo,
        "rev-parse",
        "--git-path",
        "refs/heads/nested",
    )
    ref_directory = Path(ref_directory_value)
    if not ref_directory.is_absolute():
        ref_directory = repo / ref_directory
    if ref_directory.is_dir():
        ref_directory.rmdir()
    revision = _prepared_retarget_revision(spec_dir)

    checkpoint = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )

    assert checkpoint.commit == _git(repo, "rev-parse", "HEAD^{commit}")
    assert load_checkpoint_ledger(spec_dir).checkpoints == [checkpoint]


def test_retarget_checkpoint_ref_lease_supports_linked_worktree(
    tmp_path: Path,
) -> None:
    repo, _spec_dir = _retarget_checkpoint_repo(tmp_path)
    linked = tmp_path / "retarget-linked"
    _git(repo, "worktree", "add", "-b", "linked-checkpoint", str(linked))
    spec_dir = linked / "specs" / "001-demo"
    revision = _prepared_retarget_revision(spec_dir)

    checkpoint = commit_retarget_checkpoint(
        project_root=linked,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )

    assert checkpoint.commit == _git(linked, "rev-parse", "HEAD^{commit}")
    assert load_checkpoint_ledger(spec_dir).checkpoints == [checkpoint]


def test_retarget_checkpoint_rejects_reported_reftable_before_initial_seal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    history_path = spec_dir / "retarget-history.json"
    history_before = history_path.read_bytes()
    real_run_git = checkpoint_module.run_git

    def report_reftable(project_root, *args, **kwargs):
        if args == ("rev-parse", "--show-ref-format"):
            return subprocess.CompletedProcess(
                ["git", *args],
                0,
                stdout="reftable\n",
                stderr="",
            )
        return real_run_git(project_root, *args, **kwargs)

    monkeypatch.setattr(checkpoint_module, "run_git", report_reftable)

    with pytest.raises(PhaseCheckpointError, match="ref storage.*reftable"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert history_path.read_bytes() == history_before
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


@pytest.mark.parametrize(
    ("config_result", "message"),
    [
        ((0, "reftable\n"), "ref storage.*reftable"),
        ((2, ""), "determine Git ref storage"),
    ],
)
def test_retarget_checkpoint_rejects_legacy_probe_unsupported_or_ambiguous_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_result: tuple[int, str],
    message: str,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    history_path = spec_dir / "retarget-history.json"
    history_before = history_path.read_bytes()
    real_run_git = checkpoint_module.run_git

    def report_backend(project_root, *args, **kwargs):
        if args == ("rev-parse", "--show-ref-format"):
            return subprocess.CompletedProcess(
                ["git", *args],
                0,
                stdout="--show-ref-format\n",
                stderr="",
            )
        if args == (
            "config",
            "--local",
            "--get-all",
            "extensions.refStorage",
        ):
            return subprocess.CompletedProcess(
                ["git", *args],
                config_result[0],
                stdout=config_result[1],
                stderr="",
            )
        return real_run_git(project_root, *args, **kwargs)

    monkeypatch.setattr(checkpoint_module, "run_git", report_backend)

    with pytest.raises(PhaseCheckpointError, match=message):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert history_path.read_bytes() == history_before
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_retarget_checkpoint_accepts_legacy_probe_default_files_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    real_run_git = checkpoint_module.run_git

    def report_legacy_default(project_root, *args, **kwargs):
        if args == ("rev-parse", "--show-ref-format"):
            return subprocess.CompletedProcess(
                ["git", *args],
                0,
                stdout="--show-ref-format\n",
                stderr="",
            )
        if args == (
            "config",
            "--local",
            "--get-all",
            "extensions.refStorage",
        ):
            return subprocess.CompletedProcess(
                ["git", *args],
                1,
                stdout="",
                stderr="",
            )
        return real_run_git(project_root, *args, **kwargs)

    monkeypatch.setattr(checkpoint_module, "run_git", report_legacy_default)

    checkpoint = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )

    assert checkpoint.commit == _git(repo, "rev-parse", "HEAD^{commit}")
    assert load_checkpoint_ledger(spec_dir).checkpoints == [checkpoint]


def test_retarget_checkpoint_rejects_actual_reftable_before_initial_seal(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_reftable_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    history_path = spec_dir / "retarget-history.json"
    history_before = history_path.read_bytes()
    head_before = _git(repo, "rev-parse", "HEAD^{commit}")

    with pytest.raises(PhaseCheckpointError, match="ref storage.*reftable"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert history_path.read_bytes() == history_before
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()
    assert _git(repo, "rev-parse", "HEAD^{commit}") == head_before


def test_retarget_checkpoint_rejects_reftable_recorded_replay_without_mutation(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_reftable_repo(tmp_path)
    parent = _git(repo, "rev-parse", "HEAD^{commit}")
    revision = _prepared_retarget_revision(spec_dir)
    revision = seal_retarget_checkpoint_parent(
        spec_dir,
        revision.revision_id,
        checkpoint_parent=parent,
    )
    checkpoint_id, message = _retarget_commit_message(revision)
    _git(repo, "add", "-f", "specs/001-demo/retarget-history.json")
    _git(repo, "commit", "-m", message)
    commit = _git(repo, "rev-parse", "HEAD^{commit}")
    checkpoint = PhaseCheckpoint(
        id=checkpoint_id,
        spec_id="001-demo",
        phase="retarget",
        next_phase="phase0-constitution",
        commit=commit,
        metadata_commit="",
        source="retarget-preflight",
        run_id="squad-base",
        created_at=_git(repo, "show", "-s", "--format=%cI", commit),
    )
    checkpoint_module._write_checkpoint_ledger_unlocked(
        spec_dir,
        CheckpointLedger(spec_id="001-demo", checkpoints=[checkpoint]),
    )
    history_path = spec_dir / "retarget-history.json"
    ledger_path = checkpoint_module.checkpoint_ledger_path(spec_dir)
    history_before = history_path.read_bytes()
    ledger_before = ledger_path.read_bytes()

    with pytest.raises(PhaseCheckpointError, match="ref storage.*reftable"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert history_path.read_bytes() == history_before
    assert ledger_path.read_bytes() == ledger_before


def test_retarget_checkpoint_rejects_intermediate_head_symref_before_mutation(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    history_path = spec_dir / "retarget-history.json"
    history_before = history_path.read_bytes()
    _git(repo, "symbolic-ref", "refs/heads/checkpoint-alias", "refs/heads/main")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/checkpoint-alias")

    with pytest.raises(PhaseCheckpointError, match="symbolic Git HEAD topology"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert history_path.read_bytes() == history_before
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_recorded_retarget_checkpoint_rejects_off_line_head(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    created = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )
    history_bytes = (spec_dir / "retarget-history.json").read_bytes()
    parent = _git(repo, "rev-parse", f"{created.commit}^")
    _git(repo, "reset", "--hard", parent)
    (spec_dir / "retarget-history.json").write_bytes(history_bytes)

    with pytest.raises(PhaseCheckpointError, match="current lineage"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )


def test_retarget_checkpoint_rejects_symlink_history_entry_in_commit(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    parent = _git(repo, "rev-parse", "HEAD^{commit}")
    revision = _prepared_retarget_revision(spec_dir)
    revision = seal_retarget_checkpoint_parent(
        spec_dir,
        revision.revision_id,
        checkpoint_parent=parent,
    )
    history_path = spec_dir / "retarget-history.json"
    history_bytes = history_path.read_bytes()
    history_path.unlink()
    history_path.symlink_to("spec.md")
    _checkpoint_id, message = _retarget_commit_message(revision)
    _git(repo, "add", "-f", "specs/001-demo/retarget-history.json")
    _git(repo, "commit", "-m", message)
    history_path.unlink()
    history_path.write_bytes(history_bytes)

    with pytest.raises(PhaseCheckpointError, match="regular blob mode"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )


def test_retarget_checkpoint_rejects_oversized_history_blob_before_reading(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    parent = _git(repo, "rev-parse", "HEAD^{commit}")
    revision = _prepared_retarget_revision(spec_dir)
    revision = seal_retarget_checkpoint_parent(
        spec_dir,
        revision.revision_id,
        checkpoint_parent=parent,
    )
    history_path = spec_dir / "retarget-history.json"
    history_bytes = history_path.read_bytes()
    history_path.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    _checkpoint_id, message = _retarget_commit_message(revision)
    _git(repo, "add", "-f", "specs/001-demo/retarget-history.json")
    _git(repo, "commit", "-m", message)
    history_path.write_bytes(history_bytes)

    with pytest.raises(PhaseCheckpointError, match="size limit"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )


def test_retarget_checkpoint_returns_strict_recorded_row_without_history_search(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    created = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )
    for index in range(260):
        _git(repo, "commit", "--allow-empty", "-m", f"later-{index}")
    count_before = _git(repo, "rev-list", "--count", "--all")

    replayed = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )

    assert replayed == created
    assert _git(repo, "rev-list", "--count", "--all") == count_before


@pytest.mark.parametrize(
    "payload",
    [
        {"spec_id": "001-demo", "checkpoints": [], "extra": True},
        {"spec_id": "001-demo", "checkpoints": {}},
        {
            "spec_id": "001-demo",
            "checkpoints": [
                {
                    "id": "retarget-preflight-retarget-bad",
                    "spec_id": "001-demo",
                    "phase": "retarget",
                    "next_phase": "phase0-constitution",
                    "commit": "f" * 40,
                    "metadata_commit": "",
                    "source": "retarget-preflight",
                    "run_id": "squad-base",
                    "created_at": "2026-08-04T00:00:00+00:00",
                    "extra": "bad",
                }
            ],
        },
    ],
)
def test_retarget_checkpoint_rejects_malformed_checkpoint_ledger_before_commit(
    tmp_path: Path,
    payload: object,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    path = checkpoint_module.checkpoint_ledger_path(spec_dir)
    path.write_text(json.dumps(payload), encoding="utf-8")
    head_before = _git(repo, "rev-parse", "HEAD^{commit}")

    with pytest.raises(PhaseCheckpointError, match="checkpoint ledger"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert _git(repo, "rev-parse", "HEAD^{commit}") == head_before


@pytest.mark.parametrize("location", ["top", "row"])
def test_retarget_checkpoint_rejects_duplicate_json_members_in_strict_ledger(
    tmp_path: Path,
    location: str,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    path = checkpoint_module.checkpoint_ledger_path(spec_dir)
    if location == "top":
        path.write_text(
            '{"spec_id":"001-demo","spec_id":"001-demo","checkpoints":[]}',
            encoding="utf-8",
        )
    else:
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )
        content = path.read_text(encoding="utf-8").replace(
            '"source": "retarget-preflight",',
            '"source": "retarget-preflight",\n      "source": "retarget-preflight",',
            1,
        )
        path.write_text(content, encoding="utf-8")

    with pytest.raises(PhaseCheckpointError, match="duplicate JSON member"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )


def test_retarget_checkpoint_rejects_oversized_checkpoint_ledger_before_commit(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    path = checkpoint_module.checkpoint_ledger_path(spec_dir)
    path.write_bytes(b" " * (1024 * 1024 + 1))
    head_before = _git(repo, "rev-parse", "HEAD^{commit}")

    with pytest.raises(PhaseCheckpointError, match="size limit"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert _git(repo, "rev-parse", "HEAD^{commit}") == head_before


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_retarget_checkpoint_rejects_nonregular_checkpoint_ledger_before_commit(
    tmp_path: Path,
    kind: str,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    path = checkpoint_module.checkpoint_ledger_path(spec_dir)
    if kind == "symlink":
        outside = repo / "outside-ledger.json"
        outside.write_text(
            json.dumps({"spec_id": "001-demo", "checkpoints": []}),
            encoding="utf-8",
        )
        path.symlink_to(outside)
    else:
        path.mkdir()
    head_before = _git(repo, "rev-parse", "HEAD^{commit}")

    with pytest.raises(PhaseCheckpointError, match="regular file"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert _git(repo, "rev-parse", "HEAD^{commit}") == head_before


def test_retarget_checkpoint_rejects_duplicate_deterministic_row(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    created = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )
    path = checkpoint_module.checkpoint_ledger_path(spec_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["checkpoints"].append(dict(payload["checkpoints"][0]))
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PhaseCheckpointError, match="duplicate checkpoint identity"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert _git(repo, "rev-parse", "HEAD^{commit}") == created.commit


def test_retarget_checkpoint_rejects_conflicting_deterministic_row(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _retarget_checkpoint_repo(tmp_path)
    revision = _prepared_retarget_revision(spec_dir)
    created = commit_retarget_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        run_id="squad-base",
        revision_id=revision.revision_id,
    )
    path = checkpoint_module.checkpoint_ledger_path(spec_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))

    payload["checkpoints"][0]["commit"] = "f" * 40
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PhaseCheckpointError, match="identity drift"):
        commit_retarget_checkpoint(
            project_root=repo,
            spec_dir=spec_dir,
            run_id="squad-base",
            revision_id=revision.revision_id,
        )

    assert _git(repo, "rev-parse", "HEAD^{commit}") == created.commit


def _completion_checkpoint(
    repo: Path,
    spec_dir: Path | None,
    *,
    completion_id: str = COMPLETION_A,
    checkpoint_head: str,
    expected_receipt: object | None = None,
    fault_hook=None,
) -> dict[str, object]:
    return checkpoint_module.create_or_recover_completion_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase3-plan",
        next_phase="phase3-consensus",
        run_id="spec-run",
        spec_id="001-demo" if spec_dir is not None else "",
        completion_id=completion_id,
        checkpoint_prestate={"kind": "git_head", "head": checkpoint_head},
        expected_receipt=expected_receipt,
        fault_hook=fault_hook,
    )


def test_completion_checkpoint_recovers_commit_created_before_ledger(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    count_before = int(_git(repo, "rev-list", "--count", "--all"))
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

    def crash(boundary: str) -> None:
        if boundary == "after_commit":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        _completion_checkpoint(
            repo,
            spec_dir,
            checkpoint_head=checkpoint_head,
            fault_hook=crash,
        )

    created = _git(repo, "rev-parse", "HEAD")
    assert int(_git(repo, "rev-list", "--count", "--all")) == count_before + 1
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()

    receipt = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
    )

    assert receipt == {
        "schema_version": 1,
        "completion_id": COMPLETION_A,
        "run_id": "spec-run",
        "spec_id": "001-demo",
        "phase": "phase3-plan",
        "next_phase": "phase3-consensus",
        "outcome": "committed",
        "commit": created,
    }
    assert int(_git(repo, "rev-list", "--count", "--all")) == count_before + 1
    ledger = load_checkpoint_ledger(spec_dir)
    assert len(ledger.checkpoints) == 1
    assert ledger.checkpoints[0].completion_id == COMPLETION_A
    assert ledger.checkpoints[0].commit == created


def test_completion_checkpoint_reuses_exact_ledger(tmp_path: Path) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

    receipt = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
    )
    count_after = _git(repo, "rev-list", "--count", "--all")
    ledger_bytes = checkpoint_module.checkpoint_ledger_path(spec_dir).read_bytes()

    replayed = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
        expected_receipt=receipt,
    )

    assert replayed == receipt
    assert _git(repo, "rev-list", "--count", "--all") == count_after
    assert checkpoint_module.checkpoint_ledger_path(spec_dir).read_bytes() == ledger_bytes
    assert len(load_checkpoint_ledger(spec_dir).checkpoints) == 1
    message = _git(repo, "show", "-s", "--format=%B", str(receipt["commit"]))
    assert f"Echelon-Completion: {COMPLETION_A}" in message
    assert "Echelon-Next-Phase: phase3-consensus" in message


def test_completion_checkpoint_preserves_same_phase_different_ids(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    first_head = _git(repo, "rev-parse", "HEAD")
    (spec_dir / "tasks.md").write_text("# First\n", encoding="utf-8")
    first = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=first_head,
    )

    second_head = _git(repo, "rev-parse", "HEAD")
    (spec_dir / "tasks.md").write_text("# Second\n", encoding="utf-8")
    second = _completion_checkpoint(
        repo,
        spec_dir,
        completion_id=COMPLETION_B,
        checkpoint_head=second_head,
    )

    ledger = load_checkpoint_ledger(spec_dir)
    assert [item.completion_id for item in ledger.checkpoints] == [
        COMPLETION_A,
        COMPLETION_B,
    ]
    assert first["commit"] != second["commit"]
    assert _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=first_head,
        expected_receipt=first,
    ) == first
    assert _completion_checkpoint(
        repo,
        spec_dir,
        completion_id=COMPLETION_B,
        checkpoint_head=second_head,
        expected_receipt=second,
    ) == second


def test_completion_checkpoint_finds_branch_only_commit_via_all_refs(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

    def crash(boundary: str) -> None:
        if boundary == "after_commit":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        _completion_checkpoint(
            repo,
            spec_dir,
            checkpoint_head=checkpoint_head,
            fault_hook=crash,
        )
    created = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "checkpoint-only", created)
    _git(repo, "reset", "--hard", checkpoint_head)
    current_count = _git(repo, "rev-list", "--count", "--all")

    receipt = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
    )

    assert receipt["commit"] == created
    assert _git(repo, "rev-parse", "HEAD") == checkpoint_head
    assert _git(repo, "rev-list", "--count", "--all") == current_count


def test_completion_checkpoint_rejects_duplicate_bounded_matches(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

    def crash(boundary: str) -> None:
        if boundary == "after_commit":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        _completion_checkpoint(
            repo,
            spec_dir,
            checkpoint_head=checkpoint_head,
            fault_hook=crash,
        )
    first = _git(repo, "rev-parse", "HEAD")
    message = _git(repo, "show", "-s", "--format=%B", "HEAD")
    _git(repo, "branch", "first-checkpoint", first)
    _git(repo, "reset", "--hard", checkpoint_head)
    _git(repo, "commit", "--allow-empty", "-m", message)
    count_before = _git(repo, "rev-list", "--count", "--all")

    with pytest.raises(PhaseCheckpointError):
        _completion_checkpoint(
            repo,
            spec_dir,
            checkpoint_head=checkpoint_head,
        )

    assert _git(repo, "rev-list", "--count", "--all") == count_before
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_completion_checkpoint_rejects_same_id_trailer_drift(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    drifted = build_echelon_commit_message(
        "echelon-checkpoint: 001-demo phase3-plan",
        EchelonCommitMetadata(
            origin="phase-a",
            action="checkpoint",
            spec_id="001-demo",
            run_id="wrong-run",
            phase="phase3-plan",
            next_phase="phase4-build",
            checkpoint_id="phase3-plan",
            completion_id=COMPLETION_A,
        ),
    )
    _git(repo, "commit", "--allow-empty", "-m", drifted)
    count_before = _git(repo, "rev-list", "--count", "--all")

    with pytest.raises(PhaseCheckpointError):
        _completion_checkpoint(
            repo,
            spec_dir,
            checkpoint_head=checkpoint_head,
        )

    assert _git(repo, "rev-list", "--count", "--all") == count_before
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_completion_checkpoint_rejects_exact_trailers_from_wrong_prestate(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "--allow-empty", "-m", "unrelated")
    message = build_echelon_commit_message(
        "echelon-checkpoint: 001-demo phase3-plan",
        EchelonCommitMetadata(
            origin="phase-a",
            action="checkpoint",
            spec_id="001-demo",
            run_id="spec-run",
            phase="phase3-plan",
            next_phase="phase3-consensus",
            checkpoint_id="phase3-plan",
            completion_id=COMPLETION_A,
        ),
    )
    _git(repo, "commit", "--allow-empty", "-m", message)
    count_before = _git(repo, "rev-list", "--count", "--all")

    with pytest.raises(PhaseCheckpointError):
        _completion_checkpoint(
            repo,
            spec_dir,
            checkpoint_head=checkpoint_head,
        )

    assert _git(repo, "rev-list", "--count", "--all") == count_before
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_completion_checkpoint_search_is_bounded_to_all_256(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    calls: list[tuple[str, ...]] = []
    real_run_git = checkpoint_module.run_git

    def track_run_git(project_root: Path, *args: str, **kwargs):
        if args and args[0] == "log":
            calls.append(args)
        return real_run_git(project_root, *args, **kwargs)

    monkeypatch.setattr(checkpoint_module, "run_git", track_run_git)

    receipt = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
    )

    assert receipt["outcome"] == "no_change"
    assert len(calls) == 1
    assert "--all" in calls[0]
    assert "--max-count=256" in calls[0]


def test_completion_checkpoint_no_change_uses_captured_head(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    count_before = _git(repo, "rev-list", "--count", "--all")

    receipt = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
    )

    assert receipt == {
        "schema_version": 1,
        "completion_id": COMPLETION_A,
        "run_id": "spec-run",
        "spec_id": "001-demo",
        "phase": "phase3-plan",
        "next_phase": "phase3-consensus",
        "outcome": "no_change",
        "head": checkpoint_head,
    }
    assert _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
        expected_receipt=receipt,
    ) == receipt
    assert _git(repo, "rev-list", "--count", "--all") == count_before
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_completion_checkpoint_no_change_rechecks_head_after_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    receipt = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
    )
    real_check = checkpoint_module._owned_paths_have_changes

    def advance_after_check(*args, **kwargs) -> bool:
        changed = real_check(*args, **kwargs)
        _git(repo, "commit", "--allow-empty", "-m", "concurrent")
        return changed

    monkeypatch.setattr(
        checkpoint_module,
        "_owned_paths_have_changes",
        advance_after_check,
    )

    with pytest.raises(PhaseCheckpointError):
        _completion_checkpoint(
            repo,
            spec_dir,
            checkpoint_head=checkpoint_head,
            expected_receipt=receipt,
        )


def test_completion_checkpoint_clean_but_head_advanced_fails(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "--allow-empty", "-m", "unrelated")
    count_before = _git(repo, "rev-list", "--count", "--all")

    with pytest.raises(PhaseCheckpointError):
        _completion_checkpoint(
            repo,
            spec_dir,
            checkpoint_head=checkpoint_head,
        )

    assert _git(repo, "rev-list", "--count", "--all") == count_before
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_completion_checkpoint_no_active_spec_is_not_applicable(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    count_before = _git(repo, "rev-list", "--count", "--all")

    receipt = _completion_checkpoint(
        repo,
        None,
        checkpoint_head=checkpoint_head,
    )

    assert receipt == {
        "schema_version": 1,
        "completion_id": COMPLETION_A,
        "run_id": "spec-run",
        "spec_id": "",
        "phase": "phase3-plan",
        "next_phase": "phase3-consensus",
        "outcome": "not_applicable",
    }
    assert _completion_checkpoint(
        repo,
        None,
        checkpoint_head=checkpoint_head,
        expected_receipt=receipt,
    ) == receipt
    assert _git(repo, "rev-list", "--count", "--all") == count_before
    assert not checkpoint_module.checkpoint_ledger_path(spec_dir).exists()


def test_completion_checkpoint_repairs_missing_ledger_from_bound_receipt(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    receipt = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
    )
    count_after = _git(repo, "rev-list", "--count", "--all")
    ledger_path = checkpoint_module.checkpoint_ledger_path(spec_dir)
    ledger_path.unlink()

    repaired = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
        expected_receipt=receipt,
    )

    assert repaired == receipt
    assert load_checkpoint_ledger(spec_dir).checkpoints[0].commit == receipt["commit"]
    assert _git(repo, "rev-list", "--count", "--all") == count_after

    ledger_path.write_text("{", encoding="utf-8")
    corrupt = ledger_path.read_bytes()
    with pytest.raises(PhaseCheckpointError):
        _completion_checkpoint(
            repo,
            spec_dir,
            checkpoint_head=checkpoint_head,
        )
    assert ledger_path.read_bytes() == corrupt

    assert _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
        expected_receipt=receipt,
    ) == receipt
    assert load_checkpoint_ledger(
        spec_dir
    ).checkpoints[0].completion_id == COMPLETION_A


def test_completion_checkpoint_rejects_forged_bound_receipt_without_write(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    receipt = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
    )
    ledger_path = checkpoint_module.checkpoint_ledger_path(spec_dir)
    ledger_path.unlink()
    forged = {**receipt, "commit": "f" * 40}

    with pytest.raises(PhaseCheckpointError):
        _completion_checkpoint(
            repo,
            spec_dir,
            checkpoint_head=checkpoint_head,
            expected_receipt=forged,
        )

    assert not ledger_path.exists()


def test_completion_checkpoint_ledger_replace_is_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    events: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace
    real_sync_directory = checkpoint_module._fsync_directory

    def track_fsync(fd: int) -> None:
        events.append("file_fsync")
        real_fsync(fd)

    def track_replace(source, destination) -> None:
        events.append("replace")
        real_replace(source, destination)

    def track_sync_directory(path: Path) -> None:
        events.append("directory_fsync")
        real_sync_directory(path)

    monkeypatch.setattr(checkpoint_module.os, "fsync", track_fsync)
    monkeypatch.setattr(checkpoint_module.os, "replace", track_replace)
    monkeypatch.setattr(
        checkpoint_module,
        "_fsync_directory",
        track_sync_directory,
    )

    _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
    )

    replace_index = events.index("replace")
    assert "file_fsync" in events[:replace_index]
    assert "directory_fsync" in events[replace_index + 1 :]


def test_completion_checkpoint_adopts_post_ledger_save_exception(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

    def crash(boundary: str) -> None:
        if boundary == "after_ledger":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        _completion_checkpoint(
            repo,
            spec_dir,
            checkpoint_head=checkpoint_head,
            fault_hook=crash,
        )
    count_after = _git(repo, "rev-list", "--count", "--all")

    receipt = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
    )

    assert receipt["outcome"] == "committed"
    assert _git(repo, "rev-list", "--count", "--all") == count_after
    assert len(load_checkpoint_ledger(spec_dir).checkpoints) == 1


def test_completion_checkpoint_lock_and_ledger_are_not_committed(
    tmp_path: Path,
) -> None:
    repo, spec_dir = _checkpoint_repo(tmp_path)
    checkpoint_head = _git(repo, "rev-parse", "HEAD")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

    receipt = _completion_checkpoint(
        repo,
        spec_dir,
        checkpoint_head=checkpoint_head,
    )

    assert _git(
        repo,
        "show",
        "--format=",
        "--name-only",
        str(receipt["commit"]),
    ).splitlines() == ["runs/spec-run/specs/001-demo/tasks.md"]
    assert (spec_dir / ".echelon" / "checkpoints.lock").is_file()
    assert _git(repo, "status", "--short") == ""


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
    assert _git(repo, "status", "--short") == ""


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


def test_create_phase_checkpoint_commits_active_and_published_spec_only(
    tmp_path: Path,
) -> None:
    repo, active = _checkpoint_repo(tmp_path)
    published = repo / "specs" / "001-demo"
    published.mkdir(parents=True)
    (active / "tasks.md").write_text("# Run-local tasks\n", encoding="utf-8")
    (published / "ARTIFACTS.md").write_text("# Artifacts\n", encoding="utf-8")
    (repo / "README.md").write_text("unrelated\n", encoding="utf-8")

    checkpoint = create_phase_checkpoint(
        project_root=repo,
        spec_dir=active,
        phase="phase4-document",
        next_phase="done",
        run_id="spec-run",
        additional_spec_dirs=(published,),
    )

    assert _git(repo, "show", "--format=", "--name-only", checkpoint.commit).splitlines() == [
        "runs/spec-run/specs/001-demo/tasks.md",
        "specs/001-demo/ARTIFACTS.md",
    ]
    assert "README.md" in _git(repo, "status", "--short")


def test_create_phase_checkpoint_commits_declared_kb_path_only(tmp_path: Path) -> None:
    repo, active = _checkpoint_repo(tmp_path)
    published = repo / "specs" / "001-demo"
    published.mkdir(parents=True)
    kb_target = repo / "knowledge-base" / "sage-decisions.yaml"
    kb_target.parent.mkdir(parents=True)
    kb_target.write_text("entries: []\n", encoding="utf-8")
    unrelated_kb_file = repo / "knowledge-base" / "patterns.yaml"
    unrelated_kb_file.write_text("entries: []\n", encoding="utf-8")
    (active / "tasks.md").write_text("# Run-local tasks\n", encoding="utf-8")
    (published / "ARTIFACTS.md").write_text("# Artifacts\n", encoding="utf-8")
    (repo / "README.md").write_text("unrelated\n", encoding="utf-8")

    checkpoint = create_phase_checkpoint(
        project_root=repo,
        spec_dir=active,
        phase="phase4-document",
        next_phase="done",
        run_id="spec-run",
        additional_spec_dirs=(published,),
        additional_owned_paths=(kb_target,),
    )

    assert _git(repo, "show", "--format=", "--name-only", checkpoint.commit).splitlines() == [
        "knowledge-base/sage-decisions.yaml",
        "runs/spec-run/specs/001-demo/tasks.md",
        "specs/001-demo/ARTIFACTS.md",
    ]
    status = _git(repo, "status", "--short")
    assert "README.md" in status
    assert "knowledge-base/patterns.yaml" in status


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

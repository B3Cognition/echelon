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
    create_phase_checkpoint,
    load_checkpoint_ledger,
    record_phase_checkpoint,
    resolve_checkpoint,
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

"""Checkpoint-only recovery contracts for destructive spec retargets."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from echelon.mempalace_retarget import RetargetMemoryReceipt
from echelon.spec_retarget_graph import RetargetGraphReceipt
from echelon.spec_retarget_recovery import (
    RetargetRecoveryError,
    RetargetRecoveryResult,
    create_or_recover_retarget_recovery_commit,
    activate_recovered_spec_run,
    persist_recovered_baseline_state,
    recover_retarget_checkpoint,
    restore_or_recreate_baseline_state,
)
from echelon.spec_retarget_history import (
    RetargetRecoveryProjection,
    advance_retarget_revision,
    append_prepared_revision,
    bind_recovered_revision_commit,
    load_retarget_history,
)
from harness.phase_checkpoints import PhaseCheckpoint


def _memory_receipt() -> RetargetMemoryReceipt:
    return RetargetMemoryReceipt(
        status="not_applicable",
        spec_id="001-demo",
        deleted_count=0,
        deleted_ids=(),
        drawer_set_digest=(
            "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe"
            "5ed12ab4d8e11ba873c2f11161202b945"
        ),
        mine_status="not_applicable",
        audit_status="not_applicable",
    )


def _graph_receipt() -> RetargetGraphReceipt:
    return RetargetGraphReceipt(
        spec_id="001-demo",
        spec_status="pass",
        spec_graph_hash="sha256:" + "b" * 64,
        workspace_status="pass",
        workspace_graph_hash="sha256:" + "c" * 64,
        workspace_finding_codes=(),
    )


def _invalidation_receipt() -> RetargetGraphReceipt:
    return RetargetGraphReceipt(
        spec_id="001-demo",
        spec_status="invalidated",
        spec_graph_hash=None,
        workspace_status="not_applicable_empty_workspace",
        workspace_graph_hash=None,
        workspace_finding_codes=(),
    )


def _failed_revision(project_root: Path):
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True, exist_ok=True)
    revision = append_prepared_revision(
        spec_dir,
        operation_id="retarget-operation",
        baseline_run_id="squad-base",
        replacement_run_id="squad-replacement",
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=RetargetRecoveryProjection(
            run_id="squad-base",
            status="done",
            phase="phase4-document",
            spec_status="planned",
            completed_phases=("phase3-plan", "phase4-document"),
            implementation_targets=("services/api",),
            ready_to_build=True,
        ),
    )
    return spec_dir, advance_retarget_revision(
        spec_dir,
        revision.revision_id,
        expected_status="prepared",
        status="failed",
        updates={
            "checkpoint_id": f"retarget-preflight-{revision.revision_id}",
            "checkpoint_commit": "b" * 40,
            "graph_invalidation": _invalidation_receipt().to_dict(),
            "failure_code": "retarget_artifact_invalidation_failed",
        },
    )


def _checkpoint(revision_id: str) -> PhaseCheckpoint:
    return PhaseCheckpoint(
        id=f"retarget-preflight-{revision_id}",
        spec_id="001-demo",
        phase="phase4-document",
        next_phase="phase0-constitution",
        commit="b" * 40,
        metadata_commit="b" * 40,
        source="retarget-preflight",
        run_id="squad-base",
        created_at="2026-08-05T00:00:00+00:00",
    )


def _replacement_state(revision_id: str) -> dict[str, object]:
    return {
        "run_id": "squad-replacement",
        "spec_id": "001-demo",
        "feature_branch": "001-demo",
        "retarget": {
            "revision_id": revision_id,
            "baseline_run_id": "squad-base",
            "replacement_run_id": "squad-replacement",
        },
    }


@pytest.mark.unit
def test_retarget_recovery_result_is_strict_and_binds_one_spec() -> None:
    result = RetargetRecoveryResult(
        spec_id="001-demo",
        baseline_run_id="squad-base",
        replacement_run_id="squad-replacement",
        revision_id="retarget-1",
        recovery_commit="d" * 40,
        memory=_memory_receipt(),
        graph=_graph_receipt(),
    )

    assert result.spec_id == "001-demo"
    with pytest.raises(RetargetRecoveryError, match="result"):
        replace(result, baseline_run_id="")
    with pytest.raises(RetargetRecoveryError, match="result"):
        replace(result, replacement_run_id="squad-base")
    with pytest.raises(RetargetRecoveryError, match="result"):
        replace(result, recovery_commit="not-an-oid")
    with pytest.raises(RetargetRecoveryError, match="result"):
        replace(result, memory=object())
    with pytest.raises(RetargetRecoveryError, match="result"):
        replace(result, graph=object())
    with pytest.raises(RetargetRecoveryError, match="result"):
        replace(result, memory=replace(_memory_receipt(), spec_id="002-other"))


@pytest.mark.unit
def test_failed_retarget_recovery_is_memory_first_and_recovers_same_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.spec_retarget_recovery as recovery

    spec_dir, revision = _failed_revision(tmp_path)
    events: list[str] = []
    monkeypatch.setattr(
        recovery,
        "restore_or_recreate_baseline_state",
        lambda *_args, **_kwargs: events.append("baseline") or SimpleNamespace(
            run_id="squad-base", run_dir=tmp_path / "runs" / "squad-base"
        ),
    )
    monkeypatch.setattr(
        recovery,
        "purge_retarget_spec_memory",
        lambda *_args: events.append("purge") or _memory_receipt(),
    )
    monkeypatch.setattr(
        recovery,
        "refresh_retarget_spec_memory",
        lambda *_args: events.append("refresh") or _memory_receipt(),
    )
    monkeypatch.setattr(
        recovery,
        "finalize_retarget_graphs",
        lambda *_args: events.append("graph") or _graph_receipt(),
    )
    monkeypatch.setattr(
        recovery,
        "create_or_recover_retarget_recovery_commit",
        lambda *_args: events.append("commit") or "d" * 40,
    )
    monkeypatch.setattr(
        recovery,
        "bind_retarget_recovery_commit",
        lambda *_args, **_kwargs: events.append("bind"),
    )
    monkeypatch.setattr(
        recovery,
        "persist_recovered_baseline_state",
        lambda *_args, **_kwargs: events.append("state"),
    )
    monkeypatch.setattr(
        recovery,
        "activate_recovered_spec_run",
        lambda *_args, **_kwargs: events.append("activate"),
    )

    result = recover_retarget_checkpoint(
        tmp_path,
        _checkpoint(revision.revision_id),
        _replacement_state(revision.revision_id),
    )

    recovered = load_retarget_history(spec_dir).revisions[-1]
    assert result.revision_id == revision.revision_id
    assert result.recovery_commit == "d" * 40
    assert recovered.status == "recovered"
    assert recovered.memory_finalization == _memory_receipt().to_dict()
    assert recovered.graph_finalization == _graph_receipt().to_dict()
    assert events == [
        "baseline",
        "purge",
        "refresh",
        "graph",
        "commit",
        "bind",
        "state",
        "activate",
    ]


@pytest.mark.unit
def test_baseline_state_is_recreated_only_from_committed_recovery_projection(
    tmp_path: Path,
) -> None:
    from harness.squad_state import SquadStateStore

    spec_dir, revision = _failed_revision(tmp_path)
    (tmp_path / "runs").mkdir()

    baseline = restore_or_recreate_baseline_state(
        tmp_path,
        spec_dir,
        revision,
        feature_branch="001-demo",
    )

    state = SquadStateStore(baseline.run_dir).load()
    assert baseline.run_id == "squad-base"
    assert baseline.spec_id == "001-demo"
    assert state["run_id"] == revision.recovery.run_id
    assert state["spec_id"] == "001-demo"
    assert state["feature_branch"] == "001-demo"
    assert state["spec_dir"] == str(spec_dir)
    assert state["published_spec_dir"] == str(spec_dir)
    assert state["phase"] == revision.recovery.phase
    assert state["completed_phases"] == list(revision.recovery.completed_phases)
    assert state["implementation_targets"] == list(revision.old_targets)
    assert state["spec_status"] == revision.recovery.spec_status
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "retarget_recovery_refresh_failed"
    assert state["retarget"] == {
        "revision_id": revision.revision_id,
        "baseline_run_id": revision.baseline_run_id,
        "replacement_run_id": revision.replacement_run_id,
    }


@pytest.mark.unit
def test_baseline_reconstruction_rejects_identity_drift_and_symlinks(
    tmp_path: Path,
) -> None:
    spec_dir, revision = _failed_revision(tmp_path)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_dir = runs_dir / revision.baseline_run_id
    run_dir.mkdir()
    (run_dir / "state.json").write_text(
        '{"run_id":"wrong","spec_id":"001-demo","feature_branch":"001-demo",'
        '"spec_dir":"specs/001-demo"}\n',
        encoding="utf-8",
    )

    with pytest.raises(RetargetRecoveryError, match="baseline state identity"):
        restore_or_recreate_baseline_state(
            tmp_path,
            spec_dir,
            revision,
            feature_branch="001-demo",
        )
    (run_dir / "state.json").unlink()
    (run_dir / "state.json").symlink_to(spec_dir / "retarget-history.json")
    with pytest.raises(RetargetRecoveryError, match="baseline state"):
        restore_or_recreate_baseline_state(
            tmp_path,
            spec_dir,
            revision,
            feature_branch="001-demo",
        )


@pytest.mark.unit
def test_recovery_commit_binding_is_exact_idempotent_and_fail_closed(
    tmp_path: Path,
) -> None:
    spec_dir, failed = _failed_revision(tmp_path)
    recovered = advance_retarget_revision(
        spec_dir,
        failed.revision_id,
        expected_status="failed",
        status="recovered",
        updates={
            "memory_finalization": _memory_receipt().to_dict(),
            "graph_finalization": _graph_receipt().to_dict(),
            "failure_code": None,
        },
    )

    bound = bind_recovered_revision_commit(
        spec_dir,
        recovered.revision_id,
        recovery_commit="d" * 40,
    )
    repeated = bind_recovered_revision_commit(
        spec_dir,
        recovered.revision_id,
        recovery_commit="d" * 40,
    )

    assert bound.recovery_commit == "d" * 40
    assert repeated == bound
    with pytest.raises(ValueError, match="already bound"):
        bind_recovered_revision_commit(
            spec_dir,
            recovered.revision_id,
            recovery_commit="e" * 40,
        )
    with pytest.raises(ValueError, match="precondition"):
        bind_recovered_revision_commit(
            spec_dir,
            "retarget-wrong",
            recovery_commit="d" * 40,
        )


@pytest.mark.unit
def test_recovery_commit_is_exact_scoped_and_reused_without_touching_other_index(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    for args in (
        ("init", "-b", "001-demo"),
        ("config", "user.name", "Echelon Tests"),
        ("config", "user.email", "echelon@example.test"),
    ):
        subprocess.run(
            ["git", *args], cwd=project_root, check=True, capture_output=True
        )
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# baseline\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "."], cwd=project_root, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "base"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    _, failed = _failed_revision(project_root)
    recovered = advance_retarget_revision(
        spec_dir,
        failed.revision_id,
        expected_status="failed",
        status="recovered",
        updates={
            "memory_finalization": _memory_receipt().to_dict(),
            "graph_finalization": _graph_receipt().to_dict(),
            "failure_code": None,
        },
    )
    unrelated = project_root / "unrelated.txt"
    unrelated.write_text("keep staged\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "unrelated.txt"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )

    commit = create_or_recover_retarget_recovery_commit(
        project_root,
        spec_dir,
        recovered,
        _checkpoint(recovered.revision_id),
    )
    repeated = create_or_recover_retarget_recovery_commit(
        project_root,
        spec_dir,
        recovered,
        _checkpoint(recovered.revision_id),
    )

    assert repeated == commit
    message = subprocess.run(
        ["git", "show", "-s", "--format=%B", commit],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    paths = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "Echelon-Action: retarget-recovered" in message
    assert f"Echelon-Checkpoint: {_checkpoint(recovered.revision_id).id}" in message
    assert f"Echelon-Retarget-Revision: {recovered.revision_id}" in message
    assert paths and all(path.startswith("specs/001-demo/") for path in paths)
    assert staged == ["unrelated.txt"]
    (spec_dir / "spec.md").write_text("tampered after recovery\n", encoding="utf-8")
    with pytest.raises(RetargetRecoveryError, match="live postimage"):
        create_or_recover_retarget_recovery_commit(
            project_root,
            spec_dir,
            recovered,
            _checkpoint(recovered.revision_id),
        )
    subprocess.run(
        [
            "git",
            "restore",
            f"--source={commit}",
            "--staged",
            "--worktree",
            "--",
            "specs/001-demo/spec.md",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "--only", "-m", message, "--", "unrelated.txt"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    with pytest.raises(RetargetRecoveryError, match="proof drifted"):
        create_or_recover_retarget_recovery_commit(
            project_root,
            spec_dir,
            recovered,
            _checkpoint(recovered.revision_id),
        )


@pytest.mark.unit
def test_recovered_baseline_state_and_same_branch_pointer_are_exact_and_idempotent(
    tmp_path: Path,
) -> None:
    from harness.squad_state import SquadStateStore

    subprocess.run(
        ["git", "init", "-b", "001-demo"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    spec_dir, failed = _failed_revision(tmp_path)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    baseline = restore_or_recreate_baseline_state(
        tmp_path,
        spec_dir,
        failed,
        feature_branch="001-demo",
    )
    recovered = advance_retarget_revision(
        spec_dir,
        failed.revision_id,
        expected_status="failed",
        status="recovered",
        updates={
            "memory_finalization": _memory_receipt().to_dict(),
            "graph_finalization": _graph_receipt().to_dict(),
            "failure_code": None,
        },
    )
    replacement_dir = runs_dir / recovered.replacement_run_id
    replacement_dir.mkdir()
    SquadStateStore(replacement_dir).initialize(
        recovered.replacement_run_id,
        "greenfield",
        "replacement",
        0,
        "phase0-constitution",
        implementation_targets=list(recovered.replacement_targets),
    )
    replacement_state = SquadStateStore(replacement_dir).load()
    replacement_state.update(
        {
            "spec_id": "001-demo",
            "feature_branch": "001-demo",
            "spec_dir": str(spec_dir),
            "published_spec_dir": str(spec_dir),
        }
    )
    SquadStateStore(replacement_dir).save(replacement_state)
    (runs_dir / ".current").write_text(
        f"{recovered.replacement_run_id}\n", encoding="utf-8"
    )

    persist_recovered_baseline_state(baseline, recovered, "d" * 40)
    activate_recovered_spec_run(tmp_path, baseline, recovered)
    activate_recovered_spec_run(tmp_path, baseline, recovered)

    state = SquadStateStore(baseline.run_dir).load()
    assert (runs_dir / ".current").read_text(encoding="utf-8") == "squad-base\n"
    assert state["status"] == recovered.recovery.status
    assert state["ready_to_build"] is recovered.recovery.ready_to_build
    assert state["blocked_reason"] is None
    assert state["retarget"]["status"] == "recovered"
    assert state["retarget"]["recovery_commit"] == "d" * 40
    assert not (tmp_path / ".echelon/runtime/spec-switch-intent.json").exists()


@pytest.mark.unit
def test_retry_after_postcommit_failure_reuses_revision_effects_and_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.spec_retarget_recovery as recovery

    spec_dir, failed = _failed_revision(tmp_path)
    events: list[str] = []
    state_attempts = 0

    monkeypatch.setattr(
        recovery,
        "restore_or_recreate_baseline_state",
        lambda *_args, **_kwargs: SimpleNamespace(
            run_id="squad-base", run_dir=tmp_path / "runs/squad-base"
        ),
    )
    monkeypatch.setattr(
        recovery,
        "purge_retarget_spec_memory",
        lambda *_args: events.append("purge") or _memory_receipt(),
    )
    monkeypatch.setattr(
        recovery,
        "refresh_retarget_spec_memory",
        lambda *_args: events.append("refresh") or _memory_receipt(),
    )
    monkeypatch.setattr(
        recovery,
        "finalize_retarget_graphs",
        lambda *_args: events.append("graph") or _graph_receipt(),
    )
    monkeypatch.setattr(
        recovery,
        "create_or_recover_retarget_recovery_commit",
        lambda *_args: events.append("commit") or "d" * 40,
    )
    monkeypatch.setattr(recovery, "bind_retarget_recovery_commit", lambda *_args, **_kwargs: None)

    def persist(*_args: object) -> None:
        nonlocal state_attempts
        state_attempts += 1
        events.append("state")
        if state_attempts == 1:
            raise OSError("fault after recovery commit")

    monkeypatch.setattr(recovery, "persist_recovered_baseline_state", persist)
    monkeypatch.setattr(
        recovery,
        "activate_recovered_spec_run",
        lambda *_args: events.append("activate"),
    )

    with pytest.raises(RetargetRecoveryError, match="retarget_recovery_refresh_failed"):
        recover_retarget_checkpoint(
            tmp_path,
            _checkpoint(failed.revision_id),
            _replacement_state(failed.revision_id),
        )
    result = recover_retarget_checkpoint(
        tmp_path,
        _checkpoint(failed.revision_id),
        _replacement_state(failed.revision_id),
    )

    history = load_retarget_history(spec_dir)
    assert result.revision_id == failed.revision_id
    assert len(history.revisions) == 1
    assert history.revisions[-1].status == "recovered"
    assert events == [
        "purge",
        "refresh",
        "graph",
        "commit",
        "state",
        "commit",
        "state",
        "activate",
    ]


@pytest.mark.unit
def test_checkpoint_reset_rehydrates_failed_revision_from_captured_replacement_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.spec_retarget_recovery as recovery

    spec_dir = tmp_path / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    prepared = append_prepared_revision(
        spec_dir,
        operation_id="retarget-operation",
        baseline_run_id="squad-base",
        replacement_run_id="squad-replacement",
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=RetargetRecoveryProjection(
            run_id="squad-base",
            status="done",
            phase="phase4-document",
            spec_status="planned",
            completed_phases=("phase4-document",),
            implementation_targets=("services/api",),
            ready_to_build=True,
        ),
    )
    replacement = _replacement_state(prepared.revision_id)
    replacement["retarget"].update(
        {
            "status": "rebuilding",
            "checkpoint_id": _checkpoint(prepared.revision_id).id,
            "checkpoint_commit": "b" * 40,
            "memory_purge": _memory_receipt().to_dict(),
            "graph_invalidation": _invalidation_receipt().to_dict(),
        }
    )
    monkeypatch.setattr(
        recovery,
        "restore_or_recreate_baseline_state",
        lambda *_args, **_kwargs: SimpleNamespace(run_id="squad-base"),
    )
    monkeypatch.setattr(recovery, "purge_retarget_spec_memory", lambda *_args: _memory_receipt())
    monkeypatch.setattr(recovery, "refresh_retarget_spec_memory", lambda *_args: _memory_receipt())
    monkeypatch.setattr(recovery, "finalize_retarget_graphs", lambda *_args: _graph_receipt())
    monkeypatch.setattr(
        recovery,
        "create_or_recover_retarget_recovery_commit",
        lambda *_args: "d" * 40,
    )
    monkeypatch.setattr(recovery, "bind_retarget_recovery_commit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recovery, "persist_recovered_baseline_state", lambda *_args: None)
    monkeypatch.setattr(recovery, "activate_recovered_spec_run", lambda *_args: None)

    result = recover_retarget_checkpoint(
        tmp_path,
        _checkpoint(prepared.revision_id),
        replacement,
    )

    recovered = load_retarget_history(spec_dir).revisions[-1]
    assert result.revision_id == prepared.revision_id
    assert recovered.status == "recovered"
    assert recovered.checkpoint_id == _checkpoint(prepared.revision_id).id
    assert recovered.graph_invalidation == _invalidation_receipt().to_dict()


@pytest.mark.unit
@pytest.mark.parametrize("failure_stage", ["memory", "graph"])
def test_memory_or_graph_failure_stays_blocked_and_retries_same_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    import echelon.spec_retarget_recovery as recovery
    from harness.squad_state import SquadStateStore

    spec_dir, failed = _failed_revision(tmp_path)
    attempts = {"memory": 0, "graph": 0}
    monkeypatch.setattr(recovery, "purge_retarget_spec_memory", lambda *_args: _memory_receipt())

    def refresh(*_args: object) -> RetargetMemoryReceipt:
        attempts["memory"] += 1
        if failure_stage == "memory" and attempts["memory"] == 1:
            raise RuntimeError("memory fault")
        return _memory_receipt()

    def graph(*_args: object) -> RetargetGraphReceipt:
        attempts["graph"] += 1
        if failure_stage == "graph" and attempts["graph"] == 1:
            raise RuntimeError("graph fault")
        return _graph_receipt()

    monkeypatch.setattr(recovery, "refresh_retarget_spec_memory", refresh)
    monkeypatch.setattr(recovery, "finalize_retarget_graphs", graph)
    monkeypatch.setattr(
        recovery,
        "create_or_recover_retarget_recovery_commit",
        lambda *_args: "d" * 40,
    )
    monkeypatch.setattr(recovery, "bind_retarget_recovery_commit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recovery, "activate_recovered_spec_run", lambda *_args: None)

    with pytest.raises(RetargetRecoveryError, match="retarget_recovery_refresh_failed"):
        recover_retarget_checkpoint(
            tmp_path,
            _checkpoint(failed.revision_id),
            _replacement_state(failed.revision_id),
        )
    blocked = SquadStateStore(tmp_path / "runs/squad-base").load()
    assert blocked["status"] == "blocked"
    assert blocked["blocked_reason"] == "retarget_recovery_refresh_failed"

    result = recover_retarget_checkpoint(
        tmp_path,
        _checkpoint(failed.revision_id),
        _replacement_state(failed.revision_id),
    )
    history = load_retarget_history(spec_dir)
    assert result.revision_id == failed.revision_id
    assert len(history.revisions) == 1
    assert history.revisions[-1].status == "recovered"


@pytest.mark.unit
@pytest.mark.parametrize("starting_status", ["invalidating", "rebuilding", "finalizing"])
def test_every_nonterminal_destructive_status_recovers_through_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    starting_status: str,
) -> None:
    import echelon.spec_retarget_recovery as recovery

    spec_dir = tmp_path / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    revision = append_prepared_revision(
        spec_dir,
        operation_id="retarget-operation",
        baseline_run_id="squad-base",
        replacement_run_id="squad-replacement",
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=RetargetRecoveryProjection(
            run_id="squad-base",
            status="done",
            phase="phase4-document",
            spec_status="planned",
            completed_phases=("phase4-document",),
            implementation_targets=("services/api",),
            ready_to_build=True,
        ),
    )
    revision = advance_retarget_revision(
        spec_dir,
        revision.revision_id,
        expected_status="prepared",
        status="invalidating",
        updates={
            "checkpoint_id": _checkpoint(revision.revision_id).id,
            "checkpoint_commit": "b" * 40,
            "graph_invalidation": _invalidation_receipt().to_dict(),
        },
    )
    if starting_status in {"rebuilding", "finalizing"}:
        revision = advance_retarget_revision(
            spec_dir,
            revision.revision_id,
            expected_status="invalidating",
            status="rebuilding",
            updates={},
        )
    if starting_status == "finalizing":
        revision = advance_retarget_revision(
            spec_dir,
            revision.revision_id,
            expected_status="rebuilding",
            status="finalizing",
            updates={},
        )
    monkeypatch.setattr(
        recovery,
        "restore_or_recreate_baseline_state",
        lambda *_args, **_kwargs: SimpleNamespace(run_id="squad-base"),
    )
    monkeypatch.setattr(recovery, "purge_retarget_spec_memory", lambda *_args: _memory_receipt())
    monkeypatch.setattr(recovery, "refresh_retarget_spec_memory", lambda *_args: _memory_receipt())
    monkeypatch.setattr(recovery, "finalize_retarget_graphs", lambda *_args: _graph_receipt())
    monkeypatch.setattr(
        recovery,
        "create_or_recover_retarget_recovery_commit",
        lambda *_args: "d" * 40,
    )
    monkeypatch.setattr(recovery, "bind_retarget_recovery_commit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recovery, "persist_recovered_baseline_state", lambda *_args: None)
    monkeypatch.setattr(recovery, "activate_recovered_spec_run", lambda *_args: None)

    recover_retarget_checkpoint(
        tmp_path,
        _checkpoint(revision.revision_id),
        _replacement_state(revision.revision_id),
    )

    assert load_retarget_history(spec_dir).revisions[-1].status == "recovered"

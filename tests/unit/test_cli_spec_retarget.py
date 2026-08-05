"""CLI and coordinator tests for destructive Phase A spec retargeting."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import pytest


def _git(project_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def retarget_cli_workspace(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "001-demo")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "base")
    base_commit = _git(tmp_path, "rev-parse", "HEAD").strip()
    (tmp_path / "apps/web").mkdir(parents=True)
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon/config.yml").write_text(
        "sources: []\n",
        encoding="utf-8",
    )
    spec_dir = tmp_path / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: planned\n---\n# Old result\n",
        encoding="utf-8",
    )
    (spec_dir / "plan.md").write_text("# Old plan\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text("- [ ] T001 Build it\n", encoding="utf-8")
    (spec_dir / "targets.yml").write_text(
        "targets:\n  - services/api\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs/squad-base"
    run_dir.mkdir(parents=True)
    shadow_dir = run_dir / "specs/001-demo"
    shadow_dir.mkdir(parents=True)
    for name in ("spec.md", "plan.md", "tasks.md", "targets.yml"):
        (shadow_dir / name).write_bytes((spec_dir / name).read_bytes())
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "squad-base",
                "spec_id": "001-demo",
                "feature_branch": "001-demo",
                "spec_dir": "runs/squad-base/specs/001-demo",
                "published_spec_dir": "specs/001-demo",
                "spec_number": "001",
                "phase_a_default_branch": "001-demo",
                "phase_a_base_commit": base_commit,
                "implementation_targets": ["services/api"],
                "user_message": "Build account search",
                "autonomy_mode": "semi",
                "status": "done",
                "phase": "phase3-plan",
                "completed_phases": ["phase1-what", "phase2-how", "phase3-plan"],
                "published_re_context": {"status": "absent"},
                "ignore_re": False,
                "requested_re_sources": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "runs/.current").write_text("squad-base\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "fixture")
    return tmp_path


def _workspace_snapshot(project_root: Path) -> tuple[object, ...]:
    files = tuple(
        (path.relative_to(project_root).as_posix(), path.read_bytes())
        for path in sorted(project_root.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    )
    objects = tuple(
        path.relative_to(project_root / ".git/objects").as_posix()
        for path in sorted((project_root / ".git/objects").rglob("*"))
        if path.is_file()
    )
    return (
        files,
        objects,
        _git(project_root, "show-ref"),
        _git(project_root, "count-objects", "-v"),
        _git(project_root, "status", "--porcelain=v2"),
    )


@pytest.mark.unit
def test_retarget_preview_is_byte_and_git_object_read_only(
    retarget_cli_workspace: Path,
) -> None:
    from echelon.spec_retarget import prepare_spec_retarget

    before = _workspace_snapshot(retarget_cli_workspace)
    result = prepare_spec_retarget(
        retarget_cli_workspace,
        "001-demo",
        ("apps/web",),
        confirm=False,
    )

    assert result.applied is False
    assert result.replacement_targets == ("apps/web",)
    assert result.recovery_command.startswith(
        "echelon spec rewind checkpoint:retarget-preflight-"
    )
    assert _workspace_snapshot(retarget_cli_workspace) == before


@pytest.mark.unit
def test_preview_owns_published_canonical_spec_not_frozen_run_shadow(
    retarget_cli_workspace: Path,
) -> None:
    from echelon.spec_retarget import _build_retarget_preview

    preview = _build_retarget_preview(
        retarget_cli_workspace,
        "001-demo",
        ("apps/web",),
    )

    assert preview.spec_dir == retarget_cli_workspace / "specs/001-demo"
    assert preview.baseline.spec_dir == (
        retarget_cli_workspace / "runs/squad-base/specs/001-demo"
    )
    assert preview.baseline.published_spec_dir == preview.spec_dir


@pytest.mark.unit
@pytest.mark.parametrize(
    "args",
    (
        (),
        ("001-demo",),
        ("001-demo", "apps/web"),
        ("001-demo", "--target"),
        ("001-demo", "--target", ""),
        ("001-demo", "--target", "apps/web", "--confirm", "--confirm"),
        ("001-demo", "--target", "apps/web", "--init"),
        ("001-demo", "--target", "apps/web", "--unknown"),
        ("001-demo", "002-demo", "--target", "apps/web"),
    ),
)
def test_legacy_retarget_parser_rejects_invalid_shapes_with_exit_2(
    tmp_path: Path,
    args: tuple[str, ...],
) -> None:
    from echelon.spec_retarget_cli import run_spec_retarget_command

    with pytest.raises(SystemExit) as raised:
        run_spec_retarget_command(list(args), tmp_path)

    assert raised.value.code == 2


@pytest.mark.unit
def test_legacy_retarget_help_prints_exact_installed_usage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.spec_retarget_cli import run_spec_retarget_command

    with pytest.raises(SystemExit) as raised:
        run_spec_retarget_command([], tmp_path)

    assert raised.value.code == 2
    assert (
        "Usage: echelon spec retarget <spec-id> --target <source-id-or-path> "
        "[--target <source-id-or-path> ...] [--confirm]"
    ) in capsys.readouterr().err


@pytest.mark.unit
def test_apply_retarget_holds_locks_revalidates_and_orders_destructive_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.spec_retarget as subject
    from echelon.artifact_index import RetargetArtifactPlan
    from echelon.spec_lifecycle import SpecRun
    from harness.phase_checkpoints import PhaseCheckpoint

    events: list[str] = []

    class Lock:
        def __init__(self, name: str) -> None:
            self.name = name

        def __enter__(self) -> "Lock":
            events.append(f"enter:{self.name}")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append(f"exit:{self.name}")

    class MutationLock:
        @classmethod
        def acquire(cls, *_args: object) -> Lock:
            return Lock("mutation")

    class PhaseLock:
        @classmethod
        def acquire(cls, *_args: object) -> Lock:
            return Lock("phase-a")

    class RunLock:
        @classmethod
        def acquire(cls, *_args: object) -> Lock:
            return Lock("baseline-run")

    spec_dir = tmp_path / "specs/001-demo"
    run_dir = tmp_path / "runs/squad-base"
    replacement_dir = tmp_path / "runs/squad-replacement"
    baseline = SpecRun(
        run_dir=run_dir,
        run_dir_name="squad-base",
        run_id="squad-base",
        spec_id="001-demo",
        feature_branch="001-demo",
        spec_dir=spec_dir,
        published_spec_dir=spec_dir,
    )
    preview = subject.RetargetPreview(
        project_root=tmp_path,
        spec_id="001-demo",
        baseline=baseline,
        spec_dir=spec_dir,
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        artifact_plan=RetargetArtifactPlan((), ("spec.md",), ()),
        operation_id="retarget-operation",
        original_user_message="Build account search",
        autonomy_mode="semi",
        ignore_re=False,
        explicit_re_sources=("catalog",),
    )
    checkpoint = PhaseCheckpoint(
        id="retarget-preflight-rev-1",
        spec_id="001-demo",
        phase="retarget",
        next_phase="phase0-constitution",
        commit="a" * 40,
        metadata_commit="a" * 40,
        source="retarget-preflight",
        run_id="squad-base",
        created_at="2026-08-05T00:00:00+00:00",
    )
    monkeypatch.setattr(subject, "SpecMutationLock", MutationLock, raising=False)
    monkeypatch.setattr(subject, "PhaseAExecutionLock", PhaseLock, raising=False)
    monkeypatch.setattr(subject, "SpecRunExecutionLock", RunLock, raising=False)
    monkeypatch.setattr(
        subject,
        "require_same_retarget_preflight",
        lambda value: events.append("revalidate") or value,
        raising=False,
    )
    monkeypatch.setattr(
        subject,
        "append_prepared_revision_from_preview",
        lambda value: events.append("revision")
        or SimpleNamespace(
            revision_id="rev-1",
            replacement_run_id="squad-replacement",
        ),
        raising=False,
    )
    monkeypatch.setattr(
        subject,
        "commit_retarget_checkpoint",
        lambda **_kwargs: events.append("checkpoint") or checkpoint,
        raising=False,
    )
    monkeypatch.setattr(
        subject,
        "start_retarget_phase_a_spec_from_preview",
        lambda *_args: events.append("bootstrap")
        or SimpleNamespace(run=SimpleNamespace(run_dir=replacement_dir)),
        raising=False,
    )
    monkeypatch.setattr(
        subject,
        "advance_retarget_revision",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        subject,
        "_update_run_retarget",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        subject,
        "purge_retarget_spec_memory",
        lambda *_args: events.append("purge") or SimpleNamespace(to_dict=lambda: {"status": "pass"}),
        raising=False,
    )
    monkeypatch.setattr(
        subject,
        "persist_retarget_memory_exclusion",
        lambda *_args: events.append("persist-memory"),
        raising=False,
    )
    monkeypatch.setattr(
        subject,
        "invalidate_retarget_artifacts",
        lambda *_args: events.append("artifacts") or ("spec.md",),
        raising=False,
    )
    monkeypatch.setattr(
        subject,
        "invalidate_retarget_graphs",
        lambda *_args: events.append("graphs") or SimpleNamespace(to_dict=lambda: {"spec_status": "invalidated"}),
        raising=False,
    )
    monkeypatch.setattr(
        subject,
        "write_checkpoint_coverage_context",
        lambda *_args: events.append("context"),
        raising=False,
    )
    monkeypatch.setattr(
        subject,
        "mark_retarget_rebuilding",
        lambda *_args: events.append("rebuilding"),
        raising=False,
    )

    result = subject._apply_retarget(
        preview,
        checkpoint_created=lambda _checkpoint: events.append("callback"),
    )

    assert result.applied is True
    assert events == [
        "enter:mutation",
        "enter:phase-a",
        "enter:baseline-run",
        "revalidate",
        "revision",
        "checkpoint",
        "callback",
        "bootstrap",
        "purge",
        "persist-memory",
        "artifacts",
        "graphs",
        "context",
        "rebuilding",
        "exit:baseline-run",
        "exit:phase-a",
        "exit:mutation",
    ]


@pytest.mark.unit
def test_retarget_checkpoint_callback_flushes_before_first_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.spec_retarget_cli as subject
    from echelon.spec_retarget import RetargetCommandResult

    events: list[str] = []

    class Output:
        def write(self, value: str) -> int:
            if value.strip():
                events.append(f"write:{value.strip()}")
            return len(value)

        def flush(self) -> None:
            events.append("flush")

    def fake_prepare(*_args: object, **kwargs: object) -> RetargetCommandResult:
        kwargs["checkpoint_created"](SimpleNamespace(id="retarget-preflight-rev-1"))
        events.append("destructive-effect")
        return RetargetCommandResult(
            True,
            False,
            "001-demo",
            "squad-base",
            "squad-replacement",
            ("apps/web",),
            "retarget-preflight-rev-1",
            "a" * 40,
            "echelon spec rewind checkpoint:retarget-preflight-rev-1 --confirm",
            ("spec.md",),
            "Build account search",
            "semi",
            False,
            (),
        )

    monkeypatch.setattr(subject, "prepare_spec_retarget", fake_prepare)
    monkeypatch.setattr(subject, "_resolved_targets", lambda *_args: ("apps/web",))
    monkeypatch.setattr(subject.sys, "stdout", Output())

    subject.run_spec_retarget_command(
        ["001-demo", "--target", "apps/web", "--confirm"],
        tmp_path,
    )

    assert events.index("flush") < events.index("destructive-effect")
    assert events[0] == (
        "write:echelon spec rewind checkpoint:retarget-preflight-rev-1 --confirm"
    )


@pytest.mark.unit
def test_artifact_invalidation_is_exact_and_preserves_unrelated_bytes(
    tmp_path: Path,
) -> None:
    from echelon.artifact_index import plan_retarget_artifacts
    from echelon.spec_retarget import invalidate_retarget_artifacts

    spec_dir = tmp_path / "specs/001-demo"
    shadow_dir = tmp_path / "runs/squad-replacement/specs/001-demo"
    for root in (spec_dir, shadow_dir):
        (root / "contracts").mkdir(parents=True)
        (root / "spec.md").write_text("old\n", encoding="utf-8")
        (root / "contracts/api.md").write_text("old\n", encoding="utf-8")
        (root / "run-history.json").write_text("{}\n", encoding="utf-8")
    unrelated = tmp_path / "notes/private.txt"
    unrelated.parent.mkdir()
    unrelated.write_bytes(b"keep\x00bytes\n")
    plan = plan_retarget_artifacts(spec_dir)

    invalidated = invalidate_retarget_artifacts(
        spec_dir,
        shadow_dir,
        plan,
        ("apps/web",),
    )

    assert invalidated == ("contracts", "spec.md")
    assert not (spec_dir / "spec.md").exists()
    assert not (shadow_dir / "contracts").exists()
    assert json.loads((spec_dir / "run-history.json").read_text()) == {}
    assert (spec_dir / "targets.yml").read_text(encoding="utf-8") == (
        "targets:\n- apps/web\n"
    )
    assert (shadow_dir / "targets.yml").read_bytes() == (
        spec_dir / "targets.yml"
    ).read_bytes()
    assert unrelated.read_bytes() == b"keep\x00bytes\n"


@pytest.mark.unit
def test_checkpoint_context_uses_git_bytes_and_exact_manifest(
    retarget_cli_workspace: Path,
) -> None:
    from echelon.spec_retarget import write_checkpoint_coverage_context

    commit = _git(retarget_cli_workspace, "rev-parse", "HEAD").strip()
    replacement = retarget_cli_workspace / "runs/squad-replacement"
    replacement.mkdir()
    manifest = write_checkpoint_coverage_context(
        retarget_cli_workspace,
        commit,
        "001-demo",
        replacement,
    )

    context = replacement / "context/retarget-baseline"
    assert "NON-AUTHORITATIVE RETARGET COVERAGE CONTEXT" in (
        context / "README.md"
    ).read_text(encoding="utf-8")
    assert tuple(row["path"] for row in manifest["files"]) == (
        "spec.md",
        "plan.md",
        "tasks.md",
        "targets.yml",
    )
    for row in manifest["files"]:
        assert row["sha256"].startswith("sha256:")
        assert (context / row["path"]).read_bytes() == subprocess.run(
            [
                "git",
                "show",
                f"{commit}:specs/001-demo/{row['path']}",
            ],
            cwd=retarget_cli_workspace,
            check=True,
            capture_output=True,
        ).stdout


@pytest.mark.unit
def test_checkpoint_context_prevalidates_total_cap_before_writing(
    retarget_cli_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.spec_retarget as subject

    replacement = retarget_cli_workspace / "runs/squad-replacement"
    replacement.mkdir()
    monkeypatch.setattr(subject, "_RETARGET_CONTEXT_TOTAL_CAP", 4, raising=False)
    commit = _git(retarget_cli_workspace, "rev-parse", "HEAD").strip()

    with pytest.raises(subject.RetargetError, match="total exceeds cap"):
        subject.write_checkpoint_coverage_context(
            retarget_cli_workspace,
            commit,
            "001-demo",
            replacement,
        )

    assert not (replacement / "context").exists()


@pytest.mark.unit
def test_checkpoint_context_rejects_git_symlink_before_writing(
    retarget_cli_workspace: Path,
) -> None:
    from echelon.spec_retarget import RetargetError, write_checkpoint_coverage_context

    plan = retarget_cli_workspace / "specs/001-demo/plan.md"
    plan.unlink()
    plan.symlink_to("spec.md")
    _git(retarget_cli_workspace, "add", "specs/001-demo/plan.md")
    _git(retarget_cli_workspace, "commit", "-m", "symlink baseline")
    commit = _git(retarget_cli_workspace, "rev-parse", "HEAD").strip()
    replacement = retarget_cli_workspace / "runs/squad-replacement"
    replacement.mkdir()

    with pytest.raises(RetargetError, match="regular Git blob"):
        write_checkpoint_coverage_context(
            retarget_cli_workspace,
            commit,
            "001-demo",
            replacement,
        )

    assert not (replacement / "context").exists()


@pytest.mark.unit
def test_checkpoint_artifact_extraction_failure_is_not_missing(
    retarget_cli_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.spec_retarget as subject

    commit = _git(retarget_cli_workspace, "rev-parse", "HEAD").strip()
    real_run = subject.subprocess.run

    def fail_extraction(args: list[str], **kwargs: object):
        if args[:2] == ["git", "show"] or args[:2] == ["git", "cat-file"]:
            return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"boom")
        return real_run(args, **kwargs)

    monkeypatch.setattr(subject.subprocess, "run", fail_extraction)

    with pytest.raises(subject.RetargetError, match="read checkpoint context"):
        subject.checkpoint_artifact_bytes(
            retarget_cli_workspace,
            commit,
            "001-demo",
            "spec.md",
        )


@pytest.mark.unit
def test_bounded_failure_code_is_stable() -> None:
    from echelon.mempalace_retarget import RetargetMemoryError
    from echelon.spec_retarget import (
        RetargetArtifactError,
        RetargetCheckpointError,
        RetargetEligibilityError,
        RetargetRebuildError,
        bounded_failure_code,
    )
    from echelon.spec_retarget_graph import RetargetGraphError

    assert bounded_failure_code(RetargetEligibilityError("x")) == (
        "retarget_delivery_already_started"
    )
    assert bounded_failure_code(RetargetCheckpointError("x")) == (
        "retarget_checkpoint_failed"
    )
    assert bounded_failure_code(RetargetMemoryError("x")) == (
        "retarget_memory_purge_failed"
    )
    assert bounded_failure_code(RetargetArtifactError("x")) == (
        "retarget_artifact_invalidation_failed"
    )
    assert bounded_failure_code(RetargetGraphError("x")) == (
        "retarget_graph_refresh_failed"
    )
    assert bounded_failure_code(RetargetRebuildError("x")) == (
        "retarget_rebuild_blocked"
    )
    assert bounded_failure_code(RuntimeError("x")) == "retarget_rebuild_blocked"


@pytest.mark.unit
def test_duplicate_targets_after_resolution_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.spec_retarget_cli import run_spec_retarget_command

    monkeypatch.setattr(
        "echelon.cli._resolve_spec_run_implementation_targets",
        lambda _root, _targets, allow_missing: ["apps/web"],
    )

    with pytest.raises(SystemExit) as raised:
        run_spec_retarget_command(
            [
                "001-demo",
                "--target",
                "web-source",
                "--target",
                "apps/web/",
            ],
            tmp_path,
        )

    assert raised.value.code == 2


@pytest.mark.unit
def test_preview_rendering_and_recovery_identity_are_deterministic(
    retarget_cli_workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.spec_retarget_cli import run_spec_retarget_command

    first = run_spec_retarget_command(
        ["001-demo", "--target", "apps/web"],
        retarget_cli_workspace,
    )
    first_output = capsys.readouterr().out
    second = run_spec_retarget_command(
        ["001-demo", "--target", "apps/web"],
        retarget_cli_workspace,
    )
    second_output = capsys.readouterr().out

    assert first == second
    assert first_output == second_output
    assert "RETARGET PREVIEW" in first_output
    assert "DESTRUCTIVE" in first_output
    assert "non-buildable" in first_output
    assert "old targets: services/api" in first_output
    assert "baseline result: ready to build" in first_output
    assert first.recovery_command in first_output


def _activate_retarget_retry(
    project_root: Path,
    *,
    status: str,
) -> tuple[str, str]:
    from echelon.spec_retarget_history import (
        RetargetRecoveryProjection,
        advance_retarget_revision,
        append_prepared_revision,
    )
    from harness.phase_checkpoints import PhaseCheckpoint, record_checkpoint_metadata

    baseline = json.loads(
        (project_root / "runs/squad-base/state.json").read_text(encoding="utf-8")
    )
    replacement_id = "squad-retarget-existing"
    revision = append_prepared_revision(
        project_root / "specs/001-demo",
        operation_id="retarget-existing",
        baseline_run_id="squad-base",
        replacement_run_id=replacement_id,
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=RetargetRecoveryProjection(
            run_id="squad-base",
            status="done",
            phase="phase3-plan",
            spec_status="planned",
            completed_phases=("phase3-plan",),
            implementation_targets=("services/api",),
            ready_to_build=True,
        ),
    )
    checkpoint_id = f"retarget-preflight-{revision.revision_id}"
    checkpoint_commit = _git(project_root, "rev-parse", "HEAD").strip()
    if status in {"invalidating", "rebuilding"}:
        advance_retarget_revision(
            project_root / "specs/001-demo",
            revision.revision_id,
            expected_status="prepared",
            status="invalidating",
            updates={
                "checkpoint_id": checkpoint_id,
                "checkpoint_commit": checkpoint_commit,
            },
        )
        if status == "rebuilding":
            advance_retarget_revision(
                project_root / "specs/001-demo",
                revision.revision_id,
                expected_status="invalidating",
                status="rebuilding",
                updates={},
            )
    elif status == "failed":
        advance_retarget_revision(
            project_root / "specs/001-demo",
            revision.revision_id,
            expected_status="prepared",
            status="failed",
            updates={
                "checkpoint_id": checkpoint_id,
                "checkpoint_commit": checkpoint_commit,
                "failure_code": "retarget_memory_purge_failed",
            },
        )
    record_checkpoint_metadata(
        project_root / "specs/001-demo",
        PhaseCheckpoint(
            id=checkpoint_id,
            spec_id="001-demo",
            phase="retarget",
            next_phase="phase0-constitution",
            commit=checkpoint_commit,
            metadata_commit=checkpoint_commit,
            source="retarget-preflight",
            run_id="squad-base",
            created_at="2026-08-05T00:00:00+00:00",
        ),
    )
    replacement = dict(baseline)
    replacement.update(
        {
            "run_id": replacement_id,
            "implementation_targets": ["apps/web"],
            "spec_dir": f"runs/{replacement_id}/specs/001-demo",
            "published_spec_dir": "specs/001-demo",
            "retarget": {
                "operation_id": "retarget-existing",
                "revision_id": revision.revision_id,
                "status": status,
                "failure_code": "retarget_memory_purge_failed"
                if status == "failed"
                else None,
                "baseline_run_id": "squad-base",
                "replacement_run_id": replacement_id,
                "old_targets": ["services/api"],
                "replacement_targets": ["apps/web"],
                "checkpoint_id": checkpoint_id,
                "checkpoint_commit": checkpoint_commit,
            },
        }
    )
    replacement_dir = project_root / "runs" / replacement_id
    replacement_dir.mkdir()
    replacement_shadow = replacement_dir / "specs/001-demo"
    replacement_shadow.mkdir(parents=True)
    for name in ("spec.md", "plan.md", "tasks.md", "targets.yml"):
        (replacement_shadow / name).write_bytes(
            (project_root / "specs/001-demo" / name).read_bytes()
        )
    (replacement_dir / "state.json").write_text(
        json.dumps(replacement, indent=2) + "\n",
        encoding="utf-8",
    )
    (project_root / "runs/.current").write_text(
        f"{replacement_id}\n",
        encoding="utf-8",
    )
    return replacement_id, checkpoint_id


@pytest.mark.unit
def test_matching_nonterminal_retry_reuses_recorded_run_and_checkpoint(
    retarget_cli_workspace: Path,
) -> None:
    from echelon.spec_retarget import prepare_spec_retarget

    replacement_id, checkpoint_id = _activate_retarget_retry(
        retarget_cli_workspace,
        status="rebuilding",
    )

    result = prepare_spec_retarget(
        retarget_cli_workspace,
        "001-demo",
        ("apps/web",),
        confirm=True,
    )

    assert result.applied is True
    assert result.resume_existing is True
    assert result.replacement_run_id == replacement_id
    assert result.checkpoint_id == checkpoint_id
    from echelon.spec_retarget_history import load_retarget_history

    assert len(
        load_retarget_history(retarget_cli_workspace / "specs/001-demo").revisions
    ) == 1


@pytest.mark.unit
@pytest.mark.parametrize("status", ("checkpointed", "invalidating"))
def test_retry_finishes_remaining_destructive_effects_before_dispatch(
    retarget_cli_workspace: Path,
    status: str,
) -> None:
    from echelon.spec_retarget import prepare_spec_retarget
    from echelon.spec_retarget_history import load_retarget_history

    replacement_id, checkpoint_id = _activate_retarget_retry(
        retarget_cli_workspace,
        status=status,
    )
    callbacks: list[str] = []

    result = prepare_spec_retarget(
        retarget_cli_workspace,
        "001-demo",
        ("apps/web",),
        confirm=True,
        checkpoint_created=lambda checkpoint: callbacks.append(checkpoint.id),
    )

    canonical = retarget_cli_workspace / "specs/001-demo"
    shadow = retarget_cli_workspace / f"runs/{replacement_id}/specs/001-demo"
    state = json.loads(
        (retarget_cli_workspace / f"runs/{replacement_id}/state.json").read_text(
            encoding="utf-8"
        )
    )
    history = load_retarget_history(canonical)
    assert result.applied is True and result.resume_existing is True
    assert result.replacement_run_id == replacement_id
    assert result.checkpoint_id == checkpoint_id
    assert callbacks == [checkpoint_id]
    assert len(history.revisions) == 1
    assert history.revisions[-1].status == "rebuilding"
    assert state["retarget"]["status"] == "rebuilding"
    assert state["retarget"]["memory_excluded"] is True
    assert not (canonical / "spec.md").exists()
    assert not (shadow / "spec.md").exists()
    assert (canonical / "targets.yml").read_text(encoding="utf-8") == (
        "targets:\n- apps/web\n"
    )
    assert (shadow / "targets.yml").read_bytes() == (
        canonical / "targets.yml"
    ).read_bytes()
    assert stat.S_IMODE((canonical / "targets.yml").stat().st_mode) == 0o600
    assert stat.S_IMODE((shadow / "targets.yml").stat().st_mode) == 0o600


@pytest.mark.unit
def test_retry_adopts_prepared_checkpoint_before_replacement_installation(
    retarget_cli_workspace: Path,
) -> None:
    import hashlib

    from echelon.spec_retarget import (
        _build_retarget_preview,
        _replacement_run_id,
        prepare_spec_retarget,
    )
    from echelon.spec_retarget_history import (
        RetargetRecoveryProjection,
        append_prepared_revision,
        load_retarget_history,
    )
    from harness.phase_checkpoints import commit_retarget_checkpoint

    preview = _build_retarget_preview(
        retarget_cli_workspace,
        "001-demo",
        ("apps/web",),
    )
    canonical = retarget_cli_workspace / "specs/001-demo"
    revision = append_prepared_revision(
        canonical,
        operation_id=preview.operation_id,
        baseline_run_id=preview.baseline.run_id,
        replacement_run_id=_replacement_run_id(preview),
        old_targets=preview.old_targets,
        replacement_targets=preview.replacement_targets,
        original_prompt_digest=(
            "sha256:"
            + hashlib.sha256(preview.original_user_message.encode("utf-8")).hexdigest()
        ),
        recovery=RetargetRecoveryProjection(
            run_id=preview.baseline.run_id,
            status="done",
            phase="phase3-plan",
            spec_status="planned",
            completed_phases=("phase1-what", "phase2-how", "phase3-plan"),
            implementation_targets=preview.old_targets,
            ready_to_build=True,
        ),
    )
    checkpoint = commit_retarget_checkpoint(
        project_root=retarget_cli_workspace,
        spec_dir=canonical,
        run_id=preview.baseline.run_id,
        revision_id=revision.revision_id,
    )
    callbacks: list[str] = []

    result = prepare_spec_retarget(
        retarget_cli_workspace,
        "001-demo",
        ("apps/web",),
        confirm=True,
        checkpoint_created=lambda created: callbacks.append(created.id),
    )

    history = load_retarget_history(canonical)
    assert result.resume_existing is True and result.applied is True
    assert result.replacement_run_id == revision.replacement_run_id
    assert result.checkpoint_id == checkpoint.id
    assert callbacks == [checkpoint.id]
    assert len(history.revisions) == 1
    assert history.revisions[-1].revision_id == revision.revision_id
    assert history.revisions[-1].status == "rebuilding"
    assert (retarget_cli_workspace / "runs/.current").read_text().strip() == (
        revision.replacement_run_id
    )
    assert not (canonical / "spec.md").exists()


@pytest.mark.unit
def test_matching_retry_rejects_missing_history_with_recorded_recovery(
    retarget_cli_workspace: Path,
) -> None:
    from echelon.spec_retarget import RetargetEligibilityError, prepare_spec_retarget

    _replacement_id, checkpoint_id = _activate_retarget_retry(
        retarget_cli_workspace,
        status="rebuilding",
    )
    (retarget_cli_workspace / "specs/001-demo/retarget-history.json").unlink()

    with pytest.raises(RetargetEligibilityError) as raised:
        prepare_spec_retarget(
            retarget_cli_workspace,
            "001-demo",
            ("apps/web",),
            confirm=True,
        )

    preview_recovery_command = (
        f"echelon spec rewind checkpoint:{checkpoint_id} --confirm"
    )
    assert preview_recovery_command in str(raised.value)


@pytest.mark.unit
@pytest.mark.parametrize("status", ("rebuilding", "failed"))
def test_retry_mismatch_or_failed_state_requires_recorded_rewind(
    retarget_cli_workspace: Path,
    status: str,
) -> None:
    from echelon.spec_retarget import RetargetEligibilityError, prepare_spec_retarget

    _replacement_id, checkpoint_id = _activate_retarget_retry(
        retarget_cli_workspace,
        status=status,
    )
    requested = ("services/other",) if status == "rebuilding" else ("apps/web",)

    with pytest.raises(RetargetEligibilityError) as raised:
        prepare_spec_retarget(
            retarget_cli_workspace,
            "001-demo",
            requested,
            confirm=True,
        )

    assert (
        f"echelon spec rewind checkpoint:{checkpoint_id} --confirm"
        in str(raised.value)
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("failure_stage", "expected_code"),
    (
        ("purge", "retarget_memory_purge_failed"),
        ("persist", "retarget_memory_purge_failed"),
        ("artifacts", "retarget_artifact_invalidation_failed"),
        ("graphs", "retarget_graph_refresh_failed"),
        ("context", "retarget_rebuild_blocked"),
        ("rebuilding", "retarget_rebuild_blocked"),
    ),
)
def test_destructive_failure_marks_failed_and_keeps_recovery_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    expected_code: str,
) -> None:
    import echelon.spec_retarget as subject
    from echelon.artifact_index import RetargetArtifactPlan
    from echelon.mempalace_retarget import RetargetMemoryError
    from echelon.spec_lifecycle import SpecRun
    from harness.phase_checkpoints import PhaseCheckpoint

    def fail(stage: str, error: BaseException) -> None:
        if failure_stage == stage:
            raise error

    class Lock:
        def __enter__(self) -> "Lock":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class LockType:
        @classmethod
        def acquire(cls, *_args: object) -> Lock:
            return Lock()

    spec_dir = tmp_path / "specs/001-demo"
    baseline_dir = tmp_path / "runs/squad-base"
    replacement_dir = tmp_path / "runs/squad-replacement"
    baseline = SpecRun(
        baseline_dir,
        "squad-base",
        "squad-base",
        "001-demo",
        "001-demo",
        spec_dir,
        spec_dir,
    )
    preview = subject.RetargetPreview(
        tmp_path,
        "001-demo",
        baseline,
        spec_dir,
        ("services/api",),
        ("apps/web",),
        RetargetArtifactPlan((), ("spec.md",), ()),
        "retarget-op",
        "Build account search",
        "semi",
        False,
        (),
    )
    checkpoint = PhaseCheckpoint(
        "retarget-preflight-rev-1",
        "001-demo",
        "retarget",
        "phase0-constitution",
        "a" * 40,
        "a" * 40,
        "retarget-preflight",
        "squad-base",
        "2026-08-05T00:00:00+00:00",
    )
    failed: list[str] = []
    monkeypatch.setattr(subject, "SpecMutationLock", LockType)
    monkeypatch.setattr(subject, "PhaseAExecutionLock", LockType)
    monkeypatch.setattr(subject, "SpecRunExecutionLock", LockType)
    monkeypatch.setattr(subject, "require_same_retarget_preflight", lambda value: value)
    monkeypatch.setattr(
        subject,
        "append_prepared_revision_from_preview",
        lambda _preview: SimpleNamespace(
            revision_id="rev-1",
            replacement_run_id="squad-replacement",
        ),
    )
    monkeypatch.setattr(subject, "commit_retarget_checkpoint", lambda **_kwargs: checkpoint)
    monkeypatch.setattr(
        subject,
        "start_retarget_phase_a_spec_from_preview",
        lambda *_args: SimpleNamespace(run=SimpleNamespace(run_dir=replacement_dir)),
    )
    monkeypatch.setattr(subject, "advance_retarget_revision", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(subject, "_update_run_retarget", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        subject,
        "purge_retarget_spec_memory",
        lambda *_args: fail("purge", RetargetMemoryError("purge failed"))
        or SimpleNamespace(to_dict=lambda: {"status": "pass"}),
    )
    monkeypatch.setattr(
        subject,
        "persist_retarget_memory_exclusion",
        lambda *_args: fail("persist", RetargetMemoryError("persist failed")),
    )
    monkeypatch.setattr(
        subject,
        "invalidate_retarget_artifacts",
        lambda *_args: fail(
            "artifacts",
            subject.RetargetArtifactError("artifact failure"),
        )
        or ("spec.md",),
    )
    monkeypatch.setattr(
        subject,
        "invalidate_retarget_graphs",
        lambda *_args: fail(
            "graphs",
            subject.RetargetGraphError("graph failure"),
        )
        or SimpleNamespace(to_dict=lambda: {"status": "pass"}),
    )
    monkeypatch.setattr(
        subject,
        "write_checkpoint_coverage_context",
        lambda *_args: fail(
            "context",
            subject.RetargetRebuildError("context failure"),
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_retarget_rebuilding",
        lambda *_args: fail(
            "rebuilding",
            subject.RetargetRebuildError("rebuilding failure"),
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_retarget_failed",
        lambda _run, _spec, code: failed.append(code),
    )

    with pytest.raises(subject.RetargetDestructiveError) as raised:
        subject._apply_retarget(preview, checkpoint_created=None)

    assert failed == [expected_code]
    preview_recovery = (
        "echelon spec rewind checkpoint:retarget-preflight-rev-1 --confirm"
    )
    assert preview_recovery in str(raised.value)


@pytest.mark.unit
def test_bootstrap_failure_after_checkpoint_records_failure_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.spec_retarget as subject
    from echelon.artifact_index import RetargetArtifactPlan
    from echelon.spec_lifecycle import SpecRun
    from harness.phase_checkpoints import PhaseCheckpoint

    class Lock:
        def __enter__(self) -> "Lock":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class LockType:
        @classmethod
        def acquire(cls, *_args: object) -> Lock:
            return Lock()

    spec_dir = tmp_path / "specs/001-demo"
    baseline = SpecRun(
        tmp_path / "runs/squad-base",
        "squad-base",
        "squad-base",
        "001-demo",
        "001-demo",
        spec_dir,
        spec_dir,
    )
    preview = subject.RetargetPreview(
        tmp_path,
        "001-demo",
        baseline,
        spec_dir,
        ("services/api",),
        ("apps/web",),
        RetargetArtifactPlan((), ("spec.md",), ()),
        "retarget-op",
        "Build account search",
        "semi",
        False,
        (),
    )
    revision = SimpleNamespace(
        revision_id="rev-1",
        replacement_run_id="squad-replacement",
    )
    checkpoint = PhaseCheckpoint(
        "retarget-preflight-rev-1",
        "001-demo",
        "retarget",
        "phase0-constitution",
        "a" * 40,
        "a" * 40,
        "retarget-preflight",
        "squad-base",
        "2026-08-05T00:00:00+00:00",
    )
    recorded: list[str] = []
    monkeypatch.setattr(subject, "SpecMutationLock", LockType)
    monkeypatch.setattr(subject, "PhaseAExecutionLock", LockType)
    monkeypatch.setattr(subject, "SpecRunExecutionLock", LockType)
    monkeypatch.setattr(subject, "require_same_retarget_preflight", lambda value: value)
    monkeypatch.setattr(subject, "append_prepared_revision_from_preview", lambda _: revision)
    monkeypatch.setattr(subject, "commit_retarget_checkpoint", lambda **_: checkpoint)
    monkeypatch.setattr(
        subject,
        "start_retarget_phase_a_spec_from_preview",
        lambda *_: (_ for _ in ()).throw(subject.RetargetRebuildError("bootstrap failed")),
    )
    monkeypatch.setattr(
        subject,
        "mark_retarget_failed_before_bootstrap",
        lambda *_args: recorded.append("retarget_rebuild_blocked"),
        raising=False,
    )

    with pytest.raises(subject.RetargetDestructiveError) as raised:
        subject._apply_retarget(preview, checkpoint_created=None)

    assert recorded == ["retarget_rebuild_blocked"]
    assert "echelon spec rewind checkpoint:retarget-preflight-rev-1 --confirm" in str(
        raised.value
    )


@pytest.mark.unit
@pytest.mark.parametrize("symlink_name", ("plan.md", "run-history.json"))
def test_artifact_invalidation_rejects_symlink_before_removing_anything(
    tmp_path: Path,
    symlink_name: str,
) -> None:
    from echelon.artifact_index import plan_retarget_artifacts
    from echelon.spec_retarget import RetargetArtifactError, invalidate_retarget_artifacts

    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n", encoding="utf-8")
    spec_dir = tmp_path / "specs/001-demo"
    shadow = tmp_path / "runs/squad-replacement/specs/001-demo"
    for root in (spec_dir, shadow):
        root.mkdir(parents=True)
        (root / "spec.md").write_text("old\n", encoding="utf-8")
    (spec_dir / symlink_name).symlink_to(outside)
    plan = plan_retarget_artifacts(spec_dir)

    with pytest.raises(RetargetArtifactError, match="symlink"):
        invalidate_retarget_artifacts(spec_dir, shadow, plan, ("apps/web",))

    assert (spec_dir / "spec.md").read_text(encoding="utf-8") == "old\n"
    assert outside.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.unit
@pytest.mark.parametrize("race_owner", ("canonical", "shadow"))
def test_artifact_invalidation_swap_race_cannot_delete_outside_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    race_owner: str,
) -> None:
    from echelon.artifact_index import plan_retarget_artifacts
    import echelon.spec_retarget as subject

    spec_dir = tmp_path / "specs/001-demo"
    shadow = tmp_path / "runs/squad-replacement/specs/001-demo"
    for root in (spec_dir, shadow):
        (root / "contracts").mkdir(parents=True)
        (root / "contracts/owned.txt").write_text("owned\n", encoding="utf-8")
        (root / "targets.yml").write_text(
            "targets:\n- services/api\n",
            encoding="utf-8",
        )
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_victim = outside / "must-survive.txt"
    outside_victim.write_text("keep\n", encoding="utf-8")
    race_root = spec_dir if race_owner == "canonical" else shadow
    real_rename = os.rename
    swapped = False

    def racing_rename(src: object, dst: object, *args: object, **kwargs: object):
        nonlocal swapped
        source_fd = kwargs.get("src_dir_fd")
        if (
            not swapped
            and src == "contracts"
            and isinstance(source_fd, int)
            and os.fstat(source_fd).st_ino == race_root.stat().st_ino
        ):
            swapped = True
            real_rename(race_root / "contracts", race_root / "contracts-original")
            (race_root / "contracts").symlink_to(outside, target_is_directory=True)
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(subject.os, "rename", racing_rename)

    with pytest.raises(subject.RetargetArtifactError, match="changed during invalidation"):
        subject.invalidate_retarget_artifacts(
            spec_dir,
            shadow,
            plan_retarget_artifacts(spec_dir),
            ("apps/web",),
        )

    assert swapped is True
    assert outside_victim.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.unit
@pytest.mark.parametrize("race_owner", ("canonical", "shadow"))
def test_artifact_invalidation_root_swap_before_target_publication_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    race_owner: str,
) -> None:
    """A renamed public root must not receive a replacement target contract."""
    from echelon.artifact_index import plan_retarget_artifacts
    import echelon.spec_retarget as subject

    spec_dir = tmp_path / "specs/001-demo"
    shadow = tmp_path / "runs/squad-replacement/specs/001-demo"
    for root in (spec_dir, shadow):
        (root / "contracts").mkdir(parents=True)
        (root / "contracts/owned.txt").write_text("owned\n", encoding="utf-8")
        (root / "targets.yml").write_text(
            "targets:\n- services/api\n",
            encoding="utf-8",
        )
    race_root = spec_dir if race_owner == "canonical" else shadow
    external = tmp_path / f"external-{race_owner}"
    external.mkdir()
    (external / "targets.yml").write_text("external\n", encoding="utf-8")
    real_quarantine = subject._quarantine_invalidations
    swapped = False

    def swap_after_quarantine(root: object, identities: object) -> None:
        nonlocal swapped
        real_quarantine(root, identities)
        root_path = getattr(root, "path")
        if root_path != race_root:
            return
        swapped = True
        displaced = root_path.with_name(f"{root_path.name}-displaced")
        os.rename(root_path, displaced)
        os.rename(external, root_path)

    monkeypatch.setattr(subject, "_quarantine_invalidations", swap_after_quarantine)

    with pytest.raises(subject.RetargetArtifactError, match="changed during target publication"):
        subject.invalidate_retarget_artifacts(
            spec_dir,
            shadow,
            plan_retarget_artifacts(spec_dir),
            ("apps/web",),
        )

    assert swapped is True
    assert (race_root / "targets.yml").read_text(encoding="utf-8") == "external\n"
    assert not list(tmp_path.rglob(".targets.yml.*.tmp"))


@pytest.mark.unit
@pytest.mark.parametrize("race_owner", ("canonical", "shadow"))
def test_target_publication_replace_interval_root_swap_rolls_back_both_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    race_owner: str,
) -> None:
    """A post-replace root swap must roll back every owned target contract."""
    from echelon.artifact_index import plan_retarget_artifacts
    import echelon.spec_retarget as subject

    spec_dir = tmp_path / "specs/001-demo"
    shadow = tmp_path / "runs/squad-replacement/specs/001-demo"
    old_content = b"targets:\n- services/api\n"
    old_modes = {spec_dir: 0o640, shadow: 0o600}
    for root, mode in old_modes.items():
        (root / "contracts").mkdir(parents=True)
        (root / "contracts/owned.txt").write_text("owned\n", encoding="utf-8")
        target = root / "targets.yml"
        target.write_bytes(old_content)
        target.chmod(mode)
    race_root = spec_dir if race_owner == "canonical" else shadow
    other_root = shadow if race_root == spec_dir else spec_dir
    displaced = race_root.with_name(f"{race_root.name}-displaced")
    external = tmp_path / f"external-replace-{race_owner}"
    external.mkdir()
    external_target = external / "targets.yml"
    external_target.write_bytes(b"external\n")
    external_target.chmod(0o604)
    external_preimage = (
        external_target.read_bytes(),
        stat.S_IMODE(external_target.stat().st_mode),
    )
    real_replace = subject.os.replace
    swapped = False

    def swap_inside_replace(src: object, dst: object, *args: object, **kwargs: object):
        nonlocal swapped
        result = real_replace(src, dst, *args, **kwargs)
        destination_fd = kwargs.get("dst_dir_fd")
        if (
            not swapped
            and dst == "targets.yml"
            and isinstance(destination_fd, int)
            and os.fstat(destination_fd).st_ino == race_root.stat().st_ino
        ):
            swapped = True
            os.rename(race_root, displaced)
            os.rename(external, race_root)
        return result

    monkeypatch.setattr(subject.os, "replace", swap_inside_replace)

    with pytest.raises(subject.RetargetArtifactError, match="target publication"):
        subject.invalidate_retarget_artifacts(
            spec_dir,
            shadow,
            plan_retarget_artifacts(spec_dir),
            ("apps/web",),
        )

    assert swapped is True
    assert (race_root / "targets.yml").read_bytes() == external_preimage[0]
    assert stat.S_IMODE((race_root / "targets.yml").stat().st_mode) == external_preimage[1]
    assert (displaced / "targets.yml").read_bytes() == old_content
    assert stat.S_IMODE((displaced / "targets.yml").stat().st_mode) == old_modes[race_root]
    assert (other_root / "targets.yml").read_bytes() == old_content
    assert stat.S_IMODE((other_root / "targets.yml").stat().st_mode) == old_modes[other_root]
    assert not list(tmp_path.rglob(".targets.yml.*.tmp"))


@pytest.mark.unit
@pytest.mark.parametrize("race_owner", ("canonical", "shadow"))
def test_target_publication_final_commit_check_rolls_back_both_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    race_owner: str,
) -> None:
    """A root changed after its local write check must fail the whole commit."""
    from echelon.artifact_index import plan_retarget_artifacts
    import echelon.spec_retarget as subject

    spec_dir = tmp_path / "specs/001-demo"
    shadow = tmp_path / "runs/squad-replacement/specs/001-demo"
    old_content = b"targets:\n- services/api\n"
    old_modes = {spec_dir: 0o640, shadow: 0o600}
    for root, mode in old_modes.items():
        (root / "contracts").mkdir(parents=True)
        (root / "contracts/owned.txt").write_text("owned\n", encoding="utf-8")
        target = root / "targets.yml"
        target.write_bytes(old_content)
        target.chmod(mode)
    race_root = spec_dir if race_owner == "canonical" else shadow
    other_root = shadow if race_root == spec_dir else spec_dir
    displaced = race_root.with_name(f"{race_root.name}-commit-displaced")
    external = tmp_path / f"external-commit-{race_owner}"
    external.mkdir()
    external_target = external / "targets.yml"
    external_target.write_bytes(b"external\n")
    external_target.chmod(0o604)
    external_preimage = (
        external_target.read_bytes(),
        stat.S_IMODE(external_target.stat().st_mode),
    )
    real_authenticate = subject._authenticate_pinned_retarget_root
    authentication_count = 0
    swapped = False

    def swap_after_local_publication_check(root: object, *, stage: str) -> None:
        nonlocal authentication_count, swapped
        real_authenticate(root, stage=stage)
        if getattr(root, "path") != race_root or stage != "target publication":
            return
        authentication_count += 1
        if authentication_count != 4:
            return
        swapped = True
        os.rename(race_root, displaced)
        os.rename(external, race_root)

    monkeypatch.setattr(
        subject,
        "_authenticate_pinned_retarget_root",
        swap_after_local_publication_check,
    )

    with pytest.raises(subject.RetargetArtifactError, match="target publication"):
        subject.invalidate_retarget_artifacts(
            spec_dir,
            shadow,
            plan_retarget_artifacts(spec_dir),
            ("apps/web",),
        )

    assert swapped is True
    assert (race_root / "targets.yml").read_bytes() == external_preimage[0]
    assert stat.S_IMODE((race_root / "targets.yml").stat().st_mode) == external_preimage[1]
    assert (displaced / "targets.yml").read_bytes() == old_content
    assert stat.S_IMODE((displaced / "targets.yml").stat().st_mode) == old_modes[race_root]
    assert (other_root / "targets.yml").read_bytes() == old_content
    assert stat.S_IMODE((other_root / "targets.yml").stat().st_mode) == old_modes[other_root]
    assert not list(tmp_path.rglob(".targets.yml.*.tmp"))


@pytest.mark.unit
@pytest.mark.parametrize("interrupt_after", ("first-publication", "rollback"))
@pytest.mark.parametrize("interrupt", (KeyboardInterrupt, SystemExit))
def test_target_publication_interrupt_marks_replacement_failed_with_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt_after: str,
    interrupt: type[BaseException],
) -> None:
    """Interrupts after publication begins are rolled back and durably reported."""
    from echelon.artifact_index import RetargetArtifactPlan, plan_retarget_artifacts
    from echelon.spec_lifecycle import SpecRun
    import echelon.spec_retarget as subject
    from harness.phase_checkpoints import PhaseCheckpoint

    spec_dir = tmp_path / "specs/001-demo"
    run_dir = tmp_path / "runs/squad-replacement"
    shadow = run_dir / "specs/001-demo"
    old_content = b"targets:\n- services/api\n"
    old_modes = {spec_dir: 0o640, shadow: 0o600}
    for root, mode in old_modes.items():
        (root / "contracts").mkdir(parents=True)
        (root / "contracts/owned.txt").write_text("owned\n", encoding="utf-8")
        target = root / "targets.yml"
        target.write_bytes(old_content)
        target.chmod(mode)
    replacement = SimpleNamespace(run=SimpleNamespace(run_dir=run_dir))
    baseline = SpecRun(
        tmp_path / "runs/squad-base",
        "squad-base",
        "squad-base",
        "001-demo",
        "001-demo",
        spec_dir,
        spec_dir,
    )
    preview = subject.RetargetPreview(
        tmp_path,
        "001-demo",
        baseline,
        spec_dir,
        ("services/api",),
        ("apps/web",),
        plan_retarget_artifacts(spec_dir),
        "retarget-op",
        "Build account search",
        "semi",
        False,
        (),
    )
    checkpoint = PhaseCheckpoint(
        "retarget-preflight-rev-1",
        "001-demo",
        "retarget",
        "phase0-constitution",
        "a" * 40,
        "a" * 40,
        "retarget-preflight",
        "squad-base",
        "2026-08-05T00:00:00+00:00",
    )
    monkeypatch.setattr(
        subject,
        "_persisted_memory_receipt",
        lambda _run: SimpleNamespace(to_dict=lambda: {"status": "pass"}),
    )
    monkeypatch.setattr(subject, "invalidate_retarget_graphs", lambda *_args: object())
    monkeypatch.setattr(subject, "write_checkpoint_coverage_context", lambda *_args: None)
    monkeypatch.setattr(subject, "mark_retarget_rebuilding", lambda *_args: None)
    failed: list[str] = []

    def record_failure(_run: Path, _spec: Path, code: str) -> None:
        failed.append(code)
        (run_dir / "interrupt-state.txt").write_text(
            f"failed\n{checkpoint.id}\n", encoding="utf-8"
        )

    monkeypatch.setattr(subject, "mark_retarget_failed", record_failure)
    real_replace = subject._atomic_target_contract_replace
    real_restore = subject._restore_target_contract_preimage
    publication_count = 0
    restoration_count = 0

    def interrupting_replace(*args: object, **kwargs: object) -> None:
        nonlocal publication_count
        real_replace(*args, **kwargs)
        if kwargs.get("label") == "publish":
            publication_count += 1
            if interrupt_after == "first-publication" and publication_count == 1:
                raise interrupt()
            if interrupt_after == "rollback" and publication_count == 1:
                raise subject.RetargetArtifactError("trigger rollback")

    def interrupting_restore(*args: object, **kwargs: object) -> None:
        nonlocal restoration_count
        real_restore(*args, **kwargs)
        restoration_count += 1
        if interrupt_after == "rollback" and restoration_count == 2:
            raise interrupt()

    monkeypatch.setattr(subject, "_atomic_target_contract_replace", interrupting_replace)
    monkeypatch.setattr(subject, "_restore_target_contract_preimage", interrupting_restore)

    with pytest.raises(subject.RetargetDestructiveError) as raised:
        subject._finish_retarget_invalidation(
            preview,
            SimpleNamespace(revision_id="rev-1"),
            checkpoint,
            replacement,
            starting_status="invalidating",
            reuse_persisted_memory=True,
        )

    expected_failure = (
        "retarget_artifact_invalidation_failed"
        if interrupt_after == "rollback"
        else "retarget_rebuild_blocked"
    )
    assert failed == [expected_failure]
    assert (run_dir / "interrupt-state.txt").read_text(encoding="utf-8") == (
        f"failed\n{checkpoint.id}\n"
    )
    assert f"echelon spec rewind checkpoint:{checkpoint.id} --confirm" in str(raised.value)
    for root, mode in old_modes.items():
        assert (root / "targets.yml").read_bytes() == old_content
        assert stat.S_IMODE((root / "targets.yml").stat().st_mode) == mode
    assert not list(tmp_path.rglob(".targets.yml.*.tmp"))


@pytest.mark.unit
def test_memory_exclusion_persists_the_squad_reader_gate(tmp_path: Path) -> None:
    from echelon.spec_retarget import persist_retarget_memory_exclusion

    run_dir = tmp_path / "runs/squad-replacement"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "retarget": {
                    "revision_id": "retarget-revision",
                    "status": "invalidating",
                }
            }
        ),
        encoding="utf-8",
    )
    receipt = SimpleNamespace(to_dict=lambda: {"status": "pass"})

    persist_retarget_memory_exclusion(run_dir, receipt)

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["retarget"]["memory_excluded"] is True
    assert state["retarget"]["memory_purge"] == {"status": "pass"}


@pytest.mark.unit
def test_failed_prepared_revision_advances_durably(tmp_path: Path) -> None:
    from echelon.spec_retarget import mark_retarget_failed
    from echelon.spec_retarget_history import (
        RetargetRecoveryProjection,
        append_prepared_revision,
        load_retarget_history,
    )

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
            phase="phase3-plan",
            spec_status="planned",
            completed_phases=("phase3-plan",),
            implementation_targets=("services/api",),
            ready_to_build=True,
        ),
    )
    run_dir = tmp_path / "runs/squad-replacement"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "retarget": {
                    "revision_id": revision.revision_id,
                    "status": "checkpointed",
                }
            }
        ),
        encoding="utf-8",
    )

    mark_retarget_failed(
        run_dir,
        spec_dir,
        "retarget_rebuild_blocked",
    )

    assert load_retarget_history(spec_dir).revisions[-1].status == "failed"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["retarget"]["status"] == "failed"

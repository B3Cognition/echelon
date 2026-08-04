from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from harness.verify_spec_run import complete_verify_spec_run, init_verify_spec_run
from harness.verify_spec_run import VerifySpecRunInitError


def _run_harness(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    return subprocess.run(
        [sys.executable, "-m", "harness", *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_init_verify_spec_run_uses_orchestration_current_pointer(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "sources" / "prosaic"
    spec_dir = workspace / "specs" / "001-prose-distribution-engine"
    active_run = workspace / "runs" / "spec-20260707-175124-167707"
    for path in (source, spec_dir, active_run):
        path.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (workspace / "runs" / ".current").write_text(
        "spec-20260707-175124-167707\n", encoding="utf-8"
    )

    result = init_verify_spec_run(
        project_root=source,
        spec_id="001-prose-distribution-engine",
        spec_dir=spec_dir,
    )

    assert result.verify_run_dir == (
        active_run / "verify-spec" / "001-prose-distribution-engine"
    )
    state = json.loads((result.verify_run_dir / "state.json").read_text())
    assert state["project_root"] == str(source.resolve())
    assert state["orchestration_root"] == str(workspace.resolve())
    assert state["spec_dir"] == str(spec_dir.resolve())
    assert state["verify_scope"] == "full"
    assert state["status"] == "in_progress"
    assert state["structural_evidence"] == "pending"


def test_init_verify_spec_run_rejects_path_like_current_pointer(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "sources" / "prosaic"
    spec_dir = workspace / "specs" / "001-demo"
    outside_run = workspace / "outside-run"
    for path in (source, spec_dir, outside_run):
        path.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (workspace / "runs").mkdir()
    (workspace / "runs" / ".current").write_text(
        "../outside-run\n", encoding="utf-8"
    )

    with pytest.raises(VerifySpecRunInitError, match="unsafe current run id"):
        init_verify_spec_run(
            project_root=source,
            spec_id="001-demo",
            spec_dir=spec_dir,
            timestamp="20260709-171000",
        )

    assert not (outside_run / "verify-spec").exists()


def test_init_verify_spec_run_cli_rejects_path_like_current_pointer_cleanly(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "sources" / "prosaic"
    spec_dir = workspace / "specs" / "001-demo"
    outside_run = workspace / "outside-run"
    for path in (source, spec_dir, outside_run):
        path.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (workspace / "runs").mkdir()
    (workspace / "runs" / ".current").write_text(
        "../outside-run\n", encoding="utf-8"
    )

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(source),
            "001-demo",
            str(spec_dir),
            "--timestamp",
            "20260709-171000",
        ]
    )

    assert completed.returncode == 2
    assert "unsafe current run id:" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (outside_run / "verify-spec").exists()


def test_init_verify_spec_run_rejects_missing_current_run_directory(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "sources" / "prosaic"
    spec_dir = workspace / "specs" / "001-demo"
    source.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (workspace / "runs").mkdir()
    (workspace / "runs" / ".current").write_text(
        "spec-20260709-missing\n", encoding="utf-8"
    )

    with pytest.raises(VerifySpecRunInitError, match="current run directory missing"):
        init_verify_spec_run(
            project_root=source,
            spec_id="001-demo",
            spec_dir=spec_dir,
            timestamp="20260709-172500",
        )

    assert not (workspace / "runs" / "verify-spec-001-demo-20260709-172500").exists()


def test_init_verify_spec_run_cli_rejects_missing_current_run_directory_cleanly(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "sources" / "prosaic"
    spec_dir = workspace / "specs" / "001-demo"
    source.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (workspace / "runs").mkdir()
    (workspace / "runs" / ".current").write_text(
        "spec-20260709-missing\n", encoding="utf-8"
    )

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(source),
            "001-demo",
            str(spec_dir),
            "--timestamp",
            "20260709-172500",
        ]
    )

    assert completed.returncode == 2
    assert "current run directory missing:" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (workspace / "runs" / "verify-spec-001-demo-20260709-172500").exists()


def test_init_verify_spec_run_rejects_empty_current_pointer(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "sources" / "prosaic"
    spec_dir = workspace / "specs" / "001-demo"
    source.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (workspace / "runs").mkdir()
    (workspace / "runs" / ".current").write_text("\n", encoding="utf-8")

    with pytest.raises(VerifySpecRunInitError, match="empty current run id"):
        init_verify_spec_run(
            project_root=source,
            spec_id="001-demo",
            spec_dir=spec_dir,
            timestamp="20260709-173000",
        )

    assert not (workspace / "runs" / "verify-spec-001-demo-20260709-173000").exists()


def test_init_verify_spec_run_cli_rejects_empty_current_pointer_cleanly(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "sources" / "prosaic"
    spec_dir = workspace / "specs" / "001-demo"
    source.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (workspace / "runs").mkdir()
    (workspace / "runs" / ".current").write_text("\n", encoding="utf-8")

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(source),
            "001-demo",
            str(spec_dir),
            "--timestamp",
            "20260709-173000",
        ]
    )

    assert completed.returncode == 2
    assert "empty current run id:" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (workspace / "runs" / "verify-spec-001-demo-20260709-173000").exists()


def test_init_verify_spec_run_rejects_symlinked_timestamped_verify_run(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    outside_run = tmp_path / "outside-verify-run"
    spec_dir.mkdir(parents=True)
    outside_run.mkdir()
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    runs_dir = project / "runs"
    runs_dir.mkdir()
    (runs_dir / "verify-spec-001-demo-20260709-173500").symlink_to(
        outside_run,
        target_is_directory=True,
    )

    with pytest.raises(VerifySpecRunInitError, match="unsafe verify run path"):
        init_verify_spec_run(
            project_root=project,
            spec_id="001-demo",
            spec_dir=spec_dir,
            timestamp="20260709-173500",
        )

    assert not (outside_run / "state.json").exists()


def test_init_verify_spec_run_cli_rejects_symlinked_timestamped_verify_run_cleanly(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    outside_run = tmp_path / "outside-verify-run"
    spec_dir.mkdir(parents=True)
    outside_run.mkdir()
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    runs_dir = project / "runs"
    runs_dir.mkdir()
    (runs_dir / "verify-spec-001-demo-20260709-173500").symlink_to(
        outside_run,
        target_is_directory=True,
    )

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(project),
            "001-demo",
            str(spec_dir),
            "--timestamp",
            "20260709-173500",
        ]
    )

    assert completed.returncode == 2
    assert "unsafe verify run path:" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (outside_run / "state.json").exists()


def test_init_verify_spec_run_rejects_symlinked_current_run_outside_runs(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "sources" / "prosaic"
    spec_dir = workspace / "specs" / "001-demo"
    outside_run = workspace / "outside-run"
    for path in (source, spec_dir, outside_run):
        path.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    runs_dir = workspace / "runs"
    runs_dir.mkdir()
    (runs_dir / ".current").write_text("active\n", encoding="utf-8")
    (runs_dir / "active").symlink_to(outside_run, target_is_directory=True)

    with pytest.raises(VerifySpecRunInitError, match="unsafe current run path"):
        init_verify_spec_run(
            project_root=source,
            spec_id="001-demo",
            spec_dir=spec_dir,
            timestamp="20260709-172000",
        )

    assert not (outside_run / "verify-spec").exists()


def test_init_verify_spec_run_cli_rejects_symlinked_current_run_cleanly(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "sources" / "prosaic"
    spec_dir = workspace / "specs" / "001-demo"
    outside_run = workspace / "outside-run"
    for path in (source, spec_dir, outside_run):
        path.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    runs_dir = workspace / "runs"
    runs_dir.mkdir()
    (runs_dir / ".current").write_text("active\n", encoding="utf-8")
    (runs_dir / "active").symlink_to(outside_run, target_is_directory=True)

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(source),
            "001-demo",
            str(spec_dir),
            "--timestamp",
            "20260709-172000",
        ]
    )

    assert completed.returncode == 2
    assert "unsafe current run path:" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (outside_run / "verify-spec").exists()


def test_init_verify_spec_run_creates_timestamped_scoped_run_without_current(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    result = init_verify_spec_run(
        project_root=project,
        spec_id="001-demo",
        spec_dir=spec_dir,
        verify_scope="scoped",
        scoped_ids=["FR-002", "FR-001", "FR-002"],
        base_full_verify_commit="abc123",
        strict=True,
        reconcile=True,
        dry_run=True,
        timestamp="20260709-120000",
    )

    assert result.verify_run_dir == (
        project / "runs" / "verify-spec-001-demo-20260709-120000"
    )
    state = json.loads((result.verify_run_dir / "state.json").read_text())
    assert state["verify_run_dir"] == str(result.verify_run_dir)
    assert state["verify_scope"] == "scoped"
    assert state["scoped_ids"] == ["FR-001", "FR-002"]
    assert state["base_full_verify_commit"] == "abc123"
    assert state["strict"] is True
    assert state["reconcile"] is True
    assert state["dry_run"] is True


def test_init_verify_spec_run_cli_writes_state_and_prints_json(tmp_path: Path) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(project),
            "001-demo",
            str(spec_dir),
            "--scope",
            "scoped",
            "--scoped-ids",
            "FR-002,FR-001,FR-002",
            "--base-full-verify-commit",
            "abc123",
            "--strict",
            "--reconcile",
            "--dry-run",
            "--timestamp",
            "20260709-130000",
        ]
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    verify_run_dir = project / "runs" / "verify-spec-001-demo-20260709-130000"
    assert payload["verify_run_dir"] == str(verify_run_dir.resolve())
    state = json.loads((verify_run_dir / "state.json").read_text())
    assert state["verify_scope"] == "scoped"
    assert state["scoped_ids"] == ["FR-001", "FR-002"]
    assert state["base_full_verify_commit"] == "abc123"


def test_init_verify_spec_run_rejects_missing_spec_dir_before_writing_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    spec_dir = project / "specs" / "001-demo"

    with pytest.raises(VerifySpecRunInitError, match="spec_dir does not exist"):
        init_verify_spec_run(
            project_root=project,
            spec_id="001-demo",
            spec_dir=spec_dir,
            timestamp="20260709-140000",
        )

    assert not (project / "runs").exists()


def test_init_verify_spec_run_cli_rejects_missing_spec_dir_without_traceback(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    spec_dir = project / "specs" / "001-demo"

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(project),
            "001-demo",
            str(spec_dir),
            "--timestamp",
            "20260709-140000",
        ]
    )

    assert completed.returncode == 2
    assert "spec_dir does not exist:" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (project / "runs").exists()


def test_init_verify_spec_run_rejects_spec_dir_without_spec_md_before_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    with pytest.raises(VerifySpecRunInitError, match="spec.md missing"):
        init_verify_spec_run(
            project_root=project,
            spec_id="001-demo",
            spec_dir=spec_dir,
            timestamp="20260709-143000",
        )

    assert not (project / "runs").exists()


def test_init_verify_spec_run_cli_rejects_spec_dir_without_spec_md_cleanly(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(project),
            "001-demo",
            str(spec_dir),
            "--timestamp",
            "20260709-143000",
        ]
    )

    assert completed.returncode == 2
    assert "spec.md missing in spec_dir:" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (project / "runs").exists()


def test_init_verify_spec_run_rejects_unknown_scope_before_writing_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    with pytest.raises(VerifySpecRunInitError, match="unsupported verify scope"):
        init_verify_spec_run(
            project_root=project,
            spec_id="001-demo",
            spec_dir=spec_dir,
            verify_scope="bananas",
            timestamp="20260709-150000",
        )

    assert not (project / "runs").exists()


def test_init_verify_spec_run_cli_rejects_unknown_scope_without_traceback(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(project),
            "001-demo",
            str(spec_dir),
            "--scope",
            "bananas",
            "--timestamp",
            "20260709-150000",
        ]
    )

    assert completed.returncode == 2
    assert "unsupported verify scope:" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (project / "runs").exists()


def test_init_verify_spec_run_rejects_scoped_without_ids_before_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    with pytest.raises(VerifySpecRunInitError, match="scoped verify requires"):
        init_verify_spec_run(
            project_root=project,
            spec_id="001-demo",
            spec_dir=spec_dir,
            verify_scope="scoped",
            scoped_ids=[],
            timestamp="20260709-153000",
        )

    assert not (project / "runs").exists()


def test_init_verify_spec_run_cli_rejects_scoped_without_ids_cleanly(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(project),
            "001-demo",
            str(spec_dir),
            "--scope",
            "scoped",
            "--timestamp",
            "20260709-153000",
        ]
    )

    assert completed.returncode == 2
    assert "scoped verify requires at least one scoped id" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (project / "runs").exists()


def test_init_verify_spec_run_rejects_scoped_ids_for_full_scope_before_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    with pytest.raises(VerifySpecRunInitError, match="scoped ids require"):
        init_verify_spec_run(
            project_root=project,
            spec_id="001-demo",
            spec_dir=spec_dir,
            verify_scope="full",
            scoped_ids=["FR-001"],
            timestamp="20260709-160000",
        )

    assert not (project / "runs").exists()


def test_init_verify_spec_run_cli_rejects_scoped_ids_for_full_scope_cleanly(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(project),
            "001-demo",
            str(spec_dir),
            "--scope",
            "full",
            "--scoped-ids",
            "FR-001",
            "--timestamp",
            "20260709-160000",
        ]
    )

    assert completed.returncode == 2
    assert "scoped ids require --scope scoped" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (project / "runs").exists()


def test_init_verify_spec_run_rejects_base_commit_for_full_scope_before_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    with pytest.raises(VerifySpecRunInitError, match="base full verify commit"):
        init_verify_spec_run(
            project_root=project,
            spec_id="001-demo",
            spec_dir=spec_dir,
            verify_scope="full",
            base_full_verify_commit="abc123",
            timestamp="20260709-163000",
        )

    assert not (project / "runs").exists()


def test_init_verify_spec_run_cli_rejects_base_commit_for_full_scope_cleanly(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(project),
            "001-demo",
            str(spec_dir),
            "--scope",
            "full",
            "--base-full-verify-commit",
            "abc123",
            "--timestamp",
            "20260709-163000",
        ]
    )

    assert completed.returncode == 2
    assert "base full verify commit requires --scope scoped" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (project / "runs").exists()


def test_init_verify_spec_run_rejects_path_like_timestamp_before_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    with pytest.raises(VerifySpecRunInitError, match="unsafe timestamp"):
        init_verify_spec_run(
            project_root=project,
            spec_id="001-demo",
            spec_dir=spec_dir,
            timestamp="../escape",
        )

    assert not (project / "runs").exists()
    assert not (tmp_path / "escape").exists()


def test_init_verify_spec_run_cli_rejects_path_like_timestamp_cleanly(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(project),
            "001-demo",
            str(spec_dir),
            "--timestamp",
            "../escape",
        ]
    )

    assert completed.returncode == 2
    assert "unsafe timestamp:" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (project / "runs").exists()
    assert not (tmp_path / "escape").exists()


def test_init_verify_spec_run_rejects_path_like_spec_id_before_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    with pytest.raises(VerifySpecRunInitError, match="unsafe spec_id"):
        init_verify_spec_run(
            project_root=project,
            spec_id="../escape",
            spec_dir=spec_dir,
            timestamp="20260709-170000",
        )

    assert not (project / "runs").exists()
    assert not (tmp_path / "escape-20260709-170000").exists()


def test_init_verify_spec_run_cli_rejects_path_like_spec_id_cleanly(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    completed = _run_harness(
        [
            "init-verify-spec-run",
            str(project),
            "../escape",
            str(spec_dir),
            "--timestamp",
            "20260709-170000",
        ]
    )

    assert completed.returncode == 2
    assert "unsafe spec_id:" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (project / "runs").exists()
    assert not (tmp_path / "escape-20260709-170000").exists()


def test_complete_verify_spec_run_owns_final_completion_timestamp(tmp_path: Path) -> None:
    run = tmp_path / "runs/verify-spec-001"
    run.mkdir(parents=True)
    state_path = run / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "spec_id": "001-demo",
                "status": "in_progress",
                "topology_evidence": "ready",
                "fulfillment_artifacts": "valid",
                "reconcile": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    complete_verify_spec_run(
        run,
        completed_at="2026-08-04T17:00:00+00:00",
    )

    state = json.loads(state_path.read_text())
    assert state["status"] == "complete"
    assert state["completed_at"] == "2026-08-04T17:00:00+00:00"


@pytest.mark.parametrize(
    "invalid_update",
    (
        {"topology_evidence": "pending"},
        {"fulfillment_artifacts": "invalid"},
        {"reconcile": True, "progress_reconciliation": "pending"},
    ),
)
def test_complete_verify_spec_run_revalidates_forged_complete_state_without_mutation(
    tmp_path: Path,
    invalid_update: dict[str, object],
) -> None:
    run = tmp_path / "runs/verify-spec-001"
    run.mkdir(parents=True)
    state_path = run / "state.json"
    state = {
        "spec_id": "001-demo",
        "status": "complete",
        "completed_at": "2026-08-04T17:00:00+00:00",
        "topology_evidence": "ready",
        "fulfillment_artifacts": "valid",
        "reconcile": False,
    }
    state.update(invalid_update)
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    before = state_path.read_bytes()

    with pytest.raises(VerifySpecRunInitError):
        complete_verify_spec_run(run)

    assert state_path.read_bytes() == before


def test_complete_verify_spec_run_accepts_valid_complete_state_idempotently(
    tmp_path: Path,
) -> None:
    run = tmp_path / "runs/verify-spec-001"
    run.mkdir(parents=True)
    state_path = run / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "spec_id": "001-demo",
                "status": "complete",
                "completed_at": "2026-08-04T17:00:00+00:00",
                "topology_evidence": "ready",
                "fulfillment_artifacts": "valid",
                "reconcile": False,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    before = state_path.read_bytes()

    assert complete_verify_spec_run(run) == state_path
    assert state_path.read_bytes() == before


@pytest.mark.parametrize(
    "run_relative",
    (
        Path("runs/verify-spec-001"),
        Path("runs/spec-20260804/verify-spec/001-demo"),
    ),
)
def test_complete_verify_spec_run_honors_trusted_workspace_alias(
    tmp_path: Path,
    run_relative: Path,
) -> None:
    workspace = tmp_path / "workspace"
    run = workspace / run_relative
    run.mkdir(parents=True)
    state_path = run / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "spec_id": "001-demo",
                "status": "in_progress",
                "topology_evidence": "ready",
                "fulfillment_artifacts": "valid",
                "reconcile": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    workspace_alias = tmp_path / "workspace-alias"
    workspace_alias.symlink_to(workspace, target_is_directory=True)

    result = complete_verify_spec_run(
        workspace_alias / run_relative,
        completed_at="2026-08-04T18:00:00+00:00",
    )

    assert result == workspace_alias / run_relative / "state.json"
    assert json.loads(state_path.read_text())["status"] == "complete"


def test_complete_verify_spec_run_rejects_path_without_runs_ancestry(
    tmp_path: Path,
) -> None:
    run = tmp_path / "verify-spec-001"
    run.mkdir()
    state_path = run / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "spec_id": "001-demo",
                "status": "in_progress",
                "topology_evidence": "ready",
                "fulfillment_artifacts": "valid",
                "reconcile": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = state_path.read_bytes()

    with pytest.raises(VerifySpecRunInitError, match="runs ancestry"):
        complete_verify_spec_run(run)

    assert state_path.read_bytes() == before


def test_complete_verify_spec_run_rejects_link_below_workspace_without_mutation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    runs = workspace / "runs"
    runs.mkdir(parents=True)
    outside_run = tmp_path / "outside-run"
    run = outside_run / "verify-spec/001-demo"
    run.mkdir(parents=True)
    state_path = run / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "spec_id": "001-demo",
                "status": "in_progress",
                "topology_evidence": "ready",
                "fulfillment_artifacts": "valid",
                "reconcile": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = state_path.read_bytes()
    (runs / "active").symlink_to(outside_run, target_is_directory=True)

    with pytest.raises(VerifySpecRunInitError, match="unsafe|directory"):
        complete_verify_spec_run(runs / "active/verify-spec/001-demo")

    assert state_path.read_bytes() == before

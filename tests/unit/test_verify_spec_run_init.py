from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from harness.verify_spec_run import init_verify_spec_run
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

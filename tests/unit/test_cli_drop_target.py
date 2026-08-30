"""Regression tests for removing an unused target from an active spec run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.spec_frontmatter import read_targets, write_targets


def _write_spec(spec_dir: Path) -> None:
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Video clips\n", encoding="utf-8")
    write_targets(spec_dir, ["sources/web", "sources/api"])
    for name in ("tasks.md", "critical-path.md", "risk-matrix.md", "dependencies.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")


def test_drop_target_reopens_active_run_at_planning_and_invalidates_task_outputs(
    tmp_path: Path,
) -> None:
    from echelon.cli import _cmd_drop_target

    run_dir = tmp_path / "runs" / "spec-run"
    active_spec = run_dir / "specs" / "002-video"
    published_spec = tmp_path / "specs" / "002-video"
    _write_spec(active_spec)
    _write_spec(published_spec)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "spec_id": "002-video",
                "spec_dir": "runs/spec-run/specs/002-video",
                "published_spec_dir": "specs/002-video",
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "unused declared target",
                "implementation_targets": ["sources/web", "sources/api"],
                "completed_phases": ["phase3-how", "phase3-sentinel"],
            }
        ),
        encoding="utf-8",
    )

    _cmd_drop_target(
        ["002-video", "sources/api", "--confirm"],
        project_root=tmp_path,
    )

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["implementation_targets"] == ["sources/web"]
    assert state["phase"] == "phase3-plan"
    assert state["status"] == "running"
    assert state["blocked_reason"] is None
    assert read_targets(active_spec) == ["sources/web"]
    assert read_targets(published_spec) == ["sources/web"]
    for spec_dir in (active_spec, published_spec):
        for name in ("tasks.md", "critical-path.md", "risk-matrix.md", "dependencies.md"):
            assert not (spec_dir / name).exists()


def test_drop_target_refuses_while_same_spec_mutation_is_locked(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_drop_target
    from echelon.spec_lifecycle import SpecMutationLock

    run_dir = tmp_path / "runs" / "spec-run"
    active_spec = run_dir / "specs" / "002-video"
    published_spec = tmp_path / "specs" / "002-video"
    _write_spec(active_spec)
    _write_spec(published_spec)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "spec_id": "002-video",
                "spec_dir": "runs/spec-run/specs/002-video",
                "published_spec_dir": "specs/002-video",
                "status": "blocked",
                "implementation_targets": ["sources/web", "sources/api"],
            }
        ),
        encoding="utf-8",
    )

    with SpecMutationLock.acquire(tmp_path, "002-video", "retarget-held"):
        with pytest.raises(SystemExit) as exc:
            _cmd_drop_target(
                ["002-video", "sources/api", "--confirm"],
                project_root=tmp_path,
            )

    assert exc.value.code == 1
    assert "retarget-held" in capsys.readouterr().err
    assert read_targets(active_spec) == ["sources/web", "sources/api"]

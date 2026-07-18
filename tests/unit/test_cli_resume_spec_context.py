"""Regression tests for squad resume preserving an existing spec branch."""
from __future__ import annotations

import subprocess


def test_resume_preserves_current_spec_branch_context(tmp_path):
    from echelon.cli import _preserve_active_spec_context

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", "-b", "072-pr-pipeline-fix"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    spec_dir = tmp_path / "specs" / "072-pr-pipeline-fix"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    state = {"phase": "phase1-what"}

    _preserve_active_spec_context(tmp_path, state)

    assert state["spec_id"] == "072-pr-pipeline-fix"
    assert state["spec_dir"] == "specs/072-pr-pipeline-fix"
    assert state["feature_branch"] == "072-pr-pipeline-fix"
    assert state["cartographer_resume_existing_spec"] is True


def test_resume_does_not_mark_non_spec_branch(tmp_path):
    from echelon.cli import _preserve_active_spec_context

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    state = {"phase": "phase1-what"}

    _preserve_active_spec_context(tmp_path, state)

    assert "cartographer_resume_existing_spec" not in state


def test_resume_does_not_treat_planned_spec_dir_as_existing_spec(tmp_path):
    """A Phase A bootstrap path is not resumable until it has spec.md."""
    from echelon.cli import _preserve_active_spec_context

    planned = tmp_path / "runs" / "run-004" / "specs" / "004-transform-selector"
    planned.mkdir(parents=True)
    state = {
        "phase": "phase1-what",
        "spec_dir": str(planned.relative_to(tmp_path)),
    }

    _preserve_active_spec_context(tmp_path, state)

    assert "cartographer_resume_existing_spec" not in state

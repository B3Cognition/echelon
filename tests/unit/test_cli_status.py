"""Tests for echelon status next-step selection."""

from __future__ import annotations

import json
from pathlib import Path

from echelon.cli import _find_converged_harness_build, _print_next_steps


def _write_build_state(
    project: Path,
    build_id: str,
    *,
    status: str,
    spec_id: str = "001-demo",
    termination_reason: str | None = None,
    extra: dict | None = None,
) -> None:
    state_dir = project / "runs" / build_id / "state"
    state_dir.mkdir(parents=True)
    payload = {
        "spec_id": spec_id,
        "status": status,
        "termination_reason": termination_reason,
        "pr_url": None,
    }
    if extra:
        payload.update(extra)
    (state_dir / "default.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_newer_blocked_harness_build_masks_older_converged_build(
    tmp_path: Path,
) -> None:
    _write_build_state(tmp_path, "build-20260531-222514-882423", status="converged")
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="blocked",
        termination_reason="build_incomplete",
    )

    assert _find_converged_harness_build(tmp_path) is None


def test_newer_running_harness_build_masks_older_converged_build(
    tmp_path: Path,
) -> None:
    _write_build_state(tmp_path, "build-20260531-222514-882423", status="converged")
    _write_build_state(tmp_path, "build-20260606-144357-753380", status="running")

    assert _find_converged_harness_build(tmp_path) is None


def test_latest_converged_harness_build_is_ready_to_land(tmp_path: Path) -> None:
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="converged",
        spec_id="001-demo",
    )

    assert _find_converged_harness_build(tmp_path) == ("001-demo", None)


def test_next_steps_report_latest_blocked_harness_build_before_phase_a_blockers(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="blocked",
        spec_id="001-demo",
        termination_reason="build_incomplete",
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "HARNESS BUILD BLOCKED" in captured.out
    assert "build_incomplete" in captured.out
    assert "echelon harness resume 001-demo" in captured.out
    assert "constitution.md absent" not in captured.out


def test_next_steps_warn_when_dirty_checkout_blocks_harness_recovery(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="blocked",
        spec_id="001-demo",
        termination_reason="build_incomplete",
    )
    (tmp_path / "tracked.txt").write_text("before\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )
    (tmp_path / "tracked.txt").write_text("after\n", encoding="utf-8")

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "tracked checkout changes block harness recovery" in captured.out
    assert "commit or stash tracked changes, then echelon harness resume 001-demo" in captured.out


def test_next_steps_report_salvage_commit_for_blocked_harness_build(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260606-221522-964255",
        status="blocked",
        spec_id="001-demo",
        termination_reason="build_incomplete",
        extra={
            "salvage_commit": "abcdef1234567890abcdef1234567890abcdef12",
            "salvage_branch": "harness/001-demo/default/iter-0",
            "salvage_verified": "not_run",
        },
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "salvage commit" in captured.out
    assert "abcdef123456" in captured.out
    assert "harness/001-demo/default/iter-0" in captured.out
    assert "not_run" in captured.out


def test_next_steps_labels_running_harness_build_as_in_progress(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260607-170743-443653",
        status="running",
        spec_id="001-demo",
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "HARNESS BUILD IN PROGRESS" in captured.out
    assert "HARNESS BUILD BLOCKED" not in captured.out
    assert "echelon status" in captured.out


def test_next_steps_for_docker_unavailable_tells_user_to_start_docker(
    tmp_path: Path,
    capsys,
) -> None:
    _write_build_state(
        tmp_path,
        "build-20260607-170743-443653",
        status="blocked",
        spec_id="001-demo",
        termination_reason="docker_unavailable",
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "docker_unavailable" in captured.out
    assert "start Docker Desktop" in captured.out
    assert "echelon harness run 001-demo" in captured.out
    assert "--reset" not in captured.out


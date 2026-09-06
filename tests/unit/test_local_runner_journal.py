"""Tests for isolated, recoverable local-run state."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from harness.local_runner_journal import (
    LocalRunRecoveryRequired,
    LocalRunSideEffectError,
    LocalRunJournal,
    WorkspaceLocalRunLocked,
    acquire_workspace_local_run_lock,
    assert_git_baseline_unchanged,
    assert_no_recovery_journal,
    build_host_execution_environment,
    write_local_run_journal,
)


def _lock_owner(workspace: Path) -> subprocess.Popen[str]:
    source_root = Path(__file__).parents[2] / "src"
    code = """
from pathlib import Path
import sys
import time
from harness.local_runner_journal import acquire_workspace_local_run_lock
with acquire_workspace_local_run_lock(Path(sys.argv[1])):
    print('locked', flush=True)
    time.sleep(60)
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source_root)
    return subprocess.Popen(
        [sys.executable, "-c", code, str(workspace)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


@pytest.mark.unit
def test_lock_is_released_when_owner_process_exits(tmp_path: Path) -> None:
    owner = _lock_owner(tmp_path)
    assert owner.stdout is not None
    assert owner.stdout.readline().strip() == "locked"
    with pytest.raises(WorkspaceLocalRunLocked):
        with acquire_workspace_local_run_lock(tmp_path, blocking=False):
            pass
    owner.kill()
    owner.wait(timeout=5)

    with acquire_workspace_local_run_lock(tmp_path):
        assert True


@pytest.mark.unit
def test_host_environment_redirects_all_runner_owned_state(tmp_path: Path) -> None:
    environment = build_host_execution_environment(
        tmp_path / "run-1",
        {"DATABASE_URL": "postgresql://generated", "TEST_DATABASE_URL": "postgresql://test"},
        parent_environment={
            "PATH": "/usr/bin:/bin",
            "LANG": "en_US.UTF-8",
            "AWS_SECRET_ACCESS_KEY": "must-not-leak",
            "HOME": "/Users/tester",
        },
    )

    assert environment.values["HOME"].startswith(str(tmp_path / "run-1"))
    assert environment.values["PLAYWRIGHT_BROWSERS_PATH"].startswith(
        str(tmp_path / "run-1")
    )
    assert environment.values["DATABASE_URL"] == "postgresql://generated"
    assert environment.values["GIT_CONFIG_NOSYSTEM"] == "1"
    assert "AWS_SECRET_ACCESS_KEY" not in environment.values


@pytest.mark.unit
def test_non_terminal_journal_requires_explicit_cleanup(tmp_path: Path) -> None:
    journal = LocalRunJournal(
        local_run_id="local-1",
        status="running",
        target_git_baseline="",
        workspace_git_baseline="",
    )
    journal_path = write_local_run_journal(tmp_path, journal)

    with pytest.raises(LocalRunRecoveryRequired, match=journal_path.name):
        assert_no_recovery_journal(tmp_path)


@pytest.mark.unit
def test_baseline_check_accepts_preexisting_dirty_state_but_rejects_new_change(
    tmp_path: Path,
) -> None:
    baseline = " M existing.txt\n"
    assert_git_baseline_unchanged(tmp_path, baseline, baseline)
    with pytest.raises(LocalRunSideEffectError):
        assert_git_baseline_unchanged(
            tmp_path, baseline, baseline + "?? generated.txt\n"
        )

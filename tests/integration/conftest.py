"""Integration test conftest — Docker daemon check, bare repo fixture, tmpdir.

Provides:
- Docker availability skip logic
- Bare git repo fixture for GitOps mirror/worktree tests
- Temporary directory fixtures
"""

from __future__ import annotations

import os
import subprocess
import tempfile

import pytest


def _docker_available() -> bool:
    """Check if Docker daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# Markers
skip_no_docker = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not available",
)


@pytest.fixture
def bare_repo(tmp_path):
    """Create a bare git repository with an initial commit.

    Returns:
        Path to the bare repo directory.
    """
    # Create a temp working repo, make initial commit, then clone as bare
    work_dir = tmp_path / "work-repo"
    work_dir.mkdir()

    subprocess.run(
        ["git", "init", str(work_dir)],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(work_dir), "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(work_dir), "config", "user.name", "Test"],
        capture_output=True, check=True,
    )

    # Create initial commit
    readme = work_dir / "README.md"
    readme.write_text("# Test repo\n")
    subprocess.run(
        ["git", "-C", str(work_dir), "add", "."],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(work_dir), "commit", "-m", "Initial commit"],
        capture_output=True, check=True,
    )

    # Ensure default branch is 'main'
    subprocess.run(
        ["git", "-C", str(work_dir), "branch", "-M", "main"],
        capture_output=True, check=True,
    )

    # Clone as bare
    bare_dir = tmp_path / "bare-repo.git"
    subprocess.run(
        ["git", "clone", "--bare", str(work_dir), str(bare_dir)],
        capture_output=True, check=True,
    )

    # Set HEAD to main
    subprocess.run(
        ["git", "-C", str(bare_dir), "symbolic-ref", "HEAD", "refs/heads/main"],
        capture_output=True, check=True,
    )

    return bare_dir


@pytest.fixture
def harness_config(tmp_path, bare_repo):
    """Create a minimal HarnessConfig for testing."""
    from harness.config import HarnessConfig

    return HarnessConfig(
        target_repo=str(bare_repo),
        target_default_branch="main",
        provider="docker",
        pr_host="none",
    )

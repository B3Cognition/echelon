"""Unit tests for harness/init.py — visual_tests auto-detection."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

from harness.image_resolver import ResolvedImage


def test_init_sets_visual_tests_enabled_when_playwright_detected(tmp_path):
    """init_harness writes visual_tests.enabled=true when @playwright/test found."""
    from harness.init import init_harness

    # Create a minimal git repo so git ls-remote works locally
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t.com",
        },
    )

    with (
        patch("harness.init._check_docker", return_value=True),
        patch("harness.init._check_os", return_value="linux"),
        patch("harness.init.GitOpsManager") as mock_gitops_cls,
        patch("harness.init.fingerprint_repo") as mock_fp,
        patch("harness.init.resolve_image") as mock_resolve,
        patch("harness.init.detect_playwright", return_value=True),
    ):
        mock_gitops = MagicMock()
        mock_gitops.get_default_branch.return_value = "main"
        mock_gitops.create_worktree.return_value = str(tmp_path)
        mock_gitops.clone_mirror.return_value = str(tmp_path / ".git")
        mock_gitops_cls.return_value = mock_gitops

        fp = MagicMock()
        fp.language = "typescript"
        fp.has_playwright = True
        mock_fp.return_value = fp

        mock_resolve.return_value = ResolvedImage(
            image="mcr.microsoft.com/playwright:v1.42.0-jammy",
            source="playwright",
        )

        config = init_harness(str(tmp_path), base_dir=str(tmp_path))

    assert config.visual_tests.enabled is True


def test_init_does_not_enable_visual_tests_when_playwright_absent(tmp_path):
    """init_harness writes visual_tests.enabled=false when no @playwright/test."""
    from harness.init import init_harness

    # Create a minimal git repo so git ls-remote works locally
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t.com",
        },
    )

    with (
        patch("harness.init._check_docker", return_value=True),
        patch("harness.init._check_os", return_value="linux"),
        patch("harness.init.GitOpsManager") as mock_gitops_cls,
        patch("harness.init.fingerprint_repo") as mock_fp,
        patch("harness.init.resolve_image") as mock_resolve,
        patch("harness.init.detect_playwright", return_value=False),
    ):
        mock_gitops = MagicMock()
        mock_gitops.get_default_branch.return_value = "main"
        mock_gitops.create_worktree.return_value = str(tmp_path)
        mock_gitops.clone_mirror.return_value = str(tmp_path / ".git")
        mock_gitops_cls.return_value = mock_gitops

        fp = MagicMock()
        fp.language = "typescript"
        fp.has_playwright = False
        mock_fp.return_value = fp

        mock_resolve.return_value = ResolvedImage(
            image="node:20",
            source="devcontainer",
        )

        config = init_harness(str(tmp_path), base_dir=str(tmp_path))

    assert config.visual_tests.enabled is False

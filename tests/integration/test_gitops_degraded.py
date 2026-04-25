"""Integration tests for GitOps degraded mode.

Tests that git operations work when gh/glab are absent.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from harness.config import HarnessConfig
from harness.gitops import GitOpsManager


class TestDegradedMode:
    """Tests for degraded mode (no gh/glab)."""

    def test_no_gh_glab_warns_and_continues(self, tmp_path, bare_repo, caplog):
        """Missing gh/glab logs warning, git operations still work."""
        config = HarnessConfig(
            target_repo=str(bare_repo),
            target_default_branch="main",
            provider="docker",
            pr_host="github",  # Expect gh, but mock it away
        )

        with patch("harness.gitops._check_tool_available", side_effect=lambda t: t == "git"):
            with caplog.at_level(logging.WARNING):
                mgr = GitOpsManager(config, base_dir=str(tmp_path))

        # Warning logged about missing tools
        assert "gh" in caplog.text.lower() or "glab" in caplog.text.lower()

        # Git operations still work
        mgr.clone_mirror(str(bare_repo))
        assert mgr.mirror_path.exists()

        # PR operations return empty / False
        assert mgr.create_draft_pr("branch", "spec", "strat") == ""
        assert mgr.merge_pr("https://example.com/pr/1") is False

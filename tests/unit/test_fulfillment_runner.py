"""Tests for fulfillment verification prompt orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from harness.fulfillment_runner import FulfillmentRunner


@pytest.mark.unit
class TestFulfillmentRunner:
    def test_refresh_builds_verify_spec_prompt_and_runs_provider(self, tmp_path):
        skill_dir = tmp_path / ".claude" / "skills" / "speckit-echelon-verify-spec"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify $ARGUMENTS\n",
            encoding="utf-8",
        )
        provider = MagicMock()
        provider.cli = "claude"
        provider.exec_prompt.return_value = 0

        result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result == 0
        provider.exec_prompt.assert_called_once()
        worktree_path, prompt = provider.exec_prompt.call_args.args
        assert worktree_path == str(tmp_path)
        assert "You are COMMANDER" in prompt
        assert "verify spec-001" in prompt

    def test_refresh_returns_127_when_verify_spec_skill_missing(self, tmp_path):
        provider = MagicMock()
        provider.cli = "claude"

        result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result == 127
        provider.exec_prompt.assert_not_called()

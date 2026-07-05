"""Tests for ReviewLoopController prompt invocation contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.config import HarnessConfig, LlmConfig, ReviewLoopConfig
from harness.llm_tool_policy import LlmToolPolicy
from harness.review_loop import ReviewComment, ReviewLoopController


def _config(cli: str = "claude", tool_policy: LlmToolPolicy | None = None) -> HarnessConfig:
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        pr_host="github",
        llm=LlmConfig(cli=cli, tool_policy=tool_policy or LlmToolPolicy()),
        review_loop=ReviewLoopConfig(enabled=True),
    )


@pytest.mark.unit
class TestReviewLoopInvocation:
    def test_review_loop_invokes_ai_cli_provider_facade(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        calls = []

        class FakeProvider:
            def __init__(self, config):
                self.config = config

            def run_prompt_result(self, worktree_path, prompt, extra_env=None, timeout_ms=None):
                calls.append((worktree_path, prompt, extra_env, timeout_ms))
                return CliRunResult(exit_code=0, stdout="queued", stderr="")

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", FakeProvider)
        controller = ReviewLoopController(
            gitops=MagicMock(),
            config=_config(cli="codex"),
            spec_id="005",
            strategy_id="default",
            base_dir=str(tmp_path),
            build_id="build-1",
        )

        controller._invoke_review_skill("https://github.com/org/repo/pull/1", [])

        assert calls
        assert calls[0][0] == str(tmp_path)
        assert "005 pr_url=https://github.com/org/repo/pull/1" in calls[0][1]
        assert "HARNESS_BUILD_STATUS_FILE" in calls[0][2]

    def test_review_skill_prompt_receives_deterministic_spec_and_worktree_paths(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        skill_dir = tmp_path / ".claude" / "skills" / "speckit-echelon-review"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text(
            "---\nname: echelon.review\n---\nreview $ARGUMENTS\n",
            encoding="utf-8",
        )
        spec_dir = tmp_path / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)
        worktree = tmp_path / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)

        controller = ReviewLoopController(
            gitops=MagicMock(),
            config=_config(),
            spec_id="005",
            strategy_id="default",
            base_dir=str(tmp_path),
            build_id="build-1",
        )

        calls = []

        class FakeProvider:
            def __init__(self, config):
                self.config = config

            def run_prompt_result(self, worktree_path, prompt, extra_env=None, timeout_ms=None):
                calls.append((worktree_path, prompt, extra_env, timeout_ms))
                return CliRunResult(exit_code=0, stdout="queued", stderr="")

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", FakeProvider)
        controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1",
            [
                ReviewComment(
                    comment_id="c1",
                    path="src/app.py",
                    line=10,
                    body="must fix",
                    reviewer="reviewer",
                    created_at=datetime.now(tz=timezone.utc),
                    is_inline=True,
                )
            ],
            worktree_path=str(worktree),
        )

        prompt = calls[0][1]
        assert f"review 005 pr_url=https://github.com/org/repo/pull/1 spec_dir={spec_dir}" in prompt
        assert f"worktree={worktree}" in prompt

    def test_review_loop_passes_codex_config_to_provider(self, monkeypatch, tmp_path: Path) -> None:
        configs = []
        policy = LlmToolPolicy(
            allow_unsafe_host_execution=True,
            approval_reason="Operator approved disposable worktree after sandbox review.",
        )

        class FakeProvider:
            def __init__(self, config):
                configs.append(config)

            def run_prompt_result(self, worktree_path, prompt, extra_env=None, timeout_ms=None):
                return CliRunResult(exit_code=0, stdout="queued", stderr="")

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", FakeProvider)
        controller = ReviewLoopController(
            gitops=MagicMock(),
            config=_config(cli="codex", tool_policy=policy),
            spec_id="005",
            strategy_id="default",
            base_dir=str(tmp_path),
            build_id="build-1",
        )
        controller._invoke_review_skill("https://github.com/org/repo/pull/1", [])

        assert configs
        assert configs[0].llm.cli == "codex"
        assert configs[0].llm.tool_policy is policy

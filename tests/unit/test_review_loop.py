"""Tests for ReviewLoopController prompt invocation contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.config import HarnessConfig, LlmConfig, ReviewLoopConfig
from harness.review_loop import ReviewComment, ReviewLoopController


def _config() -> HarnessConfig:
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        pr_host="github",
        llm=LlmConfig(cli="claude"),
        review_loop=ReviewLoopConfig(enabled=True),
    )


@pytest.mark.unit
class TestReviewLoopInvocation:
    def test_review_skill_prompt_receives_deterministic_spec_and_worktree_paths(
        self, tmp_path: Path
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

        completed = MagicMock()
        completed.returncode = 0

        with patch("harness.review_loop.shutil.which", return_value="claude"), patch(
            "harness.review_loop.subprocess.run", return_value=completed
        ) as run:
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

        cmd = run.call_args.args[0]
        prompt = cmd[2]
        assert f"review 005 pr_url=https://github.com/org/repo/pull/1 spec_dir={spec_dir}" in prompt
        assert f"worktree={worktree}" in prompt

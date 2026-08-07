"""Tests for ReviewLoopController prompt invocation contracts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.config import HarnessConfig, LlmConfig, ReviewLoopConfig
from harness.llm_tool_policy import LlmToolPolicy
from harness.review_loop import (
    ApprovalState,
    ReviewComment,
    ReviewLoopController,
    _ReviewSkillResult,
)


_REVIEW_AGENT_NAMES = (
    "speckit-echelon-debugger",
    "speckit-echelon-sentinel",
    "speckit-echelon-spec-guard",
)


def _scaffold_review_agents(worktree: Path) -> None:
    agents_dir = worktree / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for name in _REVIEW_AGENT_NAMES:
        (agents_dir / f"{name}.md").write_text(
            f"# {name}\n\nRead-only diagnostic instructions.\n",
            encoding="utf-8",
        )


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
    def test_review_loop_returns_queued_when_review_fix_is_created(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        controller = ReviewLoopController(
            gitops=MagicMock(),
            config=_config(),
            spec_id="005",
            strategy_id="default",
            base_dir=str(tmp_path),
            build_id="build-1",
        )
        comment = ReviewComment(
            comment_id="c1",
            path="src/app.py",
            line=10,
            body="must fix",
            reviewer="reviewer",
            created_at=datetime.now(tz=timezone.utc),
            is_inline=True,
        )
        monkeypatch.setattr(
            controller, "_fetch_unresolved_comments", MagicMock(return_value=[comment])
        )
        monkeypatch.setattr(
            controller,
            "_invoke_review_skill",
            MagicMock(return_value=_ReviewSkillResult(tokens_used=7, queued=True)),
        )

        result = controller.run_loop(
            "https://github.com/org/repo/pull/1", worktree_path=str(tmp_path)
        )

        assert result.status == "review_fix_queued"
        assert result.iterations == 1
        assert result.tokens_used == 7

    def test_review_loop_invokes_ai_cli_provider_facade(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        calls = []

        class FakeProvider:
            def __init__(self, config):
                self.config = config

            def run_prompt_result(
                self, worktree_path, prompt, *, extra_env=None, timeout_ms=None,
                request_metadata=None,
            ):
                calls.append((worktree_path, prompt, extra_env, timeout_ms, request_metadata))
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
        _scaffold_review_agents(tmp_path)
        spec_dir = tmp_path / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text("", encoding="utf-8")
        controller._spec_dir = spec_dir

        controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1",
            [],
            worktree_path=str(tmp_path),
        )

        assert calls
        assert calls[0][0] == str(tmp_path)
        assert "005 pr_url=https://github.com/org/repo/pull/1" in calls[0][1]
        assert "HARNESS_BUILD_STATUS_FILE" in calls[0][2]
        assert calls[0][4]["execution_profile"] == "review_triage_v1"

    def test_review_skill_prompt_receives_deterministic_spec_and_worktree_paths(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        workspace = tmp_path / "workspace"
        harness_root = workspace / "runs" / "targets" / "api"
        worktree = harness_root / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        skill_dir = worktree / ".claude" / "skills" / "speckit-echelon-review"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text(
            "---\nname: echelon.review\n---\nreview $ARGUMENTS\n",
            encoding="utf-8",
        )
        spec_dir = workspace / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text("", encoding="utf-8")
        _scaffold_review_agents(worktree)

        controller = ReviewLoopController(
            gitops=MagicMock(),
            config=_config(),
            spec_id="005",
            strategy_id="default",
            base_dir=str(harness_root),
            build_id="build-1",
            spec_dir=spec_dir,
        )

        calls = []

        class FakeProvider:
            def __init__(self, config):
                self.config = config

            def run_prompt_result(
                self, worktree_path, prompt, *, extra_env=None, timeout_ms=None,
                request_metadata=None,
            ):
                calls.append((worktree_path, prompt, extra_env, timeout_ms, request_metadata))
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
        assert calls[0][0] == str(worktree.resolve())
        assert f"review 005 pr_url=https://github.com/org/repo/pull/1 spec_dir={spec_dir}" in prompt
        assert f"worktree={worktree}" in prompt
        assert calls[0][2]["HARNESS_BUILD_STATUS_FILE"] == str(
            harness_root
            / "runs"
            / "build-1"
            / "state"
            / "default-review-status.json"
        )
        request_metadata = calls[0][4]
        prompt_metadata = request_metadata["prompt_metadata"]
        attempt_dir = Path(prompt_metadata["tool_write_paths"][0]).parent
        assert request_metadata["execution_profile"] == "review_triage_v1"
        assert prompt_metadata["tool_read_roots"] == [str(worktree), str(spec_dir)]
        assert all(str(attempt_dir) in path for path in prompt_metadata["tool_write_paths"][:-1])
        assert str(spec_dir / "tasks.md") not in prompt_metadata["tool_write_paths"]
        assert set(prompt_metadata["review_agents"]) == set(_REVIEW_AGENT_NAMES)
        assert '"comment_id":"c1"' in prompt.replace(" ", "")
        assert all(
            definition["tools"] == ["Read"]
            for definition in prompt_metadata["review_agents"].values()
        )

    def test_invalid_staged_output_blocks_without_canonical_mutation(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _scaffold_review_agents(worktree)
        spec_dir = tmp_path / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)
        tasks_file = spec_dir / "tasks.md"
        tasks_file.write_text("# Tasks\n", encoding="utf-8")
        provider_calls: list[object] = []

        class FakeProvider:
            def __init__(self, config):
                self.config = config

            def run_prompt_result(
                self, worktree_path, prompt, *, extra_env=None, timeout_ms=None,
                request_metadata=None,
            ):
                provider_calls.append(request_metadata)
                Path(extra_env["HARNESS_BUILD_STATUS_FILE"]).write_text(
                    json.dumps({
                        "status": "review_fix_queued",
                        "groups": 1,
                        "artifacts": ["review-fix-1.md"],
                        "tasks": [],
                        "tasks_append": "tasks-append.md",
                    }),
                    encoding="utf-8",
                )
                return CliRunResult(exit_code=0, stdout="queued", stderr="")

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", FakeProvider)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005", strategy_id="default",
            base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )
        comment = ReviewComment(
            comment_id="c1", path="src/app.py", line=10, body="must fix",
            reviewer="reviewer", created_at=datetime.now(tz=timezone.utc), is_inline=True,
        )
        monkeypatch.setattr(controller, "_fetch_unresolved_comments", MagicMock(return_value=[comment]))

        result = controller.run_loop("https://github.com/org/repo/pull/1", str(worktree))

        assert result.status == "blocked"
        assert provider_calls
        assert controller._seen_ids == set()
        assert tasks_file.read_text(encoding="utf-8") == "# Tasks\n"
        assert not list(spec_dir.glob("review-fix-*.md"))

    def test_missing_review_agent_blocks_before_provider_launch(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        spec_dir = tmp_path / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)
        provider_calls: list[HarnessConfig] = []

        class FakeProvider:
            def __init__(self, config):
                provider_calls.append(config)

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", FakeProvider)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005", strategy_id="default",
            base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )

        result = controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1", [], worktree_path=str(worktree)
        )

        assert result.queued is False
        assert provider_calls == []

    def test_review_loop_blocks_without_a_delivery_worktree(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        provider_calls: list[HarnessConfig] = []

        class FakeProvider:
            def __init__(self, config):
                provider_calls.append(config)

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", FakeProvider)
        controller = ReviewLoopController(
            gitops=MagicMock(),
            config=_config(),
            spec_id="005",
            strategy_id="default",
            base_dir=str(tmp_path),
            build_id="build-1",
        )
        comment = ReviewComment(
            comment_id="c1",
            path="src/app.py",
            line=10,
            body="must fix",
            reviewer="reviewer",
            created_at=datetime.now(tz=timezone.utc),
            is_inline=True,
        )
        monkeypatch.setattr(
            controller,
            "_fetch_unresolved_comments",
            MagicMock(return_value=[comment]),
        )

        result = controller.run_loop(
            "https://github.com/org/repo/pull/1",
            worktree_path="",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "blocker_escalation"
        assert provider_calls == []

    def test_review_loop_can_merge_approved_pr_without_a_delivery_worktree(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        gitops = MagicMock()
        gitops.merge_pr.return_value = True
        controller = ReviewLoopController(
            gitops=gitops,
            config=_config(),
            spec_id="005",
            strategy_id="default",
            base_dir=str(tmp_path),
            build_id="build-1",
        )
        monkeypatch.setattr(
            controller,
            "_fetch_unresolved_comments",
            MagicMock(return_value=[]),
        )
        monkeypatch.setattr(
            controller,
            "_fetch_approval_state",
            MagicMock(return_value=ApprovalState.APPROVED),
        )

        result = controller.run_loop(
            "https://github.com/org/repo/pull/1",
            worktree_path="",
        )

        assert result.status == "completed"
        gitops.merge_pr.assert_called_once_with("https://github.com/org/repo/pull/1")

    def test_review_skill_failure_does_not_handle_comments(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        class FailingProvider:
            def __init__(self, config):
                self.config = config

            def run_prompt_result(
                self, worktree_path, prompt, *, extra_env=None, timeout_ms=None,
                request_metadata=None,
            ):
                return CliRunResult(exit_code=1, stdout="failed", stderr="boom")

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", FailingProvider)
        controller = ReviewLoopController(
            gitops=MagicMock(),
            config=_config(),
            spec_id="005",
            strategy_id="default",
            base_dir=str(tmp_path),
            build_id="build-1",
        )
        comment = ReviewComment(
            comment_id="c1",
            path="src/app.py",
            line=10,
            body="must fix",
            reviewer="reviewer",
            created_at=datetime.now(tz=timezone.utc),
            is_inline=True,
        )
        monkeypatch.setattr(
            controller,
            "_fetch_unresolved_comments",
            MagicMock(return_value=[comment]),
        )
        resolve_thread = MagicMock()
        request_review = MagicMock()
        monkeypatch.setattr(controller, "_resolve_thread", resolve_thread)
        monkeypatch.setattr(controller, "_request_review", request_review)

        result = controller.run_loop(
            "https://github.com/org/repo/pull/1",
            worktree_path=str(tmp_path),
        )

        assert result.status == "blocked"
        assert controller._seen_ids == set()
        resolve_thread.assert_not_called()
        request_review.assert_not_called()

    def test_review_loop_passes_codex_config_to_provider(self, monkeypatch, tmp_path: Path) -> None:
        configs = []
        policy = LlmToolPolicy(
            allow_unsafe_host_execution=True,
            approval_reason="Operator approved disposable worktree after sandbox review.",
        )

        class FakeProvider:
            def __init__(self, config):
                configs.append(config)

            def run_prompt_result(
                self, worktree_path, prompt, *, extra_env=None, timeout_ms=None,
                request_metadata=None,
            ):
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
        _scaffold_review_agents(tmp_path)
        spec_dir = tmp_path / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text("", encoding="utf-8")
        controller._spec_dir = spec_dir
        controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1",
            [],
            worktree_path=str(tmp_path),
        )

        assert configs
        assert configs[0].llm.cli == "codex"
        assert configs[0].llm.tool_policy is policy

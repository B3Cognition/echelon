"""Tests for ReviewLoopController prompt invocation contracts."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.config import HarnessConfig, LlmConfig, ReviewLoopConfig
from harness.llm_tool_policy import LlmToolPolicy
from harness.prosaic_prompt_loader import ProsaicCommandArtifact, ProsaicPromptLoader
from harness.review_loop import (
    ApprovalState,
    ReviewComment,
    ReviewLoopController,
    _ReviewSkillResult,
)
from harness.review_artifacts import PublishedReviewBatch
from harness.review_triage_io import load_review_prose


_REAL_POPEN = subprocess.Popen


def _scaffold_prosaic_review_bundle(worktree: Path) -> None:
    command = worktree / ".echelon/prosaic/commands/echelon.review.md"
    command.parent.mkdir(parents=True)
    command.write_text(
        "---\nname: echelon.review\nmodel_tier: strong\neffort: medium\n---\n"
        "Compose the supplied diagnoses into the exact JSON envelope.\n",
        encoding="utf-8",
    )
    for name in (
        "echelon.review-debugger",
        "echelon.review-sentinel",
        "echelon.review-spec-guard",
    ):
        role = worktree / ".echelon/prosaic/subagents" / f"{name}.md"
        role.parent.mkdir(parents=True, exist_ok=True)
        role.write_text(
            f"---\nname: {name}\ndescription: Bounded review role\n"
            "execution: agent\nmodel_tier: strong\neffort: medium\n---\n"
            f"Perform only the {name} diagnosis.\n",
            encoding="utf-8",
        )


def _tasks_append() -> str:
    return """- [ ] T-000001 complexity=standard phase=review-fix req=FR-001 depends=none

  **Title:** RF1-T1 - Write failing test for review finding

- [ ] T-000002 complexity=standard phase=review-fix req=FR-001 depends=T-000001

  **Title:** RF1-T2 - Fix src/app.py

- [ ] T-000003 complexity=standard phase=review-fix req=FR-001 depends=T-000002

  **Title:** RF1-T3 - Verify regression and prior tests
"""


def _composer_envelope_for_loop() -> dict[str, object]:
    return {
        "manifest": {
            "status": "review_fix_queued",
            "groups": 1,
            "artifacts": ["review-fix-1.md"],
            "tasks": [
                {
                    "task_id": f"T-00000{index}",
                    "review_task_id": f"RF1-T{index}",
                    "artifact": "review-fix-1.md",
                }
                for index in (1, 2, 3)
            ],
            "tasks_append": "tasks-append.md",
        },
        "artifacts": {"review-fix-1.md": "# Review Fix 1\n"},
        "tasks_append": _tasks_append(),
    }


@pytest.fixture(autouse=True)
def _inspect_review_with_prosaic(monkeypatch, request):
    if request.node.name.startswith("test_clean_prosaic_bundle_crosses_real_facade_and_adapter"):
        return
    monkeypatch.setattr(
        ProsaicPromptLoader,
        "load_command",
        lambda _self, command_id: ProsaicCommandArtifact(
            frontmatter={
                "name": command_id,
                "description": "Review",
                "model_tier": "strong",
                "effort": "medium",
            },
            body="Compose diagnosed review groups only.",
        ),
    )
    monkeypatch.setattr(
        ProsaicPromptLoader,
        "load_subagent",
        lambda _self, role_id: ProsaicCommandArtifact(
            frontmatter={
                "name": role_id,
                "description": "Review role",
                "model_tier": "strong",
                "effort": "medium",
            },
            body=f"Perform only {role_id} analysis.",
        ),
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
    @pytest.mark.parametrize("cli", ["claude", "codex"])
    def test_clean_prosaic_bundle_crosses_real_facade_and_adapter(
        self, cli: str, monkeypatch, tmp_path: Path
    ) -> None:
        """The controller reaches each real no-tools adapter and real publisher."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _scaffold_prosaic_review_bundle(worktree)
        captured_prose = load_review_prose(worktree, timeout_s=5.0)
        monkeypatch.setattr(
            "harness.review_loop.load_review_prose",
            lambda _worktree, *, timeout_s: captured_prose,
        )
        spec_dir = tmp_path / "specs/005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
        answers = [
            json.dumps({"action": "result", "analysis": "debugger"}),
            json.dumps({"action": "result", "analysis": "sentinel"}),
            json.dumps({"action": "result", "analysis": "spec guard"}),
            json.dumps(_composer_envelope_for_loop()),
        ]
        wires = []
        for answer in answers:
            if cli == "codex":
                events = [
                    {"type": "item.completed", "item": {"type": "agent_message", "text": answer}},
                    {"type": "turn.completed", "usage": {"input_tokens": 2, "output_tokens": 1}},
                ]
                wires.append(
                    b"".join(
                        json.dumps(event, separators=(",", ":")).encode() + b"\n"
                        for event in events
                    )
                )
            else:
                wires.append(
                    json.dumps(
                        {
                            "type": "result",
                            "subtype": "success",
                            "is_error": False,
                            "result": answer,
                            "total_cost_usd": 0.0,
                            "usage": {"input_tokens": 2, "output_tokens": 1},
                        },
                        separators=(",", ":"),
                    ).encode()
                    + b"\n"
                )
        launches: list[list[str]] = []

        def launch(command, **kwargs):
            if Path(command[0]).name == "prosaic":
                return _REAL_POPEN(command, **kwargs)
            launches.append(list(command))
            wire = wires.pop(0)
            script = f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({wire!r})"
            return _REAL_POPEN([sys.executable, "-c", script], **kwargs)

        target = (
            "harness.ai_cli_backends.codex.subprocess.Popen"
            if cli == "codex"
            else "harness.ai_cli_backends.claude_triage.subprocess.Popen"
        )
        monkeypatch.setattr(target, launch)
        if cli == "claude":
            monkeypatch.setattr(
                "harness.ai_cli_backends.claude_triage._sandbox_exec_path",
                lambda: "/usr/bin/sandbox-exec",
            )
            monkeypatch.setattr(
                "harness.ai_cli_backends.claude_triage.sys.platform", "darwin"
            )
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(cli=cli), spec_id="005",             base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )
        comment = ReviewComment(
            comment_id="c1", path="src/app.py", line=1, body="must fix",
            reviewer="reviewer", created_at=datetime.now(tz=timezone.utc), is_inline=True,
        )

        result = controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1", [comment], worktree_path=str(worktree)
        )

        assert result.queued is True
        assert result.tokens_used == 12
        assert len(launches) == 4
        assert wires == []
        assert (spec_dir / "review-fix-1.md").read_text() == "# Review Fix 1\n"

    def test_clean_prosaic_only_bundle_runs_host_owned_triage_and_publishes(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """Reintroducing the native-agent loader would reject a clean neutral bundle."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _scaffold_prosaic_review_bundle(worktree)
        (worktree / "src").mkdir()
        (worktree / "src/app.py").write_text("def value():\n    return 1\n")
        spec_dir = tmp_path / "specs/005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
        (spec_dir / "spec.md").write_text("# Requirement\n", encoding="utf-8")
        responses = [
            json.dumps({"action": "result", "analysis": f"analysis-{role}"})
            for role in ("debugger", "sentinel", "spec-guard")
        ]
        responses.append(
            json.dumps(
                {
                    "manifest": {
                        "status": "review_fix_queued",
                        "groups": 1,
                        "artifacts": ["review-fix-1.md"],
                        "tasks": [
                            {
                                "task_id": f"T-00000{index}",
                                "review_task_id": f"RF1-T{index}",
                                "artifact": "review-fix-1.md",
                            }
                            for index in (1, 2, 3)
                        ],
                        "tasks_append": "tasks-append.md",
                    },
                    "artifacts": {"review-fix-1.md": "# Review Fix 1\n"},
                    "tasks_append": _tasks_append(),
                }
            )
        )
        calls: list[tuple[str, str]] = []

        class ScriptedProvider:
            def __init__(self, config):
                self.config = config

            def run_review_triage_turn(
                self, worktree_path, prompt, *, frontmatter, timeout_ms
            ):
                calls.append((frontmatter["name"], prompt))
                response = responses.pop(0)
                process = subprocess.run(
                    [sys.executable, "-c", "import sys; print(sys.argv[1])", response],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return CliRunResult(
                    exit_code=0, stdout=process.stdout.strip(), stderr="", token_usage=2
                )

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", ScriptedProvider)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005",             base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )
        comment = ReviewComment(
            comment_id="c1", path="src/app.py", line=1, body="must fix",
            reviewer="reviewer", created_at=datetime.now(tz=timezone.utc), is_inline=True,
        )

        result = controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1", [comment], worktree_path=str(worktree)
        )

        assert result.queued is True
        assert result.tokens_used == 8
        assert [name for name, _prompt in calls] == [
            "echelon.review-debugger",
            "echelon.review-sentinel",
            "echelon.review-spec-guard",
            "echelon.review",
        ]
        assert "analysis-debugger" in calls[1][1]
        assert "analysis-sentinel" in calls[2][1]
        composer_prompt = calls[3][1]
        assert (
            '"row_syntax":"- [ ] {task_id} complexity=standard phase=review-fix '
            'req={requirement_ids} depends={depends}"'
            in composer_prompt
        )
        assert (
            '"title_syntax":"  **Title:** {review_task_id} - {nonempty title}"'
            in composer_prompt
        )
        assert (
            '"depends":"none","review_task_id":"RF1-T1","task_id":"T-000001"'
            in composer_prompt
        )
        assert (
            '"depends":"T-000001","review_task_id":"RF1-T2","task_id":"T-000002"'
            in composer_prompt
        )
        assert (
            '"depends":"T-000002","review_task_id":"RF1-T3","task_id":"T-000003"'
            in composer_prompt
        )
        assert (spec_dir / "review-fix-1.md").read_text() == "# Review Fix 1\n"
        assert "RF1-T3" in (spec_dir / "tasks.md").read_text()

    def test_empty_comment_input_publishes_empty_manifest_without_model_work(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        spec_dir = tmp_path / "specs/005-my-spec"
        spec_dir.mkdir(parents=True)
        tasks_file = spec_dir / "tasks.md"
        tasks_file.write_text("# Tasks\n", encoding="utf-8")
        launches: list[object] = []

        class Provider:
            def __init__(self, config):
                launches.append(config)

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", Provider)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005",             base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )

        result = controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1", [], worktree_path=str(worktree)
        )

        assert result.queued is False
        assert result.tokens_used == 0
        assert launches == []
        assert controller._published_batch is not None
        assert controller._published_batch.status == "no_blocking_comments"
        assert tasks_file.read_text(encoding="utf-8") == "# Tasks\n"

    def test_missing_neutral_role_blocks_before_provider_launch(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _scaffold_prosaic_review_bundle(worktree)
        (worktree / ".echelon/prosaic/subagents/echelon.review-sentinel.md").unlink()
        spec_dir = tmp_path / "specs/005-my-spec"
        spec_dir.mkdir(parents=True)
        tasks_file = spec_dir / "tasks.md"
        tasks_file.write_text("# Tasks\n", encoding="utf-8")
        launches: list[object] = []

        class Provider:
            def __init__(self, config):
                launches.append(config)

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", Provider)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005",             base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )
        comment = ReviewComment(
            comment_id="c1", path="src.py", line=1, body="must fix",
            reviewer="reviewer", created_at=datetime.now(tz=timezone.utc), is_inline=True,
        )

        result = controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1", [comment], worktree_path=str(worktree)
        )

        assert result.queued is False
        assert launches == []
        assert tasks_file.read_text(encoding="utf-8") == "# Tasks\n"

    def test_restart_preserves_last_blocking_comment_time_for_silence_merge(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        config = _config()
        config.review_loop.merge_timeout_hours = 0
        gitops = MagicMock()
        gitops.merge_pr.return_value = True
        comment = ReviewComment(
            comment_id="c1", path="src/app.py", line=1, body="must fix",
            reviewer="reviewer", created_at=datetime.now(tz=timezone.utc), is_inline=True,
        )
        first = ReviewLoopController(
            gitops=gitops, config=config, spec_id="005",             base_dir=str(tmp_path), build_id="build-1",
        )
        monkeypatch.setattr(first, "_fetch_unresolved_comments", MagicMock(return_value=[comment]))
        monkeypatch.setattr(first, "_fetch_approval_state", MagicMock(return_value=ApprovalState.PENDING))
        monkeypatch.setattr(first, "_invoke_review_skill", MagicMock(return_value=_ReviewSkillResult(tokens_used=1, queued=True)))
        assert first.run_loop("https://github.com/org/repo/pull/1", str(tmp_path)).status == "review_fix_queued"

        restarted = ReviewLoopController(
            gitops=gitops, config=config, spec_id="005",             base_dir=str(tmp_path), build_id="build-1",
        )
        monkeypatch.setattr(restarted, "_fetch_unresolved_comments", MagicMock(return_value=[]))
        monkeypatch.setattr(restarted, "_fetch_approval_state", MagicMock(return_value=ApprovalState.PENDING))

        result = restarted.run_loop("https://github.com/org/repo/pull/1", str(tmp_path))

        assert result.status == "completed"
        assert json.loads(restarted._state_file.read_text())["last_blocking_comment_at"]
        gitops.merge_pr.assert_called_once()

    def test_review_loop_returns_queued_when_review_fix_is_created(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        controller = ReviewLoopController(
            gitops=MagicMock(),
            config=_config(),
            spec_id="005",
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

    def test_invalid_composer_output_blocks_without_canonical_mutation(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _scaffold_prosaic_review_bundle(worktree)
        spec_dir = tmp_path / "specs/005-my-spec"
        spec_dir.mkdir(parents=True)
        tasks_file = spec_dir / "tasks.md"
        tasks_file.write_text("# Tasks\n", encoding="utf-8")
        responses = [
            json.dumps({"action": "result", "analysis": "valid"}),
            json.dumps({"action": "result", "analysis": "valid"}),
            json.dumps({"action": "result", "analysis": "valid"}),
            json.dumps(
                {
                    **_composer_envelope_for_loop(),
                    "artifacts": {"../outside.md": "escape"},
                }
            ),
        ]

        class Provider:
            def __init__(self, config):
                self.config = config

            def run_review_triage_turn(self, cwd, prompt, *, frontmatter, timeout_ms):
                return CliRunResult(0, responses.pop(0), "", token_usage=4)

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", Provider)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005",             base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )
        comment = ReviewComment(
            comment_id="c1", path="src/app.py", line=10, body="must fix",
            reviewer="reviewer", created_at=datetime.now(tz=timezone.utc), is_inline=True,
        )

        result = controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1", [comment], worktree_path=str(worktree)
        )

        assert result.queued is False
        assert result.tokens_used == 16
        assert controller._seen_ids == set()
        assert tasks_file.read_text(encoding="utf-8") == "# Tasks\n"
        assert not list(spec_dir.glob("review-fix-*.md"))

    @pytest.mark.parametrize(
        "failure",
        ["malformed", "invalid-read", "blocked", "timeout", "overflow"],
    )
    def test_diagnostic_failures_leave_canonical_review_state_unchanged(
        self, failure: str, monkeypatch, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _scaffold_prosaic_review_bundle(worktree)
        spec_dir = tmp_path / "specs/005-my-spec"
        spec_dir.mkdir(parents=True)
        tasks_file = spec_dir / "tasks.md"
        tasks_file.write_text("# Tasks\n", encoding="utf-8")

        class Provider:
            def __init__(self, config):
                self.config = config

            def run_review_triage_turn(self, cwd, prompt, *, frontmatter, timeout_ms):
                if failure == "malformed":
                    return CliRunResult(0, "not-json", "", token_usage=5)
                if failure == "invalid-read":
                    return CliRunResult(
                        0,
                        json.dumps(
                            {
                                "action": "read",
                                "request": {
                                    "op": "list_directory",
                                    "root": "worktree",
                                    "path": "../escape",
                                },
                            }
                        ),
                        "",
                        token_usage=5,
                    )
                if failure == "blocked":
                    return CliRunResult(
                        0,
                        json.dumps({"action": "blocked", "reason": "insufficient evidence"}),
                        "",
                        token_usage=5,
                    )
                if failure == "timeout":
                    return CliRunResult(124, "", "", token_usage=5, timed_out=True)
                return CliRunResult(0, "x" * (256 * 1024 + 1), "", token_usage=5)

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", Provider)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005",             base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )
        comment = ReviewComment(
            comment_id="c1", path="src/app.py", line=1, body="must fix",
            reviewer="reviewer", created_at=datetime.now(tz=timezone.utc), is_inline=True,
        )

        result = controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1", [comment], worktree_path=str(worktree)
        )

        assert result.queued is False
        assert result.tokens_used == 5
        assert controller._seen_ids == set()
        assert tasks_file.read_text(encoding="utf-8") == "# Tasks\n"
        assert not list(spec_dir.glob("review-fix-*.md"))

    def test_usage_from_completed_and_failed_role_turns_is_retained(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _scaffold_prosaic_review_bundle(worktree)
        (worktree / "src.py").write_text("evidence\n", encoding="utf-8")
        spec_dir = tmp_path / "specs/005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
        replies = [
            CliRunResult(
                0,
                json.dumps(
                    {
                        "action": "read",
                        "request": {
                            "op": "read_file", "root": "worktree", "path": "src.py",
                            "start_line": 1, "line_count": 1,
                        },
                    }
                ),
                "",
                token_usage=2,
            ),
            CliRunResult(
                0, json.dumps({"action": "result", "analysis": "root cause"}), "",
                token_usage=3,
            ),
            CliRunResult(1, "", "provider error", token_usage=7),
        ]

        class Provider:
            def __init__(self, config):
                self.config = config

            def run_review_triage_turn(self, cwd, prompt, *, frontmatter, timeout_ms):
                return replies.pop(0)

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", Provider)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005",             base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )
        comment = ReviewComment(
            comment_id="c1", path="src.py", line=1, body="must fix",
            reviewer="reviewer", created_at=datetime.now(tz=timezone.utc), is_inline=True,
        )

        result = controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1", [comment], worktree_path=str(worktree)
        )

        assert result.queued is False
        assert result.tokens_used == 12
        assert controller._seen_ids == set()

    def test_all_role_and_composer_turns_share_one_decreasing_deadline(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _scaffold_prosaic_review_bundle(worktree)
        spec_dir = tmp_path / "specs/005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
        captured_prose = load_review_prose(worktree, timeout_s=5.0)
        now = [1_000.0]
        timeouts: list[int] = []
        load_timeouts: list[float] = []

        def load_prose(_worktree, *, timeout_s):
            load_timeouts.append(timeout_s)
            now[0] += 5.0
            return captured_prose

        class Provider:
            def __init__(self, config):
                self.config = config

            def run_review_triage_turn(self, cwd, prompt, *, frontmatter, timeout_ms):
                timeouts.append(timeout_ms)
                now[0] += 1.0
                if frontmatter["name"] == "echelon.review":
                    return CliRunResult(0, json.dumps(_composer_envelope_for_loop()), "")
                return CliRunResult(
                    0, json.dumps({"action": "result", "analysis": "valid"}), ""
                )

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", Provider)
        monkeypatch.setattr("harness.review_loop.time.monotonic", lambda: now[0])
        monkeypatch.setattr("harness.review_loop.load_review_prose", load_prose)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005",             base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )
        comment = ReviewComment(
            comment_id="c1", path="src.py", line=1, body="must fix",
            reviewer="reviewer", created_at=datetime.now(tz=timezone.utc), is_inline=True,
        )

        result = controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1", [comment], worktree_path=str(worktree)
        )

        assert result.queued is True
        assert load_timeouts == [1_200.0]
        assert len(timeouts) == 4
        assert timeouts == sorted(timeouts, reverse=True)
        assert len(set(timeouts)) == 4
        assert timeouts[0] == 1_195_000

    def test_outer_publication_state_failure_retains_spent_turn_usage(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _scaffold_prosaic_review_bundle(worktree)
        spec_dir = tmp_path / "specs/005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

        class Provider:
            def __init__(self, config):
                self.config = config

            def run_review_triage_turn(self, cwd, prompt, *, frontmatter, timeout_ms):
                if frontmatter["name"] == "echelon.review":
                    return CliRunResult(
                        0, json.dumps(_composer_envelope_for_loop()), "", token_usage=2
                    )
                return CliRunResult(
                    0,
                    json.dumps({"action": "result", "analysis": "valid"}),
                    "",
                    token_usage=2,
                )

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", Provider)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005",             base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )
        monkeypatch.setattr(
            controller,
            "_record_pending_batch",
            MagicMock(side_effect=OSError("state unavailable")),
        )
        comment = ReviewComment(
            comment_id="c1", path="src.py", line=1, body="must fix",
            reviewer="reviewer", created_at=datetime.now(tz=timezone.utc), is_inline=True,
        )

        result = controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1", [comment], worktree_path=str(worktree)
        )

        assert result.queued is False
        assert result.tokens_used == 8
        assert result.reason == "review_staging_failed"

    @pytest.mark.parametrize("symlinked", ["worktree", "spec"])
    def test_supplied_root_symlink_components_are_not_resolved_before_validation(
        self, symlinked: str, monkeypatch, tmp_path: Path
    ) -> None:
        actual_worktree = tmp_path / "actual-worktree"
        actual_worktree.mkdir()
        _scaffold_prosaic_review_bundle(actual_worktree)
        actual_spec = tmp_path / "actual-spec"
        actual_spec.mkdir()
        tasks_file = actual_spec / "tasks.md"
        tasks_file.write_text("# Tasks\n", encoding="utf-8")
        worktree = actual_worktree
        spec_dir = actual_spec
        if symlinked == "worktree":
            worktree = tmp_path / "worktree-link"
            worktree.symlink_to(actual_worktree, target_is_directory=True)
        else:
            spec_dir = tmp_path / "spec-link"
            spec_dir.symlink_to(actual_spec, target_is_directory=True)
        launches: list[object] = []

        class Provider:
            def __init__(self, config):
                launches.append(config)

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", Provider)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005",             base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )
        comment = ReviewComment(
            comment_id="c1", path="src.py", line=1, body="must fix",
            reviewer="reviewer", created_at=datetime.now(tz=timezone.utc), is_inline=True,
        )

        result = controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1", [comment], worktree_path=str(worktree)
        )

        assert result.queued is False
        assert launches == []
        assert tasks_file.read_text(encoding="utf-8") == "# Tasks\n"

    def test_remote_side_effect_failure_keeps_published_batch_retryable(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """A failed remote effect may not consume the publication journal."""
        spec_dir = tmp_path / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)
        batch = PublishedReviewBatch(
            attempt_id="attempt-1", status="review_fix_queued", artifact_paths=(),
            task_ids=("T-002", "T-003", "T-004"), comment_ids=("c1",),
        )
        consumed: list[str] = []

        class FakePublisher:
            def __init__(self, *args):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def recover_publication(self, seen_ids):
                return batch

            def mark_consumed(self, attempt_id):
                consumed.append(attempt_id)

        monkeypatch.setattr("harness.review_loop.ReviewArtifactPublisher", FakePublisher)
        controller = ReviewLoopController(
            gitops=MagicMock(), config=_config(), spec_id="005",             base_dir=str(tmp_path), build_id="build-1", spec_dir=spec_dir,
        )
        controller._record_pending_batch(batch)
        resolve = MagicMock(return_value=False)
        monkeypatch.setattr(controller, "_resolve_thread", resolve)

        assert controller.complete_published_batch("https://github.com/o/r/pull/1", "attempt-1") is False
        assert consumed == []
        assert controller._seen_ids == set()

        resolve.return_value = True
        assert controller.complete_published_batch("https://github.com/o/r/pull/1", "attempt-1") is True
        assert consumed == ["attempt-1"]
        assert controller._seen_ids == {"c1"}

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
        assert result.termination_reason == "review_staging_failed"
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

            def run_review_triage_turn(
                self, worktree_path, prompt, *, frontmatter, timeout_ms
            ):
                return CliRunResult(
                    exit_code=1, stdout="", stderr="boom", token_usage=9
                )

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", FailingProvider)
        controller = ReviewLoopController(
            gitops=MagicMock(),
            config=_config(),
            spec_id="005",
                        base_dir=str(tmp_path),
            build_id="build-1",
        )
        _scaffold_prosaic_review_bundle(tmp_path)
        spec_dir = tmp_path / "specs/005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
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
        assert result.tokens_used == 9
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

            def run_review_triage_turn(
                self, worktree_path, prompt, *, frontmatter, timeout_ms
            ):
                if frontmatter["name"] == "echelon.review":
                    return CliRunResult(0, json.dumps(_composer_envelope_for_loop()), "")
                return CliRunResult(
                    0, json.dumps({"action": "result", "analysis": "valid"}), ""
                )

        monkeypatch.setattr("harness.review_loop.AICodingCliProvider", FakeProvider)
        controller = ReviewLoopController(
            gitops=MagicMock(),
            config=_config(cli="codex", tool_policy=policy),
            spec_id="005",
                        base_dir=str(tmp_path),
            build_id="build-1",
        )
        _scaffold_prosaic_review_bundle(tmp_path)
        spec_dir = tmp_path / "specs" / "005-my-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text("", encoding="utf-8")
        controller._spec_dir = spec_dir
        controller._invoke_review_skill(
            "https://github.com/org/repo/pull/1",
            [
                ReviewComment(
                    comment_id="c1", path="src/app.py", line=1, body="must fix",
                    reviewer="reviewer", created_at=datetime.now(tz=timezone.utc),
                    is_inline=True,
                )
            ],
            worktree_path=str(tmp_path),
        )

        assert configs
        assert configs[0].llm.cli == "codex"
        assert configs[0].llm.tool_policy is policy

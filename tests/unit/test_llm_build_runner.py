"""Tests for LLM-backed build/fix runner semantics."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.llm_build_runner import LlmBuildRunner


def _executor(returncode=0, status=None):
    executor = MagicMock()

    def fake_exec_prompt(worktree_path, prompt, *, extra_env=None):
        if status is not None:
            path = (extra_env or {}).get("HARNESS_BUILD_STATUS_FILE")
            if path:
                Path(path).write_text(json.dumps(status), encoding="utf-8")
        return returncode

    executor.exec_prompt.side_effect = fake_exec_prompt
    return executor


@pytest.mark.unit
class TestLlmBuildRunner:
    def test_exec_build_sets_status_file_env(self, tmp_path):
        executor = _executor(status={"status": "done"})

        result = LlmBuildRunner(executor).exec_build(str(tmp_path), "build this")

        assert result.succeeded is True
        extra_env = executor.exec_prompt.call_args.kwargs["extra_env"]
        assert extra_env["HARNESS_BUILD_STATUS_FILE"].endswith("harness-build-status.json")

    def test_exec_build_anchors_project_env_to_worktree(self, tmp_path):
        executor = _executor(status={"status": "done"})

        LlmBuildRunner(executor).exec_build(str(tmp_path), "build this")

        extra_env = executor.exec_prompt.call_args.kwargs["extra_env"]
        assert extra_env["PROJECT_ROOT"] == str(tmp_path)
        assert extra_env["SPEC_KIT_ROOT"] == str(tmp_path)
        assert extra_env["HARNESS_WORKTREE"] == str(tmp_path)

    def test_exec_build_exposes_harness_source_dir(self, tmp_path):
        executor = _executor(status={"status": "done"})

        LlmBuildRunner(executor).exec_build(str(tmp_path), "build this")

        extra_env = executor.exec_prompt.call_args.kwargs["extra_env"]
        assert extra_env["HARNESS_SOURCE_DIR"].endswith("src/harness")

    def test_exec_build_returns_impasse_from_status_file(self, tmp_path):
        executor = _executor(
            status={"status": "impasse", "impasse_file": "codegen-impasse.md"}
        )

        result = LlmBuildRunner(executor).exec_build(str(tmp_path), "build this")

        assert result.is_impasse is True
        assert result.impasse_file == "codegen-impasse.md"

    def test_exec_build_returns_unknown_when_status_file_missing(self, tmp_path):
        executor = _executor()

        result = LlmBuildRunner(executor).exec_build(str(tmp_path), "build this")

        assert result.status == "unknown"
        assert result.succeeded is False

    def test_exec_build_preserves_provider_output_when_status_file_missing(self, tmp_path):
        executor = _executor(returncode=1)
        executor.last_stdout = "You've hit your session limit"
        executor.last_stderr = "resets 9:10pm"

        result = LlmBuildRunner(executor).exec_build(str(tmp_path), "build this")

        assert result.status == "unknown"
        assert result.stdout == "You've hit your session limit"
        assert result.stderr == "resets 9:10pm"

    def test_exec_build_recovers_done_status_from_final_json_when_marker_missing(
        self, tmp_path
    ):
        executor = _executor(returncode=0)
        executor.last_stdout = (
            "Build complete.\n"
            "```json\n"
            '{"status":"complete","state_updates":{"completed_task_ids":["T-001","T-002"]}}\n'
            "```\n"
        )

        result = LlmBuildRunner(executor).exec_build(str(tmp_path), "build this")

        assert result.status == "done"
        assert result.succeeded is True
        assert result.task_ids == ["T-001", "T-002"]
        assert "final JSON output" in (result.reason or "")

    def test_exec_feedback_delegates_to_build_semantics(self, tmp_path):
        executor = _executor(status={"status": "done"})

        result = LlmBuildRunner(executor).exec_feedback(str(tmp_path), "fix this")

        assert result.succeeded is True
        executor.exec_prompt.assert_called_once()
        assert executor.exec_prompt.call_args.args == (str(tmp_path), "fix this")

    def test_exec_build_returns_timeout_result_on_timeout(self, tmp_path):
        executor = _executor(returncode=-1)

        result = LlmBuildRunner(executor).exec_build(str(tmp_path), "build this")

        assert result.status == "timeout"
        assert result.exit_code == -1

    def test_exec_build_preserves_prompt_executor_token_usage(self, tmp_path):
        executor = _executor(status={"status": "done"})
        executor.last_token_usage = 4321

        result = LlmBuildRunner(executor).exec_build(str(tmp_path), "build this")

        assert result.token_usage == 4321

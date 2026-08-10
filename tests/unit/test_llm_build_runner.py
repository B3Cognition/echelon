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
        assert "SPEC_KIT_ROOT" not in extra_env
        assert extra_env["HARNESS_WORKTREE"] == str(tmp_path)

    def test_exec_build_does_not_expose_harness_source_dir(self, tmp_path):
        executor = _executor(status={"status": "done"})

        LlmBuildRunner(executor).exec_build(str(tmp_path), "build this")

        extra_env = executor.exec_prompt.call_args.kwargs["extra_env"]
        assert "HARNESS_SOURCE_DIR" not in extra_env

    def test_exec_build_exposes_containment_policy_file_when_provided(self, tmp_path):
        executor = _executor(status={"status": "done"})
        policy_file = tmp_path / "delivery-containment-policy.json"
        policy_file.write_text(
            json.dumps({"allowed_roots": {"implementation": [str(tmp_path)]}}),
            encoding="utf-8",
        )

        LlmBuildRunner(executor).exec_build(
            str(tmp_path),
            "build this",
            containment_policy_file=str(policy_file),
        )

        extra_env = executor.exec_prompt.call_args.kwargs["extra_env"]
        assert extra_env["ECHELON_CONTAINMENT_POLICY_FILE"] == str(policy_file)

    def test_exec_build_exposes_provider_root_lists_from_containment_policy(self, tmp_path):
        executor = _executor(status={"status": "done"})
        policy_file = tmp_path / "delivery-containment-policy.json"
        context_root = tmp_path / "context"
        spec_root = tmp_path / "specs" / "001-prose"
        state_root = tmp_path / "runs" / "targets" / "prosaic" / "state"
        forbidden_root = tmp_path / "sources" / "spec-kit"
        policy_file.write_text(
            json.dumps(
                {
                    "allowed_roots": {
                        "implementation": [str(tmp_path)],
                        "context": [str(context_root)],
                        "spec_inputs": [str(spec_root)],
                        "harness_state": [str(state_root)],
                    },
                    "forbidden_source_roots": [str(forbidden_root)],
                    "forbidden_source_root_aliases": [
                        "sources/spec-kit",
                        "./sources/spec-kit",
                    ],
                }
            ),
            encoding="utf-8",
        )

        LlmBuildRunner(executor).exec_build(
            str(tmp_path),
            "build this",
            containment_policy_file=str(policy_file),
        )

        extra_env = executor.exec_prompt.call_args.kwargs["extra_env"]
        allowed_roots = json.loads(extra_env["ECHELON_ALLOWED_ROOTS_JSON"])
        forbidden_roots = json.loads(extra_env["ECHELON_FORBIDDEN_ROOTS_JSON"])
        forbidden_aliases = json.loads(extra_env["ECHELON_FORBIDDEN_ROOT_ALIASES_JSON"])
        assert allowed_roots == [
            str(tmp_path),
            str(context_root),
            str(spec_root),
            str(state_root),
        ]
        assert forbidden_roots == [str(forbidden_root)]
        assert forbidden_aliases == ["sources/spec-kit", "./sources/spec-kit"]

    def test_exec_build_blocks_malformed_containment_policy(self, tmp_path):
        executor = _executor(status={"status": "done"})
        policy_file = tmp_path / "delivery-containment-policy.json"
        policy_file.write_text("{not-json", encoding="utf-8")

        result = LlmBuildRunner(executor).exec_build(
            str(tmp_path),
            "build this",
            containment_policy_file=str(policy_file),
        )

        assert result.status == "error"
        assert result.exit_code == 125
        assert "malformed containment policy" in (result.reason or "")
        executor.exec_prompt.assert_not_called()

    def test_exec_build_blocks_missing_containment_policy(self, tmp_path):
        executor = _executor(status={"status": "done"})
        policy_file = tmp_path / "delivery-containment-policy.json"

        result = LlmBuildRunner(executor).exec_build(
            str(tmp_path),
            "build this",
            containment_policy_file=str(policy_file),
        )

        assert result.status == "error"
        assert result.exit_code == 125
        assert "missing containment policy" in (result.reason or "")
        executor.exec_prompt.assert_not_called()

    def test_exec_build_blocks_empty_containment_policy(self, tmp_path):
        executor = _executor(status={"status": "done"})
        policy_file = tmp_path / "delivery-containment-policy.json"
        policy_file.write_text("{}", encoding="utf-8")

        result = LlmBuildRunner(executor).exec_build(
            str(tmp_path),
            "build this",
            containment_policy_file=str(policy_file),
        )

        assert result.status == "error"
        assert result.exit_code == 125
        assert "empty containment policy" in (result.reason or "")
        executor.exec_prompt.assert_not_called()

    def test_exec_build_blocks_worktree_outside_allowed_containment_policy(
        self, tmp_path
    ):
        executor = _executor(status={"status": "done"})
        policy_file = tmp_path / "delivery-containment-policy.json"
        policy_file.write_text(
            json.dumps(
                {
                    "allowed_roots": {
                        "implementation": [str(tmp_path / "other-worktree")]
                    }
                }
            ),
            encoding="utf-8",
        )

        result = LlmBuildRunner(executor).exec_build(
            str(tmp_path),
            "build this",
            containment_policy_file=str(policy_file),
        )

        assert result.status == "error"
        assert result.exit_code == 125
        assert "worktree outside containment policy allowed roots" in (
            result.reason or ""
        )
        executor.exec_prompt.assert_not_called()

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

    def test_exec_build_recovers_blocked_legacy_echelon_result_marker(self, tmp_path):
        executor = _executor()

        def write_legacy_result(worktree_path, _prompt, *, extra_env=None):
            del extra_env
            (Path(worktree_path) / "echelon_result.json").write_text(
                json.dumps(
                    {
                        "status": "partial",
                        "verdict": "BLOCKED",
                        "completed_task_ids": ["T-001", "T-002"],
                        "state_updates": {
                            "fulfillment_gap_blocked": "NFR-008 requires an owner spec decision"
                        },
                    }
                ),
                encoding="utf-8",
            )
            return 0

        executor.exec_prompt.side_effect = write_legacy_result

        result = LlmBuildRunner(executor).exec_build(str(tmp_path), "build this")

        assert result.status == "blocked"
        assert result.succeeded is False
        assert result.task_ids == ["T-001", "T-002"]
        assert result.reason == "NFR-008 requires an owner spec decision"

    def test_exec_build_does_not_treat_nonblocking_echelon_result_as_completion(self, tmp_path):
        executor = _executor()

        def write_legacy_result(worktree_path, _prompt, *, extra_env=None):
            del extra_env
            (Path(worktree_path) / "echelon_result.json").write_text(
                json.dumps(
                    {
                        "status": "partial",
                        "verdict": "DONE",
                        "completed_task_ids": ["T-001"],
                    }
                ),
                encoding="utf-8",
            )
            return 0

        executor.exec_prompt.side_effect = write_legacy_result

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

    def test_exec_feedback_exposes_containment_policy_file_when_provided(self, tmp_path):
        executor = _executor(status={"status": "done"})
        policy_file = tmp_path / "delivery-containment-policy.json"
        policy_file.write_text(
            json.dumps({"allowed_roots": {"implementation": [str(tmp_path)]}}),
            encoding="utf-8",
        )

        LlmBuildRunner(executor).exec_feedback(
            str(tmp_path),
            "fix this",
            containment_policy_file=str(policy_file),
        )

        extra_env = executor.exec_prompt.call_args.kwargs["extra_env"]
        assert extra_env["ECHELON_CONTAINMENT_POLICY_FILE"] == str(policy_file)

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

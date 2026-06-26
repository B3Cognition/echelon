"""Tests for CLI host-side LLM tool policy wiring."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest

from echelon import cli
from harness.llm_tool_policy import LlmToolPolicy


@pytest.mark.unit
def test_run_claude_streaming_uses_default_tool_policy_without_dangerous_bypass(tmp_path: Path) -> None:
    captured_cmd: list[str] = []

    class FakeProcess:
        stdin = io.BytesIO()
        stdout = io.BytesIO(b'{"type":"result","is_error":false,"num_turns":0,"duration_ms":0}\n')
        returncode = 0

        def wait(self) -> int:
            return self.returncode

    def fake_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return FakeProcess()

    with patch("echelon.cli.subprocess.Popen", side_effect=fake_popen), pytest.raises(SystemExit) as exc:
        cli._run_claude_streaming(
            "claude",
            "Do the work.",
            tmp_path,
            tool_policy=LlmToolPolicy(),
        )

    assert exc.value.code == 0
    assert "--dangerously-skip-permissions" not in captured_cmd
    assert "--output-format" in captured_cmd

"""Tests for _cmd_harness_run argument parsing in cli.py.

Covers the free-text task description capture introduced to fix the bug
where 'echelon harness run 013 strategy=codegen "do X"' silently dropped "do X".
"""

from __future__ import annotations

import pytest

from harness.run_intent import parse_intent


@pytest.mark.unit
class TestHarnessRunArgParsing:
    """Verify the user_message built by _cmd_harness_run reaches parse_intent correctly."""

    def _build_user_message(self, args: list[str]) -> str:
        """Replicate the user_message construction logic from _cmd_harness_run."""
        spec_id = args[0]
        kv: dict[str, str] = {}
        free_text: list[str] = []
        for arg in args[1:]:
            if "=" in arg:
                k, _, v = arg.partition("=")
                kv[k.strip()] = v.strip()
            else:
                free_text.append(arg)
        strategy = kv.get("strategy", "default")
        mode = kv.get("mode", "semi")
        parts = [f"spec {spec_id}", f"{mode} mode", f"strategies={strategy}"]
        if free_text:
            parts.append(f"task: {' '.join(free_text)}")
        return " ".join(parts)

    def test_free_text_becomes_task_description(self) -> None:
        """Free-text arg is forwarded as task_description through parse_intent."""
        msg = self._build_user_message(
            ["013", "strategy=codegen", "fix the bug as described in 'bugfix-1.md'"]
        )
        intent = parse_intent(msg)
        assert intent.task_description == "fix the bug as described in 'bugfix-1.md'"
        assert intent.spec_id == "013"
        assert intent.strategies == ["codegen"]

    def test_no_free_text_gives_empty_task_description(self) -> None:
        """When only kv args are given, task_description is empty."""
        msg = self._build_user_message(["013", "strategy=codegen"])
        intent = parse_intent(msg)
        assert intent.task_description == ""

    def test_multiple_free_text_words_joined(self) -> None:
        """Multiple free-text tokens are joined into a single task_description."""
        msg = self._build_user_message(["013", "implement", "feature", "X"])
        intent = parse_intent(msg)
        assert intent.task_description == "implement feature X"

    def test_kv_args_not_leaked_into_task(self) -> None:
        """key=value pairs are not included in task_description."""
        msg = self._build_user_message(["013", "mode=banzai", "strategy=default", "do the thing"])
        intent = parse_intent(msg)
        assert intent.task_description == "do the thing"
        assert intent.mode == "banzai"
        assert "mode=banzai" not in intent.task_description

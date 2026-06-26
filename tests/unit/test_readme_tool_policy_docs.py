"""Regression tests for public host LLM tool-policy documentation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"


def test_readme_does_not_document_unconditional_dangerous_claude_bypass() -> None:
    text = README.read_text(encoding="utf-8")

    assert "claude -p <prompt> --dangerously-skip-permissions" not in text
    assert "allow_unsafe_host_execution: true" in text
    assert "approval_reason" in text
    assert "fail-closed" in text

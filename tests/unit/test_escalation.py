"""Tests for EscalationHandler.

Per T030 task specification:
- Test escalation file creation and content structure
- Test check_resume with/without answer
- Test resume appends correctly
- Test invalid category rejection
"""

from __future__ import annotations

import os
import json
from pathlib import Path

import pytest

from harness.escalation import (
    EscalationHandler,
    InvalidCategoryError,
    VALID_CATEGORIES,
)


def _json_section(content: str, heading: str) -> dict:
    start = content.index(f"## {heading}")
    fence_start = content.index("```json", start) + len("```json")
    fence_end = content.index("```", fence_start)
    return json.loads(content[fence_start:fence_end].strip())


@pytest.fixture
def escalation_dir(tmp_path: Path) -> Path:
    """Provide a temporary escalation directory."""
    return tmp_path / "harness"


@pytest.fixture
def handler(escalation_dir: Path) -> EscalationHandler:
    """Create an EscalationHandler with temp directory."""
    return EscalationHandler(str(escalation_dir))


@pytest.mark.unit
class TestEscalationFileCreation:
    """Test escalation file writing."""

    def test_creates_file_at_correct_path(self, handler: EscalationHandler) -> None:
        filepath = handler.escalate(
            spec_id="012",
            strategy_id="default",
            category="same_failure_repeat",
            context="3 identical failures in inner loop",
        )
        assert Path(filepath).exists()
        assert "012-default-" in filepath
        assert filepath.endswith(".md")

    def test_file_contains_all_required_fields(
        self, handler: EscalationHandler
    ) -> None:
        filepath = handler.escalate(
            spec_id="012",
            strategy_id="aggressive",
            category="infra_failure",
            context="Docker daemon not responding",
            question="Should we retry or abort?",
            options_considered=["Retry after 30s", "Abort and notify"],
            recommended_answer="Retry after 30s",
            last_verify_result={"passed": False, "failures": []},
        )
        content = Path(filepath).read_text(encoding="utf-8")

        assert "# Escalation: infra_failure" in content
        assert "**Spec:** 012" in content
        assert "**Strategy:** aggressive" in content
        assert "**Category:** infra_failure" in content
        assert "**Timestamp:**" in content
        assert "## Question" in content
        assert "Should we retry or abort?" in content
        assert "## Context" in content
        assert "Docker daemon not responding" in content
        assert "## Options Considered" in content
        assert "Retry after 30s" in content
        assert "## Recommended Answer" in content
        assert "## Last Verify Result" in content
        assert "echelon harness resume 012" in content
        assert "/speckit-harness-resume" not in content

    def test_file_contains_machine_readable_decision_metadata(
        self, handler: EscalationHandler
    ) -> None:
        filepath = handler.escalate(
            spec_id="012",
            strategy_id="aggressive",
            category="infra_failure",
            context="Docker daemon not responding",
            question="Should we retry or abort?",
            options_considered=["Retry after 30s", "Abort and notify"],
            recommended_answer="Retry after 30s",
        )

        metadata = _json_section(Path(filepath).read_text(encoding="utf-8"), "Decision Metadata")
        assert metadata["schema_version"] == 1
        assert metadata["answer_type"] == "free_text"
        assert metadata["question"] == "Should we retry or abort?"
        assert metadata["options_considered"] == ["Retry after 30s", "Abort and notify"]
        assert metadata["recommended_answer"] == "Retry after 30s"

    def test_banner_printed_to_stderr(
        self, handler: EscalationHandler, capsys: pytest.CaptureFixture
    ) -> None:
        handler.escalate(
            spec_id="012",
            strategy_id="default",
            category="same_failure_repeat",
            context="Repeated failure",
        )
        captured = capsys.readouterr()
        assert "BLOCKED" in captured.err
        assert "same_failure_repeat" in captured.err
        assert "echelon harness resume 012" in captured.err
        assert "/speckit-harness-resume" not in captured.err

    def test_all_valid_categories_accepted(
        self, handler: EscalationHandler
    ) -> None:
        for category in VALID_CATEGORIES:
            filepath = handler.escalate(
                spec_id="012",
                strategy_id="default",
                category=category,
                context=f"Test context for {category}",
            )
            assert Path(filepath).exists()


@pytest.mark.unit
class TestInvalidCategory:
    """Test category validation."""

    def test_invalid_category_raises(self, handler: EscalationHandler) -> None:
        with pytest.raises(InvalidCategoryError, match="Invalid escalation category"):
            handler.escalate(
                spec_id="012",
                strategy_id="default",
                category="invalid_category",
                context="test",
            )

    def test_empty_category_raises(self, handler: EscalationHandler) -> None:
        with pytest.raises(InvalidCategoryError):
            handler.escalate(
                spec_id="012",
                strategy_id="default",
                category="",
                context="test",
            )


@pytest.mark.unit
class TestCheckResume:
    """Test check_resume with/without answer."""

    def test_returns_none_when_no_answer(
        self, handler: EscalationHandler
    ) -> None:
        filepath = handler.escalate(
            spec_id="012",
            strategy_id="default",
            category="same_failure_repeat",
            context="test",
        )
        assert handler.check_resume(filepath) is None

    def test_returns_answer_when_present(
        self, handler: EscalationHandler
    ) -> None:
        filepath = handler.escalate(
            spec_id="012",
            strategy_id="default",
            category="same_failure_repeat",
            context="test",
        )
        # Simulate user adding answer
        content = Path(filepath).read_text(encoding="utf-8")
        content += "\n\n## Answer\n\nTry a different approach using mock objects.\n"
        Path(filepath).write_text(content, encoding="utf-8")

        answer = handler.check_resume(filepath)
        assert answer is not None
        assert "different approach" in answer

    def test_returns_none_for_nonexistent_file(
        self, handler: EscalationHandler
    ) -> None:
        assert handler.check_resume("/nonexistent/path.md") is None

    def test_returns_none_for_empty_answer_section(
        self, handler: EscalationHandler
    ) -> None:
        filepath = handler.escalate(
            spec_id="012",
            strategy_id="default",
            category="same_failure_repeat",
            context="test",
        )
        content = Path(filepath).read_text(encoding="utf-8")
        content += "\n\n## Answer\n\n"
        Path(filepath).write_text(content, encoding="utf-8")

        assert handler.check_resume(filepath) is None


@pytest.mark.unit
class TestResume:
    """Test resume appends correctly."""

    def test_resume_appends_answer(self, handler: EscalationHandler) -> None:
        filepath = handler.escalate(
            spec_id="012",
            strategy_id="default",
            category="same_failure_repeat",
            context="test",
        )
        handler.resume(filepath, "Use retry with exponential backoff")

        content = Path(filepath).read_text(encoding="utf-8")
        assert "## Answer" in content
        assert "Use retry with exponential backoff" in content
        assert "Answered at:" in content

    def test_resume_answer_readable_by_check_resume(
        self, handler: EscalationHandler
    ) -> None:
        filepath = handler.escalate(
            spec_id="012",
            strategy_id="default",
            category="same_failure_repeat",
            context="test",
        )
        handler.resume(filepath, "Switch to mock provider")

        answer = handler.check_resume(filepath)
        assert answer is not None
        assert "Switch to mock provider" in answer

    def test_resume_appends_machine_readable_resume_metadata(
        self, handler: EscalationHandler
    ) -> None:
        filepath = handler.escalate(
            spec_id="012",
            strategy_id="default",
            category="same_failure_repeat",
            context="test",
        )
        handler.resume(filepath, "Switch to mock provider")

        metadata = _json_section(Path(filepath).read_text(encoding="utf-8"), "Resume Metadata")
        assert metadata["schema_version"] == 1
        assert metadata["answer_type"] == "free_text"
        assert metadata["answer"] == "Switch to mock provider"
        assert metadata["source"] == "echelon-harness-resume"

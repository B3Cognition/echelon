"""Tests for EscalationHandler.

Per T030 task specification:
- Test escalation file creation and content structure
- Test check_resume with/without answer
- Test resume appends correctly
- Test invalid category rejection
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.escalation import (
    EscalationHandler,
    InvalidCategoryError,
    VALID_CATEGORIES,
)


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
        assert "/speckit-harness-resume" in content

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
        assert "/speckit-harness-resume" in captured.err

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

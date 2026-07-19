"""Tests for terminal banner output.

Per T037 task specification:
- Banner output content verification
- NO_COLOR suppresses formatting
"""

from __future__ import annotations

import io
import os

import pytest

from harness.terminal import color_text, print_banner, print_escalation_banner


class _TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.unit
class TestBanner:
    """Test banner output."""

    def test_banner_contains_header_and_body(self) -> None:
        buf = io.StringIO()
        print_banner("TEST HEADER", "Test body content", file=buf, width=80)
        output = buf.getvalue()
        assert "TEST HEADER" in output
        assert "Test body content" in output
        assert "=" * 80 in output

    def test_banner_adapts_to_width(self) -> None:
        buf = io.StringIO()
        print_banner("HEAD", "Body", file=buf, width=40)
        output = buf.getvalue()
        assert "=" * 40 in output
        assert "=" * 80 not in output

    def test_banner_with_footer(self) -> None:
        buf = io.StringIO()
        print_banner("HEAD", "Body", footer="Run /resume", file=buf, width=80)
        output = buf.getvalue()
        assert "/resume" in output


@pytest.mark.unit
class TestEscalationBanner:
    """Test escalation-specific banner."""

    def test_escalation_banner_content(self) -> None:
        buf = io.StringIO()
        print_escalation_banner(
            category="same_failure_repeat",
            question="How to proceed?",
            context="3 identical failures",
            spec_id="001-demo",
            file=buf,
        )
        output = buf.getvalue()
        assert "BLOCKED" in output
        assert "same_failure_repeat" in output
        assert "How to proceed?" in output
        assert "3 identical failures" in output
        assert "echelon delivery resume 001-demo" in output
        assert "/speckit-harness-resume" not in output

    def test_escalation_banner_to_stderr(self, capsys: pytest.CaptureFixture) -> None:
        import sys
        print_escalation_banner(
            category="infra_failure",
            question="Docker down?",
            context="Container creation failed",
        )
        captured = capsys.readouterr()
        assert "BLOCKED" in captured.err
        assert "infra_failure" in captured.err


@pytest.mark.unit
class TestColorText:
    """Test ANSI styling helper for Echelon-owned terminal output."""

    def test_known_color_styles_text_on_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)

        styled = color_text("CHIEF", "blue", file=_TTYBuffer())

        assert styled == "\033[34mCHIEF\033[0m"

    def test_no_color_disables_styling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")

        styled = color_text("CHIEF", "blue", file=_TTYBuffer())

        assert styled == "CHIEF"

    def test_unknown_color_returns_plain_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)

        styled = color_text("CHIEF", "sparkle", file=_TTYBuffer())

        assert styled == "CHIEF"

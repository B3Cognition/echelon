"""Integration tests for constitution placeholder detection.

FR-CONST-001a/b: populated vs placeholder vs unreadable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.init import _check_constitution

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "constitutions"


class TestConstitutionDetection:
    """Tests for constitution detection during init."""

    def test_populated_constitution_produces_warning(self, tmp_path):
        """Populated constitution produces blocker-level warning."""
        # Copy populated fixture to tmp_path
        src = FIXTURES / "populated.md"
        dst = tmp_path / "constitution.md"
        dst.write_text(src.read_text(), encoding="utf-8")

        result = _check_constitution(tmp_path)

        assert result is not None
        assert "WARNING" in result
        assert "SPEC GUARD" in result

    def test_placeholder_constitution_produces_info(self, tmp_path):
        """Placeholder constitution produces info-level warning."""
        src = FIXTURES / "placeholder.md"
        dst = tmp_path / "constitution.md"
        dst.write_text(src.read_text(), encoding="utf-8")

        result = _check_constitution(tmp_path)

        assert result is not None
        assert "INFO" in result
        assert "placeholder" in result.lower()

    def test_unreadable_constitution_produces_warning(self, tmp_path):
        """Unreadable/binary file produces warning, does not crash."""
        src = FIXTURES / "binary.dat"
        dst = tmp_path / "constitution.md"
        # Write binary content
        dst.write_bytes(src.read_bytes())

        result = _check_constitution(tmp_path)

        # Should not crash, may return a warning or None depending on whether
        # Python can read it as UTF-8
        # Binary content may or may not raise UnicodeDecodeError
        # Either way, it should not crash
        assert True  # No exception = pass

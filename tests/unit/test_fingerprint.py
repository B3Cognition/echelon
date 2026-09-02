"""Tests for target repo language/package-manager fingerprinting.

6 tests covering all 5 language detections + Playwright override.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.fingerprint import Fingerprint, playwright_version, fingerprint_repo


@pytest.mark.unit
class TestFingerprint:
    """Test language detection from marker files."""

    def test_detects_node(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"name": "test"}))
        fp = fingerprint_repo(tmp_path)
        assert fp.language == "node"
        assert "node" in fp.image

    def test_detects_python(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
        fp = fingerprint_repo(tmp_path)
        assert fp.language == "python"
        assert "python" in fp.image

    def test_detects_rust(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]\nname = 'test'\n")
        fp = fingerprint_repo(tmp_path)
        assert fp.language == "rust"
        assert "rust" in fp.image

    def test_detects_go(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example.com/test\ngo 1.22\n")
        fp = fingerprint_repo(tmp_path)
        assert fp.language == "go"
        assert "golang" in fp.image

    def test_unknown_language_is_generic(self, tmp_path: Path) -> None:
        # No marker files
        fp = fingerprint_repo(tmp_path)
        assert fp.language == "generic"
        assert "ubuntu" in fp.image

    def test_playwright_is_detected_with_a_sandbox_browser_image(self, tmp_path: Path) -> None:
        pkg = {
            "name": "test",
            "devDependencies": {"@playwright/test": "^1.42.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))

        fp = fingerprint_repo(tmp_path)
        assert fp.language == "node"
        assert fp.has_playwright is True
        assert fp.image == "mcr.microsoft.com/playwright:v1.42.0-jammy"

    def test_extracts_pinned_playwright_version(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({
            "devDependencies": {"@playwright/test": "1.62.1"},
        }))

        assert playwright_version(tmp_path) == "1.62.1"

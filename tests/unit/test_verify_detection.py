"""Tests for deterministic harness verify_command detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.verify_detection import detect_verify_command


@pytest.mark.unit
class TestVerifyCommandDetection:
    """High-confidence verify_command detection."""

    def test_detects_pnpm_test_script(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest run"}}),
            encoding="utf-8",
        )
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

        result = detect_verify_command(tmp_path)

        assert result.command == "pnpm test"
        assert result.confidence == "high"
        assert "package.json scripts.test" in result.evidence

    def test_rejects_placeholder_node_test_script(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "echo \"Error: no test specified\" && exit 1"}}),
            encoding="utf-8",
        )
        (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")

        result = detect_verify_command(tmp_path)

        assert result.command is None
        assert result.confidence == "none"

    def test_detects_uv_pytest(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[project]\ndependencies = ['pytest']\n",
            encoding="utf-8",
        )
        (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")

        result = detect_verify_command(tmp_path)

        assert result.command == "uv run pytest"
        assert result.confidence == "high"
        assert "pytest marker" in result.evidence

    def test_does_not_treat_non_python_tests_directory_as_pytest(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"units": "jest"}}),
            encoding="utf-8",
        )
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "smoke.wdio.conf.ts").write_text("export const config = {}\n", encoding="utf-8")

        result = detect_verify_command(tmp_path)

        assert result.command is None
        assert result.confidence == "none"

    def test_detects_go_test(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example.test/app\ngo 1.22\n", encoding="utf-8")

        result = detect_verify_command(tmp_path)

        assert result.command == "go test ./..."
        assert result.confidence == "high"

    def test_detects_swift_package_path(self, tmp_path: Path) -> None:
        pkg = tmp_path / "Packages" / "Core"
        pkg.mkdir(parents=True)
        (pkg / "Package.swift").write_text("// swift-tools-version: 5.10\n", encoding="utf-8")

        result = detect_verify_command(tmp_path)

        assert result.command == "swift test --package-path Packages/Core"
        assert result.confidence == "high"

    def test_does_not_guess_when_multiple_markers_conflict(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest run"}}),
            encoding="utf-8",
        )
        (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
        (tmp_path / "go.mod").write_text("module example.test/app\ngo 1.22\n", encoding="utf-8")

        result = detect_verify_command(tmp_path)

        assert result.command is None
        assert result.confidence == "ambiguous"
        assert "multiple high-confidence candidates" in result.reason

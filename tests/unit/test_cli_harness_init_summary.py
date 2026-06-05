"""Tests for harness init detection summary output."""

from __future__ import annotations

from pathlib import Path

import pytest

from echelon.cli import _harness_init_detection_fields


@pytest.mark.unit
class TestHarnessInitDetectionFields:
    """Harness init reports what it detected instead of leaving YAML as the UI."""

    def test_reports_detected_verify_and_command_app_runtime(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "verify_command: npm test\n"
            "harness:\n"
            "  verify_command_detection: high\n"
            "  detected_verify_command: npm test\n"
            "  app_detection: high\n"
            "  app:\n"
            "    enabled: true\n"
            "    mode: command\n"
            "    app: frontend\n"
            "    url: http://localhost:3000\n",
            encoding="utf-8",
        )

        fields = _harness_init_detection_fields(config_file)

        assert ("Verify", "npm test (auto-detected)") in fields
        assert ("App runtime", "frontend via command at http://localhost:3000 (auto-detected)") in fields

    def test_reports_detection_reasons_when_harness_declines(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "harness:\n"
            "  verify_command_detection: ambiguous\n"
            "  verify_command_reason: multiple test ecosystems found\n"
            "  app_detection: none\n"
            "  app_reason: no Dockerfile, compose file, or frontend dev target detected\n",
            encoding="utf-8",
        )

        fields = _harness_init_detection_fields(config_file)

        assert ("Verify", "not configured - ambiguous: multiple test ecosystems found") in fields
        assert (
            "App runtime",
            "not configured - none: no Dockerfile, compose file, or frontend dev target detected",
        ) in fields

    def test_reports_manual_settings_without_auto_detection_metadata(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "verify_command: pytest\n"
            "harness:\n"
            "  app:\n"
            "    enabled: true\n"
            "    mode: docker_compose\n"
            "    service: web\n"
            "    url: http://localhost:8080\n",
            encoding="utf-8",
        )

        fields = _harness_init_detection_fields(config_file)

        assert ("Verify", "pytest (configured)") in fields
        assert ("App runtime", "web via docker_compose at http://localhost:8080 (configured)") in fields

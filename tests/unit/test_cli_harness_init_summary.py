"""Tests for harness init detection summary output."""

from __future__ import annotations

from pathlib import Path

import pytest

from echelon.cli import _harness_init_detection_fields, _harness_init_next_step


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

    def test_reports_sandbox_suggestion_approval_point(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "harness:\n"
            "  sandbox_suggestion:\n"
            "    confidence: high\n"
            "    confidence_score: 0.95\n"
            "    suggested_strategy: Use the Docker-backed harness sandbox.\n"
            "    human_approval_point: Before dependency install or app execution, approve the sandbox plan.\n",
            encoding="utf-8",
        )

        fields = _harness_init_detection_fields(config_file)

        assert (
            "Sandbox",
            "high (0.95) - Use the Docker-backed harness sandbox. Approval: Before dependency install or app execution, approve the sandbox plan.",
        ) in fields
        assert ("Sandbox report", str(config_file.with_name("sandbox-suggestion.md"))) in fields

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

    def test_init_next_step_blocks_harness_run_when_verify_detection_declined(
        self,
        tmp_path: Path,
    ) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "harness:\n"
            "  verify_command_detection: none\n"
            "  verify_command_reason: no high-confidence test runner detected\n",
            encoding="utf-8",
        )

        next_step = _harness_init_next_step(config_file)

        assert "set top-level verify_command before harness build" in next_step
        assert "no high-confidence test runner detected" in next_step
        assert "verify_command: pytest" in next_step
        assert not next_step.startswith("echelon run")

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

    def test_init_next_step_allows_harness_run_when_verify_is_configured(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("verify_command: pytest\n", encoding="utf-8")

        next_step = _harness_init_next_step(config_file)

        assert next_step == 'echelon run "<feature>"\n  echelon harness run <spec_id>'

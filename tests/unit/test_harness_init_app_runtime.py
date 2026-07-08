"""Tests for app runtime profile wiring during harness initialization."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness.init import _apply_app_runtime_detection


@pytest.mark.unit
class TestHarnessInitAppRuntime:
    """Harness init writes only high-confidence app runtime profiles."""

    def test_writes_high_confidence_app_profile(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "harness:\n  provider: docker\n",
            encoding="utf-8",
        )
        (tmp_path / "Dockerfile").write_text("FROM nginx:alpine\nEXPOSE 80\n", encoding="utf-8")

        result = _apply_app_runtime_detection(config_file, tmp_path)

        data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert result.profile is not None
        assert data["harness"]["app"]["mode"] == "dockerfile"
        assert data["harness"]["app"]["container_port"] == 80
        assert data["harness"]["app_detection"] == "high"

    def test_preserves_existing_app_profile(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "harness:\n"
            "  provider: docker\n"
            "  app:\n"
            "    enabled: true\n"
            "    mode: manual\n"
            "    start_command: ./scripts/start-preview.sh\n",
            encoding="utf-8",
        )
        (tmp_path / "Dockerfile").write_text("FROM nginx:alpine\nEXPOSE 80\n", encoding="utf-8")

        result = _apply_app_runtime_detection(config_file, tmp_path)

        data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert result.confidence == "existing"
        assert data["harness"]["app"]["mode"] == "manual"
        assert data["harness"]["app_detection"] == "existing"

    def test_records_ambiguous_detection_without_writing_app(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "harness:\n  provider: docker\n",
            encoding="utf-8",
        )
        (tmp_path / "docker-compose.yml").write_text(
            """
services:
  web:
    ports: ["3000:3000"]
  admin:
    ports: ["4000:4000"]
""",
            encoding="utf-8",
        )

        result = _apply_app_runtime_detection(config_file, tmp_path)

        data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert result.profile is None
        assert "app" not in data["harness"]
        assert data["harness"]["app_detection"] == "ambiguous"

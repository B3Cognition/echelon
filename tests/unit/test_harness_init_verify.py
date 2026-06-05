"""Tests for verify_command wiring during harness initialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from harness.config import load_config
from harness.init import _apply_verify_command_detection


@pytest.mark.unit
class TestHarnessInitVerifyCommand:
    """Harness init writes only high-confidence verify_command values."""

    def test_writes_high_confidence_verify_command_at_top_level(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "harness:\n  target_repo: .\n  target_default_branch: main\n  provider: docker\n",
            encoding="utf-8",
        )
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest run"}}),
            encoding="utf-8",
        )
        (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")

        result = _apply_verify_command_detection(config_file, tmp_path)

        data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert result.command == "npm test"
        assert data["verify_command"] == "npm test"
        assert data["harness"]["detected_verify_command"] == "npm test"

    def test_preserves_existing_verify_command(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "verify_command: custom test\n"
            "harness:\n  target_repo: .\n  target_default_branch: main\n  provider: docker\n",
            encoding="utf-8",
        )
        (tmp_path / "go.mod").write_text("module example.test/app\ngo 1.22\n", encoding="utf-8")

        result = _apply_verify_command_detection(config_file, tmp_path)

        data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert result.command == "custom test"
        assert data["verify_command"] == "custom test"
        assert data["harness"]["detected_verify_command"] == "custom test"
        assert data["harness"]["verify_command_detection"] == "existing"

    def test_does_not_write_ambiguous_verify_command(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "harness:\n  target_repo: .\n  target_default_branch: main\n  provider: docker\n",
            encoding="utf-8",
        )
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest run"}}),
            encoding="utf-8",
        )
        (tmp_path / "go.mod").write_text("module example.test/app\ngo 1.22\n", encoding="utf-8")

        result = _apply_verify_command_detection(config_file, tmp_path)

        data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert result.command is None
        assert "verify_command" not in data
        assert data["harness"]["verify_command_detection"] == "ambiguous"


@pytest.mark.unit
def test_load_config_reads_top_level_verify_command_with_harness_section(tmp_path: Path) -> None:
    config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        "verify_command: pytest\n"
        "harness:\n"
        "  target_repo: .\n"
        "  target_default_branch: main\n"
        "  provider: docker\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.verify_command == "pytest"

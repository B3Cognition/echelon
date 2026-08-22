"""Tests for verify_command wiring during harness initialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from harness.config import load_config
from harness.init import (
    _apply_verify_command_detection,
    _harness_config_file,
    _write_local_llm_config,
)


@pytest.mark.unit
class TestHarnessInitVerifyCommand:
    """Harness init writes only high-confidence verify_command values."""

    def test_writes_high_confidence_verify_command_at_top_level(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "harness:\n  provider: docker\n",
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
            "harness:\n  provider: docker\n",
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
            "harness:\n  provider: docker\n",
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
    config_file = tmp_path / ".echelon" / "config.yml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        "verify_command: pytest\n"
        "harness:\n"
        "  provider: docker\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.verify_command == "pytest"


@pytest.mark.unit
def test_harness_init_uses_canonical_config_for_new_workspace(tmp_path: Path) -> None:
    config_file = _harness_config_file(tmp_path)

    assert config_file == tmp_path / ".echelon" / "config.yml"


@pytest.mark.unit
def test_harness_init_uses_canonical_config_for_legacy_workspace(tmp_path: Path) -> None:
    legacy = tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "harness:\n  provider: docker\n",
        encoding="utf-8",
    )

    config_file = _harness_config_file(tmp_path)

    assert config_file == tmp_path / ".echelon" / "config.yml"


@pytest.mark.unit
def test_harness_init_writes_detected_llm_provider_to_local_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ECHELON_LLM", raising=False)

    _write_local_llm_config(
        tmp_path,
        detected_cli="codex",
    )

    local = yaml.safe_load((tmp_path / ".echelon" / "local.yml").read_text(encoding="utf-8"))
    assert local["harness"]["llm"]["cli"] == "codex"


@pytest.mark.unit
def test_harness_init_env_llm_overrides_local_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ECHELON_LLM", "opencode")
    local_path = tmp_path / ".echelon" / "local.yml"
    local_path.parent.mkdir(parents=True)
    local_path.write_text("harness:\n  llm:\n    cli: codex\n", encoding="utf-8")

    _write_local_llm_config(
        tmp_path,
        detected_cli="claude",
    )

    local = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    assert local["harness"]["llm"]["cli"] == "opencode"

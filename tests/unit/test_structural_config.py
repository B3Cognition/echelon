"""Structural tests for the shipped Echelon runtime configuration."""
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_governance_artifacts_present():
    g = yaml.safe_load(
        (ROOT / "runtime/echelon-config.yml").read_text(encoding="utf-8")
    )["governance"]
    assert g["enabled"] is True
    assert g["artifacts"]["feasibility"]["verdict"]["enum"] == ["PASS", "KILL", "DEFER"]
    assert g["artifacts"]["intent-alignment-check"]["template"] == "intent-alignment-check-template.md"


@pytest.mark.unit
@pytest.mark.parametrize(
    "relative_path",
    ["runtime/echelon-config.yml", "runtime/config-template.yml"],
)
def test_agent_timeout_defaults_to_one_hour(
    relative_path: str,
) -> None:
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    config = yaml.safe_load(text)

    assert config["execution"]["agent_timeout_seconds"] == 3600
    assert "longer timeout under harness.llm.timeout_ms" in text

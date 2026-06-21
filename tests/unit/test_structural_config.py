"""Unit tests for the governance.artifacts config block in echelon-config.yml."""
import pytest
import yaml


@pytest.mark.unit
def test_governance_artifacts_present():
    g = yaml.safe_load(open("extension/echelon-config.yml"))["governance"]
    assert g["enabled"] is True
    assert g["artifacts"]["feasibility"]["verdict"]["enum"] == ["PASS", "KILL", "DEFER"]
    assert g["artifacts"]["intent-alignment-check"]["template"] == "intent-alignment-check-template.md"

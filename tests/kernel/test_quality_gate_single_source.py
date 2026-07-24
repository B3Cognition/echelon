"""Static contracts preventing quality-gate threshold drift in prompts."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_sage_workflow_uses_runtime_resolved_quality_gates() -> None:
    why2 = (ROOT / "extension/workflow/phases/phase1-why2.md").read_text(
        encoding="utf-8"
    )
    init = (ROOT / "extension/workflow/phases/init.md").read_text(encoding="utf-8")
    command = (
        ROOT / "extension/commands/echelon.understanding-validate.md"
    ).read_text(encoding="utf-8")

    assert "Quality gates: overall >= 0.70" not in why2
    assert "Quality gates: overall >= 0.70" not in init
    assert "| Overall | >= 0.70" not in command
    assert "Resolved Quality Gates" in why2
    assert "thresholds from resolved project" in why2
    assert "values and verdicts are authoritative" in why2
    assert "resolved project configuration" in command


def test_sage_belief_defers_to_authoritative_config_without_numeric_copy() -> None:
    belief_path = ROOT / "extension/config/belief-registers/sage.yaml"
    belief = yaml.safe_load(belief_path.read_text(encoding="utf-8"))
    sag_001 = next(item for item in belief["beliefs"] if item["id"] == "SAG-001")

    assert "echelon-config.yml" in sag_001["claim"]
    assert ">=" not in sag_001["claim"]
    assert "0.70" not in sag_001["claim"]

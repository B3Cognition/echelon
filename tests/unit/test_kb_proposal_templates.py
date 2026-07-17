"""Contract tests for KB proposal templates."""

from __future__ import annotations

from pathlib import Path

import yaml

from echelon.kb_proposals import validate_proposal_document


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates" / "kb-proposals"


def test_kb_proposal_templates_parse_and_validate() -> None:
    templates = sorted(TEMPLATE_DIR.glob("*.yaml"))
    assert {path.name for path in templates} == {
        "calibration-observation-proposal-template.yaml",
        "internalization-observation-proposal-template.yaml",
        "pattern-proposal-template.yaml",
        "pitfall-proposal-template.yaml",
        "sage-decision-proposal-template.yaml",
    }
    for path in templates:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        result = validate_proposal_document(path.name, data, expected_run_id="squad-template")
        assert result.ok, (path.name, result.issues)

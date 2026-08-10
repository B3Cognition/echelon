"""Contract tests for KB proposal templates."""

from __future__ import annotations

from pathlib import Path

import yaml

from codegen.memory.kb_schema_validator import validate_kb_document
from echelon.kb_proposals import validate_proposal_document


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "runtime" / "templates" / "kb-proposals"


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


def test_sage_decision_template_sets_initial_correctness() -> None:
    data = yaml.safe_load(
        (TEMPLATE_DIR / "sage-decision-proposal-template.yaml").read_text(encoding="utf-8")
    )

    assert data["payload"]["was_correct"] is True


def test_sage_decision_template_payload_is_canonically_valid() -> None:
    data = yaml.safe_load(
        (TEMPLATE_DIR / "sage-decision-proposal-template.yaml").read_text(encoding="utf-8")
    )
    entry = {
        "run_id": data["run_id"],
        "source": data["agent"],
        "created_at": data["created_at"],
        **data["payload"],
    }

    result = validate_kb_document(
        "sage-decisions.yaml",
        {"schema_version": 2, "append_only": True, "entries": [entry]},
    )

    assert result.ok, result.issues

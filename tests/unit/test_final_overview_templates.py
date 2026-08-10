"""Templates and schema for final Phase A overview artifacts."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "runtime" / "templates"
PHASE4 = ROOT / "runtime" / "workflow" / "phases" / "phase4-document.md"


def test_final_overview_template_exists_with_required_sections() -> None:
    text = (TEMPLATE_DIR / "00-overview-template.md").read_text(encoding="utf-8")

    for anchor in (
        "## What This Builds",
        "## Delivery Sequence",
        "## Dependencies to Control First",
        "## Partial Result Target",
        "## Stop and Ask",
    ):
        assert anchor in text


def test_plan_conformance_template_exists_with_required_checks() -> None:
    text = (TEMPLATE_DIR / "plan-conformance-template.md").read_text(
        encoding="utf-8"
    )

    for anchor in (
        "## Summary",
        "## Requirement Coverage",
        "## Plan and Task Traceability",
        "## MVP and Deferred Scope Alignment",
        "## Overview Backing Check",
        "## Findings",
    ):
        assert anchor in text


def test_plan_conformance_schema_requires_status_findings_and_sources() -> None:
    schema = json.loads(
        (TEMPLATE_DIR / "plan-conformance.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert schema["type"] == "object"
    assert set(schema["required"]) >= {"status", "findings", "sources"}
    assert schema["properties"]["status"]["enum"] == ["pass", "needs_repair"]
    assert schema["additionalProperties"] is False


def test_phase4_document_references_final_artifact_templates_and_schema() -> None:
    text = PHASE4.read_text(encoding="utf-8")

    assert ".echelon/runtime/templates/00-overview-template.md" in text
    assert ".echelon/runtime/templates/plan-conformance-template.md" in text
    assert ".echelon/runtime/templates/plan-conformance.schema.json" in text

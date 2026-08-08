"""Contracts for Echelon-owned constitution authoring in the Prosaic runtime."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
CHIEF = ROOT / "prosaic" / "subagents" / "echelon.chief.md"


def test_runtime_supplies_a_generic_constitution_template() -> None:
    text = (RUNTIME / "templates" / "constitution-template.md").read_text(
        encoding="utf-8"
    )

    for heading in (
        "# [PROJECT_NAME] Constitution",
        "## Core Principles",
        "## Project Constraints",
        "## Delivery and Quality Gates",
        "## Governance",
    ):
        assert heading in text

    for marker in (
        "[PRINCIPLE_1_NAME]",
        "[PRINCIPLE_1_RULE]",
        "[PRINCIPLE_1_RATIONALE]",
        "[CONSTITUTION_VERSION]",
        "[RATIFICATION_DATE]",
        "[LAST_AMENDED_DATE]",
    ):
        assert marker in text

    assert "MUST" in text
    assert "semantic versioning" in text.lower()


def test_chief_uses_the_runtime_template_and_reports_repair_attempts() -> None:
    text = CHIEF.read_text(encoding="utf-8")

    assert ".echelon/runtime/templates/constitution-template.md" in text
    assert "repair_attempted" in text
    assert "skill_retry_used" not in text


def test_runtime_journal_schema_records_repair_attempts() -> None:
    schema = yaml.safe_load(
        (RUNTIME / "workflow" / "journal-entry-types.yaml").read_text(encoding="utf-8")
    )
    fields = schema["types"]["constitution_created"]["required_data_fields"]

    assert "repair_attempted" in fields
    assert "skill_retry_used" not in fields


def test_runtime_finalize_publishes_the_echelon_constitution() -> None:
    text = (RUNTIME / "scripts" / "bash" / "finalize-run.sh").read_text(
        encoding="utf-8"
    )

    assert 'CONSTITUTION_SRC="${PROJECT_ROOT}/.echelon/constitution.md"' in text
    assert "speckit.constitution" not in text
    assert ".specify/memory/constitution.md" not in text

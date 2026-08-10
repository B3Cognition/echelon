"""Tests for canonical plan.md templates and contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from kernel.plan_contract import validate_plan_markdown


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "runtime" / "templates"


@pytest.mark.unit
class TestPlanTemplates:
    def test_plan_template_contains_required_sections(self) -> None:
        text = (TEMPLATE_DIR / "plan-template.md").read_text(encoding="utf-8")

        result = validate_plan_markdown(text)

        assert result.valid is True
        assert result.errors == []
        assert "## Plan Section Contract" in text
        assert "## Requirement Preservation" in text
        assert "| Requirement | Product Invariant | Architecture Decision | Preserves? | Evidence |" in text

    def test_plan_template_keeps_domain_sections_bounded(self) -> None:
        text = (TEMPLATE_DIR / "plan-template.md").read_text(encoding="utf-8")

        assert len(text.splitlines()) < 180
        assert "TBD" not in text

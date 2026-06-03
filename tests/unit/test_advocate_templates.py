from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "specialists" / "advocate.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase3-specialists.md"


class TestAdvocateTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "accessibility-requirements-template.md",
                [
                    "## WCAG AA Checklist",
                    "| Criterion | Status | Impact | Requirement / Fix |",
                    "## Component Requirements",
                    "## Assistive Technology Test Plan",
                ],
            ),
            (
                "user-flow-template.md",
                [
                    "## Primary Journeys",
                    "## Error State Flows",
                    "## Empty and Loading States",
                    "## Decision Points",
                ],
            ),
            (
                "ux-amendments-template.md",
                [
                    "## Spec Amendments",
                    "| Area | Requirement | User Impact | Priority |",
                    "## Error Messages",
                    "## Interaction Requirements",
                ],
            ),
        ],
    )
    def test_templates_exist_with_required_anchors(
        self, filename: str, anchors: list[str]
    ) -> None:
        text = (TEMPLATE_DIR / filename).read_text(encoding="utf-8")

        for anchor in anchors:
            assert anchor in text

    def test_advocate_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "accessibility-requirements-template.md",
            "user-flow-template.md",
            "ux-amendments-template.md",
        ]:
            assert f"extension/templates/{filename}" in text

        assert "ux-report.md" not in text

    def test_phase3_specialist_dispatch_includes_advocate_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/accessibility-requirements-template.md" in text
        assert "extension/templates/user-flow-template.md" in text
        assert "extension/templates/ux-amendments-template.md" in text

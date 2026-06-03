from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "exploration" / "scout.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase1-discover.md"


class TestScoutTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "glossary-template.md",
                ["# Domain Glossary", "## Terms", "## Overloaded Terms"],
            ),
            (
                "mental-model-template.md",
                ["# Mental Model", "## Core Entities", "## Relationships", "## Behavioral Patterns"],
            ),
            (
                "boundaries-template.md",
                ["# System Boundaries", "## Internal Boundaries", "## External Boundaries", "## Trust Boundaries"],
            ),
            (
                "assumptions-template.md",
                ["# Assumptions", "## Critical Assumptions", "## Standard Assumptions", "## Low-Risk Assumptions"],
            ),
            (
                "unknowns-template.md",
                ["# Unknowns", "## Known Unknowns", "## Potential Unknown Unknowns"],
            ),
            (
                "reference-architectures-template.md",
                ["# Reference Architectures", "## Common Patterns Across References", "## Divergence Points"],
            ),
        ],
    )
    def test_templates_exist_with_required_anchors(
        self, filename: str, anchors: list[str]
    ) -> None:
        text = (TEMPLATE_DIR / filename).read_text(encoding="utf-8")

        for anchor in anchors:
            assert anchor in text

    def test_scout_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "glossary-template.md",
            "mental-model-template.md",
            "boundaries-template.md",
            "assumptions-template.md",
            "unknowns-template.md",
            "reference-architectures-template.md",
        ]:
            assert f"extension/templates/{filename}" in text

        assert "```markdown\n# Domain Glossary" not in text
        assert ".specify/..." not in text

    def test_phase1_discover_dispatch_includes_scout_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/glossary-template.md" in text
        assert "extension/templates/mental-model-template.md" in text
        assert "extension/templates/boundaries-template.md" in text
        assert "extension/templates/assumptions-template.md" in text
        assert "extension/templates/unknowns-template.md" in text
        assert "extension/templates/reference-architectures-template.md" in text

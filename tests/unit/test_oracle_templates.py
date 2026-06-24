from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "specialists" / "oracle.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase3-specialists.md"


class TestOracleTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "domain-patterns-template.md",
                [
                    "## Domain Identification",
                    "## Applicable Patterns",
                    "| Pattern | Applies? | Rationale | Evidence / Source |",
                    "## Common Pitfalls",
                ],
            ),
            (
                "domain-amendments-template.md",
                [
                    "## Spec Amendments",
                    "## Plan Amendments",
                    "## Glossary Amendments",
                    "| Artifact | Amendment | Reason | Priority |",
                ],
            ),
            (
                "compliance-gaps-template.md",
                [
                    "## COMPLIANCE_GAP Items",
                    "| ID | Requirement | Source / Date | Gap | Blocking? |",
                    "## Regulatory Volatility",
                ],
            ),
            (
                "terminology-corrections-template.md",
                [
                    "## Corrections",
                    "| Term | Current Use | Correct Use | Reason |",
                    "## Missing Terms",
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

    def test_oracle_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "domain-patterns-template.md",
            "domain-amendments-template.md",
            "compliance-gaps-template.md",
            "terminology-corrections-template.md",
        ]:
            assert f"extension/templates/{filename}" in text

        assert "domain-knowledge.md" not in text
        assert ".specify/..." not in text
        assert (
            "  output_files:\n"
            "    - {spec_dir}/domain-patterns.md\n"
            "  state_updates: {}\n"
            "  journal_entries:\n"
            in text
        )
        assert "agent: speckit-echelon-oracle (ORACLE)" in text

    def test_phase3_specialist_dispatch_includes_oracle_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/domain-patterns-template.md" in text
        assert "extension/templates/domain-amendments-template.md" in text
        assert "extension/templates/compliance-gaps-template.md" in text
        assert "extension/templates/terminology-corrections-template.md" in text

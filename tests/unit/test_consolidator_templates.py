from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "learning" / "consolidator.md"


class TestConsolidatorTemplates:
    def test_schema_consolidation_template_exists_with_required_anchors(self) -> None:
        text = (TEMPLATE_DIR / "schema-consolidation-template.md").read_text(
            encoding="utf-8"
        )

        for anchor in [
            "# Schema Consolidation",
            "## Promoted Schemas",
            "## Reinforced Schemas",
            "## Consolidated Traces",
            "## Simulation Results",
        ]:
            assert anchor in text

    def test_consolidator_prompt_references_template_and_canonical_outputs(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "extension/templates/schema-consolidation-template.md" in text
        assert ".specify/specs/" not in text
        assert "{spec_dir}/patterns/schema-consolidation.md" in text
        assert "agent: speckit-echelon-consolidator (CONSOLIDATOR)" in text

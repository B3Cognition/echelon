from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "control" / "strategist.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase2-strategic-overview.md"


class TestStrategistTemplates:
    def test_strategic_overview_template_exists_with_required_anchors(self) -> None:
        text = (TEMPLATE_DIR / "strategic-overview-template.md").read_text(
            encoding="utf-8"
        )

        for anchor in [
            "# Strategic Overview",
            "## Risk-Weighted Component Map",
            "## Effort Allocation Recommendations",
            "## High-Blast-Radius Decisions",
            "## Consequences Over Time",
            "## Specialist Allocation Advice",
        ]:
            assert anchor in text

    def test_strategist_prompt_references_template_and_canonical_output(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "extension/templates/strategic-overview-template.md" in text
        assert ".specify/..." not in text
        assert "{spec_dir}/strategic-overview.md" in text
        assert "agent: echelon-strategist (STRATEGIST)" in text
        assert "agent: OVERVIEW" not in text

    def test_phase2_strategic_overview_dispatch_includes_template(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/strategic-overview-template.md" in text
        assert "using the provided template" in text
        assert "specs/{NNN}-{feature}/" not in text
        assert "{spec_dir}/" in text

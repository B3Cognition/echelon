from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "learning" / "adaptive.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase4-document.md"


class TestAdaptiveTemplates:
    def test_prompt_recommendation_template_exists_with_required_anchors(self) -> None:
        text = (TEMPLATE_DIR / "prompt-recommendation-template.md").read_text(
            encoding="utf-8"
        )

        for anchor in [
            "## Prompt Recommendation:",
            "Agent:",
            "Evidence:",
            "Correlation:",
            "Recommended change:",
            "Confidence:",
        ]:
            assert anchor in text

    def test_adaptive_prompt_references_template_and_canonical_outputs(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "extension/templates/prompt-recommendation-template.md" in text
        assert ".specify/specs/" not in text
        assert "specs/{feature}/" not in text
        assert "{spec_dir}/" in text
        assert "{spec_dir}/evolution-report.md" in text
        assert "{spec_dir}/improvement-metrics.md" in text
        assert "agent: echelon-adaptive (ADAPTIVE)" in text
        assert "agent: EVOLVE" not in text

    def test_finalize_dispatch_includes_adaptive_template(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/prompt-recommendation-template.md" in text
        assert "using the provided template" in text

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "exploration" / "modeler.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase1-modeler.md"


class TestModelerTemplates:
    def test_mental_model_code_template_exists_with_required_anchors(self) -> None:
        text = (TEMPLATE_DIR / "mental-model-code-template.md").read_text(
            encoding="utf-8"
        )

        for anchor in [
            "# Mental Model Code",
            "## Entity Graph",
            "## Contract Map",
            "## Data Flow",
            "## Invariants",
            "## Invariant Violations",
            "## Impact Traces",
        ]:
            assert anchor in text

    def test_modeler_prompt_references_template_and_canonical_output(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "extension/templates/mental-model-code-template.md" in text
        assert "mental-model-code.md" in text
        assert "code-model.md" not in text
        assert "agent: speckit-echelon-modeler (MODELER)" in text

    def test_phase1_modeler_dispatch_includes_template(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/mental-model-code-template.md" in text
        assert "using the provided template" in text

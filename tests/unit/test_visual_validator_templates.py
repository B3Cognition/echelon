from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "prosaic" / "subagents" / "echelon.visual-validator.md"
PHASE = ROOT / "runtime" / "workflow" / "phases" / "build-7-integration.md"


class TestVisualValidatorTemplates:
    def test_visual_validator_prompt_uses_canonical_output_path_and_agent_label(
        self,
    ) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/..." not in text
        assert "{spec_dir}/visual-validation-report.md" in text
        assert (
            "agent: echelon-visual-validator (VISUAL VALIDATOR)"
            in text
        )
        assert "agent: VISUAL_VALIDATOR" not in text

    def test_integration_phase_uses_canonical_visual_report_path(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "Write or append to `{spec_dir}/visual-validation-report.md`" in text

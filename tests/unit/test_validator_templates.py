from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "prosaic" / "subagents" / "echelon.validator.md"
WORKFLOW = ROOT / "runtime" / "workflow" / "definition.yaml"


class TestValidatorTemplates:
    def test_validator_prompt_uses_canonical_output_path_and_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/specs/" not in text
        assert "{spec_dir}/internalization-report.md" in text
        assert "agent: echelon-validator (VALIDATOR)" in text
        assert "agent: INTERNALIZATION_GATE" not in text

    def test_workflow_dispatches_validator_with_canonical_agent_label(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")

        assert "agent: echelon.validator (VALIDATOR)" in text

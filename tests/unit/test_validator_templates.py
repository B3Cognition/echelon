from pathlib import Path

import yaml


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

    def test_retained_validator_does_not_restore_legacy_delivery_routing(self) -> None:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        assert not any(phase["id"].startswith("build-") for phase in workflow["phases"])
        assert not (ROOT / "runtime/workflow/phases/build-1-init.md").exists()

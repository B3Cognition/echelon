from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "prosaic" / "subagents" / "echelon.change-controller.md"


class TestChangeControllerTemplates:
    def test_change_controller_prompt_uses_canonical_output_path_and_agent_label(
        self,
    ) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/..." not in text
        assert "specs/{feature}/change-impact-report.md" not in text
        assert "{spec_dir}/change-impact-report.md" in text
        assert "agent: echelon-change-controller (CHANGE CONTROLLER)" in text
        assert "agent: CHANGE_CONTROLLER" not in text

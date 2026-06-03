from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "build" / "engineering-manager.md"


class TestEngineeringManagerTemplates:
    def test_engineering_manager_prompt_uses_canonical_output_and_agent_label(
        self,
    ) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/..." not in text
        assert "{spec_dir}/build-status.md" in text
        assert (
            "agent: speckit-echelon-engineering-manager (ENGINEERING MANAGER)"
            in text
        )
        assert "agent: ENGINEERING_MANAGER" not in text

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "prosaic" / "subagents" / "echelon.implementer.md"


class TestImplementerTemplates:
    def test_implementer_prompt_uses_canonical_output_path_and_agent_label(
        self,
    ) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/..." not in text
        assert "{spec_dir}/implementation/<file>" in text
        assert "agent: echelon-implementer (IMPLEMENTER)" in text
        assert "agent: IMPLEMENTER" not in text

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "exploration" / "golddigger.md"


class TestGolddiggerTemplates:
    def test_golddigger_prompt_uses_canonical_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "agent: speckit-echelon-golddigger (GOLDDIGGER)" in text
        assert "agent: EXTRACT" not in text

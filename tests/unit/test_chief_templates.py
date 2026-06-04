from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "control" / "chief.md"


class TestChiefTemplates:
    def test_chief_prompt_uses_canonical_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/memory/constitution.md" in text
        assert "agent: speckit-echelon-chief (CHIEF)" in text
        assert "agent: CHIEF" not in text

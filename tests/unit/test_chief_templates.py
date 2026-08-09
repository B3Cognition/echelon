from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "control" / "chief.md"


class TestChiefTemplates:
    def test_chief_prompt_uses_canonical_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/memory/constitution.md" in text
        assert "agent: echelon-chief (CHIEF)" in text
        assert "agent: CHIEF" not in text

    def test_chief_verifies_all_constitution_template_markers(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for marker in (
            "[PROJECT_NAME]",
            "[PRINCIPLE_1_NAME]",
            "[CONSTITUTION_VERSION]",
            "[RATIFICATION_DATE]",
            "[LAST_AMENDED_DATE]",
        ):
            assert marker in text

        assert "Do not emit `verdict: DONE` while any marker remains" in text

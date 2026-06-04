from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "learning" / "monitor.md"


class TestMonitorTemplates:
    def test_monitor_prompt_uses_canonical_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "agent: speckit-echelon-monitor (MONITOR)" in text
        assert "METACOGNITION-speckit-echelon-monitor (MONITOR)" not in text

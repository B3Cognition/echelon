from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "prosaic" / "subagents" / "echelon.monitor.md"


class TestMonitorTemplates:
    def test_monitor_prompt_uses_canonical_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "agent: echelon-monitor (MONITOR)" in text
        assert "METACOGNITION-echelon-monitor (MONITOR)" not in text

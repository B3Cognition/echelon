from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "build" / "debugger.md"


class TestDebuggerTemplates:
    def test_debugger_prompt_uses_canonical_output_path_and_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/..." not in text
        assert "{spec_dir}/debug-report.md" in text
        assert "agent: speckit-echelon-debugger (DEBUGGER)" in text

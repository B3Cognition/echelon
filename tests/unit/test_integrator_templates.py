from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "build" / "integrator.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "build-7-integration.md"


class TestIntegratorTemplates:
    def test_integrator_prompt_uses_canonical_output_path_and_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/specs/" not in text
        assert ".specify/..." not in text
        assert "{spec_dir}/integration-report.md" in text
        assert "agent: echelon-integrator (INTEGRATOR)" in text

    def test_integration_phase_uses_canonical_output_path(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "Write `{spec_dir}/integration-report.md`" in text

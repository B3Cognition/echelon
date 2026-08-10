from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "prosaic" / "subagents" / "echelon.test-guardian.md"
PHASE = ROOT / "runtime" / "workflow" / "phases" / "build-5-test-guard.md"


class TestTestGuardianTemplates:
    def test_test_guardian_prompt_uses_canonical_output_path_and_agent_label(
        self,
    ) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/specs/" not in text
        assert ".specify/..." not in text
        assert "{spec_dir}/test-quality-report.md" in text
        assert "agent: echelon-test-guardian (TEST GUARDIAN)" in text
        assert "agent: TEST_GUARDIAN" not in text

    def test_test_guardian_phase_uses_canonical_output_path(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "Append to `{spec_dir}/test-quality-report.md`" in text

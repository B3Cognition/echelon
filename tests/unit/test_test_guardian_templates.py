from pathlib import Path

import yaml


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

    def test_retained_test_guardian_does_not_restore_legacy_delivery_routing(self) -> None:
        workflow = yaml.safe_load((ROOT / "runtime/workflow/definition.yaml").read_text())
        assert PHASE.stem not in {phase["id"] for phase in workflow["phases"]}
        assert not PHASE.exists()

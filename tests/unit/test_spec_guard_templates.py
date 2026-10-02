from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "prosaic" / "subagents" / "echelon.spec-guard.md"
PHASE = ROOT / "runtime" / "workflow" / "phases" / "build-3-spec-guard.md"


class TestSpecGuardTemplates:
    def test_spec_guard_prompt_uses_canonical_outputs_and_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/specs/" not in text
        assert ".specify/..." not in text
        assert "{spec_dir}/spec-compliance-report.md" in text
        assert "{spec_dir}/traceability-matrix.md" in text
        assert "agent: echelon-spec-guard (SPEC GUARD)" in text
        assert "agent: SPEC_GUARD" not in text

    def test_retained_spec_guard_does_not_restore_legacy_delivery_routing(self) -> None:
        workflow = yaml.safe_load((ROOT / "runtime/workflow/definition.yaml").read_text())
        assert PHASE.stem not in {phase["id"] for phase in workflow["phases"]}
        assert not PHASE.exists()

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "build" / "spec-guard.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "build-3-spec-guard.md"


class TestSpecGuardTemplates:
    def test_spec_guard_prompt_uses_canonical_outputs_and_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/specs/" not in text
        assert ".specify/..." not in text
        assert "{spec_dir}/spec-compliance-report.md" in text
        assert "{spec_dir}/traceability-matrix.md" in text
        assert "agent: echelon-spec-guard (SPEC GUARD)" in text
        assert "agent: SPEC_GUARD" not in text

    def test_spec_guard_phase_uses_canonical_output_paths(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "Append to `{spec_dir}/spec-compliance-report.md`" in text
        assert "Update `{spec_dir}/traceability-matrix.md`" in text

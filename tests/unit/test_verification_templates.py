from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "build" / "verification.md"


class TestVerificationTemplates:
    def test_verification_prompt_uses_canonical_output_paths_and_agent_label(
        self,
    ) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/..." not in text
        assert "specs/{feature}/gap-report.md" not in text
        assert "specs/{feature}/verification-summary.md" not in text
        assert "{spec_dir}/gap-report.md" in text
        assert "{spec_dir}/verification-summary.md" in text
        assert "agent: speckit-echelon-verification (VERIFICATION)" in text
        assert "agent: VERIFICATION" not in text

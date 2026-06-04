from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RE_SPECIFIER = ROOT / "extension" / "agents" / "re" / "specifier.md"
RE_EXTRACT_2_SPECIFY = (
    ROOT / "extension" / "workflow" / "phases" / "re-extract-2-specify.md"
)


class TestRePromptOutputContracts:
    def test_re_specifier_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_SPECIFIER, RE_EXTRACT_2_SPECIFY]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/spec.md" not in text
            assert "specs/NNN-re-{domain}/spec.md" in text

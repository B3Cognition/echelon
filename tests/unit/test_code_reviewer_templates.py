from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "build" / "code-reviewer.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "build-4-code-review.md"
PYTHON_RULES = ROOT / "knowledge-base" / "language-rules" / "python.md"


class TestCodeReviewerTemplates:
    def test_code_reviewer_prompt_uses_canonical_output_path_and_agent_label(
        self,
    ) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/..." not in text
        assert "specs/{feature}/code-review-report.md" not in text
        assert "{spec_dir}/code-review-report.md" in text
        assert "agent: echelon-code-reviewer (CODE REVIEWER)" in text
        assert "agent: CODE_REVIEWER" not in text

    def test_code_review_phase_uses_canonical_output_path(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "Append to `{spec_dir}/code-review-report.md`" in text

    def test_python_style_claims_require_ruff_format_check(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        python_text = PYTHON_RULES.read_text(encoding="utf-8")

        assert "knowledge-base/language-rules/{language}.md" in agent_text
        assert "ruff format --check" not in agent_text
        assert "ruff check" in python_text
        assert "ruff format --check" in python_text
        assert "Do not report Python style, lint, or formatting as clean from `ruff check` alone" in python_text

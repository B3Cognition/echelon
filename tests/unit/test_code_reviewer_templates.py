from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "prosaic" / "subagents" / "echelon.code-reviewer.md"
PHASE = ROOT / "runtime" / "workflow" / "phases" / "build-4-code-review.md"
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

    def test_retained_code_reviewer_does_not_restore_legacy_delivery_routing(self) -> None:
        workflow = yaml.safe_load((ROOT / "runtime/workflow/definition.yaml").read_text())
        assert "build-4-code-review" not in {phase["id"] for phase in workflow["phases"]}
        assert not PHASE.exists()

    def test_python_style_claims_require_ruff_format_check(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        python_text = PYTHON_RULES.read_text(encoding="utf-8")

        assert "knowledge-base/language-rules/{language}.md" in agent_text
        assert "ruff format --check" not in agent_text
        assert "ruff check" in python_text
        assert "ruff format --check" in python_text
        assert "Do not report Python style, lint, or formatting as clean from `ruff check` alone" in python_text

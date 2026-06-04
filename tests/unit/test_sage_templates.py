from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "agents" / "exploration" / "templates"
AGENT = ROOT / "extension" / "agents" / "exploration" / "sage.md"
WHY1_PHASE = ROOT / "extension" / "workflow" / "phases" / "phase1-why1.md"
WHY2_PHASE = ROOT / "extension" / "workflow" / "phases" / "phase1-why2.md"
WHY3_PHASE = ROOT / "extension" / "workflow" / "phases" / "phase3-consensus.md"


class TestSageTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "sage-assumption-review-template.md",
                [
                    "# Assumption Review",
                    "## Verdict:",
                    "## Assumption Analysis",
                    "## SCIENTIST Referrals",
                ],
            ),
            (
                "sage-quality-gates-template.md",
                [
                    "# Quality Gates",
                    "## Quality Scores",
                    "## Metric Improvement Recommendations",
                    "STATUS COLUMN",
                ],
            ),
            (
                "sage-issues-template.md",
                [
                    "# Issues",
                    "## Summary",
                    "## Issues",
                    "## Cross-Artifact Consistency",
                ],
            ),
            (
                "sage-decision-entry-template.yaml",
                [
                    "- run_id:",
                    "challenge_type:",
                    "outcome:",
                    "was_correct:",
                ],
            ),
        ],
    )
    def test_templates_exist_with_required_anchors(
        self, filename: str, anchors: list[str]
    ) -> None:
        text = (TEMPLATE_DIR / filename).read_text(encoding="utf-8")

        for anchor in anchors:
            assert anchor in text

    def test_sage_prompt_references_templates_and_canonical_outputs(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "agents/exploration/templates/sage-assumption-review-template.md" in text
        assert "agents/exploration/templates/sage-quality-gates-template.md" in text
        assert "agents/exploration/templates/sage-issues-template.md" in text
        assert "agents/exploration/templates/sage-decision-entry-template.yaml" in text
        assert ".specify/..." not in text
        assert "${STAGING_DIR}/assumption-review.md" in text
        assert "${STAGING_DIR}/issues.md" in text
        assert "{spec_dir}/quality-gates.md" in text
        assert "{spec_dir}/issues.md" in text
        assert "agent: speckit-echelon-sage (SAGE)" in text
        assert "agent: WHY" not in text

    def test_why1_dispatch_includes_sage_templates(self) -> None:
        text = WHY1_PHASE.read_text(encoding="utf-8")

        assert "agents/exploration/templates/sage-assumption-review-template.md" in text
        assert "agents/exploration/templates/sage-issues-template.md" in text
        assert "using the provided templates" in text

    def test_why2_dispatch_includes_sage_templates(self) -> None:
        text = WHY2_PHASE.read_text(encoding="utf-8")

        assert "agents/exploration/templates/sage-quality-gates-template.md" in text
        assert "agents/exploration/templates/sage-issues-template.md" in text
        assert "using the provided templates" in text
        assert "Produce outputs in `specs/{NNN}-{feature}/`" not in text
        assert "Produce outputs in `{spec_dir}/`" in text

    def test_why3_dispatch_includes_sage_templates(self) -> None:
        text = WHY3_PHASE.read_text(encoding="utf-8")

        assert "agents/exploration/templates/sage-quality-gates-template.md" in text
        assert "agents/exploration/templates/sage-issues-template.md" in text
        assert "using the provided templates" in text

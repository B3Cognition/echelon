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
        assert "extension/templates/kb-proposals/sage-decision-proposal-template.yaml" in text
        assert "agents/exploration/templates/sage-decision-entry-template.yaml" not in text
        assert ".specify/..." not in text
        assert "${STAGING_DIR}/assumption-review.md" in text
        assert "${STAGING_DIR}/issues.md" in text
        assert "{spec_dir}/quality-gates.md" in text
        assert "{spec_dir}/issues.md" in text
        assert "agent: speckit-echelon-sage (SAGE)" in text
        assert "agent: WHY" not in text

    def test_sage_pass_verdict_forbids_required_amendments(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "report PASS but flag the borderline metrics" not in text
        assert "PASS means no required amendments remain" in text
        assert "NEVER return `verdict: PASS`" in text
        assert "mandatory amendments" in text
        assert "route to CARTOGRAPHER" in text
        assert "If any issue requires CARTOGRAPHER" in text

    def test_sage_understanding_contract_uses_documented_temp_outputs(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "--output /tmp/u_validate.json" in text
        assert "--output /tmp/u_perreq.json" in text
        assert "Never check for `/tmp/understanding_output.json`" in text

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

    def test_why2_dispatch_blocks_required_amendments_even_without_critical(self) -> None:
        text = WHY2_PHASE.read_text(encoding="utf-8")

        assert "required amendments remain" in text
        assert "mandatory amendments" in text
        assert "HIGH issues marked required" in text
        assert "Quality gates pass AND no CRITICAL issues**" not in text
        assert "Quality gates pass AND no CRITICAL issues AND no required amendments remain" in text

    def test_why3_dispatch_includes_sage_templates(self) -> None:
        text = WHY3_PHASE.read_text(encoding="utf-8")

        assert "agents/exploration/templates/sage-quality-gates-template.md" in text
        assert "agents/exploration/templates/sage-issues-template.md" in text
        assert "using the provided templates" in text

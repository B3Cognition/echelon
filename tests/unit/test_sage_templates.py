from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "prosaic" / "agents" / "exploration" / "templates"
AGENT = ROOT / "prosaic" / "subagents" / "echelon.sage.md"
CONTRADICTION_REFERENCE = (
    ROOT
    / "prosaic"
    / "agents"
    / "exploration"
    / "appendices"
    / "sage-contradiction-detection-reference.md"
)
WHY1_PHASE = ROOT / "runtime" / "workflow" / "phases" / "phase1-why1.md"
WHY2_PHASE = ROOT / "runtime" / "workflow" / "phases" / "phase1-why2.md"
WHY3_PHASE = ROOT / "runtime" / "workflow" / "phases" / "phase3-consensus.md"


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
        assert ".echelon/runtime/templates/kb-proposals/sage-decision-proposal-template.yaml" in text
        assert "agents/exploration/templates/sage-decision-entry-template.yaml" not in text
        assert ".specify/..." not in text
        assert "${STAGING_DIR}/assumption-review.md" in text
        assert "${STAGING_DIR}/issues.md" in text
        assert "{spec_dir}/quality-gates.md" in text
        assert "{spec_dir}/issues.md" in text
        assert "agent: echelon-sage (SAGE)" in text
        assert "agent: WHY" not in text
        assert "architecture_requirement_drift" in text
        assert "plan.md, research.md, data-model.md, contracts/" in text
        assert "validated `spec.md`" in text

    def test_sage_pass_verdict_forbids_required_amendments(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "report PASS but flag the borderline metrics" not in text
        assert "If you find only MEDIUM/LOW issues:** Report PASS" not in text
        assert "PASS means no required amendments remain" in text
        assert "NEVER return `verdict: PASS`" in text
        assert "mandatory amendments" in text
        assert "route to CARTOGRAPHER" in text
        assert "If any issue requires CARTOGRAPHER" in text

    def test_sage_understanding_contract_uses_certified_evidence(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "harness-injected **Certified Evidence** report" in text
        assert "NEVER invoke validators" in text
        assert "--output /tmp/u_validate.json" not in text
        assert "/tmp/understanding_output.json" not in text

    def test_sage_output_contract_separates_questions_from_missing_evidence(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "Verdict: <PASS | FAIL | STOP_AND_ASK | BLOCKED>" in text
        assert "verdict: <PASS | FAIL | STOP_AND_ASK | BLOCKED>" in text
        assert "`blocked_reason: human_clarification_required`" in text
        assert "heuristic equivalents" not in text

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
        assert "Produce in `{spec_dir}/`" in text

    def test_why2_dispatch_retains_strict_prompt_boundaries_and_paths(self) -> None:
        text = WHY2_PHASE.read_text(encoding="utf-8")

        assert "<context>" in text
        assert "</context>" in text
        assert "<instructions>" in text
        assert "</instructions>" in text
        assert "<outputs>" in text
        assert "</outputs>" in text
        assert text.index("<context>") < text.index("<instructions>")
        assert text.index("<instructions>") < text.index("<outputs>")
        assert "`{spec_dir}/spec.md`" in text
        assert "`{spec_dir}/assumptions.md`" in text
        assert "`.echelon/constitution.md`" in text
        assert "Treat `{spec_dir}` / `ACTIVE_SPEC_DIR` as authoritative" in text

    def test_why2_dispatch_blocks_required_amendments_even_without_critical(self) -> None:
        text = WHY2_PHASE.read_text(encoding="utf-8")

        assert "required amendments remain" in text
        assert "mandatory amendments" in text
        assert "HIGH issues marked required" in text
        assert "Quality gates pass AND no CRITICAL issues**" not in text
        assert "Certified gates pass, no CRITICAL issues, and no required amendments remain" in text

    def test_why2_dispatch_requires_structured_evidence_resolution_requests(self) -> None:
        text = WHY2_PHASE.read_text(encoding="utf-8")

        assert "evidence_resolution_status: pending" in text
        assert "evidence_requests" in text
        assert "spec_repair" in text
        assert "human_decision" in text

    def test_why3_dispatch_includes_sage_templates(self) -> None:
        text = WHY3_PHASE.read_text(encoding="utf-8")

        assert "agents/exploration/templates/sage-quality-gates-template.md" in text
        assert "agents/exploration/templates/sage-issues-template.md" in text
        assert "using the provided templates" in text
        assert "architecture_requirement_drift" in text
        assert "validated `spec.md`" in text

    def test_owned_deferred_automation_is_not_a_phase_a_blocker(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "owned `deferred-automation`" in text
        assert "does not require a Phase A amendment" in text

    def test_why3_issue_ownership_names_each_repair_plane(self) -> None:
        agent = AGENT.read_text(encoding="utf-8")
        template = (TEMPLATE_DIR / "sage-issues-template.md").read_text(
            encoding="utf-8"
        )
        phase = WHY3_PHASE.read_text(encoding="utf-8")

        for owner in ("WHAT", "HOW", "SENTINEL", "ORCHESTRATOR"):
            assert owner in agent
            assert owner in template
            assert owner in phase
        assert "earliest agent that can edit" in agent
        assert "controller routes the next pass from that field" in phase

    def test_sage_contradiction_reference_includes_architecture_drift(self) -> None:
        text = CONTRADICTION_REFERENCE.read_text(encoding="utf-8")

        assert "architecture_requirement_drift" in text
        assert "validated `spec.md`" in text
        assert "plan.md, research.md, data-model.md, contracts/" in text

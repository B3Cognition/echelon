from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "runtime" / "templates"
AGENT = ROOT / "prosaic" / "subagents" / "echelon.gatekeeper.md"
PHASE2 = ROOT / "runtime" / "workflow" / "phases" / "phase2-decide.md"
PHASE3 = ROOT / "runtime" / "workflow" / "phases" / "phase3-consensus.md"


class TestGatekeeperTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "feasibility-template.md",
                [
                    "## Feasibility Verdict",
                    "| Dimension | Verdict | Rationale | Evidence |",
                    "## Kill / Defer / Pass Decision",
                ],
            ),
            (
                "prioritization-template.md",
                [
                    "## Feature Ranking",
                    "| Feature | Kano | Reach | Impact | Confidence | Effort | RICE | Tier |",
                    "## Natural Break Point",
                ],
            ),
            (
                "estimates-template.md",
                [
                    "## Function Point Breakdown",
                    "| Type | Count | Complexity | Weight | UFP |",
                    "## Calibration Adjustment",
                    "## Effort Range",
                    "## Delivery Estimate Summary",
                    "## Phase A — Specification Estimate",
                    "## Phase B — Implementation Estimate",
                    "## AI-Assisted Token and USD Budget",
                    "| Workstream | Input Tokens | Output Tokens | Total Tokens | USD Budget | Pricing Basis |",
                ],
            ),
            (
                "mvp-scope-template.md",
                [
                    "## Must-Ship",
                    "## Should-Ship",
                    "## Could-Ship",
                    "## Won't-Ship",
                    "## MVP Coherence Check",
                ],
            ),
            (
                "implementability-report-template.md",
                [
                    "## Summary",
                    "| Task | Status | Self-Sufficiency | Reference Validity | Parallelism Integrity | Skill Match | Task Containment | Testability | Recommendation |",
                    "## Critical Feasibility Issues",
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

    def test_gatekeeper_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "feasibility-template.md",
            "prioritization-template.md",
            "estimates-template.md",
            "mvp-scope-template.md",
            "implementability-report-template.md",
            "kill-report.md",
        ]:
            assert f".echelon/runtime/templates/{filename}" in text

        assert ".specify/..." not in text
        assert "verdict: PASS | KILL | DEFER" in text
        assert "verdict: PASS | REJECTED | BLOCKED" in text
        assert "- {spec_dir}/kill-report.md  # KILL only" in text
        assert "- {spec_dir}/implementability-report.md" in text
        assert "agent: echelon-gatekeeper (GATEKEEPER)" in text
        assert "agent: ASSESS" not in text

    def test_gatekeeper_mode_contracts_do_not_conflict(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "verdict: <PASS | KILL | DEFER>" not in text
        assert "Use the mode-specific result block above" in text
        assert "`.echelon/constitution.md`" in text

    def test_phase2_decide_dispatch_includes_first_pass_templates(self) -> None:
        text = PHASE2.read_text(encoding="utf-8")

        assert ".echelon/runtime/templates/feasibility-template.md" in text
        assert ".echelon/runtime/templates/prioritization-template.md" in text
        assert ".echelon/runtime/templates/estimates-template.md" in text
        assert ".echelon/runtime/templates/mvp-scope-template.md" in text
        assert ".echelon/runtime/templates/kill-report.md" in text

    def test_phase3_consensus_dispatch_includes_implementability_template(self) -> None:
        text = PHASE3.read_text(encoding="utf-8")

        assert ".echelon/runtime/templates/implementability-report-template.md" in text

    def test_gatekeeper_requires_phase_a_human_and_ai_estimates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "Phase A — specification authoring" in text
        assert "human-only and AI-assisted scenarios" in text
        assert "token and USD budgets" in text

    def test_assess2_reconciles_all_estimation_scenarios(self) -> None:
        text = PHASE3.read_text(encoding="utf-8")

        assert "Phase A, Phase B, human-only, and AI-assisted" in text
        assert "token and USD budgets" in text

    def test_assess2_uses_dedicated_implementability_metrics_state_update(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        phase_text = PHASE3.read_text(encoding="utf-8")
        definition_text = (ROOT / "runtime" / "workflow" / "definition.yaml").read_text(
            encoding="utf-8"
        )

        assert "implementability_metrics" in agent_text
        assert "implementability_metrics" in phase_text
        assert "      - implementability_metrics" in definition_text
        assert "Do not put ASSESS2 implementability metrics under `quality_scores`" in agent_text

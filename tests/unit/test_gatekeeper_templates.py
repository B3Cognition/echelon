from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "feasibility" / "gatekeeper.md"
PHASE2 = ROOT / "extension" / "workflow" / "phases" / "phase2-decide.md"
PHASE3 = ROOT / "extension" / "workflow" / "phases" / "phase3-consensus.md"


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
            assert f"extension/templates/{filename}" in text

    def test_phase2_decide_dispatch_includes_first_pass_templates(self) -> None:
        text = PHASE2.read_text(encoding="utf-8")

        assert "extension/templates/feasibility-template.md" in text
        assert "extension/templates/prioritization-template.md" in text
        assert "extension/templates/estimates-template.md" in text
        assert "extension/templates/mvp-scope-template.md" in text
        assert "extension/templates/kill-report.md" in text

    def test_phase3_consensus_dispatch_includes_implementability_template(self) -> None:
        text = PHASE3.read_text(encoding="utf-8")

        assert "extension/templates/implementability-report-template.md" in text

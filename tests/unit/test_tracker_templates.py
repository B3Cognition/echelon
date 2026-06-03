from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "control" / "tracker.md"
PHASE1 = ROOT / "extension" / "workflow" / "phases" / "phase1-tracker.md"
PHASE2 = ROOT / "extension" / "workflow" / "phases" / "phase2-tracker-alignment.md"
POST_BUILD = (
    ROOT
    / "extension"
    / "workflow"
    / "phases"
    / "appendices"
    / "build-8-feedback-reference.md"
)


class TestTrackerTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "user-intent-template.md",
                [
                    "## Explicit Statements",
                    "## Inferred Intent",
                    "## Intent vs Spec Alignment",
                    "## Red Flags",
                ],
            ),
            (
                "intent-alignment-check-template.md",
                [
                    "## Alignment Verdict",
                    "| User Intent | Gatekeeper Scope / Decision | Aligned? | Divergence |",
                    "## Required Action",
                ],
            ),
            (
                "intent-alignment-final-template.md",
                [
                    "drift_severity: {ALIGNED|MINOR_DRIFT|MAJOR_DRIFT}",
                    "## Built vs Intended",
                    "## Unmet Intent Points",
                    "## Correction Gate",
                ],
            ),
            (
                "stakeholder-model-template.md",
                [
                    "## Stakeholders",
                    "| Stakeholder | Role | Primary Goal | Key Constraint | Potential Conflicts |",
                    "## Priority Conflicts",
                    "## Tradeoff Decisions",
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

    def test_tracker_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "user-intent-template.md",
            "intent-alignment-check-template.md",
            "intent-alignment-final-template.md",
            "stakeholder-model-template.md",
        ]:
            assert f"extension/templates/{filename}" in text

    def test_phase1_tracker_dispatch_includes_intent_templates(self) -> None:
        text = PHASE1.read_text(encoding="utf-8")

        assert "extension/templates/user-intent-template.md" in text
        assert "extension/templates/stakeholder-model-template.md" in text

    def test_phase2_tracker_alignment_dispatch_includes_alignment_template(self) -> None:
        text = PHASE2.read_text(encoding="utf-8")

        assert "extension/templates/intent-alignment-check-template.md" in text

    def test_post_build_alignment_dispatch_includes_final_template(self) -> None:
        text = POST_BUILD.read_text(encoding="utf-8")

        assert "extension/templates/intent-alignment-final-template.md" in text

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "runtime" / "templates"
AGENT = ROOT / "prosaic" / "subagents" / "echelon.tracker.md"
PHASE1 = ROOT / "runtime" / "workflow" / "phases" / "phase1-tracker.md"
PHASE2 = ROOT / "runtime" / "workflow" / "phases" / "phase2-tracker-alignment.md"
DEFINITION = ROOT / "runtime" / "workflow" / "definition.yaml"
POST_BUILD = (
    ROOT
    / "runtime"
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
            assert f".echelon/runtime/templates/{filename}" in text

        assert "${STAGING_DIR}/user-intent.md" in text
        assert "${STAGING_DIR}/stakeholder-model.md" in text
        assert ".specify/.../user-intent.md" not in text
        assert "agent: INTENT" not in text
        assert "agent: echelon-tracker (TRACKER)" in text

    def test_phase1_tracker_dispatch_includes_intent_templates(self) -> None:
        text = PHASE1.read_text(encoding="utf-8")

        assert ".echelon/runtime/templates/user-intent-template.md" in text
        assert ".echelon/runtime/templates/stakeholder-model-template.md" in text
        assert "- `stakeholder-model.md` (if multiple stakeholders are detectable)" in text

    def test_workflow_definition_lists_stakeholder_model_output(self) -> None:
        text = DEFINITION.read_text(encoding="utf-8")

        assert "stakeholder-model.md" in text

    def test_phase2_tracker_alignment_dispatch_includes_alignment_template(self) -> None:
        text = PHASE2.read_text(encoding="utf-8")

        assert ".echelon/runtime/templates/intent-alignment-check-template.md" in text
        assert "intent-alignment-check.md` in `specs/{NNN}-{feature}/`" not in text
        assert "intent-alignment-check.md` in `{spec_dir}/`" in text

    def test_retained_tracker_does_not_restore_legacy_delivery_routing(self) -> None:
        workflow = yaml.safe_load(DEFINITION.read_text(encoding="utf-8"))
        assert "build-8-finalize" not in {phase["id"] for phase in workflow["phases"]}
        assert not POST_BUILD.exists()

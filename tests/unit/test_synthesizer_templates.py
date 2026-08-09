from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "exploration" / "synthesizer.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase1-synthesizer.md"
MODELER_PHASE = ROOT / "extension" / "workflow" / "phases" / "phase1-modeler.md"
DEFINITION = ROOT / "extension" / "workflow" / "definition.yaml"


class TestSynthesizerTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "contradictions-and-gaps-template.md",
                [
                    "# Contradictions and Gaps",
                    "## Contradictions",
                    "| Finding | Source A | Source B | Conflict Type |",
                    "## Emergent Patterns",
                ],
            ),
            (
                "risks-template.md",
                [
                    "# Risks",
                    "## Synthesized Risks",
                    "| Risk | Evidence | Impact | Owner / Follow-up |",
                ],
            ),
            (
                "people-and-teams-template.md",
                [
                    "# People and Teams",
                    "## Ownership Map",
                    "## Knowledge Concentration Risks",
                ],
            ),
            (
                "timeline-template.md",
                ["# Timeline", "## Development History", "## Velocity Trends", "## Stale Modules"],
            ),
            (
                "qa-test-strategy-inputs-template.md",
                [
                    "# QA Test Strategy Inputs",
                    "## Current Test State",
                    "## Coverage and Gaps",
                    "## Frameworks and Tooling",
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

    def test_synthesizer_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "glossary-template.md",
            "mental-model-template.md",
            "boundaries-template.md",
            "assumptions-template.md",
            "unknowns-template.md",
            "contradictions-and-gaps-template.md",
            "risks-template.md",
            "people-and-teams-template.md",
            "timeline-template.md",
            "qa-test-strategy-inputs-template.md",
        ]:
            assert f"extension/templates/{filename}" in text

        assert ".specify/..." not in text
        assert "agent: echelon-synthesizer (SYNTHESIZER)" in text
        assert "agent: SYNTHESIZER" not in text

    def test_phase1_synthesizer_dispatch_includes_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/glossary-template.md" in text
        assert "extension/templates/mental-model-template.md" in text
        assert "extension/templates/boundaries-template.md" in text
        assert "extension/templates/assumptions-template.md" in text
        assert "extension/templates/unknowns-template.md" in text
        assert "extension/templates/contradictions-and-gaps-template.md" in text
        assert "extension/templates/risks-template.md" in text
        assert "extension/templates/people-and-teams-template.md" in text
        assert "extension/templates/timeline-template.md" in text
        assert "extension/templates/qa-test-strategy-inputs-template.md" in text

    def test_modeler_phase_consumes_actual_synthesizer_outputs(self) -> None:
        text = MODELER_PHASE.read_text(encoding="utf-8")

        assert "synthesis.md" not in text
        assert "${STAGING_DIR}/mental-model.md" in text
        assert "${STAGING_DIR}/contradictions-and-gaps.md" in text

    def test_workflow_definition_lists_core_synthesizer_outputs(self) -> None:
        text = DEFINITION.read_text(encoding="utf-8")

        assert "unknowns.md              # unified, prioritized" in text
        assert "risks.md                 # synthesized risks" in text

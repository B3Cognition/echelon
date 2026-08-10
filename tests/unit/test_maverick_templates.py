from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "runtime" / "templates"
AGENT = ROOT / "prosaic" / "subagents" / "echelon.maverick.md"
PHASE = ROOT / "runtime" / "workflow" / "phases" / "phase3-specialists.md"
COMMAND = ROOT / "prosaic" / "commands" / "echelon.innovate.md"
EXTENSION = ROOT / "extension" / "extension.yml"


class TestMaverickTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "alternatives-template.md",
                [
                    "## Alternative <N>: <Name>",
                    "### Approach",
                    "### How It Differs",
                    "### Validation Path",
                ],
            ),
            (
                "risk-opportunities-template.md",
                [
                    "## Risk Opportunities",
                    "| Idea | Probability | Upside | Cost of Failure |",
                    "## Validation Approach",
                ],
            ),
            (
                "challenge-assumptions-template.md",
                [
                    "## Challenged Assumptions",
                    "| Assumption | Challenge | Evidence | Impact | Recommendation |",
                    "## Assumptions To Test",
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

    def test_maverick_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "alternatives-template.md",
            "risk-opportunities-template.md",
            "challenge-assumptions-template.md",
        ]:
            assert f".echelon/runtime/templates/{filename}" in text

        assert ".specify/.../alternatives.md" not in text
        assert "specs/..." not in text
        for filename in [
            "alternatives.md",
            "risk-opportunities.md",
            "challenge-assumptions.md",
        ]:
            assert f"{{spec_dir}}/{filename}" in text

    def test_phase3_specialist_dispatch_includes_maverick_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert ".echelon/runtime/templates/alternatives-template.md" in text
        assert ".echelon/runtime/templates/risk-opportunities-template.md" in text
        assert ".echelon/runtime/templates/challenge-assumptions-template.md" in text

    def test_manual_innovate_command_includes_maverick_templates(self) -> None:
        text = COMMAND.read_text(encoding="utf-8")

        assert ".echelon/runtime/templates/alternatives-template.md" in text
        assert ".echelon/runtime/templates/risk-opportunities-template.md" in text
        assert ".echelon/runtime/templates/challenge-assumptions-template.md" in text

    def test_extension_registry_lists_all_maverick_outputs(self) -> None:
        text = EXTENSION.read_text(encoding="utf-8")

        assert "alternatives.md, risk-opportunities.md, challenge-assumptions.md" in text

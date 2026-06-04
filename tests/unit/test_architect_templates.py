from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "solution" / "architect.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase3-how.md"


class TestArchitectTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "architecture-research-template.md",
                [
                    "## ADR Index",
                    "## ADR-<NNN>: <Decision Title>",
                    "## Proposed Technical Principles",
                ],
            ),
            (
                "architecture-adr-template.md",
                [
                    "## Context",
                    "## Decision Drivers",
                    "## Considered Options",
                    "## Decision",
                    "## Evidence",
                    "## Consequences",
                    "## Self-Check",
                ],
            ),
            (
                "data-model-template.md",
                [
                    "## Entity Index",
                    "## Entity: <Name>",
                    "| Field | Type | Required | Constraints | Description |",
                    "## Explicit Exclusions",
                ],
            ),
            (
                "contracts-template.md",
                [
                    "## Boundary Index",
                    "## Contract: <Boundary Name>",
                    "## Internal Interfaces",
                    "| Interface | Provider | Consumers | Operations | Stability |",
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

    def test_architect_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "plan-template.md",
            "architecture-research-template.md",
            "architecture-adr-template.md",
            "data-model-template.md",
            "contracts-template.md",
        ]:
            assert f"extension/templates/{filename}" in text

        assert ".specify/..." not in text
        assert (
            "  output_files:\n"
            "    - {spec_dir}/architecture.md\n"
            "    - {spec_dir}/adr/ADR-001.md\n"
            "    - {spec_dir}/data-model.md\n"
            "    - {spec_dir}/api-contracts.md\n"
            "  journal_entries:\n"
            in text
        )
        assert text.count("agent: speckit-echelon-architect (ARCHITECT)") == 2
        assert "agent: HOW" not in text

    def test_phase3_how_dispatch_includes_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/plan-template.md" in text
        assert "extension/templates/architecture-research-template.md" in text
        assert "extension/templates/architecture-adr-template.md" in text
        assert "extension/templates/data-model-template.md" in text
        assert "extension/templates/contracts-template.md" in text
        assert "files in `specs/{NNN}-{feature}/`" not in text
        assert "files in `{spec_dir}/`" in text

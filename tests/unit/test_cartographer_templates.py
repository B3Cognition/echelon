from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "agents" / "exploration" / "templates"
AGENT = ROOT / "extension" / "agents" / "exploration" / "cartographer.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase1-what.md"
DEFINITION = ROOT / "extension" / "workflow" / "definition.yaml"


class TestCartographerTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "cartographer-spec-template.md",
                [
                    "## User Scenarios & Testing",
                    "## Functional Requirements",
                    "- **FR-001**:",
                    "## Assumptions in Effect",
                ],
            ),
            (
                "cartographer-overview-template.md",
                [
                    "## Summary",
                    "## Dependency Graph",
                    "## Domain Areas",
                    "## Key Risks",
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

    def test_cartographer_prompt_references_templates_and_canonical_outputs(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "agents/exploration/templates/cartographer-spec-template.md" in text
        assert "agents/exploration/templates/cartographer-overview-template.md" in text
        assert ".specify/..." not in text
        assert "{spec_dir}/spec.md" in text
        assert "{spec_dir}/00-overview.md" in text
        assert "agent: speckit-echelon-cartographer (CARTOGRAPHER)" in text
        assert "agent: WHAT" not in text

    def test_cartographer_uses_only_the_controller_owned_spec_directory(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        phase_text = PHASE.read_text(encoding="utf-8")

        for text in (agent_text, phase_text):
            assert "speckit.specify" not in text
            assert "controller-owned Phase A identity" in text
        assert "{spec_dir}/spec.md" in agent_text
        assert "{spec_dir}/00-overview.md" in agent_text

    def test_cartographer_blocked_outputs_include_echelon_result(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "echelon_result:" in text
        assert "verdict: BLOCKED" in text
        assert "blocked_reason: \"spec_dir missing after Phase A bootstrap\"" in text

    def test_phase1_what_dispatch_includes_cartographer_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "agents/exploration/templates/cartographer-spec-template.md" in text
        assert "agents/exploration/templates/cartographer-overview-template.md" in text
        assert "using the provided templates" in text

    def test_validation_execution_is_controller_owned(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        phase_text = PHASE.read_text(encoding="utf-8")

        for text in (agent_text, phase_text):
            assert "understanding scan" not in text
            assert "lexicon validate" not in text
            assert "python3 -c" not in text
            assert "```bash" not in text
            assert "/tmp/cartographer-understanding.json" not in text
            assert "controller-owned" in text.lower()

    def test_prompt_consumes_injected_configuration_and_findings(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        phase_text = PHASE.read_text(encoding="utf-8")

        for text in (agent_text, phase_text):
            assert "Controller Configuration" in text
            assert "Spec Lexicon Repair" in text
            assert "Do not discover" in text
        assert "after the final source write" in agent_text
        assert "Never estimate" in agent_text

    def test_workflow_definition_lists_cartographer_outputs(self) -> None:
        text = DEFINITION.read_text(encoding="utf-8")

        assert "spec.md" in text
        assert "00-overview.md" in text

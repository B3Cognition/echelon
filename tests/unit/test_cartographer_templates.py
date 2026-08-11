from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "prosaic" / "agents" / "exploration" / "templates"
AGENT = ROOT / "prosaic" / "subagents" / "echelon.cartographer.md"
PHASE = ROOT / "runtime" / "workflow" / "phases" / "phase1-what.md"
DERIVER = ROOT / "prosaic" / "subagents" / "echelon.lexicon-deriver.md"
DERIVE_PHASE = (
    ROOT / "runtime" / "workflow" / "phases" / "phase1-lexicon-derive.md"
)
DEFINITION = ROOT / "runtime" / "workflow" / "definition.yaml"


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
        assert "{spec_dir}/requirements-overview.md" in text
        assert "agent: echelon-cartographer (CARTOGRAPHER)" in text
        assert "agent: WHAT" not in text

    def test_cartographer_uses_only_the_controller_owned_spec_directory(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        phase_text = PHASE.read_text(encoding="utf-8")

        for text in (agent_text, phase_text):
            assert "speckit.specify" not in text
            assert "controller-owned Phase A identity" in text
        assert "{spec_dir}/spec.md" in agent_text
        assert "{spec_dir}/requirements-overview.md" in agent_text

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

    def test_cartographer_classifies_complexity_before_authoring(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        phase_text = PHASE.read_text(encoding="utf-8")

        assert "Classify Feature Complexity Before Authoring" in agent_text
        assert "small deterministic feature" in agent_text
        assert "document-volume quota" in agent_text
        assert "Classify the discovered feature's complexity" in phase_text

    def test_cartographer_avoids_duplicate_obligations(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        template_text = (TEMPLATE_DIR / "cartographer-spec-template.md").read_text(
            encoding="utf-8"
        )

        for text in (agent_text, template_text):
            assert "one canonical formal requirement" in text
            assert "verification path" in text
        assert "at least 2 acceptance criteria" not in agent_text
        assert "- **FR-002**:" not in template_text
        assert "- **NFR-002**:" not in template_text

    def test_cartographer_keeps_only_evidenced_optional_depth(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        template_text = (TEMPLATE_DIR / "cartographer-spec-template.md").read_text(
            encoding="utf-8"
        )

        assert "Only write an NFR category" in agent_text
        assert "Do not manufacture entities" in agent_text
        assert "Omit this section when no distinct" in template_text
        assert "Do not add an NFR merely to populate" in template_text
        normalized_agent_text = agent_text.lower()
        assert "preserve material negative behavior" in normalized_agent_text
        assert "unresolved uncertainty" in normalized_agent_text

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

    def test_lexicon_deriver_consumes_injected_configuration_and_findings(
        self,
    ) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        phase_text = PHASE.read_text(encoding="utf-8")
        deriver_text = DERIVER.read_text(encoding="utf-8")
        derive_phase_text = DERIVE_PHASE.read_text(encoding="utf-8")

        for text in (agent_text, phase_text):
            assert "Spec Lexicon Repair" not in text
            assert "requirements.lexicon.md" not in text
        for text in (deriver_text, derive_phase_text):
            assert "Controller Configuration" in text
            assert "spec-lexicon-report.json" in text
            assert "requirements.lexicon.md" in text
        assert "Never edit" in deriver_text
        assert "spec.md" in deriver_text
        assert "Never declare specification quality" in deriver_text

    def test_workflow_definition_lists_cartographer_outputs(self) -> None:
        text = DEFINITION.read_text(encoding="utf-8")

        assert "spec.md" in text
        assert "requirements-overview.md" in text

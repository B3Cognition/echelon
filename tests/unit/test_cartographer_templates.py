from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
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

    def test_cartographer_defines_both_authoring_modes(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        phase_text = PHASE.read_text(encoding="utf-8")

        assert "Specification Authoring Modes" in agent_text
        assert "### Proportional Mode" in agent_text
        assert "### Perfectionist Mode" in agent_text
        assert "Classify Feature Complexity Before Authoring" in agent_text
        assert "small deterministic feature" in agent_text
        assert "systematic applicability review" in agent_text
        assert "document-volume quota" in agent_text
        assert "controller-injected `Specification Authoring Mode`" in phase_text
        assert "Classify the discovered feature's complexity" not in phase_text

    def test_perfectionist_mode_preserves_common_cartographer_invariants(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")

        assert "one canonical formal requirement" in agent_text
        assert "never fabricate a requirement" in agent_text
        assert "unresolved facts" in agent_text
        assert "acceptance-to-requirement" in agent_text
        assert "product-input traceability" in agent_text

    def test_workflow_keeps_cartographer_as_the_only_what_agent(self) -> None:
        definition = DEFINITION.read_text(encoding="utf-8")

        assert "agent: echelon.cartographer" in definition
        assert "echelon.perfectionist" not in definition

    def test_readme_documents_perfectionist_as_authoring_depth_only(self) -> None:
        text = README.read_text(encoding="utf-8")
        normalized = " ".join(text.split())

        assert "echelon spec run --perfectionist" in text
        assert "proportional" in text
        assert "does not change autonomy, provider, model, effort" in normalized

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

    def test_cartographer_defines_machine_recognizable_testability(self) -> None:
        agent_text = AGENT.read_text(encoding="utf-8")
        phase_text = PHASE.read_text(encoding="utf-8")

        assert "Machine-Recognizable Testability" in agent_text
        assert "<metric> <comparator> <value> [unit]" in agent_text
        assert "`<`, `<=`, `=`, `>=`, or `>`" in agent_text
        assert "MUST NOT" in agent_text
        assert "SHALL NOT" in agent_text
        assert "invent thresholds" in agent_text
        assert "Machine-Recognizable Testability" not in phase_text

    def test_spec_template_demonstrates_grounded_metric_visible_constraints(
        self,
    ) -> None:
        text = (TEMPLATE_DIR / "cartographer-spec-template.md").read_text(
            encoding="utf-8"
        )

        assert "Constraint: `result_count = 0`" in text
        assert "Constraint: `page_size <= 50 items`" in text
        assert "MUST NOT expose records outside" in text
        assert "only when supported by" in text

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

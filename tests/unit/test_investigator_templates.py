"""Tests for INVESTIGATOR output templates."""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "runtime" / "templates"
AGENT = ROOT / "prosaic" / "subagents" / "echelon.investigator.md"
PHASE1 = ROOT / "runtime" / "workflow" / "phases" / "phase1-investigate.md"
PHASE = ROOT / "runtime" / "workflow" / "phases" / "phase3-specialists.md"


@pytest.mark.unit
class TestInvestigatorTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "investigation-report-template.md",
                [
                    "## 1. Question",
                    "## 2. Research",
                    "## 3. Evaluate",
                    "## 4. Hypothesize",
                    "## 5. Experiment",
                    "## 6. Measure",
                    "## 7. Synthesize",
                    "## 8. Recommend",
                ],
            ),
            (
                "evidence-grades-template.md",
                ["| ID | Question | Source | Grade | Finding | URL | Confidence Impact |"],
            ),
            (
                "recommendations-template.md",
                ["| ID | Recommendation | Confidence | Evidence | Caveats | Alternatives |"],
            ),
            (
                "knowledge-gaps-template.md",
                ["| ID | Unknown | Decision Impact | Cost of Not Knowing | Resolution Path |"],
            ),
        ],
    )
    def test_templates_exist_with_required_anchors(
        self, filename: str, anchors: list[str]
    ) -> None:
        text = (TEMPLATE_DIR / filename).read_text(encoding="utf-8")

        for anchor in anchors:
            assert anchor in text

    def test_investigator_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "investigation-report-template.md",
            "evidence-grades-template.md",
            "recommendations-template.md",
            "knowledge-gaps-template.md",
        ]:
            assert f".echelon/runtime/templates/{filename}" in text

        assert ".specify/..." not in text
        assert (
            "  output_files:\n"
            "    - {spec_dir}/research.md\n"
            "  state_updates: {}\n"
            "  journal_entries:\n"
            in text
        )
        assert "agent: echelon-investigator (INVESTIGATOR)" in text

    def test_phase3_specialist_dispatch_includes_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert ".echelon/runtime/templates/investigation-report-template.md" in text
        assert ".echelon/runtime/templates/evidence-grades-template.md" in text
        assert ".echelon/runtime/templates/recommendations-template.md" in text
        assert ".echelon/runtime/templates/knowledge-gaps-template.md" in text

    def test_phase1_reference_acquisition_precedes_endpoint_discovery(self) -> None:
        phase_text = PHASE1.read_text(encoding="utf-8")
        agent_text = AGENT.read_text(encoding="utf-8")

        assert "## Reference Acquisition Protocol" in phase_text
        assert "every declared snapshot" in phase_text
        assert "Before web search or endpoint discovery" in phase_text
        assert "same-origin links, redirects, and static assets" in phase_text
        assert "NEVER guess conventional schema or API paths" in phase_text
        assert "browser automation only after" in phase_text
        assert "## Evidence Inventory and Bounded Expansion" in phase_text
        assert "Do not select one sibling source as representative" in phase_text
        assert "evidence-inventory.json" in phase_text
        assert "Phase 1 Evidence Resolution" in agent_text
        assert "declared product references take priority" in agent_text

    def test_phase1_investigate_repairs_missing_artifacts_without_repeating_research(self) -> None:
        text = PHASE1.read_text(encoding="utf-8")

        assert "## Missing-Output Recovery" in text
        assert "Do not repeat external retrieval" in text
        assert "evidence-resolution.md`, `evidence-grades.md`, and `evidence-inventory.json`" in text
        assert "Before returning `echelon_result`" in text

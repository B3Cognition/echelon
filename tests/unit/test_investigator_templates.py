"""Tests for INVESTIGATOR output templates."""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "specialists" / "investigator.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase3-specialists.md"


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
            assert f"extension/templates/{filename}" in text

        assert ".specify/..." not in text
        assert (
            "  output_files:\n"
            "    - {spec_dir}/research.md\n"
            "  journal_entries:\n"
            in text
        )
        assert "agent: speckit-echelon-investigator (INVESTIGATOR)" in text

    def test_phase3_specialist_dispatch_includes_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/investigation-report-template.md" in text
        assert "extension/templates/evidence-grades-template.md" in text
        assert "extension/templates/recommendations-template.md" in text
        assert "extension/templates/knowledge-gaps-template.md" in text

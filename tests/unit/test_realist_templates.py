from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "learning" / "realist.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase4-document.md"


class TestRealistTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "reality-check-template.md",
                [
                    "# Reality Check",
                    "## Executive Summary",
                    "## Reality Gaps",
                    "## Operational Constraints",
                ],
            ),
            (
                "cost-analysis-template.md",
                [
                    "# Cost Analysis",
                    "## Cost Summary",
                    "| Component | Monthly Cost | Annual Cost | Source |",
                    "## Budget Fit",
                ],
            ),
            (
                "benchmark-data-template.md",
                [
                    "# Benchmark Data",
                    "## Source Search Log",
                    "## Performance Benchmarks",
                    "## Estimate Grounding",
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

    def test_realist_prompt_references_templates_and_canonical_outputs(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "reality-check-template.md",
            "cost-analysis-template.md",
            "benchmark-data-template.md",
        ]:
            assert f"extension/templates/{filename}" in text

        assert ".specify/specs/{feature}/constitution.md" not in text
        assert "{spec_dir}/constitution.md" in text
        assert "{spec_dir}/reality-check.md" in text
        assert "{spec_dir}/cost-analysis.md" in text
        assert "{spec_dir}/benchmark-data.md" in text
        assert "agent: echelon-realist (REALIST)" in text
        assert "agent: GROUND" not in text

    def test_finalize_dispatch_includes_realist_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/reality-check-template.md" in text
        assert "extension/templates/cost-analysis-template.md" in text
        assert "extension/templates/benchmark-data-template.md" in text
        assert "using the provided templates" in text

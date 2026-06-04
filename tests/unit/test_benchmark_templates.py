from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "specialists" / "benchmark.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase3-specialists.md"


class TestBenchmarkTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "performance-requirements-template.md",
                [
                    "## SLO Table",
                    "| Critical Path | Metric | Target | Load Context | Measurement |",
                    "## Latency Budget",
                    "## Performance Acceptance Criteria",
                ],
            ),
            (
                "capacity-model-template.md",
                [
                    "## Load Model",
                    "| Dimension | Current | Peak | 10x | Assumptions | Confidence |",
                    "## Resource Sizing",
                    "## Growth Timeline",
                ],
            ),
            (
                "performance-amendments-template.md",
                [
                    "## Plan Amendments",
                    "| Area | Recommendation | Metric / Trigger | Rationale |",
                    "## Bottleneck Risks",
                    "## Benchmark Plan",
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

    def test_benchmark_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "performance-requirements-template.md",
            "capacity-model-template.md",
            "performance-amendments-template.md",
        ]:
            assert f"extension/templates/{filename}" in text

        assert "performance-model.md" not in text
        assert ".specify/..." not in text
        assert (
            "  output_files:\n"
            "    - {spec_dir}/performance-requirements.md\n"
            "    - {spec_dir}/capacity-model.md\n"
            "  journal_entries:\n"
            in text
        )
        assert "agent: speckit-echelon-benchmark (BENCHMARK)" in text

    def test_phase3_specialist_dispatch_includes_benchmark_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/performance-requirements-template.md" in text
        assert "extension/templates/capacity-model-template.md" in text
        assert "extension/templates/performance-amendments-template.md" in text

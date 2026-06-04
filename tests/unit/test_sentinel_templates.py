from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "solution" / "sentinel.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase3-sentinel.md"


class TestSentinelTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "test-strategy-template.md",
                [
                    "## Stack Detection",
                    "## Testability Deficiency",
                    "## Test Pyramid",
                    "## CI/CD Pipeline",
                    "## Flakiness Management",
                ],
            ),
            (
                "test-architecture-template.md",
                [
                    "## Framework Choices",
                    "## Test Folder Structure",
                    "## Shared Test Utilities",
                    "## Test Doubles",
                    "## Naming Conventions",
                ],
            ),
            (
                "coverage-map-template.md",
                [
                    "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |",
                    "## Gap Analysis",
                    "## Escalations",
                    "NEVER use `manual` as Coverage Type or Automation Status",
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

    def test_sentinel_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "test-strategy-template.md",
            "test-architecture-template.md",
            "coverage-map-template.md",
        ]:
            assert f"extension/templates/{filename}" in text

        assert ".specify/..." not in text
        assert (
            "  output_files:\n"
            "    - {spec_dir}/test-strategy.md\n"
            "    - {spec_dir}/test-architecture.md\n"
            "    - {spec_dir}/coverage-map.md\n"
            "  journal_entries:\n"
            in text
        )
        assert "agent: speckit-echelon-sentinel (SENTINEL)" in text

    def test_phase3_sentinel_dispatch_includes_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/test-strategy-template.md" in text
        assert "extension/templates/test-architecture-template.md" in text
        assert "extension/templates/coverage-map-template.md" in text
        assert "Produce outputs in `specs/{NNN}-{feature}/`" not in text
        assert "Produce outputs in `{spec_dir}/`" in text
        assert "three files in `specs/{NNN}-{feature}/`" not in text
        assert "three files in `{spec_dir}/`" in text

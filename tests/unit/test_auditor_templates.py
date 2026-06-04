from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
APPENDIX_DIR = ROOT / "extension" / "agents" / "learning" / "appendices"
AGENT = ROOT / "extension" / "agents" / "learning" / "auditor.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase4-document.md"


class TestAuditorTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "auditor-dashboard-template.md",
                [
                    "## Domain Calibration Overview",
                    "## Evolution Signals",
                    "## Calibration Analytics",
                ],
            ),
            (
                "auditor-output-formats.md",
                [
                    "## Calibration Profile Entry",
                    "## Auto Feedback Schema",
                    "## Feedback Report Sections",
                ],
            ),
        ],
    )
    def test_appendices_exist_with_required_anchors(
        self, filename: str, anchors: list[str]
    ) -> None:
        text = (APPENDIX_DIR / filename).read_text(encoding="utf-8")

        for anchor in anchors:
            assert anchor in text

    def test_auditor_prompt_references_appendices_and_canonical_outputs(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "agents/learning/appendices/auditor-dashboard-template.md" in text
        assert "agents/learning/appendices/auditor-output-formats.md" in text
        assert ".specify/specs/" not in text
        assert "{spec_dir}/calibration-dashboard.md" in text
        assert "{spec_dir}/calibration-analytics.md" in text
        assert "{spec_dir}/confidence-flags.md" in text
        assert "{spec_dir}/feedback-report.md" in text
        assert "agent: speckit-echelon-auditor (AUDITOR)" in text
        assert "agent: CALIBRATE" not in text

    def test_auditor_output_appendix_uses_canonical_feedback_report_path(self) -> None:
        text = (APPENDIX_DIR / "auditor-output-formats.md").read_text(encoding="utf-8")

        assert "specs/{feature}/feedback-report.md" not in text
        assert "{spec_dir}/feedback-report.md" in text

    def test_finalize_dispatch_includes_auditor_appendices(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "agents/learning/appendices/auditor-dashboard-template.md" in text
        assert "agents/learning/appendices/auditor-output-formats.md" in text
        assert "using the provided appendices" in text

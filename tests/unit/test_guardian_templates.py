from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "specialists" / "guardian.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase3-specialists.md"


class TestGuardianTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "security-checklist-template.md",
                [
                    "| # | Check | Status | Finding |",
                    "## Overall Recommendation",
                    "PROCEED_WITH_WARNINGS",
                ],
            ),
            (
                "threat-model-template.md",
                [
                    "## Asset Inventory",
                    "## STRIDE Analysis",
                    "## OWASP Top 10 Mapping",
                    "## Prioritized Mitigations",
                ],
            ),
            (
                "compliance-requirements-template.md",
                [
                    "## Applicable Frameworks",
                    "| Framework | Control | Requirement | Current Coverage | Priority |",
                    "## Gap Analysis",
                ],
            ),
            (
                "risk-acceptance-log-template.md",
                [
                    "## Risk Acceptance Records",
                    "### RAR-<NNN>: <Finding Title>",
                    "## Human Review Required",
                ],
            ),
            (
                "security-findings-template.md",
                [
                    "## Findings Summary",
                    "| ID | Severity | Finding | Impact | Likelihood | Confidence | Mitigation |",
                    "## Architecture Amendments",
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

    def test_guardian_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "security-checklist-template.md",
            "threat-model-template.md",
            "compliance-requirements-template.md",
            "risk-acceptance-log-template.md",
            "security-findings-template.md",
        ]:
            assert f"extension/templates/{filename}" in text

        assert ".specify/..." not in text
        assert "security-checklist.md` in `specs/{NNN}-{feature}/`" not in text
        assert "security-checklist.md` in `{spec_dir}/`" in text
        assert (
            "  output_files:\n"
            "    - {spec_dir}/security-findings.md\n"
            "    - {spec_dir}/risk-acceptance-log.md\n"
            "  state_updates: {}\n"
            "  journal_entries:\n"
            in text
        )
        assert "agent: speckit-echelon-guardian (GUARDIAN)" in text

    def test_phase3_specialist_dispatch_includes_guardian_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/security-checklist-template.md" in text
        assert "extension/templates/threat-model-template.md" in text
        assert "extension/templates/compliance-requirements-template.md" in text
        assert "extension/templates/risk-acceptance-log-template.md" in text
        assert "extension/templates/security-findings-template.md" in text

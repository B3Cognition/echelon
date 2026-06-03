from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "learning" / "mirror.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase4-document.md"


class TestMirrorTemplates:
    def test_knowledge_transfer_template_exists_with_required_anchors(self) -> None:
        text = (TEMPLATE_DIR / "knowledge-transfer-assessment-template.md").read_text(
            encoding="utf-8"
        )

        for anchor in [
            "## Knowledge Transfer Assessment",
            "### Risk Table",
            "### Documentation Level Criteria",
            "### Concentration Risk Criteria",
            "### Overall Verdict",
            "### Recommended Actions",
        ]:
            assert anchor in text

    def test_mirror_prompt_references_template_and_canonical_outputs(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "extension/templates/knowledge-transfer-assessment-template.md" in text
        assert ".specify/specs/" not in text
        assert "{spec_dir}/knowledge-transfer-assessment.md" in text
        assert "knowledge-base/patterns.yaml" in text
        assert "knowledge-base/pitfalls.yaml" in text
        assert "agent: speckit-echelon-mirror (MIRROR)" in text
        assert "agent: REFLECT" not in text

    def test_finalize_dispatch_includes_mirror_template(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/knowledge-transfer-assessment-template.md" in text
        assert "using the provided template" in text

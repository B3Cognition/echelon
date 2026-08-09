from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "learning" / "veteran.md"


class TestVeteranTemplates:
    def test_marketplace_entry_template_exists_with_required_anchors(self) -> None:
        text = (TEMPLATE_DIR / "marketplace-index-entry-template.yaml").read_text(
            encoding="utf-8"
        )

        for anchor in [
            "- id:",
            "source_fingerprints:",
            "reuse_count:",
            "last_seen:",
        ]:
            assert anchor in text

    def test_veteran_prompt_references_template_and_canonical_outputs(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "extension/templates/marketplace-index-entry-template.yaml" in text
        assert "knowledge-base/patterns.yaml" in text
        assert "knowledge-base/pitfalls.yaml" in text
        assert "knowledge-base/marketplace-index.yaml" in text
        assert "agent: echelon-veteran (VETERAN)" in text

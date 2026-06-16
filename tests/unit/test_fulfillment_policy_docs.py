from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_readme_documents_fulfillment_refresh_policies() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Harness fulfillment refresh policy" in text
    assert "refresh_policy: scoped" in text
    assert "`milestone`" in text
    assert "`scoped`" in text
    assert "`every_slice`" in text
    assert "`convergence_only`" in text


def test_config_template_mentions_scoped_refresh_policy() -> None:
    text = (ROOT / "extension/config-template.yml").read_text(encoding="utf-8")

    assert "# - scoped: re-judge only deterministically impacted requirement rows" in text

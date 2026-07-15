"""Documentation contracts for PerlGraph integration."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent


def test_re_overview_lists_perlgraph_artifacts() -> None:
    text = (ROOT / "docs" / "re-overview.md").read_text(encoding="utf-8")

    assert "perlgraph-analysis.json" in text
    assert "perlgraph-summary.json" in text
    assert "PerlGraph" in text


def test_readme_re_analyze_mentions_perlgraph_artifacts() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "optional CodeGraph and PerlGraph artifacts" in text

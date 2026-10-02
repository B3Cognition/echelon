"""Documentation contracts for PerlGraph integration."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent


def test_re_overview_lists_perlgraph_artifacts() -> None:
    text = (ROOT / "docs" / "re-overview.md").read_text(encoding="utf-8")

    assert "perlgraph-analysis.json" in text
    assert "perlgraph-summary.json" in text
    assert "PerlGraph" in text


def test_readme_re_run_describes_optional_bounded_graph_evidence() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "optional CodeGraph and PerlGraph evidence" in normalized
    assert "`echelon re run`" in normalized
    assert "`echelon re refresh`" in normalized
    assert "temporary pinned source tree" in normalized
    assert "never indexes the mutable source checkout" in normalized
    assert "do not block core RE or spec authoring" in normalized
    assert "read-only `echelon re analyze` baseline and cost report" in normalized

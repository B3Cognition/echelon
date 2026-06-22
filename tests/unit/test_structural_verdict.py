import pytest
from lexicon.structural import verdict_findings
from lexicon.manifest import _norm_heading

SEC = _norm_heading("Kill / Defer / Pass Decision")
ENUM = ["PASS", "KILL", "DEFER"]

@pytest.mark.unit
def test_valid_verdict_clean():
    doc = f"## Kill / Defer / Pass Decision\nDecision: PASS — proceed.\n"
    assert verdict_findings(doc, SEC, ENUM) == []

@pytest.mark.unit
def test_missing_verdict_flagged():
    doc = "## Kill / Defer / Pass Decision\nWe will think about it later.\n"
    assert [f.code for f in verdict_findings(doc, SEC, ENUM)] == ["missing-verdict"]

@pytest.mark.unit
def test_absent_section_is_missing_verdict():
    doc = "## Something Else\nPASS\n"
    assert [f.code for f in verdict_findings(doc, SEC, ENUM)] == ["missing-verdict"]

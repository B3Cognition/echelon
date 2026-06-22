import pytest
from lexicon.structural import section_findings
from lexicon.manifest import _norm_heading

REQ = [_norm_heading("Feasibility Verdict"), _norm_heading("Key Risks")]

@pytest.mark.unit
def test_missing_section_flagged():
    doc = "# Title\n\n## Feasibility Verdict\nPASS\n"
    codes = [f.code for f in section_findings(doc, REQ)]
    assert "missing-section" in codes  # Key Risks absent

@pytest.mark.unit
def test_empty_section_flagged():
    doc = "## Feasibility Verdict\nPASS\n\n## Key Risks\n\n"
    fs = section_findings(doc, REQ)
    assert any(f.code == "missing-section" and "Key Risks".casefold() in f.span for f in fs)

@pytest.mark.unit
def test_all_present_clean():
    doc = "## Feasibility Verdict\nPASS\n\n## Key Risks\n- r1\n"
    assert section_findings(doc, REQ) == []

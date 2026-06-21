import pytest
from lexicon.structural import unresolved_ref_findings

SPEC = (
    "ARTIFACT: SPEC\nTITLE: T\n\n"
    "REQ: FR-001\nGIVEN: g\nWHEN: w\nTHEN: the system MUST x\nOUTPUT: o\nEXAMPLE: AC-001\n\n"
    "AC: AC-001\nGIVEN: g\nWHEN: w\nTHEN: y\n"
)

@pytest.mark.unit
def test_unresolved_ref_flagged():
    doc = "## Divergence Points\nDiverges from FR-999 and FR-001.\n"
    fs = unresolved_ref_findings(doc, "REQ|FR|NFR", SPEC)
    assert [f.span for f in fs] == ["FR-999"]   # FR-001 resolves, FR-999 does not

@pytest.mark.unit
def test_all_resolve_clean():
    doc = "## Divergence Points\nAligned to FR-001 / AC-001.\n"
    assert unresolved_ref_findings(doc, "REQ|FR|NFR", SPEC) == []

@pytest.mark.unit
def test_no_spec_no_findings():
    assert unresolved_ref_findings("FR-001", "REQ|FR|NFR", "") == []

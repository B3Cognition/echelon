import pytest
from lexicon.structural import structural_validate

SPEC = ("ARTIFACT: SPEC\nTITLE: T\n\nREQ: FR-001\nGIVEN: g\nWHEN: w\n"
        "THEN: the system MUST x\nOUTPUT: o\nEXAMPLE: AC-001\n\n"
        "AC: AC-001\nGIVEN: g\nWHEN: w\nTHEN: y\n")

ENTRY = {
    "template": "intent-alignment-check-template.md",
    "verdict": {"section": "Alignment Verdict", "enum": ["ALIGNED", "DRIFT"]},
    "cross_refs": [{"ids": "REQ|FR|NFR", "against": "spec.md"}],
}

def _doc(verdict="ALIGNED", ref="FR-001"):
    return (
        "## Metadata\nrun: r1\n\n"
        f"## Alignment Verdict\n{verdict}\n\n"
        f"## Divergence Points\nNone material; cf {ref}.\n\n"
        "## Required Action\nproceed\n"
    )

@pytest.mark.unit
def test_clean_doc_ok():
    r = structural_validate(_doc(), ENTRY, SPEC)
    assert r.ok is True, [f.code for f in r.findings]

@pytest.mark.unit
def test_bad_verdict_not_ok():
    r = structural_validate(_doc(verdict="maybe"), ENTRY, SPEC)
    assert r.ok is False and "missing-verdict" in [f.code for f in r.findings]

@pytest.mark.unit
def test_unresolved_ref_not_ok():
    r = structural_validate(_doc(ref="FR-404"), ENTRY, SPEC)
    assert "unresolved-ref" in [f.code for f in r.findings]

@pytest.mark.unit
def test_malformed_returns_report_not_exception():
    assert structural_validate("", ENTRY, SPEC).ok is False

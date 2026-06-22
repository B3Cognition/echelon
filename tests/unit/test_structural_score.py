import pytest
from lexicon.structural_score import structural_quality

ENTRY = {"template": "feasibility-template.md",
         "verdict": {"section": "Kill / Defer / Pass Decision", "enum": ["PASS", "KILL", "DEFER"]}}

@pytest.mark.unit
def test_score_in_unit_interval():
    s = structural_quality("", ENTRY)
    assert 0.0 <= s <= 1.0

@pytest.mark.unit
def test_clean_scores_one():
    doc = ("## Metadata\nr\n\n## Feasibility Verdict\nfeasible\n\n"
           "## Key Risks\n- r\n\n## Kill / Defer / Pass Decision\nPASS\n")
    assert structural_quality(doc, ENTRY) == 1.0

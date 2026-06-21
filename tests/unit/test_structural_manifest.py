import pytest
import pathlib
from lexicon.manifest import required_sections, _norm_heading

TPL = pathlib.Path("extension/templates")


@pytest.mark.unit
def test_required_sections_from_feasibility_template():
    secs = required_sections(TPL / "feasibility-template.md")
    assert _norm_heading("Kill / Defer / Pass Decision") in secs
    assert _norm_heading("Feasibility Verdict") in secs


@pytest.mark.unit
def test_norm_heading_normalizes():
    assert _norm_heading("  Feasibility Verdict:  ") == _norm_heading("feasibility verdict")

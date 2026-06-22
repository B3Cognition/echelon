"""Referential-integrity gate for the spec REQ DEPENDS field.

Every DEPENDS target must be a REQ defined in this spec; a REQ may not depend on
itself; the DEPENDS graph must be acyclic. Mirrors the tasks-grammar
dep-missing / dep-cycle checks.
"""

import pytest

from lexicon.crossdoc import spec_depends_findings
from lexicon.validity import validate

_HDR = "ARTIFACT: SPEC\nTITLE: Catalog\n\n"


def _req(rid, depends=None, example="AC-001"):
    block = (
        f"REQ: {rid}\n"
        "GIVEN: a precondition\n"
        "WHEN: a trigger\n"
        f"THEN: the system MUST act on {rid.lower().replace('-', '_')}\n"
        "OUTPUT: an observable result\n"
    )
    if depends is not None:
        block += f"DEPENDS: {depends}\n"
    block += f"EXAMPLE: {example}\n"
    return block


_AC = "AC: AC-001\nGIVEN: a state\nWHEN: an action\nTHEN: an observable outcome\n"


def _codes(text):
    return {f.code for f in spec_depends_findings(text)}


@pytest.mark.unit
def test_valid_depends_chain_has_no_findings():
    text = _HDR + _req("FR-001", "none") + _req("FR-002", "FR-001") + _AC
    assert spec_depends_findings(text) == []


@pytest.mark.unit
def test_depends_on_undefined_requirement_flagged():
    text = _HDR + _req("FR-001", "FR-099") + _AC
    assert "dep-missing" in _codes(text)


@pytest.mark.unit
def test_self_dependency_flagged():
    text = _HDR + _req("FR-001", "FR-001") + _AC
    assert "dep-self" in _codes(text)


@pytest.mark.unit
def test_dependency_cycle_flagged():
    text = _HDR + _req("FR-001", "FR-002") + _req("FR-002", "FR-001") + _AC
    assert "dep-cycle" in _codes(text)


@pytest.mark.unit
def test_depends_none_and_omitted_are_clean():
    text = _HDR + _req("FR-001", "none") + _req("FR-002", depends=None) + _AC
    assert spec_depends_findings(text) == []


@pytest.mark.unit
def test_gate_wired_into_validate():
    """validate() surfaces dep-missing for a SPEC (the gate is wired in)."""
    text = _HDR + _req("FR-001", "FR-099") + _AC
    report = validate(text, artifact_type="SPEC")
    assert any(f.code == "dep-missing" for f in report.findings)
    assert report.ok is False

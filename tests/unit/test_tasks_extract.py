import pytest
from lexicon.tasks import extract_tasks

DOC = """ARTIFACT: TASKS
TITLE: t

TASK: T-001
PHASE: foundation
COMPLEXITY: standard
PARALLEL: no
REQ: REQ-001 REQ-002
DEPENDS: none
ACCEPTANCE: the list renders
TEST: a test asserts the list

TASK: T-002
PHASE: foundation
COMPLEXITY: complex
PARALLEL: yes
REQ: INFRA
DEPENDS: T-001
ACCEPTANCE: the store persists
TEST: a test asserts persistence
"""

@pytest.mark.unit
def test_extract_parses_fields_and_lists():
    ts = extract_tasks(DOC)
    assert [t.id for t in ts] == ["T-001", "T-002"]
    assert ts[0].reqs == ["REQ-001", "REQ-002"]
    assert ts[0].depends == []          # "none" -> empty
    assert ts[1].reqs == ["INFRA"]
    assert ts[1].depends == ["T-001"]
    assert ts[1].parallel is True

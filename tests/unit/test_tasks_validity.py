import pytest
from lexicon.tasks import validate_tasks

SPEC = ("ARTIFACT: SPEC\nTITLE: t\n\nREQ: REQ-001\nGIVEN: g\nWHEN: w\n"
        "THEN: the system MUST act\nOUTPUT: r\nEXAMPLE: AC-001\n\n"
        "AC: AC-001\nGIVEN: g\nWHEN: w\nTHEN: visible\n")

TASKS_OK = """# Tasks: t

- [ ] T-001 complexity=standard phase=p req=REQ-001 depends=none

  **Title:** Do the thing
  **Description:** Build it.
  **Test:** a test asserts one row renders
  **Acceptance Criteria:**
  - [ ] the run list renders one row
"""


@pytest.mark.unit
def test_clean_tasks_valid():
    r = validate_tasks(TASKS_OK, glossary=set(), spec_text=SPEC)
    assert r.ok is True and r.parse_pass is True and r.findings == []


@pytest.mark.unit
def test_uncovered_req_makes_invalid():
    tasks = TASKS_OK.replace("req=REQ-001", "req=INFRA")  # REQ-001 now uncovered
    r = validate_tasks(tasks, glossary=set(), spec_text=SPEC)
    assert r.ok is False
    assert any(f.code == "req-uncovered" for f in r.findings)


@pytest.mark.unit
def test_parse_error_makes_invalid():
    r = validate_tasks("not a tasks doc", glossary=set(), spec_text=SPEC)
    assert r.ok is False and r.parse_pass is False

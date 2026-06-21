import pytest
from lexicon.tasks import extract_tasks

TASKS_OK = """# Tasks: Demo

## Phase: Foundation

- [ ] T-001 [P] complexity=standard phase=foundation req=FR-001 depends=none

  **Title:** Establish project structure
  **Description:** Scaffold the workspace.
  **Test:** A CI lint and type-check run passes on the scaffold.
  **Acceptance Criteria:**
  - [ ] the workspace builds under TS strict

- [ ] T-002 complexity=standard phase=foundation req=FR-002 depends=T-001

  **Title:** Add the daemon
  **Description:** Implement the loopback daemon.
  **Test:** A test asserts GET / returns 200 with a non-empty body.
  **Acceptance Criteria:**
  - [ ] the daemon serves on 127.0.0.1

- [ ] T-003 complexity=standard phase=foundation req=FR-001,FR-002 depends=none

  **Title:** Document the system
  **Description:** Write comprehensive API documentation.
  **Test:** A docs build runs without warnings and the output is HTML.
  **Acceptance Criteria:**
  - [ ] all public APIs are documented
"""

@pytest.mark.unit
def test_extract_canonical_rows():
    ts = extract_tasks(TASKS_OK)
    assert [t.id for t in ts] == ["T-001", "T-002", "T-003"]
    assert ts[0].parallel is True and ts[1].parallel is False
    assert ts[0].reqs == ["FR-001"] and ts[1].depends == ["T-001"]
    assert ts[2].reqs == ["FR-001", "FR-002"]        # multi-req extraction
    assert "200" in ts[1].test                       # **Test:** captured
    assert "TS strict" in ts[0].acceptance           # acceptance criteria joined
    assert ts[0].line > 0

@pytest.mark.unit
def test_extract_malformed_returns_empty():
    assert extract_tasks("not a tasks doc") == []

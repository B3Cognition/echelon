import pytest
from lexicon.crossdoc import cross_doc_findings

SPEC = """ARTIFACT: SPEC
TITLE: t

REQ: REQ-001
GIVEN: g
WHEN: w
THEN: the system MUST act
OUTPUT: a result
EXAMPLE: AC-001

REQ: REQ-002
GIVEN: g
WHEN: w
THEN: the system MUST persist
OUTPUT: stored
EXAMPLE: AC-002

AC: AC-001
GIVEN: g
WHEN: w
THEN: visible

AC: AC-002
GIVEN: g
WHEN: w
THEN: persisted
"""


def _tasks(*rows):
    body = "".join(rows)
    return f"# Tasks: t\n\n{body}"


def _task(tid, req, depends="none", test="a test asserts it"):
    depends_val = depends
    return (
        f"- [ ] {tid} complexity=standard phase=p req={req} depends={depends_val}\n\n"
        f"  **Title:** Task {tid}\n"
        f"  **Description:** Implements {req}.\n"
        f"  **Test:** {test}\n"
        f"  **Acceptance Criteria:**\n"
        f"  - [ ] x is observable\n\n"
    )


@pytest.mark.unit
def test_uncovered_req_flagged():
    # only REQ-001 covered; REQ-002 has no task
    f = cross_doc_findings(_tasks(_task("T-001", "REQ-001")), SPEC)
    assert any(x.code == "req-uncovered" and x.span == "REQ-002" for x in f)


@pytest.mark.unit
def test_orphan_task_req_flagged():
    f = cross_doc_findings(_tasks(_task("T-001", "REQ-001"), _task("T-002", "REQ-999")), SPEC)
    assert any(x.code == "task-orphan-req" and "REQ-999" in x.message for x in f)


@pytest.mark.unit
def test_dependency_cycle_flagged():
    f = cross_doc_findings(
        _tasks(_task("T-001", "REQ-001", "T-002"), _task("T-002", "REQ-002", "T-001")),
        SPEC,
    )
    assert any(x.code == "dep-cycle" for x in f)


@pytest.mark.unit
def test_full_coverage_acyclic_passes():
    f = cross_doc_findings(
        _tasks(_task("T-001", "REQ-001"), _task("T-002", "REQ-002", "T-001")),
        SPEC,
    )
    assert f == []

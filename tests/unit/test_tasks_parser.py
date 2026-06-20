"""Unit tests for the TASKS grammar parser."""

import pytest
from lexicon.tasks_parser import parse_pass

GOOD = """ARTIFACT: TASKS
TITLE: Build the workbench

TASK: T-001
PHASE: foundation
COMPLEXITY: standard
PARALLEL: no
REQ: REQ-001
DEPENDS: none
ACCEPTANCE: the run list renders three rows from three run directories
TEST: integration test asserts three rows for a three-run fixture
"""

MISSING_TEST = """ARTIFACT: TASKS
TITLE: t

TASK: T-001
PHASE: foundation
COMPLEXITY: standard
PARALLEL: no
REQ: REQ-001
DEPENDS: none
ACCEPTANCE: something observable
"""

@pytest.mark.unit
def test_valid_tasks_doc_parses():
    assert parse_pass(GOOD) is True

@pytest.mark.unit
def test_task_missing_required_field_fails():
    assert parse_pass(MISSING_TEST) is False

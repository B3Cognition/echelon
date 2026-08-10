"""Contract test: the shipped template's example rows are parseable canonical rows,
and the gate-clean fixture passes both the lexicon governance gate and the
harness's canonical validator (the same file is governed and buildable)."""
import pathlib

import pytest

from kernel.task_contract import parse_task_rows, validate_tasks_markdown
from lexicon.tasks import validate_tasks

FX = pathlib.Path("tests/fixtures/lexicon")
SPEC = FX / "spec_ok.md"


@pytest.mark.unit
def test_template_parses_as_canonical_rows():
    """Anti-drift: the shipped template's example rows ARE canonical rows."""
    tpl = pathlib.Path("runtime/templates/tasks-template.md").read_text()
    assert len(parse_task_rows(tpl)) >= 1


@pytest.mark.unit
def test_gate_clean_tasks_is_harness_valid():
    """The gate-clean fixture passes lexicon governance AND the harness validator."""
    tasks = (FX / "tasks_ok.md").read_text()
    spec = SPEC.read_text()
    # lexicon governance gate passes
    assert validate_tasks(tasks, glossary=set(), spec_text=spec).ok is True, \
        [f.code for f in validate_tasks(tasks, glossary=set(), spec_text=spec).findings]
    # AND the harness's canonical validator accepts the same file
    assert validate_tasks_markdown(tasks).valid is True

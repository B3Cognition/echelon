import pytest, pathlib
from lexicon.tasks import validate_tasks

FX = pathlib.Path("tests/fixtures/lexicon")

@pytest.mark.unit
def test_fixture_pair_is_valid_end_to_end():
    tasks = (FX / "tasks_ok.md").read_text()
    spec = (FX / "spec_ok.md").read_text()
    r = validate_tasks(tasks, glossary=set(), spec_text=spec)
    assert r.ok is True, [f.code for f in r.findings]

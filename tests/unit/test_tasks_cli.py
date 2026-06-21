import pytest
from typer.testing import CliRunner
from lexicon.cli import app

runner = CliRunner()
SPEC = ("ARTIFACT: SPEC\nTITLE: t\n\nREQ: REQ-001\nGIVEN: g\nWHEN: w\n"
        "THEN: the system MUST act\nOUTPUT: r\nEXAMPLE: AC-001\n\n"
        "AC: AC-001\nGIVEN: g\nWHEN: w\nTHEN: visible\n")
TASKS_OK = ("ARTIFACT: TASKS\nTITLE: t\n\nTASK: T-001\nPHASE: p\nCOMPLEXITY: standard\n"
            "PARALLEL: no\nREQ: REQ-001\nDEPENDS: none\n"
            "ACCEPTANCE: the run list renders one row\nTEST: a test asserts one row\n")

def _w(tmp, name, body):
    p = tmp / name; p.write_text(body, encoding="utf-8"); return str(p)

@pytest.mark.unit
def test_valid_tasks_exits_zero(tmp_path):
    t = _w(tmp_path, "tasks.md", TASKS_OK); s = _w(tmp_path, "spec.md", SPEC)
    res = runner.invoke(app, ["validate", t, "--type", "tasks", "--spec-ref", s])
    assert res.exit_code == 0

@pytest.mark.unit
def test_uncovered_req_exits_one(tmp_path):
    t = _w(tmp_path, "tasks.md", TASKS_OK.replace("REQ: REQ-001", "REQ: INFRA"))
    s = _w(tmp_path, "spec.md", SPEC)
    res = runner.invoke(app, ["validate", t, "--type", "tasks", "--spec-ref", s])
    assert res.exit_code == 1
    assert "req-uncovered" in res.stdout

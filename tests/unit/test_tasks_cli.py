import pytest
from typer.testing import CliRunner
from lexicon.cli import app

runner = CliRunner()
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


def _w(tmp, name, body):
    p = tmp / name; p.write_text(body, encoding="utf-8"); return str(p)


@pytest.mark.unit
def test_valid_tasks_exits_zero(tmp_path):
    t = _w(tmp_path, "tasks.md", TASKS_OK); s = _w(tmp_path, "spec.md", SPEC)
    res = runner.invoke(app, ["validate", t, "--type", "tasks", "--spec-ref", s])
    assert res.exit_code == 0


@pytest.mark.unit
def test_uncovered_req_exits_one(tmp_path):
    t = _w(tmp_path, "tasks.md", TASKS_OK.replace("req=REQ-001", "req=INFRA"))
    s = _w(tmp_path, "spec.md", SPEC)
    res = runner.invoke(app, ["validate", t, "--type", "tasks", "--spec-ref", s])
    assert res.exit_code == 1
    assert "req-uncovered" in res.stdout

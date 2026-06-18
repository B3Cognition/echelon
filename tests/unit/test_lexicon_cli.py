"""Unit tests for the `lexicon` CLI wiring (exit codes + glossary loading)."""

import pytest
from typer.testing import CliRunner

from lexicon.cli import app

runner = CliRunner()

GOOD_SPEC = """ARTIFACT: SPEC
TITLE: Overdue task dashboard

REQ: TASK-07
GIVEN: the user has at least one overdue task
WHEN: the user opens the task dashboard
THEN: the dashboard MUST display the overdue list sorted by due_date ascending
OUTPUT: a visible overdue list
CONSTRAINT: latency <= 500 ms for p95 requests
EXAMPLE: AC-1

AC: AC-1
GIVEN: the user has at least one overdue task
WHEN: the user opens the task dashboard
THEN: the overdue list is shown
"""

BANNED_SPEC = GOOD_SPEC.replace("the overdue list", "a robust overdue list")


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


@pytest.mark.unit
def test_valid_spec_exits_zero(tmp_path):
    spec = _write(tmp_path, "spec.md", GOOD_SPEC)
    glossary = _write(tmp_path, "glossary.md", "due_date\n")
    result = runner.invoke(app, ["validate", spec, "--glossary", glossary])
    assert result.exit_code == 0


@pytest.mark.unit
def test_banned_word_exits_one_and_reports(tmp_path):
    spec = _write(tmp_path, "spec.md", BANNED_SPEC)
    glossary = _write(tmp_path, "glossary.md", "due_date\n")
    result = runner.invoke(app, ["validate", spec, "--glossary", glossary])
    assert result.exit_code == 1
    assert "banned-word" in result.stdout
    assert "robust" in result.stdout


@pytest.mark.unit
def test_unresolved_term_without_glossary_exits_one(tmp_path):
    spec = _write(tmp_path, "spec.md", GOOD_SPEC)
    result = runner.invoke(app, ["validate", spec])
    assert result.exit_code == 1
    assert "due_date" in result.stdout

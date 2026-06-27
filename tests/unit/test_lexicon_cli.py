"""Unit tests for the `lexicon` CLI wiring (exit codes + glossary loading)."""

import hashlib
import json

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


RICH_SOURCE_SPEC = """# Feature Specification

## Functional Requirements

- **FR-001**: Render themed ASCII animation from user input.

## Acceptance Criteria

- **AC-001**: Given user text and a theme, when rendering starts, then frames are shown.

## Error Cases

- **ERR-001**: Empty theme is rejected.
"""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _derived_spec(source_text: str, req_id: str = "FR-001") -> str:
    return f"""# SOURCE: spec.md
# SOURCE_SHA256: {_hash(source_text)}
ARTIFACT: SPEC
TITLE: Themed ASCII animation

REQ: {req_id}
GIVEN: the user provides text
WHEN: the user selects a theme
THEN: the program MUST render animated ascii art
OUTPUT: animated ascii art frames
DEPENDS: none
EXAMPLE: AC-001

AC: AC-001
GIVEN: the user provides text
WHEN: the user starts rendering
THEN: animated ascii art frames are shown

ERROR: ERR-001
WHEN: the selected theme is empty
THEN: reject the request with a message
ERROR_CODE: EMPTYTHEME
"""


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


@pytest.mark.unit
def test_source_ref_accepts_fresh_derived_spec_with_same_requirement_ids(tmp_path):
    source = _write(tmp_path, "spec.md", RICH_SOURCE_SPEC)
    derived = _write(tmp_path, "requirements.lexicon.md", _derived_spec(RICH_SOURCE_SPEC))

    result = runner.invoke(
        app,
        ["validate", derived, "--type", "spec", "--source-ref", source, "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["source_ref"] == source


@pytest.mark.unit
def test_source_ref_rejects_stale_derived_spec_hash(tmp_path):
    source = _write(tmp_path, "spec.md", RICH_SOURCE_SPEC + "\n- **FR-002**: New.\n")
    derived = _write(tmp_path, "requirements.lexicon.md", _derived_spec(RICH_SOURCE_SPEC))

    result = runner.invoke(
        app,
        ["validate", derived, "--type", "spec", "--source-ref", source, "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert any(f["code"] == "source-hash-mismatch" for f in payload["findings"])


@pytest.mark.unit
def test_source_ref_rejects_derived_spec_ids_absent_from_source(tmp_path):
    source = _write(tmp_path, "spec.md", RICH_SOURCE_SPEC)
    derived = _write(tmp_path, "requirements.lexicon.md", _derived_spec(RICH_SOURCE_SPEC, "FR-999"))

    result = runner.invoke(
        app,
        ["validate", derived, "--type", "spec", "--source-ref", source, "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert any(f["code"] == "source-id-extra" for f in payload["findings"])

"""
Integration tests for the journal-append helper (spec 027).

Tests INT-01 through INT-04 per test-strategy.md.
Covers: FR-002, FR-003, FR-004, FR-010, FR-011, NFR-002.

Run:
    pytest tests/integration/test_journal_append_helper.py -v
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
APPEND_SCRIPT = ROOT / "runtime" / "scripts" / "bash" / "journal-append.sh"
VALIDATOR_SCRIPT = ROOT / "runtime" / "scripts" / "bash" / "validate-journal-entry.sh"
YAML_PATH = ROOT / "runtime" / "workflow" / "journal-entry-types.yaml"
JSON_PATH = ROOT / "runtime" / "workflow" / "journal-entry-types.json"
FIXTURES = ROOT / "tests" / "fixtures" / "journal-entries"


def _run_append(entry_json: str, journal_path: Path) -> subprocess.CompletedProcess:
    """Run journal-append.sh with the given entry and journal path."""
    return subprocess.run(
        ["bash", str(APPEND_SCRIPT), "--entry", entry_json, "--journal-path", str(journal_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )


# ---------------------------------------------------------------------------
# INT-01: Full flow with valid routing_decision — no schema_warning
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_int01_valid_routing_decision_no_warning(tmp_path):
    """Complete routing_decision entry produces no schema_warning."""
    journal = tmp_path / "journal.jsonl"
    entry = json.loads((FIXTURES / "valid-routing-decision.json").read_text())
    entry_json = json.dumps(entry)

    result = _run_append(entry_json, journal)
    assert result.returncode == 0

    lines = journal.read_text().strip().split("\n")
    assert len(lines) == 1

    parsed = json.loads(lines[0])
    assert parsed["type"] == "routing_decision"

    # No schema_warning should exist
    warning_lines = [l for l in lines if '"schema_warning"' in l]
    assert len(warning_lines) == 0


# ---------------------------------------------------------------------------
# INT-02: Full flow with invalid entry — entry + schema_warning
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_int02_invalid_entry_produces_warning(tmp_path):
    """Incomplete routing_decision produces entry + schema_warning in journal."""
    journal = tmp_path / "journal.jsonl"
    entry = json.loads((FIXTURES / "invalid-missing-field.json").read_text())
    entry_json = json.dumps(entry)

    result = _run_append(entry_json, journal)
    assert result.returncode == 0

    lines = journal.read_text().strip().split("\n")
    assert len(lines) == 2

    # First line is the original entry
    first = json.loads(lines[0])
    assert first["type"] == "routing_decision"

    # Second line is schema_warning
    second = json.loads(lines[1])
    assert second["type"] == "schema_warning"
    assert second["data"]["violating_entry_id"] == entry["id"]
    assert "violation_type" in second["data"]
    assert "details" in second["data"]


# ---------------------------------------------------------------------------
# INT-03: Schema regeneration — modified YAML -> new JSON -> validator works
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_int03_schema_regeneration(tmp_path):
    """Regenerated JSON from YAML is recognized by the validator."""
    import yaml

    # Read current YAML
    yaml_data = yaml.safe_load(YAML_PATH.read_text())

    # Verify schema_warning type exists
    assert "schema_warning" in yaml_data["types"]

    # Regenerate JSON to temp location
    temp_json = tmp_path / "journal-entry-types.json"
    temp_json.write_text(json.dumps(yaml_data, indent=2))

    # Validate a schema_warning entry against regenerated JSON
    entry = json.loads((FIXTURES / "valid-schema-warning.json").read_text())
    entry_json = json.dumps(entry)

    result = subprocess.run(
        ["bash", str(VALIDATOR_SCRIPT)],
        input=entry_json,
        capture_output=True,
        text=True,
        timeout=10,
        env={**__import__("os").environ, "SCHEMA_PATH": str(temp_json)},
    )

    assert result.returncode == 0
    verdict = json.loads(result.stdout)
    assert verdict["valid"] is True
    assert verdict["entry_type"] == "schema_warning"


# ---------------------------------------------------------------------------
# INT-04: Legacy state.json loads and normalizes correctly
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_int04_legacy_state_loads_and_normalizes():
    """Legacy state.json with pass (no pass_counter, no source) loads correctly."""
    from kernel.accessors import get_last_quality_scores, get_quality_scores_window

    legacy = json.loads((FIXTURES / "legacy-quality-scores-entry.json").read_text())
    state = {"quality_scores": [legacy]}

    last = get_last_quality_scores(state)
    assert last is not None
    assert last["pass_counter"] == 2  # copied from pass
    assert last["source"] == "legacy_unknown"  # grandfathered
    assert last["overall"] == 0.78

    window = get_quality_scores_window(state, 1)
    assert window is not None
    assert len(window) == 1
    assert window[0]["pass_counter"] == 2
    assert window[0]["source"] == "legacy_unknown"

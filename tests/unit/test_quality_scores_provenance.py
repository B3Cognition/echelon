"""
Unit tests for quality_scores provenance normalization (spec 027).

Tests QS-01 through QS-09 per test-strategy.md.
Covers: FR-005, FR-007, FR-008, FR-013, NFR-002.

Run:
    pytest tests/unit/test_quality_scores_provenance.py -v
"""

import json
from pathlib import Path

import pytest

from kernel.accessors import (
    _normalize_quality_entry,
    get_last_quality_scores,
    get_quality_scores_window,
    is_grounded,
)
from kernel.evaluator import _eval_convergence_detected

FIXTURES = Path(__file__).parent.parent / "fixtures" / "journal-entries"


# ---------------------------------------------------------------------------
# QS-01: pass_counter used directly
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_qs01_pass_counter_used_directly():
    """Entry with pass_counter: accessor returns pass_counter value."""
    entry = {"pass_counter": 3, "overall": 0.85, "source": "tool:understanding.validate"}
    normalized = _normalize_quality_entry(entry)
    assert normalized["pass_counter"] == 3


# ---------------------------------------------------------------------------
# QS-02: Legacy pass field accepted
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_qs02_legacy_pass_field_accepted():
    """Entry with pass but no pass_counter: accessor returns pass value as pass_counter."""
    entry = {"pass": 2, "overall": 0.78}
    normalized = _normalize_quality_entry(entry)
    assert normalized["pass_counter"] == 2


# ---------------------------------------------------------------------------
# QS-03: pass_counter takes precedence
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_qs03_pass_counter_takes_precedence():
    """Entry with both pass and pass_counter: pass_counter wins."""
    entry = {"pass": 1, "pass_counter": 2, "overall": 0.80}
    normalized = _normalize_quality_entry(entry)
    assert normalized["pass_counter"] == 2


# ---------------------------------------------------------------------------
# QS-04: Missing source grandfathered
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_qs04_missing_source_grandfathered():
    """Entry without source: treated as legacy_unknown."""
    entry = {"pass": 1, "overall": 0.75}
    normalized = _normalize_quality_entry(entry)
    assert normalized["source"] == "legacy_unknown"


# ---------------------------------------------------------------------------
# QS-05: legacy_unknown excluded from convergence
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_qs05_legacy_unknown_excluded_from_convergence():
    """Mixed entries: convergence baseline excludes legacy_unknown entries."""
    state = {
        "quality_scores": [
            {"overall": 0.70, "pass": 1},  # legacy — no source
            {"overall": 0.71, "pass": 2},  # legacy — no source
            {"overall": 0.72, "pass_counter": 3, "source": "tool:understanding.validate",
             "tool_output_ref": "RJ-050"},
        ]
    }
    config = {
        "convergence": {
            "quality_delta_threshold": 0.05,
            "consecutive_passes_required": 1,
        }
    }
    # With only 1 grounded entry, convergence cannot be detected (< 2 grounded)
    result, fields, observed = _eval_convergence_detected(state, config, {}, {})
    assert result is False
    assert observed.get("grounded_count", 0) < 2


@pytest.mark.unit
def test_qs05b_grounded_entries_enable_convergence():
    """When enough grounded entries exist and deltas are small, convergence is detected."""
    state = {
        "quality_scores": [
            {"overall": 0.90, "pass_counter": 1, "source": "tool:understanding.validate",
             "tool_output_ref": "RJ-051"},
            {"overall": 0.91, "pass_counter": 2, "source": "tool:understanding.validate",
             "tool_output_ref": "RJ-052"},
        ]
    }
    config = {
        "convergence": {
            "quality_delta_threshold": 0.05,
            "consecutive_passes_required": 1,
        }
    }
    result, fields, observed = _eval_convergence_detected(state, config, {}, {})
    assert result is True


# ---------------------------------------------------------------------------
# QS-06: source field validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_qs06_valid_tool_source_with_ref():
    """Entry with tool source and ref passes is_grounded."""
    entry = {
        "overall": 0.92,
        "pass_counter": 3,
        "source": "tool:understanding.validate",
        "tool_output_ref": "RJ-050",
    }
    assert is_grounded(entry) is True


# ---------------------------------------------------------------------------
# QS-07: source=tool:* requires ref (advisory, not enforced at accessor level)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_qs07_tool_source_without_ref_still_grounded():
    """Entry with tool source but no ref is still grounded (enforcement is in COMMANDER mandate)."""
    entry = {
        "overall": 0.92,
        "pass_counter": 3,
        "source": "tool:understanding.validate",
    }
    # is_grounded only checks source value, not tool_output_ref
    assert is_grounded(entry) is True


# ---------------------------------------------------------------------------
# QS-08: Valid source enum values
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_qs08_valid_source_enum():
    """Each valid source value is accepted as grounded."""
    valid_sources = [
        "tool:understanding.validate",
        "agent_self_assessment",
        "commander_estimate",
    ]
    for source in valid_sources:
        entry = {"overall": 0.80, "pass_counter": 1, "source": source}
        assert is_grounded(entry) is True, f"source={source} should be grounded"

    # legacy_unknown is explicitly not grounded
    entry = {"overall": 0.80, "pass_counter": 1, "source": "legacy_unknown"}
    assert is_grounded(entry) is False


# ---------------------------------------------------------------------------
# QS-09: Backward compat — old state loads
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_qs09_backward_compat_old_state_loads():
    """state.json with only pass and no source loads without error."""
    legacy_fixture = FIXTURES / "legacy-quality-scores-entry.json"
    legacy_entry = json.loads(legacy_fixture.read_text())

    state = {"quality_scores": [legacy_entry]}

    # get_last_quality_scores should work
    result = get_last_quality_scores(state)
    assert result is not None
    assert result["pass_counter"] == 2  # copied from pass
    assert result["source"] == "legacy_unknown"
    assert result["overall"] == 0.78

    # get_quality_scores_window should work
    window = get_quality_scores_window(state, 1)
    assert window is not None
    assert len(window) == 1
    assert window[0]["pass_counter"] == 2


@pytest.mark.unit
def test_qs09b_original_dict_not_mutated():
    """Normalization returns a copy, not a mutated original."""
    original = {"pass": 2, "overall": 0.78}
    normalized = _normalize_quality_entry(original)
    assert "pass_counter" in normalized
    assert "pass_counter" not in original  # original unchanged
    assert "source" in normalized
    assert "source" not in original  # original unchanged

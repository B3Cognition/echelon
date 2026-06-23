"""Tests for deterministic echelon_result schema validation."""
import sys
from pathlib import Path

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.echelon_result_schema import (  # noqa: E402
    EchelonResultValidationError,
    validate_echelon_result,
)


def test_valid_result_is_normalized_without_mutating_input():
    payload = {
        "verdict": "DONE",
        "state_updates": {"coverage_pct": 72},
        "journal_entries": [{"type": "quality_check"}],
    }

    normalized = validate_echelon_result(payload)

    assert normalized == payload
    assert normalized is not payload


def test_bad_top_level_type_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="must be an object"):
        validate_echelon_result(["not", "an", "object"])


def test_missing_verdict_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="verdict"):
        validate_echelon_result({"state_updates": {}})


def test_non_string_verdict_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="verdict"):
        validate_echelon_result({"verdict": 123, "state_updates": {}})


def test_unsupported_verdict_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="unsupported verdict"):
        validate_echelon_result({"verdict": "MAYBE", "state_updates": {}})


def test_missing_state_updates_defaults_for_non_blocking_verdict():
    assert validate_echelon_result({"verdict": "PASS"})["state_updates"] == {}


def test_blocked_result_requires_state_updates():
    with pytest.raises(EchelonResultValidationError, match="state_updates"):
        validate_echelon_result({"verdict": "BLOCKED"})


def test_bad_state_updates_type_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="state_updates"):
        validate_echelon_result({"verdict": "DONE", "state_updates": []})


def test_bad_journal_entries_type_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="journal_entries"):
        validate_echelon_result({
            "verdict": "DONE",
            "state_updates": {},
            "journal_entries": {},
        })


def test_reserved_harness_state_key_is_rejected():
    with pytest.raises(EchelonResultValidationError, match="last_dispatch"):
        validate_echelon_result({
            "verdict": "DONE",
            "state_updates": {"last_dispatch": {"phase_id": "fake"}},
        })

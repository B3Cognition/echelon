"""T052: Unit tests — re-* state machine protocol (re_state.py)."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from kernel.re_state import (
    complete_dispatch,
    get_current_phase,
    init_re_state,
    should_redispatch,
    write_last_dispatch,
)


def _base_state():
    return init_re_state()


class TestInitReState:
    def test_returns_dict_with_required_keys(self):
        s = init_re_state()
        for key in ["run_id", "status", "phase", "last_dispatch",
                    "mode", "output_dir", "domains",
                    "coverage_pct", "coverage_threshold",
                    "verify_expand_iterations",
                    "resolution_pct", "resolution_threshold",
                    "validate_iterations", "max_validate_iterations",
                    "artifacts", "issues_log"]:
            assert key in s, f"Missing key: {key}"

    def test_status_is_in_progress(self):
        assert init_re_state()["status"] == "in_progress"

    def test_post_dispatch_complete_false_on_init(self):
        s = init_re_state()
        assert s["last_dispatch"]["post_dispatch_complete"] is False

    def test_custom_thresholds(self):
        s = init_re_state(coverage_threshold=90, resolution_threshold=75, max_validate_iterations=5)
        assert s["coverage_threshold"] == 90
        assert s["resolution_threshold"] == 75
        assert s["max_validate_iterations"] == 5

    def test_default_thresholds(self):
        s = init_re_state()
        assert s["coverage_threshold"] == 80
        assert s["resolution_threshold"] == 80
        assert s["max_validate_iterations"] == 3

    def test_custom_output_dir_reflected_in_artifacts(self):
        s = init_re_state(output_dir="/custom/path")
        assert s["output_dir"] == "/custom/path"
        assert s["artifacts"]["analysis_json"] == "/custom/path/analysis.json"
        assert s["artifacts"]["repos_manifest"] == "/custom/path/repos-manifest.json"


class TestWriteLastDispatch:
    def test_sets_phase_id_and_agent(self):
        s = _base_state()
        s2 = write_last_dispatch(s, "re-extract-2-specify", "speckit-echelon-re-specifier")
        assert s2["last_dispatch"]["phase_id"] == "re-extract-2-specify"
        assert s2["last_dispatch"]["agent"] == "speckit-echelon-re-specifier"

    def test_sets_post_dispatch_complete_false(self):
        s = _base_state()
        s2 = write_last_dispatch(s, "re-extract-1-analyze", "speckit-echelon-re-analyzer")
        assert s2["last_dispatch"]["post_dispatch_complete"] is False

    def test_updates_phase_field(self):
        s = _base_state()
        s2 = write_last_dispatch(s, "re-extract-3-verify", "speckit-echelon-re-verifier")
        assert s2["phase"] == "re-extract-3-verify"

    def test_dispatched_at_is_iso8601(self):
        s = _base_state()
        s2 = write_last_dispatch(s, "re-extract-1-analyze", "speckit-echelon-re-analyzer")
        datetime.fromisoformat(s2["last_dispatch"]["dispatched_at"].replace("Z", "+00:00"))

    def test_does_not_mutate_input(self):
        s = _base_state()
        original_phase = s["phase"]
        write_last_dispatch(s, "re-extract-2-specify", "speckit-echelon-re-specifier")
        assert s["phase"] == original_phase


class TestCompleteDispatch:
    def _dispatched_state(self):
        s = _base_state()
        return write_last_dispatch(s, "re-extract-3-verify", "speckit-echelon-re-verifier")

    def test_sets_post_dispatch_complete_true(self):
        s = self._dispatched_state()
        result = {"verdict": "DONE", "phase_id": "re-extract-3-verify", "state_updates": {}}
        s2 = complete_dispatch(s, result)
        assert s2["last_dispatch"]["post_dispatch_complete"] is True

    def test_applies_coverage_pct_update(self):
        s = self._dispatched_state()
        result = {"verdict": "DONE", "phase_id": "re-extract-3-verify",
                  "state_updates": {"coverage_pct": 72}}
        s2 = complete_dispatch(s, result)
        assert s2["coverage_pct"] == 72

    def test_applies_domains_update(self):
        s = self._dispatched_state()
        result = {"verdict": "DONE", "phase_id": "re-extract-1-analyze",
                  "state_updates": {"domains": ["auth", "api"]}}
        s2 = complete_dispatch(s, result)
        assert s2["domains"] == ["auth", "api"]

    def test_applies_validate_iterations_update(self):
        s = _base_state()
        s = write_last_dispatch(s, "re-extract-5-validate", "speckit-echelon-re-validator")
        result = {"verdict": "DONE", "phase_id": "re-extract-5-validate",
                  "state_updates": {"resolution_pct": 85, "validate_iterations": 1}}
        s2 = complete_dispatch(s, result)
        assert s2["resolution_pct"] == 85
        assert s2["validate_iterations"] == 1

    def test_does_not_mutate_input(self):
        s = self._dispatched_state()
        original = s["last_dispatch"]["post_dispatch_complete"]
        complete_dispatch(s, {"verdict": "DONE", "phase_id": "x", "state_updates": {}})
        assert s["last_dispatch"]["post_dispatch_complete"] == original

    def test_raises_key_error_when_last_dispatch_absent(self):
        s = {"status": "in_progress", "phase": "re-extract-1-analyze"}
        with pytest.raises(KeyError, match="last_dispatch sentinel"):
            complete_dispatch(s, {"verdict": "DONE", "phase_id": "x", "state_updates": {}})


class TestShouldRedispatch:
    def test_true_when_post_dispatch_complete_false(self):
        s = _base_state()
        s = write_last_dispatch(s, "re-extract-2-specify", "speckit-echelon-re-specifier")
        assert should_redispatch(s) is True

    def test_false_when_post_dispatch_complete_true(self):
        s = _base_state()
        s = write_last_dispatch(s, "re-extract-2-specify", "speckit-echelon-re-specifier")
        s = complete_dispatch(s, {"verdict": "DONE", "phase_id": "re-extract-2-specify",
                                  "state_updates": {}})
        assert should_redispatch(s) is False

    def test_false_on_fresh_state(self):
        s = init_re_state()
        assert should_redispatch(s) is False


class TestGetCurrentPhase:
    def test_returns_phase_field(self):
        s = _base_state()
        s = write_last_dispatch(s, "re-extract-3-verify", "speckit-echelon-re-verifier")
        assert get_current_phase(s) == "re-extract-3-verify"

    def test_returns_none_on_empty_state(self):
        assert get_current_phase({}) is None

"""T014: Unit test pack — accessors.py

One positive + one missing-field test per accessor function.
All accessor functions exercised.
Missing-field branches covered.
"""

import sys
from pathlib import Path

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from kernel.accessors import (
    get_autonomy_mode,
    get_checkpoint_approved,
    get_config_assess_defer_limit,
    get_config_consecutive_passes,
    get_config_guardian_mode,
    get_config_max_iterations,
    get_config_quality_delta_threshold,
    get_config_quality_gates,
    get_critical_issues,
    get_defer_count,
    get_dependency_check,
    get_dependency_check_status,
    get_iteration,
    get_last_outputs_verdict,
    get_last_quality_scores,
    get_meta_run,
    get_mode,
    get_qualitative_scores,
    get_quality_scores_window,
    has_critical_issues,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FULL_STATE = {
    "quality_scores": [
        {"overall": 0.65, "structure": 0.60},
        {"overall": 0.71, "structure": 0.65},
    ],
    "qualitative_scores": {
        "structure": 4, "testability": 3, "semantic": 4,
        "cognitive": 5, "readability": 5, "behavioral": 4, "depth": 3,
        "measured_numerically": False,
    },
    "issues_log": [
        {"id": "ISS-001", "severity": "CRITICAL", "resolved": False, "source": "SAGE"},
        {"id": "ISS-002", "severity": "HIGH", "resolved": False, "source": "SAGE"},
        {"id": "ISS-003", "severity": "CRITICAL", "resolved": True, "source": "SAGE"},  # resolved
    ],
    "iteration": 2,
    "mode": "brownfield",
    "meta_run": True,
    "defer_count": 1,
    "autonomy_mode": "semi",
    "checkpoint_responses": {
        "phase1-gate": {"approved": True, "comment": "LGTM"},
        "phase2-gate": {"approved": False},
    },
    "dependency_checks": {
        "understanding": {"status": "available", "checked_at": "2026-04-11T00:00:00Z"},
        "brownfield": {"status": "unavailable"},
    },
}

FULL_CONFIG = {
    "convergence": {
        "max_iterations": 5,
        "quality_delta_threshold": 0.02,
        "consecutive_passes_required": 2,
        "assess_defer_loop_limit": 2,
    },
    "quality_gates": {
        "spec": {"overall": 0.7, "structure": 0.6},
    },
    "specialists": {
        "guardian_mode": "always_on",
    },
}

EMPTY_STATE: dict = {}
EMPTY_CONFIG: dict = {}


# ---------------------------------------------------------------------------
# quality score accessors
# ---------------------------------------------------------------------------


class TestGetLastQualityScores:
    def test_positive(self):
        result = get_last_quality_scores(FULL_STATE)
        # Per spec 027 FR-008: entries without `source` are grandfathered to "legacy_unknown"
        assert result == {"overall": 0.71, "structure": 0.65, "source": "legacy_unknown"}

    def test_missing_field(self):
        assert get_last_quality_scores(EMPTY_STATE) is None

    def test_empty_list(self):
        assert get_last_quality_scores({"quality_scores": []}) is None

    def test_non_list(self):
        assert get_last_quality_scores({"quality_scores": "not-a-list"}) is None


class TestGetQualityScoresWindow:
    def test_positive(self):
        result = get_quality_scores_window(FULL_STATE, window=2)
        assert len(result) == 2

    def test_missing_field(self):
        assert get_quality_scores_window(EMPTY_STATE) is None

    def test_window_larger_than_list(self):
        result = get_quality_scores_window(FULL_STATE, window=10)
        assert len(result) == 2  # only 2 scores available


class TestGetQualitativeScores:
    def test_positive(self):
        result = get_qualitative_scores(FULL_STATE)
        assert isinstance(result, dict)
        assert result["structure"] == 4

    def test_missing_field(self):
        assert get_qualitative_scores(EMPTY_STATE) is None


# ---------------------------------------------------------------------------
# issues log accessors
# ---------------------------------------------------------------------------


class TestGetCriticalIssues:
    def test_positive_returns_only_unresolved_critical(self):
        result = get_critical_issues(FULL_STATE)
        assert len(result) == 1
        assert result[0]["id"] == "ISS-001"

    def test_missing_field(self):
        assert get_critical_issues(EMPTY_STATE) == []

    def test_non_list(self):
        assert get_critical_issues({"issues_log": "not-a-list"}) == []


class TestHasCriticalIssues:
    def test_true_when_unresolved(self):
        assert has_critical_issues(FULL_STATE) is True

    def test_false_when_empty(self):
        assert has_critical_issues(EMPTY_STATE) is False

    def test_false_when_all_resolved(self):
        state = {"issues_log": [{"severity": "CRITICAL", "resolved": True}]}
        assert has_critical_issues(state) is False


# ---------------------------------------------------------------------------
# iteration accessor
# ---------------------------------------------------------------------------


class TestGetIteration:
    def test_positive(self):
        assert get_iteration(FULL_STATE) == 2

    def test_missing_field(self):
        assert get_iteration(EMPTY_STATE) is None

    def test_bool_returns_none(self):
        assert get_iteration({"iteration": True}) is None


# ---------------------------------------------------------------------------
# mode accessor
# ---------------------------------------------------------------------------


class TestGetMode:
    def test_positive(self):
        assert get_mode(FULL_STATE) == "brownfield"

    def test_missing_field(self):
        assert get_mode(EMPTY_STATE) is None

    def test_non_string(self):
        assert get_mode({"mode": 42}) is None


# ---------------------------------------------------------------------------
# meta_run accessor
# ---------------------------------------------------------------------------


class TestGetMetaRun:
    def test_positive_true(self):
        assert get_meta_run(FULL_STATE) is True

    def test_positive_false(self):
        assert get_meta_run({"meta_run": False}) is False

    def test_missing_field(self):
        assert get_meta_run(EMPTY_STATE) is None

    def test_non_bool(self):
        assert get_meta_run({"meta_run": "yes"}) is None


# ---------------------------------------------------------------------------
# defer_count accessor
# ---------------------------------------------------------------------------


class TestGetDeferCount:
    def test_positive(self):
        assert get_defer_count(FULL_STATE) == 1

    def test_missing_field(self):
        assert get_defer_count(EMPTY_STATE) is None

    def test_bool_returns_none(self):
        assert get_defer_count({"defer_count": False}) is None


# ---------------------------------------------------------------------------
# autonomy_mode accessor
# ---------------------------------------------------------------------------


class TestGetAutonomyMode:
    def test_positive(self):
        assert get_autonomy_mode(FULL_STATE) == "semi"

    def test_missing_field(self):
        assert get_autonomy_mode(EMPTY_STATE) is None

    def test_non_string(self):
        assert get_autonomy_mode({"autonomy_mode": 1}) is None


# ---------------------------------------------------------------------------
# checkpoint_responses accessor
# ---------------------------------------------------------------------------


class TestGetCheckpointApproved:
    def test_positive_approved(self):
        assert get_checkpoint_approved(FULL_STATE, "phase1-gate") is True

    def test_positive_rejected(self):
        assert get_checkpoint_approved(FULL_STATE, "phase2-gate") is False

    def test_missing_checkpoint(self):
        assert get_checkpoint_approved(FULL_STATE, "nonexistent") is None

    def test_missing_field(self):
        assert get_checkpoint_approved(EMPTY_STATE, "phase1-gate") is None


# ---------------------------------------------------------------------------
# last_outputs verdict accessor
# ---------------------------------------------------------------------------


class TestGetLastOutputsVerdict:
    def test_positive(self):
        assert get_last_outputs_verdict({"verdict": "PASS"}) == "PASS"

    def test_missing_field(self):
        assert get_last_outputs_verdict({}) is None

    def test_non_dict(self):
        assert get_last_outputs_verdict("not-a-dict") is None  # type: ignore


# ---------------------------------------------------------------------------
# dependency_checks accessors
# ---------------------------------------------------------------------------


class TestGetDependencyCheck:
    def test_positive(self):
        result = get_dependency_check(FULL_STATE, "understanding")
        assert isinstance(result, dict)
        assert result["status"] == "available"

    def test_missing_dep(self):
        assert get_dependency_check(FULL_STATE, "golddigger") is None

    def test_missing_field(self):
        assert get_dependency_check(EMPTY_STATE, "understanding") is None


class TestGetDependencyCheckStatus:
    def test_positive(self):
        assert get_dependency_check_status(FULL_STATE, "understanding") == "available"

    def test_unavailable(self):
        assert get_dependency_check_status(FULL_STATE, "brownfield") == "unavailable"

    def test_missing(self):
        assert get_dependency_check_status(EMPTY_STATE, "understanding") is None


# ---------------------------------------------------------------------------
# Config accessors
# ---------------------------------------------------------------------------


class TestConfigAccessors:
    def test_max_iterations_positive(self):
        assert get_config_max_iterations(FULL_CONFIG) == 5

    def test_max_iterations_missing(self):
        assert get_config_max_iterations(EMPTY_CONFIG) is None

    def test_quality_delta_threshold_positive(self):
        assert get_config_quality_delta_threshold(FULL_CONFIG) == pytest.approx(0.02)

    def test_quality_delta_threshold_missing(self):
        assert get_config_quality_delta_threshold(EMPTY_CONFIG) is None

    def test_consecutive_passes_positive(self):
        assert get_config_consecutive_passes(FULL_CONFIG) == 2

    def test_consecutive_passes_missing(self):
        assert get_config_consecutive_passes(EMPTY_CONFIG) is None

    def test_assess_defer_limit_positive(self):
        assert get_config_assess_defer_limit(FULL_CONFIG) == 2

    def test_assess_defer_limit_missing(self):
        assert get_config_assess_defer_limit(EMPTY_CONFIG) is None

    def test_quality_gates_positive(self):
        result = get_config_quality_gates(FULL_CONFIG)
        assert isinstance(result, dict)
        assert "spec" in result

    def test_quality_gates_missing(self):
        assert get_config_quality_gates(EMPTY_CONFIG) is None

    def test_guardian_mode_nested(self):
        assert get_config_guardian_mode(FULL_CONFIG) == "always_on"

    def test_guardian_mode_top_level(self):
        config = {"guardian_mode": "on_demand"}
        assert get_config_guardian_mode(config) == "on_demand"

    def test_guardian_mode_missing(self):
        assert get_config_guardian_mode(EMPTY_CONFIG) is None

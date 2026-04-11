"""T012a: Unit test pack — evaluator predicates (≥ 50 tests).

Tests per contracts/evaluator-contract.md test-contract:
1. One test per atomic predicate (16 predicates)
2. Combinator truth tables (AND + OR)
3. Undefined-field fail-closed behavior
4. no_transition_matched path
5. Purity: same inputs × N
6. Trace completeness

Also covers SKIPPED_PREFLIGHT_NODE routing boundary.
"""

import sys
from pathlib import Path

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from kernel.evaluator import (
    EvaluatorResult,
    PredicateNotDefined,
    UnknownPredicate,
    evaluate_transitions,
    evaluate_transitions_list,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _state(overrides=None) -> dict:  # type: ignore[type-arg]
    """Build a base valid state dict."""
    base = {
        "run_id": "squad-99999",
        "phase": "phase1-what",
        "mode": "brownfield",
        "meta_run": False,
        "iteration": 2,
        "degraded_mode_stack": [],
        "issues_log": [],
        "dependency_checks": {"understanding": {"status": "available"}},
        "last_dispatch": {"agent": "SAGE", "dispatched_at": "2026-04-11T00:00:00Z", "post_dispatch_complete": True, "journal_entries_written": []},
        "dispatch_counters": {},
        "defer_count": 1,
        "autonomy_mode": "guided",
        "updated_at": "2026-04-11T00:00:00Z",
        "quality_scores": [
            {"overall": 0.60, "structure": 0.55},
            {"overall": 0.72, "structure": 0.65},
        ],
    }
    if overrides:
        base.update(overrides)
    return base


def _config(overrides=None) -> dict:  # type: ignore[type-arg]
    """Build a base valid config dict."""
    base = {
        "convergence": {
            "max_iterations": 5,
            "quality_delta_threshold": 0.02,
            "consecutive_passes_required": 2,
            "assess_defer_loop_limit": 2,
        },
        "quality_gates": {"spec": {"overall": 0.70}},
        "specialists": {"guardian_mode": "always_on"},
    }
    if overrides:
        base.update(overrides)
    return base


def _transitions(condition: str, target: str = "next") -> list[dict]:
    return [{"condition": condition, "to": target}]


def _eval(condition: str, state=None, config=None, last_outputs=None) -> EvaluatorResult:
    return evaluate_transitions_list(
        _transitions(condition),
        state or _state(),
        config or _config(),
        last_outputs or {},
    )


def _matched(condition: str, **kwargs) -> bool:
    return _eval(condition, **kwargs)["guard_result"] == "PASS"


# ---------------------------------------------------------------------------
# Predicate 1: always
# ---------------------------------------------------------------------------


class TestPredicateAlways:
    def test_always_matches(self):
        result = _eval("always")
        assert result["guard_result"] == "PASS"
        assert result["next_phase"] == "next"

    def test_always_trace_present_but_empty(self):
        result = _eval("always")
        # always produces one trace entry with empty fields_read
        assert len(result["trace"]) > 0
        assert result["trace"][0]["fields_read"] == []


# ---------------------------------------------------------------------------
# Predicate 2: quality_gates.pass
# ---------------------------------------------------------------------------


class TestPredicateQualityGatesPass:
    def test_pass_when_above_threshold(self):
        state = _state({"quality_scores": [{"overall": 0.75}]})
        assert _matched("quality_gates.pass", state=state)

    def test_fail_when_below_threshold(self):
        state = _state({"quality_scores": [{"overall": 0.60}]})
        assert not _matched("quality_gates.pass", state=state)

    def test_fail_when_no_scores(self):
        state = _state({"quality_scores": []})
        assert not _matched("quality_gates.pass", state=state)

    def test_trace_contains_quality_scores(self):
        result = _eval("quality_gates.pass")
        assert any("quality_scores" in f for entry in result["trace"] for f in entry["fields_read"])


# ---------------------------------------------------------------------------
# Predicate 3: quality_gates.fail
# ---------------------------------------------------------------------------


class TestPredicateQualityGatesFail:
    def test_fail_when_below_threshold(self):
        state = _state({"quality_scores": [{"overall": 0.60}]})
        assert _matched("quality_gates.fail", state=state)

    def test_not_when_above_threshold(self):
        state = _state({"quality_scores": [{"overall": 0.80}]})
        assert not _matched("quality_gates.fail", state=state)


# ---------------------------------------------------------------------------
# Predicate 4: convergence_detected
# ---------------------------------------------------------------------------


class TestPredicateConvergenceDetected:
    def test_convergence_when_delta_tiny(self):
        # Two passes with tiny delta should converge
        state = _state({"quality_scores": [
            {"overall": 0.71},
            {"overall": 0.715},
            {"overall": 0.717},
        ]})
        config = _config({"convergence": {
            "max_iterations": 5,
            "quality_delta_threshold": 0.02,
            "consecutive_passes_required": 2,
            "assess_defer_loop_limit": 2,
        }})
        assert _matched("convergence_detected", state=state, config=config)

    def test_no_convergence_when_improving(self):
        state = _state({"quality_scores": [
            {"overall": 0.50},
            {"overall": 0.65},
            {"overall": 0.72},
        ]})
        assert not _matched("convergence_detected", state=state)

    def test_no_convergence_with_single_score(self):
        state = _state({"quality_scores": [{"overall": 0.72}]})
        assert not _matched("convergence_detected", state=state)


# ---------------------------------------------------------------------------
# Predicate 5: CRITICAL_issues
# ---------------------------------------------------------------------------


class TestPredicateCriticalIssues:
    def test_true_when_unresolved_critical(self):
        state = _state({"issues_log": [
            {"severity": "CRITICAL", "resolved": False, "id": "ISS-001"}
        ]})
        assert _matched("CRITICAL_issues", state=state)

    def test_false_when_no_issues(self):
        assert not _matched("CRITICAL_issues")

    def test_false_when_resolved_critical(self):
        state = _state({"issues_log": [
            {"severity": "CRITICAL", "resolved": True, "id": "ISS-001"}
        ]})
        assert not _matched("CRITICAL_issues", state=state)

    def test_false_when_only_high(self):
        state = _state({"issues_log": [
            {"severity": "HIGH", "resolved": False, "id": "ISS-001"}
        ]})
        assert not _matched("CRITICAL_issues", state=state)


# ---------------------------------------------------------------------------
# Predicate 6: no_CRITICAL_issues
# ---------------------------------------------------------------------------


class TestPredicateNoCriticalIssues:
    def test_true_when_no_issues(self):
        assert _matched("no_CRITICAL_issues")

    def test_false_when_unresolved_critical(self):
        state = _state({"issues_log": [
            {"severity": "CRITICAL", "resolved": False}
        ]})
        assert not _matched("no_CRITICAL_issues", state=state)


# ---------------------------------------------------------------------------
# Predicate 7: iteration < max_iterations
# ---------------------------------------------------------------------------


class TestPredicateIterationLt:
    def test_true_when_below(self):
        state = _state({"iteration": 2})
        assert _matched("iteration < max_iterations", state=state)

    def test_false_when_at_max(self):
        state = _state({"iteration": 5})
        assert not _matched("iteration < max_iterations", state=state)

    def test_false_when_above_max(self):
        state = _state({"iteration": 10})
        assert not _matched("iteration < max_iterations", state=state)


# ---------------------------------------------------------------------------
# Predicate 8: iteration >= max_iterations
# ---------------------------------------------------------------------------


class TestPredicateIterationGte:
    def test_true_when_at_max(self):
        state = _state({"iteration": 5})
        assert _matched("iteration >= max_iterations", state=state)

    def test_false_when_below_max(self):
        state = _state({"iteration": 2})
        assert not _matched("iteration >= max_iterations", state=state)


# ---------------------------------------------------------------------------
# Predicate 9: verdict = <value>
# ---------------------------------------------------------------------------


class TestPredicateVerdictEq:
    def test_match_pass(self):
        assert _matched("verdict = PASS", last_outputs={"verdict": "PASS"})

    def test_match_fail(self):
        assert _matched("verdict = FAIL", last_outputs={"verdict": "FAIL"})

    def test_no_match_wrong_value(self):
        assert not _matched("verdict = PASS", last_outputs={"verdict": "FAIL"})

    def test_no_match_missing_verdict(self):
        assert not _matched("verdict = PASS", last_outputs={})


# ---------------------------------------------------------------------------
# Predicate 10: defer_count >= assess_defer_loop_limit
# ---------------------------------------------------------------------------


class TestPredicateDeferCount:
    def test_true_when_at_limit(self):
        state = _state({"defer_count": 2})
        assert _matched("defer_count >= assess_defer_loop_limit", state=state)

    def test_true_when_above_limit(self):
        state = _state({"defer_count": 5})
        assert _matched("defer_count >= assess_defer_loop_limit", state=state)

    def test_false_when_below_limit(self):
        state = _state({"defer_count": 1})
        assert not _matched("defer_count >= assess_defer_loop_limit", state=state)


# ---------------------------------------------------------------------------
# Predicate 11: autonomy in [guided, semi, banzai]
# ---------------------------------------------------------------------------


class TestPredicateAutonomyIn:
    def test_guided_matches(self):
        state = _state({"autonomy_mode": "guided"})
        assert _matched("autonomy in [guided, semi, banzai]", state=state)

    def test_semi_matches(self):
        state = _state({"autonomy_mode": "semi"})
        assert _matched("autonomy in [guided, semi, banzai]", state=state)

    def test_banzai_matches(self):
        state = _state({"autonomy_mode": "banzai"})
        assert _matched("autonomy in [guided, semi, banzai]", state=state)

    def test_partial_list(self):
        state = _state({"autonomy_mode": "guided"})
        assert _matched("autonomy in [guided]", state=state)

    def test_not_in_list(self):
        state = _state({"autonomy_mode": "turbo"})
        assert not _matched("autonomy in [guided, semi, banzai]", state=state)


# ---------------------------------------------------------------------------
# Predicate 12: human_approved
# ---------------------------------------------------------------------------


class TestPredicateHumanApproved:
    def test_approved_with_empty_checkpoint_key(self):
        # human_approved with empty checkpoint key uses "" as key
        state = _state({"checkpoint_responses": {"": {"approved": True}}})
        assert _matched("human_approved", state=state)

    def test_rejected_with_empty_checkpoint_key(self):
        state = _state({"checkpoint_responses": {"": {"approved": False}}})
        assert not _matched("human_approved", state=state)

    def test_missing_checkpoint(self):
        # No checkpoint_responses at all → fail-closed
        assert not _matched("human_approved")


# ---------------------------------------------------------------------------
# Predicate 13: mode = brownfield
# ---------------------------------------------------------------------------


class TestPredicateModeEq:
    def test_brownfield(self):
        assert _matched("mode = brownfield")

    def test_not_greenfield(self):
        state = _state({"mode": "greenfield"})
        assert not _matched("mode = brownfield", state=state)

    def test_self_analysis(self):
        state = _state({"mode": "self_analysis"})
        assert _matched("mode = self_analysis", state=state)


# ---------------------------------------------------------------------------
# Predicate 14: guardian_mode = always_on
# ---------------------------------------------------------------------------


class TestPredicateGuardianMode:
    def test_always_on(self):
        assert _matched("guardian_mode = always_on")

    def test_on_demand(self):
        config = _config()
        config["specialists"]["guardian_mode"] = "on_demand"
        assert not _matched("guardian_mode = always_on", config=config)


# ---------------------------------------------------------------------------
# Predicate 15: stagnation_detected (not yet defined)
# ---------------------------------------------------------------------------


class TestPredicateStagnationDetected:
    def test_raises_predicate_not_defined(self):
        with pytest.raises(PredicateNotDefined) as exc_info:
            _eval("stagnation_detected")
        assert "stagnation_detected" in exc_info.value.predicate_name


# ---------------------------------------------------------------------------
# Predicate 16: unknown_territory (not yet defined)
# ---------------------------------------------------------------------------


class TestPredicateUnknownTerritory:
    def test_raises_predicate_not_defined(self):
        with pytest.raises(PredicateNotDefined) as exc_info:
            _eval("unknown_territory")
        assert "unknown_territory" in exc_info.value.predicate_name


# ---------------------------------------------------------------------------
# Unknown predicate
# ---------------------------------------------------------------------------


class TestUnknownPredicate:
    def test_unknown_predicate_adds_error(self):
        result = evaluate_transitions_list(
            [{"condition": "totally_made_up_predicate", "to": "x"}],
            _state(), _config(), {}
        )
        assert any("unknown_predicate" in e for e in result["errors"])

    def test_unknown_predicate_does_not_match(self):
        result = evaluate_transitions_list(
            [{"condition": "totally_made_up_predicate", "to": "x"}],
            _state(), _config(), {}
        )
        assert result["guard_result"] == "FAIL"


# ---------------------------------------------------------------------------
# Combinator: AND truth table
# ---------------------------------------------------------------------------


class TestAndCombinator:
    def test_true_and_true(self):
        assert _matched("always AND iteration < max_iterations")

    def test_true_and_false(self):
        state = _state({"iteration": 10})  # >= max_iterations
        assert not _matched("always AND iteration < max_iterations", state=state)

    def test_false_and_true(self):
        state = _state({"issues_log": [{"severity": "CRITICAL", "resolved": False}]})
        assert not _matched("no_CRITICAL_issues AND always", state=state)

    def test_false_and_false(self):
        state = _state({"issues_log": [{"severity": "CRITICAL", "resolved": False}], "iteration": 10})
        assert not _matched("no_CRITICAL_issues AND iteration < max_iterations", state=state)


# ---------------------------------------------------------------------------
# Combinator: OR truth table
# ---------------------------------------------------------------------------


class TestOrCombinator:
    def test_true_or_true(self):
        assert _matched("always OR no_CRITICAL_issues")

    def test_true_or_false(self):
        state = _state({"issues_log": [{"severity": "CRITICAL", "resolved": False}]})
        assert _matched("always OR no_CRITICAL_issues", state=state)

    def test_false_or_true(self):
        state = _state({"issues_log": [{"severity": "CRITICAL", "resolved": False}]})
        assert _matched("CRITICAL_issues OR no_CRITICAL_issues", state=state)

    def test_false_or_false(self):
        assert not _matched("CRITICAL_issues OR iteration >= max_iterations")


# ---------------------------------------------------------------------------
# Undefined field — fail-closed
# ---------------------------------------------------------------------------


class TestUndefinedFieldFailClosed:
    def test_missing_iteration_fails_closed(self):
        state = _state()
        del state["iteration"]
        result = evaluate_transitions_list(
            _transitions("iteration < max_iterations"),
            state, _config(), {}
        )
        assert result["guard_result"] == "FAIL"

    def test_missing_mode_fails_closed(self):
        state = _state()
        del state["mode"]
        result = evaluate_transitions_list(
            _transitions("mode = brownfield"),
            state, _config(), {}
        )
        assert result["guard_result"] == "FAIL"

    def test_undefined_entry_in_trace_is_false(self):
        state = _state()
        del state["iteration"]
        result = evaluate_transitions_list(
            _transitions("iteration < max_iterations"),
            state, _config(), {}
        )
        # trace should show result as "false" (fail-closed contributes as false)
        assert any(entry["result"] in ("false", "undefined") for entry in result["trace"])


# ---------------------------------------------------------------------------
# no_transition_matched path
# ---------------------------------------------------------------------------


class TestNoTransitionMatched:
    def test_empty_transitions_returns_fail(self):
        result = evaluate_transitions_list([], _state(), _config(), {})
        assert result["guard_result"] == "FAIL"
        assert "no_transition_matched" in result["errors"]
        assert result["next_phase"] is None
        assert result["matched_transition_index"] is None

    def test_all_conditions_false_returns_fail(self):
        state = _state({"iteration": 10})  # iteration >= max
        result = evaluate_transitions_list(
            _transitions("iteration < max_iterations"),
            state, _config(), {}
        )
        assert result["guard_result"] == "FAIL"
        assert "no_transition_matched" in result["errors"]


# ---------------------------------------------------------------------------
# Purity test
# ---------------------------------------------------------------------------


class TestPurity:
    def test_same_inputs_yield_same_outputs(self):
        state = _state()
        config = _config()
        last_outputs = {"verdict": "PASS"}
        transitions = _transitions("iteration < max_iterations")

        results = [
            evaluate_transitions_list(transitions, state, config, last_outputs)
            for _ in range(100)
        ]

        first = results[0]
        for r in results[1:]:
            assert r["guard_result"] == first["guard_result"]
            assert r["next_phase"] == first["next_phase"]
            assert r["matched_transition_index"] == first["matched_transition_index"]


# ---------------------------------------------------------------------------
# Trace completeness
# ---------------------------------------------------------------------------


class TestTraceCompleteness:
    def test_non_always_trace_has_fields_read(self):
        result = _eval("iteration < max_iterations")
        trace = result["trace"]
        assert len(trace) > 0
        # At least one entry should have fields_read populated
        assert any(len(entry["fields_read"]) > 0 for entry in trace)

    def test_multiple_conditions_all_traced(self):
        result = evaluate_transitions_list(
            [
                {"condition": "CRITICAL_issues", "to": "flag"},
                {"condition": "always", "to": "proceed"},
            ],
            _state(), _config(), {}
        )
        # Should trace: CRITICAL_issues (false) then always (true)
        assert len(result["trace"]) >= 2

    def test_first_match_wins(self):
        result = evaluate_transitions_list(
            [
                {"condition": "always", "to": "first"},
                {"condition": "always", "to": "second"},
            ],
            _state(), _config(), {}
        )
        assert result["next_phase"] == "first"
        assert result["matched_transition_index"] == 0


# ---------------------------------------------------------------------------
# SKIPPED_PREFLIGHT_NODE routing boundary
# ---------------------------------------------------------------------------


class TestPreflightNodeBoundary:
    def test_preflight_node_returns_skipped(self):
        definition = {
            "phases": [
                {
                    "id": "phase1-why2-preflight",
                    "type": "commander_internal",
                    "preflight": True,
                    "dependency": "understanding",
                    "transitions": [
                        {"condition": "always", "to": "phase1-why2"}
                    ]
                }
            ]
        }
        result = evaluate_transitions(
            "phase1-why2-preflight",
            _state(), _config(), {},
            definition=definition
        )
        assert result["guard_result"] == "SKIPPED_PREFLIGHT_NODE"
        assert result["next_phase"] is None
        assert any("preflight_node_skipped" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Actions field propagation
# ---------------------------------------------------------------------------


class TestActionsField:
    def test_actions_returned_on_match(self):
        result = evaluate_transitions_list(
            [{"condition": "always", "to": "next", "actions": ["backup_state", "emit_log"]}],
            _state(), _config(), {}
        )
        assert result["actions"] == ["backup_state", "emit_log"]

    def test_empty_actions_when_no_match(self):
        result = evaluate_transitions_list([], _state(), _config(), {})
        assert result["actions"] == []

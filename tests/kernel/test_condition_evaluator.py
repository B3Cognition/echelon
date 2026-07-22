"""Tests for ConditionEvaluator — covers all condition patterns in definition.yaml."""
import sys
from pathlib import Path

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.condition_evaluator import ConditionEvaluator
from harness.squad_provider import SquadAgentResult


def _result(verdict: str) -> SquadAgentResult:
    return SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": verdict, "state_updates": {}},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )


class TestConditionEvaluator:
    ev = ConditionEvaluator()

    def test_always(self):
        assert self.ev.evaluate("always", {}) is True

    def test_verdict_done(self):
        assert self.ev.evaluate("verdict = DONE", {}, _result("DONE")) is True

    def test_verdict_done_mismatch(self):
        assert self.ev.evaluate("verdict = DONE", {}, _result("FAIL")) is False

    def test_verdict_pass(self):
        assert self.ev.evaluate("verdict = PASS", {}, _result("PASS")) is True

    def test_mode_brownfield(self):
        assert self.ev.evaluate("mode = brownfield", {"mode": "brownfield"}) is True

    def test_mode_brownfield_mismatch(self):
        assert self.ev.evaluate("mode = brownfield", {"mode": "greenfield"}) is False

    def test_string_equality(self):
        assert self.ev.evaluate("guardian_mode = always_on",
                                {"guardian_mode": "always_on"}) is True

    def test_numeric_gte_true(self):
        assert self.ev.evaluate("coverage_pct >= coverage_threshold",
                                {"coverage_pct": 80, "coverage_threshold": 80}) is True

    def test_numeric_gte_false(self):
        assert self.ev.evaluate("coverage_pct >= coverage_threshold",
                                {"coverage_pct": 72, "coverage_threshold": 80}) is False

    def test_numeric_lt_true(self):
        assert self.ev.evaluate("validate_iterations < max_validate_iterations",
                                {"validate_iterations": 2,
                                 "max_validate_iterations": 3}) is True

    def test_numeric_lt_false(self):
        assert self.ev.evaluate("validate_iterations < max_validate_iterations",
                                {"validate_iterations": 3,
                                 "max_validate_iterations": 3}) is False

    def test_autonomy_in_list(self):
        assert self.ev.evaluate("autonomy in [semi, banzai]",
                                {"autonomy": "semi"}) is True

    def test_autonomy_not_in_list(self):
        assert self.ev.evaluate("autonomy in [semi, banzai]",
                                {"autonomy": "guided"}) is False

    def test_boolean_field_true(self):
        assert self.ev.evaluate("convergence_detected",
                                {"convergence_detected": True}) is True

    def test_boolean_field_false(self):
        assert self.ev.evaluate("convergence_detected",
                                {"convergence_detected": False}) is False

    def test_dotted_path_true(self):
        assert self.ev.evaluate("quality_gates.pass",
                                {"quality_gates": {"pass": True}}) is True

    def test_dotted_path_false(self):
        assert self.ev.evaluate("quality_gates.pass",
                                {"quality_gates": {"pass": False}}) is False

    def test_and_both_true(self):
        assert self.ev.evaluate(
            "coverage_pct >= coverage_threshold AND validate_iterations < max_validate_iterations",
            {"coverage_pct": 85, "coverage_threshold": 80,
             "validate_iterations": 1, "max_validate_iterations": 3},
        ) is True

    def test_and_one_false(self):
        assert self.ev.evaluate(
            "coverage_pct >= coverage_threshold AND validate_iterations < max_validate_iterations",
            {"coverage_pct": 72, "coverage_threshold": 80,
             "validate_iterations": 1, "max_validate_iterations": 3},
        ) is False

    def test_and_false_dominates_unknown(self):
        assert self.ev.evaluate(
            "lexicon_gate.enabled AND NOT tasks_lexicon_pass",
            {"lexicon_gate": {"enabled": False}},
        ) is False

    def test_and_verdict_and_field(self):
        assert self.ev.evaluate(
            "verdict = PASS AND convergence_detected",
            {"convergence_detected": True},
            _result("PASS"),
        ) is True

    def test_or_first_true(self):
        assert self.ev.evaluate(
            "coverage_pct >= coverage_threshold OR verify_expand_iterations >= max_verify_expand_iterations",
            {"coverage_pct": 85, "coverage_threshold": 80,
             "verify_expand_iterations": 2, "max_verify_expand_iterations": 5},
        ) is True

    def test_or_true_short_circuits_unknown_human_approved(self):
        assert self.ev.evaluate(
            "autonomy in [semi, banzai] OR human_approved",
            {"autonomy_mode": "banzai"},
        ) is True

    def test_or_both_false(self):
        assert self.ev.evaluate(
            "coverage_pct >= coverage_threshold OR verify_expand_iterations >= max_verify_expand_iterations",
            {"coverage_pct": 72, "coverage_threshold": 80,
             "verify_expand_iterations": 2, "max_verify_expand_iterations": 5},
        ) is False

    def test_two_verdict_fields_and(self):
        assert self.ev.evaluate(
            "why3_verdict = PASS AND assess2_verdict = PASS",
            {"why3_verdict": "PASS", "assess2_verdict": "PASS"},
        ) is True

    def test_two_verdict_fields_one_fails(self):
        assert self.ev.evaluate(
            "why3_verdict = PASS AND assess2_verdict = PASS",
            {"why3_verdict": "PASS", "assess2_verdict": "FAIL"},
        ) is False

    def test_hyphenated_verdict_conditions_read_underscored_state_keys(self):
        assert self.ev.evaluate(
            "why3-verdict = FAIL OR assess2-verdict = REJECTED",
            {"why3_verdict": "FAIL", "assess2_verdict": "PASS"},
        ) is True

    def test_unknown_condition_returns_none(self):
        assert self.ev.evaluate("some_unknown_thing xyz", {}) is None

    def test_missing_field_comparison_false(self):
        assert self.ev.evaluate("coverage_pct >= coverage_threshold", {}) is False

    # ── quality_gates.* derived from quality_scores ──────────────────────

    def test_quality_gates_pass_from_quality_scores(self):
        state = {"quality_scores": [{"pass": True}]}
        assert self.ev.evaluate("quality_gates.pass", state) is True

    def test_quality_gates_fail_from_quality_scores(self):
        state = {"quality_scores": [{"pass": False}]}
        assert self.ev.evaluate("quality_gates.fail", state) is True

    def test_quality_gates_pass_false_when_scores_fail(self):
        state = {"quality_scores": [{"pass": False}]}
        assert self.ev.evaluate("quality_gates.pass", state) is False

    def test_quality_gates_string_pass_value_is_not_truthy(self):
        state = {"quality_scores": [{"pass": "WHY2-iter-0"}]}
        assert self.ev.evaluate("quality_gates.pass", state) is False
        assert self.ev.evaluate("quality_gates.fail", state) is True

    def test_quality_gates_falls_back_to_direct_field(self):
        # No quality_scores — fall back to state["quality_gates"]["pass"]
        state = {"quality_gates": {"pass": True}}
        assert self.ev.evaluate("quality_gates.pass", state) is True

    def test_quality_gates_uses_latest_score(self):
        state = {"quality_scores": [{"pass": True}, {"pass": False}]}
        assert self.ev.evaluate("quality_gates.fail", state) is True

    # ── CRITICAL_issues / no_CRITICAL_issues ─────────────────────────────

    def test_critical_issues_from_quality_scores_fail(self):
        state = {"quality_scores": [{"pass": False}], "issues_log": []}
        assert self.ev.evaluate("CRITICAL_issues", state) is True

    def test_no_critical_issues_from_quality_scores_pass(self):
        state = {"quality_scores": [{"pass": True}], "issues_log": []}
        assert self.ev.evaluate("no_CRITICAL_issues", state) is True

    def test_critical_issues_from_issues_log(self):
        state = {"issues_log": [{"severity": "CRITICAL", "id": "ISS-001"}],
                 "quality_scores": [{"pass": True}]}  # log takes priority
        assert self.ev.evaluate("CRITICAL_issues", state) is True

    def test_why1_fail_routes_to_discover(self):
        """Regression: WHY1 FAIL + iteration=0 must route to phase1-discover."""
        state = {
            "quality_scores": [{"pass": False}],
            "iteration": 0,
            "max_iterations": 5,
            "issues_log": [],
            "convergence_detected": False,
        }
        assert self.ev.evaluate("quality_gates.fail AND iteration < max_iterations", state) is True
        assert self.ev.evaluate("quality_gates.pass OR convergence_detected", state) is False
        assert self.ev.evaluate("iteration >= max_iterations", state) is False

    # ── Literal numeric RHS in comparisons ───────────────────────────────
    # Regression guard: conditions like "fix_cycle < 2" use a numeric literal
    # on the right, not a state field name. Previously _get(state, "2") returned
    # None, so the comparison always returned False regardless of fix_cycle.

    def test_literal_rhs_lt_true(self):
        assert self.ev.evaluate("fix_cycle < 2", {"fix_cycle": 1}) is True

    def test_literal_rhs_lt_false(self):
        assert self.ev.evaluate("fix_cycle < 2", {"fix_cycle": 2}) is False

    def test_literal_rhs_gte_true(self):
        assert self.ev.evaluate("fix_cycle >= 2", {"fix_cycle": 2}) is True

    def test_literal_rhs_gte_false(self):
        assert self.ev.evaluate("fix_cycle >= 2", {"fix_cycle": 1}) is False

    def test_literal_rhs_blocked_task_count(self):
        assert self.ev.evaluate("blocked_task_count >= 3", {"blocked_task_count": 3}) is True
        assert self.ev.evaluate("blocked_task_count >= 3", {"blocked_task_count": 2}) is False

    def test_literal_rhs_retry_count(self):
        assert self.ev.evaluate("retry_count < 2", {"retry_count": 1}) is True
        assert self.ev.evaluate("retry_count < 2", {"retry_count": 2}) is False

    # ── Compound conditions from build phases (definition.yaml lines 943-1065) ──
    # Regression guard: these conditions used lowercase "and" which the evaluator
    # splits on \bAND\b (uppercase only). The compound was treated as a single
    # field=value match (field="verdict", expected="FAIL and fix_cycle < 2"),
    # always returning False even when both sides would have been True.

    def test_verdict_and_literal_early_cycle(self):
        """verdict = FAIL AND fix_cycle < 2: both true → True."""
        assert self.ev.evaluate(
            "verdict = FAIL AND fix_cycle < 2",
            {"fix_cycle": 1},
            _result("FAIL"),
        ) is True

    def test_verdict_and_literal_late_cycle(self):
        """verdict = FAIL AND fix_cycle >= 2: fix_cycle satisfied → True."""
        assert self.ev.evaluate(
            "verdict = FAIL AND fix_cycle >= 2",
            {"fix_cycle": 2},
            _result("FAIL"),
        ) is True

    def test_verdict_and_literal_wrong_verdict(self):
        """verdict = FAIL AND fix_cycle < 2: verdict mismatch → False."""
        assert self.ev.evaluate(
            "verdict = FAIL AND fix_cycle < 2",
            {"fix_cycle": 1},
            _result("PASS"),
        ) is False

    def test_verdict_and_literal_cycle_exhausted(self):
        """verdict = FAIL AND fix_cycle < 2: cycle exhausted → False."""
        assert self.ev.evaluate(
            "verdict = FAIL AND fix_cycle < 2",
            {"fix_cycle": 2},
            _result("FAIL"),
        ) is False

    def test_changes_requested_and_literal(self):
        assert self.ev.evaluate(
            "verdict = CHANGES_REQUESTED AND fix_cycle < 2",
            {"fix_cycle": 0},
            _result("CHANGES_REQUESTED"),
        ) is True

    def test_needs_context_and_literal(self):
        assert self.ev.evaluate(
            "verdict = NEEDS_CONTEXT AND retry_count < 2",
            {"retry_count": 1},
            _result("NEEDS_CONTEXT"),
        ) is True

    def test_all_tasks_complete_and_no_more_checkpoints(self):
        state = {"all_tasks_complete": True, "no_more_phase_checkpoints": True}
        assert self.ev.evaluate("all_tasks_complete AND no_more_phase_checkpoints", state) is True

    def test_all_tasks_complete_but_more_checkpoints(self):
        state = {"all_tasks_complete": True, "no_more_phase_checkpoints": False}
        assert self.ev.evaluate("all_tasks_complete AND no_more_phase_checkpoints", state) is False

    # ── NOT <field> negation ─────────────────────────────────────────────
    # The lexicon-gate self-loop guards use `NOT lexicon_pass` / `NOT
    # tasks_lexicon_pass`. Without a NOT handler these return None, making the
    # whole AND indeterminate and punting the re-dispatch to COMMANDER instead
    # of evaluating deterministically.

    def test_not_false_field_is_true(self):
        assert self.ev.evaluate("NOT tasks_lexicon_pass", {"tasks_lexicon_pass": False}) is True

    def test_not_true_field_is_false(self):
        assert self.ev.evaluate("NOT tasks_lexicon_pass", {"tasks_lexicon_pass": True}) is False

    def test_not_absent_field_is_none(self):
        # Unknown/absent field stays indeterminate → COMMANDER (contract preserved).
        assert self.ev.evaluate("NOT tasks_lexicon_pass", {}) is None

    def test_not_dotted_path(self):
        assert self.ev.evaluate("NOT quality_gates.pass", {"quality_gates": {"pass": False}}) is True

    # ── Lexicon-gate re-dispatch guards evaluate deterministically ───────
    # Real conditions from definition.yaml phase1-what (spec) and phase3-plan
    # (tasks). With lexicon_gate config merged into the eval state (squad.py),
    # both the controller-owned failed and pending paths resolve deterministically
    # instead of punting to COMMANDER.

    TASKS_GUARD = "lexicon_gate.enabled AND NOT tasks_lexicon_pass AND iteration < max_iterations"
    SPEC_GUARD = "lexicon_gate.enabled AND lexicon_evaluation = failed AND iteration < max_iterations"
    PENDING_SPEC_GUARD = "lexicon_gate.enabled AND lexicon_evaluation = pending AND iteration < max_iterations"

    def test_tasks_guard_fail_path_redispatches(self):
        state = {"lexicon_gate": {"enabled": True}, "tasks_lexicon_pass": False,
                 "iteration": 0, "max_iterations": 3}
        assert self.ev.evaluate(self.TASKS_GUARD, state) is True

    def test_tasks_guard_pass_path_falls_through(self):
        state = {"lexicon_gate": {"enabled": True}, "tasks_lexicon_pass": True,
                 "iteration": 0, "max_iterations": 3}
        assert self.ev.evaluate(self.TASKS_GUARD, state) is False

    def test_tasks_guard_exhausted_iterations_falls_through(self):
        state = {"lexicon_gate": {"enabled": True}, "tasks_lexicon_pass": False,
                 "iteration": 3, "max_iterations": 3}
        assert self.ev.evaluate(self.TASKS_GUARD, state) is False

    def test_spec_guard_fail_path_redispatches(self):
        state = {"lexicon_gate": {"enabled": True}, "lexicon_evaluation": "failed",
                 "iteration": 0, "max_iterations": 3}
        assert self.ev.evaluate(self.SPEC_GUARD, state) is True

    def test_spec_guard_pending_path_redispatches(self):
        state = {"lexicon_gate": {"enabled": True}, "lexicon_evaluation": "pending",
                 "iteration": 0, "max_iterations": 3}
        assert self.ev.evaluate(self.PENDING_SPEC_GUARD, state) is True

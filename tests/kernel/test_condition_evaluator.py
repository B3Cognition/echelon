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

    def test_unknown_condition_returns_none(self):
        assert self.ev.evaluate("some_unknown_thing xyz", {}) is None

    def test_missing_field_comparison_false(self):
        assert self.ev.evaluate("coverage_pct >= coverage_threshold", {}) is False

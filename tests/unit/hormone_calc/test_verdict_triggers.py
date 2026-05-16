"""Tests for src/hormone_calc/triggers/verdict.py — A-category rules.

T-GATE-PASS, T-GATE-FAIL, T-REWORK, T-LOW-CONFIDENCE.
"""
from hormone_calc.triggers.verdict import VerdictTrigger
from hormone_calc.observable import ObservableState
from hormone_calc.output import HandlerCall


def _obs(*, agent="SAGE", verdict="PASS", confidence=None, prior_verdict=None, recent=None):
    result = {"verdict": verdict}
    if confidence is not None:
        result["data"] = {"confidence": confidence}
    return ObservableState(
        agent=agent, dispatch_id="D-001",
        result=result, archetype="validation",
        state={}, iteration=0, token_ratio=0.0, autonomy_mode="banzai",
        recent_dispatches=recent or [],
        quality_score_series=[],
        prior_verdict_for_agent=prior_verdict, upstream_agent=None,
        current_hormones={},
    )


# T-GATE-PASS — pass verdicts

def test_gate_pass_fires_for_PASS():
    t = VerdictTrigger()
    out = t.detect(_obs(verdict="PASS"))
    assert HandlerCall(name="on_gate_pass", args=("SAGE",)) in out


def test_gate_pass_fires_for_APPROVED():
    out = VerdictTrigger().detect(_obs(verdict="APPROVED"))
    assert HandlerCall(name="on_gate_pass", args=("SAGE",)) in out


def test_gate_pass_fires_for_DONE():
    out = VerdictTrigger().detect(_obs(verdict="DONE"))
    assert HandlerCall(name="on_gate_pass", args=("SAGE",)) in out


def test_gate_pass_fires_for_STABLE():
    out = VerdictTrigger().detect(_obs(verdict="STABLE"))
    assert HandlerCall(name="on_gate_pass", args=("SAGE",)) in out


# T-GATE-FAIL — fail verdicts

def test_gate_fail_fires_for_FAIL():
    out = VerdictTrigger().detect(_obs(verdict="FAIL"))
    assert HandlerCall(name="on_gate_fail", args=("SAGE",)) in out


def test_gate_fail_fires_for_CHANGES_REQUESTED():
    out = VerdictTrigger().detect(_obs(verdict="CHANGES_REQUESTED"))
    assert HandlerCall(name="on_gate_fail", args=("SAGE",)) in out


def test_gate_fail_fires_for_KILL():
    out = VerdictTrigger().detect(_obs(verdict="KILL"))
    assert HandlerCall(name="on_gate_fail", args=("SAGE",)) in out


# T-REWORK — prior + current both non-PASS

def test_rework_fires_when_prior_and_current_both_fail():
    out = VerdictTrigger().detect(_obs(verdict="FAIL", prior_verdict="FAIL"))
    assert HandlerCall(name="on_rework", args=("SAGE",)) in out


def test_rework_does_not_fire_when_prior_passed():
    out = VerdictTrigger().detect(_obs(verdict="FAIL", prior_verdict="PASS"))
    assert HandlerCall(name="on_rework", args=("SAGE",)) not in out


def test_rework_does_not_fire_when_no_prior():
    out = VerdictTrigger().detect(_obs(verdict="FAIL", prior_verdict=None))
    assert HandlerCall(name="on_rework", args=("SAGE",)) not in out


# T-LOW-CONFIDENCE — confidence < 0.5 OR soft-fail verdict

def test_low_confidence_fires_for_low_confidence_field():
    out = VerdictTrigger().detect(_obs(verdict="PASS", confidence=0.3))
    assert HandlerCall(name="on_low_confidence", args=("SAGE",)) in out


def test_low_confidence_fires_for_DONE_WITH_CONCERNS():
    out = VerdictTrigger().detect(_obs(verdict="DONE_WITH_CONCERNS"))
    assert HandlerCall(name="on_low_confidence", args=("SAGE",)) in out

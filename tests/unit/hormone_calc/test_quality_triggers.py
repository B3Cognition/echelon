"""Tests for src/hormone_calc/triggers/quality.py — T-QUALITY-IMPROVE / REGRESS."""
from hormone_calc.triggers.quality import QualityTrigger
from hormone_calc.observable import ObservableState
from hormone_calc.output import HandlerCall


def _obs(series):
    return ObservableState(
        agent="SAGE", dispatch_id="D-001",
        result={}, archetype="validation",
        state={}, iteration=0, token_ratio=0.0, autonomy_mode="banzai",
        recent_dispatches=[], quality_score_series=series,
        prior_verdict_for_agent=None, upstream_agent=None,
        current_hormones={},
    )


def test_improve_fires_when_delta_plus_005():
    out = QualityTrigger().detect(_obs([0.70, 0.75]))
    assert HandlerCall(name="on_quality_improvement", args=()) in out


def test_improve_fires_when_delta_plus_010():
    out = QualityTrigger().detect(_obs([0.60, 0.70]))
    assert HandlerCall(name="on_quality_improvement", args=()) in out


def test_regress_fires_when_delta_minus_005():
    out = QualityTrigger().detect(_obs([0.75, 0.70]))
    assert HandlerCall(name="on_quality_regression", args=()) in out


def test_no_fire_when_delta_under_threshold():
    # 0.03 delta is under the 0.05 trigger threshold
    out = QualityTrigger().detect(_obs([0.70, 0.73]))
    assert out == []


def test_no_fire_when_single_entry():
    out = QualityTrigger().detect(_obs([0.70]))
    assert out == []


def test_no_fire_when_empty_series():
    out = QualityTrigger().detect(_obs([]))
    assert out == []

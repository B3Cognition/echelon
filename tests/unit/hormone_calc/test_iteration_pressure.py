"""Tests for src/hormone_calc/triggers/iteration_pressure.py — F2."""
from hormone_calc.triggers.iteration_pressure import IterationPressureTrigger
from hormone_calc.observable import ObservableState
from hormone_calc.output import HormoneUpdate
from hormone_calc.config import DEFAULT_DYNAMICS


def _obs(iteration, max_iter=10):
    return ObservableState(
        agent="SAGE", dispatch_id="D-001",
        result={}, archetype="validation",
        state={"thresholds": {"max_squad_iterations": max_iter}},
        iteration=iteration, token_ratio=0.0, autonomy_mode="banzai",
        recent_dispatches=[], quality_score_series=[],
        prior_verdict_for_agent=None, upstream_agent=None,
        current_hormones={},
    )


def test_no_pressure_early():
    t = IterationPressureTrigger(DEFAULT_DYNAMICS)
    assert t.detect(_obs(iteration=2)) == []   # ratio 0.2
    assert t.detect(_obs(iteration=4)) == []   # ratio 0.4


def test_mid_band_emits_003():
    t = IterationPressureTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(iteration=6))   # ratio 0.6 ∈ [0.5, 0.75)
    assert out == [HormoneUpdate(agent="SAGE", hormone="adrenaline", delta=0.03)]


def test_late_band_emits_008():
    t = IterationPressureTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(iteration=8))   # ratio 0.8 ∈ [0.75, 1.00)
    assert out == [HormoneUpdate(agent="SAGE", hormone="adrenaline", delta=0.08)]


def test_boundary_half_max_uses_mid_band():
    """ratio == 0.5 falls in [0.5, 0.75) band → +0.03"""
    t = IterationPressureTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(iteration=5))
    assert out == [HormoneUpdate(agent="SAGE", hormone="adrenaline", delta=0.03)]


def test_iteration_at_max_emits_late_band():
    t = IterationPressureTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(iteration=10))  # ratio 1.0
    assert out == [HormoneUpdate(agent="SAGE", hormone="adrenaline", delta=0.08)]

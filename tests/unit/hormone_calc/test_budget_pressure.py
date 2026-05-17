"""Tests for src/hormone_calc/triggers/budget_pressure.py — F1."""
import pytest
from hormone_calc.triggers.budget_pressure import BudgetPressureTrigger
from hormone_calc.observable import ObservableState
from hormone_calc.output import HormoneUpdate, BroadcastAdrenaline
from hormone_calc.config import DEFAULT_DYNAMICS


def _obs(token_ratio):
    return ObservableState(
        agent="SAGE", dispatch_id="D-001",
        result={}, archetype="validation",
        state={}, iteration=0, token_ratio=token_ratio, autonomy_mode="banzai",
        recent_dispatches=[], quality_score_series=[],
        prior_verdict_for_agent=None, upstream_agent=None,
        current_hormones={},
    )


def test_no_pressure_in_calm_band():
    t = BudgetPressureTrigger(DEFAULT_DYNAMICS)
    assert t.detect(_obs(0.20)) == []
    assert t.detect(_obs(0.39)) == []


def test_mild_band_emits_002():
    t = BudgetPressureTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(0.50))
    assert out == [HormoneUpdate(agent="SAGE", hormone="adrenaline", delta=0.02)]


def test_moderate_band_emits_005():
    t = BudgetPressureTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(0.70))
    assert out == [HormoneUpdate(agent="SAGE", hormone="adrenaline", delta=0.05)]


def test_high_band_emits_010():
    t = BudgetPressureTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(0.85))
    assert out == [HormoneUpdate(agent="SAGE", hormone="adrenaline", delta=0.10)]


def test_critical_band_emits_015_plus_broadcast():
    t = BudgetPressureTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(0.97))
    assert HormoneUpdate(agent="SAGE", hormone="adrenaline", delta=0.15) in out
    assert BroadcastAdrenaline(delta=0.05) in out


def test_band_boundary_uses_lower_inclusive():
    """ratio == 0.40 falls in the [0.40, 0.60) band → mild +0.02"""
    t = BudgetPressureTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(0.40))
    assert out == [HormoneUpdate(agent="SAGE", hormone="adrenaline", delta=0.02)]


def test_ratio_at_1_emits_critical():
    t = BudgetPressureTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(1.00))
    assert HormoneUpdate(agent="SAGE", hormone="adrenaline", delta=0.15) in out
    assert BroadcastAdrenaline(delta=0.05) in out

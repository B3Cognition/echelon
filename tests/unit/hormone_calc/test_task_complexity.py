"""Tests for src/hormone_calc/triggers/task_complexity.py — F3."""
import pytest
from hormone_calc.triggers.task_complexity import TaskComplexityTrigger
from hormone_calc.observable import ObservableState
from hormone_calc.output import HormoneUpdate
from hormone_calc.config import DEFAULT_DYNAMICS


def _obs(agent, archetype):
    return ObservableState(
        agent=agent, dispatch_id="D-001",
        result={}, archetype=archetype,
        state={}, iteration=0, token_ratio=0.0, autonomy_mode="banzai",
        recent_dispatches=[], quality_score_series=[],
        prior_verdict_for_agent=None, upstream_agent=None,
        current_hormones={},
    )


def test_scout_exploration_baseline_emits_negative_delta():
    """exploration base 0.40 - 0.5 = -0.10; * 0.15 = -0.015"""
    t = TaskComplexityTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(agent="SCOUT", archetype="exploration"))
    assert out == [HormoneUpdate(agent="SCOUT", hormone="norepinephrine", delta=-0.015)]


def test_implementer_build_with_bump_emits_006():
    """(0.80 build + 0.10 IMPLEMENTER bump - 0.5) * 0.15 = 0.06"""
    t = TaskComplexityTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(agent="IMPLEMENTER", archetype="build"))
    assert out == [HormoneUpdate(agent="IMPLEMENTER", hormone="norepinephrine", delta=0.06)]


def test_debugger_build_with_largest_bump():
    """(0.80 + 0.15 DEBUGGER - 0.5) * 0.15 = 0.0675"""
    t = TaskComplexityTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(agent="DEBUGGER", archetype="build"))
    assert out == [HormoneUpdate(agent="DEBUGGER", hormone="norepinephrine", delta=0.0675)]


def test_gatekeeper_feasibility_with_bump():
    """(0.60 feasibility + 0.10 GATEKEEPER - 0.5) * 0.15 = 0.03"""
    t = TaskComplexityTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(agent="GATEKEEPER", archetype="feasibility"))
    assert out == [HormoneUpdate(agent="GATEKEEPER", hormone="norepinephrine", delta=0.03)]


def test_unbumped_agent_uses_archetype_base_only():
    """SAGE has no bump; validation 0.5 → (0.5 - 0.5) * 0.15 = 0.0 → no emission"""
    t = TaskComplexityTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(agent="SAGE", archetype="validation"))
    assert out == []


def test_commander_control_archetype_no_bump_no_delta():
    """control base 0.40, no bump → (0.40 - 0.5) * 0.15 = -0.015"""
    t = TaskComplexityTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(agent="COMMANDER", archetype="control"))
    assert out == [HormoneUpdate(agent="COMMANDER", hormone="norepinephrine", delta=-0.015)]


def test_learning_archetype_lowest_baseline():
    """learning 0.30 - 0.5 = -0.20; * 0.15 = -0.03"""
    t = TaskComplexityTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(agent="AUDITOR", archetype="learning"))
    assert out == [HormoneUpdate(agent="AUDITOR", hormone="norepinephrine", delta=-0.03)]


def test_clamped_at_1_when_archetype_plus_bump_exceeds():
    """Synthetic: build 0.80 + hypothetical 0.30 bump = 1.10 → clamp to 1.0
       (1.0 - 0.5) * 0.15 = 0.075"""
    from hormone_calc.config import DynamicsConfig, BudgetPressureConfig, IterationPressureConfig, TaskComplexityConfig, Band
    cfg = DynamicsConfig(
        budget_pressure=BudgetPressureConfig(bands=(Band(1.0, 0.0),), critical_broadcast=0.0),
        iteration_pressure=IterationPressureConfig(bands=(Band(1.0, 0.0),)),
        task_complexity=TaskComplexityConfig(
            multiplier=0.15,
            archetype_base={"build": 0.80},
            agent_bump={"WEIRD_AGENT": 0.30},
        ),
    )
    t = TaskComplexityTrigger(cfg)
    out = t.detect(_obs(agent="WEIRD_AGENT", archetype="build"))
    # (min(0.80 + 0.30, 1.0) - 0.5) * 0.15 = (1.0 - 0.5) * 0.15 = 0.075
    assert out == [HormoneUpdate(agent="WEIRD_AGENT", hormone="norepinephrine", delta=0.075)]


def test_clamped_at_0_when_archetype_plus_negative_bump_below_0():
    """Synthetic: control 0.40 + hypothetical -0.50 bump = -0.10 → clamp to 0
       (0 - 0.5) * 0.15 = -0.075"""
    from hormone_calc.config import DynamicsConfig, BudgetPressureConfig, IterationPressureConfig, TaskComplexityConfig, Band
    cfg = DynamicsConfig(
        budget_pressure=BudgetPressureConfig(bands=(Band(1.0, 0.0),), critical_broadcast=0.0),
        iteration_pressure=IterationPressureConfig(bands=(Band(1.0, 0.0),)),
        task_complexity=TaskComplexityConfig(
            multiplier=0.15,
            archetype_base={"control": 0.40},
            agent_bump={"WEIRD_AGENT": -0.50},
        ),
    )
    t = TaskComplexityTrigger(cfg)
    out = t.detect(_obs(agent="WEIRD_AGENT", archetype="control"))
    assert out == [HormoneUpdate(agent="WEIRD_AGENT", hormone="norepinephrine", delta=-0.075)]


def test_unknown_archetype_uses_zero_base():
    """archetype not in archetype_base → base 0; no bump → (0 - 0.5) * 0.15 = -0.075"""
    t = TaskComplexityTrigger(DEFAULT_DYNAMICS)
    out = t.detect(_obs(agent="SAGE", archetype="WEIRDTYPE"))
    assert out == [HormoneUpdate(agent="SAGE", hormone="norepinephrine", delta=-0.075)]


def test_explicit_zero_delta_skips_emission():
    """(0.5 + 0 - 0.5) * 0.15 = 0.0 → no emission"""
    from hormone_calc.config import DynamicsConfig, BudgetPressureConfig, IterationPressureConfig, TaskComplexityConfig, Band
    cfg = DynamicsConfig(
        budget_pressure=BudgetPressureConfig(bands=(Band(1.0, 0.0),), critical_broadcast=0.0),
        iteration_pressure=IterationPressureConfig(bands=(Band(1.0, 0.0),)),
        task_complexity=TaskComplexityConfig(
            multiplier=0.15,
            archetype_base={"middle": 0.5},
            agent_bump={},
        ),
    )
    t = TaskComplexityTrigger(cfg)
    out = t.detect(_obs(agent="WHATEVER", archetype="middle"))
    assert out == []


def test_zero_multiplier_skips_emission():
    """multiplier == 0 → all deltas 0 → no emission"""
    from hormone_calc.config import DynamicsConfig, BudgetPressureConfig, IterationPressureConfig, TaskComplexityConfig, Band
    cfg = DynamicsConfig(
        budget_pressure=BudgetPressureConfig(bands=(Band(1.0, 0.0),), critical_broadcast=0.0),
        iteration_pressure=IterationPressureConfig(bands=(Band(1.0, 0.0),)),
        task_complexity=TaskComplexityConfig(
            multiplier=0.0,
            archetype_base={"build": 0.80},
            agent_bump={"IMPLEMENTER": 0.10},
        ),
    )
    t = TaskComplexityTrigger(cfg)
    out = t.detect(_obs(agent="IMPLEMENTER", archetype="build"))
    assert out == []

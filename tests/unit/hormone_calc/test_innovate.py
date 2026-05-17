"""Tests for src/hormone_calc/triggers/innovate.py — T-INNOVATE-SUMMON."""
from hormone_calc.triggers.innovate import InnovateTrigger
from hormone_calc.observable import ObservableState
from hormone_calc.output import HandlerCall


def _obs(agent):
    return ObservableState(
        agent=agent, dispatch_id="D-001",
        result={}, archetype="innovation" if agent == "MAVERICK" else "control",
        state={}, iteration=0, token_ratio=0.0, autonomy_mode="banzai",
        recent_dispatches=[], quality_score_series=[],
        prior_verdict_for_agent=None, upstream_agent=None,
        current_hormones={},
    )


def test_innovate_fires_for_maverick():
    t = InnovateTrigger()
    out = t.detect(_obs(agent="MAVERICK"))
    assert out == [HandlerCall(name="on_innovate_summon", args=())]


def test_innovate_does_not_fire_for_other_agents():
    t = InnovateTrigger()
    for agent in ("SAGE", "IMPLEMENTER", "COMMANDER", "GOLDDIGGER", "SCOUT"):
        assert t.detect(_obs(agent=agent)) == []

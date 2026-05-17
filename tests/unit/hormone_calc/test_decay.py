"""Tests for src/hormone_calc/triggers/decay.py — always-on T-DECAY."""
import pytest
from hormone_calc.triggers.decay import DecayTrigger
from hormone_calc.observable import ObservableState
from hormone_calc.output import HandlerCall


def _obs(agent="SAGE"):
    return ObservableState(
        agent=agent, dispatch_id="D-001",
        result={}, archetype="validation",
        state={}, iteration=0, token_ratio=0.0, autonomy_mode="banzai",
        recent_dispatches=[], quality_score_series=[],
        prior_verdict_for_agent=None, upstream_agent=None,
        current_hormones={},
    )


def test_decay_always_emits_one_call_for_current_agent():
    t = DecayTrigger()
    out = t.detect(_obs(agent="SAGE"))
    assert out == [HandlerCall(name="decay_hormones", args=("SAGE",))]

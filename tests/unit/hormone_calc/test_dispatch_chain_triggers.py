"""Tests for src/hormone_calc/triggers/dispatch_chain.py — C-category rules."""
from hormone_calc.triggers.dispatch_chain import DispatchChainTrigger
from hormone_calc.observable import ObservableState
from hormone_calc.output import HandlerCall


def _obs(*, agent="SAGE", verdict="PASS", upstream=None, state=None):
    return ObservableState(
        agent=agent, dispatch_id="D-001",
        result={"verdict": verdict}, archetype="validation",
        state=state or {}, iteration=0, token_ratio=0.0, autonomy_mode="banzai",
        recent_dispatches=[], quality_score_series=[],
        prior_verdict_for_agent=None,
        upstream_agent=upstream,
        current_hormones={},
    )


def test_no_upstream_all_rules_skip():
    out = DispatchChainTrigger().detect(_obs(upstream=None))
    assert out == []


def test_propagate_downstream_fires_when_upstream_present():
    out = DispatchChainTrigger().detect(_obs(upstream="CARTOGRAPHER"))
    assert HandlerCall(name="propagate_downstream", args=("CARTOGRAPHER", "SAGE")) in out


def test_cortisol_contagion_fires_when_upstream_cortisol_high():
    state = {"endocrine_state": {"agents": {"CARTOGRAPHER": {"hormones": {"cortisol": 0.90}}}}}
    out = DispatchChainTrigger().detect(_obs(upstream="CARTOGRAPHER", state=state))
    assert HandlerCall(name="propagate_cortisol_contagion", args=("CARTOGRAPHER", "SAGE")) in out


def test_cortisol_contagion_does_not_fire_when_upstream_cortisol_low():
    state = {"endocrine_state": {"agents": {"CARTOGRAPHER": {"hormones": {"cortisol": 0.50}}}}}
    out = DispatchChainTrigger().detect(_obs(upstream="CARTOGRAPHER", state=state))
    assert HandlerCall(name="propagate_cortisol_contagion", args=("CARTOGRAPHER", "SAGE")) not in out


def test_peer_accept_fires_when_gate_agent_passes():
    out = DispatchChainTrigger().detect(_obs(agent="SAGE", verdict="PASS", upstream="CARTOGRAPHER"))
    assert HandlerCall(name="on_peer_accept", args=("CARTOGRAPHER", "SAGE")) in out


def test_peer_reject_fires_when_gate_agent_fails():
    out = DispatchChainTrigger().detect(_obs(agent="SAGE", verdict="FAIL", upstream="CARTOGRAPHER"))
    assert HandlerCall(name="on_peer_reject", args=("CARTOGRAPHER", "SAGE")) in out


def test_peer_accept_does_not_fire_for_non_gate_agent():
    """IMPLEMENTER is not a GATE_AGENT — peer_accept should not fire even on PASS."""
    out = DispatchChainTrigger().detect(_obs(agent="IMPLEMENTER", verdict="DONE", upstream="ARCHITECT"))
    assert HandlerCall(name="on_peer_accept", args=("ARCHITECT", "IMPLEMENTER")) not in out


def test_peer_reject_does_not_fire_for_non_gate_agent():
    out = DispatchChainTrigger().detect(_obs(agent="IMPLEMENTER", verdict="FAIL", upstream="ARCHITECT"))
    assert HandlerCall(name="on_peer_reject", args=("ARCHITECT", "IMPLEMENTER")) not in out


def test_all_C_rules_fire_for_gate_agent_failing_high_cortisol_upstream():
    state = {"endocrine_state": {"agents": {"CARTOGRAPHER": {"hormones": {"cortisol": 0.90}}}}}
    out = DispatchChainTrigger().detect(_obs(agent="SAGE", verdict="FAIL", upstream="CARTOGRAPHER", state=state))
    names = {tr.name for tr in out}
    assert names == {
        "propagate_downstream",
        "propagate_cortisol_contagion",
        "on_peer_reject",
    }


def test_upstream_missing_from_state_skips_cortisol_contagion():
    """If upstream agent has no entry in endocrine_state, cortisol unknown — skip."""
    out = DispatchChainTrigger().detect(_obs(upstream="UNKNOWN_AGENT"))
    # propagate_downstream still fires, but contagion should not
    assert HandlerCall(name="propagate_downstream", args=("UNKNOWN_AGENT", "SAGE")) in out
    assert HandlerCall(name="propagate_cortisol_contagion", args=("UNKNOWN_AGENT", "SAGE")) not in out

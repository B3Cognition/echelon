"""Tests for src/hormone_calc/upstream.py — derive_upstream() heuristic.

Returns the most recent dispatched agent (from routing_decision journal entries)
that isn't the current agent. None if no such entry in the last 50.
"""
import pytest
from hormone_calc.upstream import derive_upstream
from hormone_calc.observable import ObservableState


def _obs(*, agent="SAGE", recent=None, state=None):
    return ObservableState(
        agent=agent, dispatch_id="D-001",
        result={}, archetype="validation",
        state=state or {"phase": "phase1-why2"},
        iteration=1, token_ratio=0.1, autonomy_mode="banzai",
        recent_dispatches=recent or [],
        quality_score_series=[],
        prior_verdict_for_agent=None, upstream_agent=None,
        current_hormones={},
    )


def test_no_journal_returns_none():
    obs = _obs(recent=[])
    assert derive_upstream(obs) is None


def test_only_self_in_journal_returns_none():
    recent = [
        {"id": "RJ-001", "type": "routing_decision", "agent": "SAGE", "phase": "phase1-why2",
         "data": {"output_files": ["issues.md"]}},
    ]
    obs = _obs(recent=recent)
    assert derive_upstream(obs) is None


def test_prior_different_agent_same_phase_returned():
    recent = [
        {"id": "RJ-001", "type": "routing_decision", "agent": "CARTOGRAPHER", "phase": "phase1-what",
         "data": {"output_files": ["spec.md"]}},
        {"id": "RJ-002", "type": "routing_decision", "agent": "SAGE", "phase": "phase1-why2",
         "data": {"output_files": []}},
    ]
    obs = _obs(state={"phase": "phase1-why2"}, recent=recent)
    # SAGE WHY2 always consumes CARTOGRAPHER's spec.md → CARTOGRAPHER is upstream
    assert derive_upstream(obs) == "CARTOGRAPHER"


def test_walks_backward_skipping_same_agent():
    recent = [
        {"id": "RJ-001", "type": "routing_decision", "agent": "SCOUT", "phase": "phase1-discover",
         "data": {"output_files": ["glossary.md"]}},
        {"id": "RJ-002", "type": "routing_decision", "agent": "SAGE", "phase": "phase1-why1",
         "data": {"output_files": []}},   # earlier SAGE pass
        {"id": "RJ-003", "type": "routing_decision", "agent": "SAGE", "phase": "phase1-why1",
         "data": {"output_files": []}},   # another SAGE pass
    ]
    # If current is SAGE and prior SAGEs are skipped, SCOUT is upstream
    obs = _obs(state={"phase": "phase1-why1"}, recent=recent)
    assert derive_upstream(obs) == "SCOUT"


def test_walks_backward_finds_most_recent_other_agent():
    recent = [
        {"id": "RJ-001", "type": "routing_decision", "agent": "SCOUT", "phase": "phase1-discover",
         "data": {"output_files": ["glossary.md"]}},
        {"id": "RJ-002", "type": "routing_decision", "agent": "SYNTHESIZER", "phase": "phase1-synthesize",
         "data": {"output_files": ["fused-glossary.md"]}},
        {"id": "RJ-003", "type": "routing_decision", "agent": "CARTOGRAPHER", "phase": "phase1-what",
         "data": {"output_files": ["spec.md"]}},
    ]
    obs = _obs(state={"phase": "phase1-why2"}, recent=recent)
    # Most recent non-SAGE is CARTOGRAPHER
    assert derive_upstream(obs) == "CARTOGRAPHER"


def test_ignores_non_routing_decision_entries():
    recent = [
        {"id": "RJ-001", "type": "init_knowledge_read", "agent": "COMMANDER", "phase": "init",
         "data": {}},
        {"id": "RJ-002", "type": "endocrine_event", "agent": "COMMANDER", "phase": "init",
         "data": {"trigger": "decay_hormones"}},
    ]
    obs = _obs(state={"phase": "phase1-why2"}, recent=recent)
    assert derive_upstream(obs) is None


def test_upstream_normalizes_speckit_form_to_uppercase():
    """Journal contains 'echelon-commander'; derive_upstream returns 'COMMANDER'."""
    recent = [
        {"id": "RJ-001", "type": "routing_decision", "agent": "echelon-commander",
         "phase": "init", "data": {"verdict": "DONE"}},
    ]
    obs = _obs(recent=recent)
    assert derive_upstream(obs) == "COMMANDER"


def test_upstream_normalizes_multi_part_speckit_name():
    """echelon-spec-guard → SPEC_GUARD."""
    recent = [
        {"id": "RJ-001", "type": "routing_decision", "agent": "echelon-spec-guard",
         "phase": "build-3", "data": {"verdict": "PASS"}},
    ]
    obs = _obs(recent=recent)
    assert derive_upstream(obs) == "SPEC_GUARD"

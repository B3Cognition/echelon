"""Tests for src/hormone_calc/observable.py — ObservableState + build_from."""
import json
from pathlib import Path
import pytest
import yaml

from hormone_calc.observable import ObservableState, build_from


@pytest.fixture
def minimal_state(tmp_path):
    state = {
        "iteration": 3,
        "thresholds": {"token_budget_k": 1000},
        "token_ledger": {"total_estimated_tokens": 350_000},
        "autonomy_mode": "banzai",
        "quality_scores": [{"overall": 0.72}, {"overall": 0.78}],
        "endocrine_state": {
            "agents": {
                "SAGE": {
                    "archetype": "validation",
                    "hormones": {
                        "adrenaline": 0.40, "dopamine": 0.30, "cortisol": 0.80,
                        "serotonin": 0.40, "oxytocin": 0.40, "norepinephrine": 0.70,
                    },
                }
            }
        },
    }
    p = tmp_path / "state.json"
    p.write_text(json.dumps(state))
    return p


@pytest.fixture
def minimal_journal(tmp_path):
    p = tmp_path / "journal.jsonl"
    p.write_text(
        '{"id":"RJ-001","type":"routing_decision","agent":"CARTOGRAPHER","data":{"verdict":"DONE"}}\n'
        '{"id":"RJ-002","type":"routing_decision","agent":"SAGE","data":{"verdict":"FAIL"}}\n'
    )
    return p


@pytest.fixture
def minimal_result(tmp_path):
    result = {"verdict": "PASS", "agent": "SAGE"}
    p = tmp_path / "result.yaml"
    p.write_text(yaml.dump(result))
    return p


def _fake_archetype_fn(agent):
    return {"SAGE": "validation", "CARTOGRAPHER": "exploration"}.get(agent, "control")


def test_build_from_populates_basic_fields(minimal_state, minimal_journal, minimal_result):
    obs = build_from(
        agent="SAGE",
        dispatch_id="D-007",
        result_path=minimal_result,
        state_path=minimal_state,
        journal_path=minimal_journal,
        archetype_fn=_fake_archetype_fn,
    )
    assert obs.agent == "SAGE"
    assert obs.dispatch_id == "D-007"
    assert obs.archetype == "validation"
    assert obs.iteration == 3
    assert obs.token_ratio == pytest.approx(0.35)  # 350k / 1M
    assert obs.autonomy_mode == "banzai"
    assert obs.quality_score_series == [0.72, 0.78]
    assert obs.current_hormones["cortisol"] == 0.80


def test_build_from_finds_prior_verdict(minimal_state, minimal_journal, minimal_result):
    obs = build_from(
        agent="SAGE",
        dispatch_id="D-007",
        result_path=minimal_result,
        state_path=minimal_state,
        journal_path=minimal_journal,
        archetype_fn=_fake_archetype_fn,
    )
    assert obs.prior_verdict_for_agent == "FAIL"


def test_build_from_no_prior_verdict_returns_none(minimal_state, tmp_path, minimal_result):
    empty_journal = tmp_path / "empty.jsonl"
    empty_journal.write_text("")
    obs = build_from(
        agent="SAGE",
        dispatch_id="D-007",
        result_path=minimal_result,
        state_path=minimal_state,
        journal_path=empty_journal,
        archetype_fn=_fake_archetype_fn,
    )
    assert obs.prior_verdict_for_agent is None


def test_build_from_token_ratio_zero_budget(minimal_state, minimal_journal, minimal_result):
    # Zero budget shouldn't crash — return 0.0
    state = json.loads(minimal_state.read_text())
    state["thresholds"]["token_budget_k"] = 0
    minimal_state.write_text(json.dumps(state))
    obs = build_from(
        agent="SAGE",
        dispatch_id="D-007",
        result_path=minimal_result,
        state_path=minimal_state,
        journal_path=minimal_journal,
        archetype_fn=_fake_archetype_fn,
    )
    assert obs.token_ratio == 0.0


def test_build_from_journal_tail_limit_50(minimal_state, tmp_path, minimal_result):
    big_journal = tmp_path / "big.jsonl"
    lines = []
    for i in range(100):
        lines.append(f'{{"id":"RJ-{i:03d}","type":"routing_decision","agent":"X","data":{{}}}}')
    big_journal.write_text("\n".join(lines))
    obs = build_from(
        agent="SAGE",
        dispatch_id="D-007",
        result_path=minimal_result,
        state_path=minimal_state,
        journal_path=big_journal,
        archetype_fn=_fake_archetype_fn,
    )
    assert len(obs.recent_dispatches) == 50
    # Last 50 (RJ-050..RJ-099); last in list should be RJ-099
    assert obs.recent_dispatches[-1]["id"] == "RJ-099"

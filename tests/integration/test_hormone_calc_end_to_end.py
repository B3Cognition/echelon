"""End-to-end integration test — `hormone-calc compute` against synthetic fixtures."""
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def workspace(tmp_path, repo_root):
    """Build a minimal workspace with state.json, journal, result file, and config."""
    state = {
        "iteration": 7,
        "thresholds": {"token_budget_k": 1000, "max_squad_iterations": 10},
        "token_ledger": {"total_estimated_tokens": 700_000},
        "autonomy_mode": "banzai",
        "quality_scores": [{"overall": 0.70}, {"overall": 0.78}],   # +0.08 → improvement
        "endocrine_state": {
            "agents": {
                "SPEC_GUARD": {
                    "archetype": "validation",
                    "hormones": {"adrenaline": 0.5, "dopamine": 0.5, "cortisol": 0.90,
                                 "serotonin": 0.5, "oxytocin": 0.5, "norepinephrine": 0.5},
                },
                "IMPLEMENTER": {
                    "archetype": "build",
                    "hormones": {"adrenaline": 0.7, "dopamine": 0.5, "cortisol": 0.5,
                                 "serotonin": 0.4, "oxytocin": 0.7, "norepinephrine": 0.9},
                },
            }
        },
    }

    journal_path = tmp_path / "journal.jsonl"
    journal_path.write_text(
        '{"id":"RJ-001","type":"routing_decision","agent":"SPEC_GUARD","phase":"build-3-spec-guard","data":{"verdict":"FAIL","output_files":["spec-issues.md"]}}\n'
        '{"id":"RJ-002","type":"routing_decision","agent":"IMPLEMENTER","phase":"build-2-implement","data":{"verdict":"FAIL"}}\n'
    )

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state))

    result_path = tmp_path / "result.yaml"
    result_path.write_text(yaml.dump({"verdict": "FAIL", "agent": "IMPLEMENTER"}))

    # Minimal echelon-config so DynamicsConfig defaults are used (block absent)
    config_path = tmp_path / "echelon-config.yml"
    config_path.write_text("endocrine:\n  enabled: true\n")

    return {
        "state": state_path,
        "journal": journal_path,
        "result": result_path,
        "config": config_path,
    }


def _run_compute(args_dict, repo_root):
    """Invoke `python3 -m hormone_calc.cli compute ...`. Preserves the test env's
    PATH but ensures PYTHONPATH includes src/."""
    env = dict(os.environ)
    src = str(repo_root / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src}:{existing}" if existing else src

    cmd = ["python3", "-m", "hormone_calc.cli", "compute"]
    for k, v in args_dict.items():
        cmd.append(f"--{k}")
        cmd.append(str(v))
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(repo_root))


def test_compute_emits_expected_triggers(workspace, repo_root):
    result = _run_compute({
        "agent": "IMPLEMENTER",
        "dispatch-id": "D-007",
        "result-file": workspace["result"],
        "state": workspace["state"],
        "journal": workspace["journal"],
        "config": workspace["config"],
    }, repo_root)

    assert result.returncode == 0, f"stderr: {result.stderr}"

    lines = [l for l in result.stdout.strip().split("\n") if l]

    # Expected triggers (build archetype IMPLEMENTER, FAIL verdict, rework, upstream=SPEC_GUARD high cortisol):
    # decay_hormones IMPLEMENTER                              (E)
    # hormone_update IMPLEMENTER adrenaline +0.05             (F1: ratio 0.7 in band [0.6, 0.8))
    # hormone_update IMPLEMENTER adrenaline +0.03             (F2: iter 7/10=0.7 in band [0.5, 0.75))
    # hormone_update IMPLEMENTER norepinephrine +0.06         (F3: build 0.80 + IMPLEMENTER 0.10 - 0.5 = 0.4 * 0.15)
    # propagate_downstream SPEC_GUARD IMPLEMENTER             (C)
    # propagate_cortisol_contagion SPEC_GUARD IMPLEMENTER     (C: SPEC_GUARD cortisol 0.9 > 0.8)
    # on_gate_fail IMPLEMENTER                                (A: FAIL)
    # on_rework IMPLEMENTER                                   (A: prior=FAIL + current=FAIL)
    # on_low_confidence IMPLEMENTER                           (A: not soft-fail; data.confidence absent — should NOT fire actually)
    # on_quality_improvement                                  (B: 0.70 → 0.78 = +0.08)
    #
    # NOTE: low_confidence only fires for confidence<0.5 OR soft-fail verdict. FAIL is not soft-fail.
    # So on_low_confidence should NOT fire for verdict=FAIL.
    #
    # IMPLEMENTER is not a GATE_AGENT, so peer_accept/reject NOT fired.
    # MAVERICK not dispatched, so innovate NOT fired.

    assert "decay_hormones IMPLEMENTER" in lines
    assert "hormone_update IMPLEMENTER adrenaline +0.05" in lines
    assert "hormone_update IMPLEMENTER adrenaline +0.03" in lines
    assert "hormone_update IMPLEMENTER norepinephrine +0.06" in lines
    assert "propagate_downstream SPEC_GUARD IMPLEMENTER" in lines
    assert "propagate_cortisol_contagion SPEC_GUARD IMPLEMENTER" in lines
    assert "on_gate_fail IMPLEMENTER" in lines
    assert "on_rework IMPLEMENTER" in lines
    assert "on_quality_improvement" in lines
    # Verify low_confidence does NOT fire for verdict=FAIL without confidence field
    assert "on_low_confidence IMPLEMENTER" not in lines


def test_compute_empty_when_no_dynamics_and_no_events(workspace, repo_root):
    """Cold start: fresh state, no journal events, no quality history, calm budget.
    Only decay + gate_pass should fire for SAGE."""

    fresh_state = json.loads(workspace["state"].read_text())
    fresh_state["iteration"] = 0
    fresh_state["token_ledger"]["total_estimated_tokens"] = 0
    fresh_state["quality_scores"] = []
    # Ensure SAGE is in endocrine_state so observable.py finds it
    fresh_state["endocrine_state"]["agents"]["SAGE"] = {
        "archetype": "validation",
        "hormones": {"adrenaline": 0.4, "dopamine": 0.3, "cortisol": 0.8,
                     "serotonin": 0.4, "oxytocin": 0.4, "norepinephrine": 0.7},
    }
    workspace["state"].write_text(json.dumps(fresh_state))

    # Empty journal
    workspace["journal"].write_text("")

    # PASS verdict for SAGE
    workspace["result"].write_text(yaml.dump({"verdict": "PASS"}))

    result = _run_compute({
        "agent": "SAGE",
        "dispatch-id": "D-001",
        "result-file": workspace["result"],
        "state": workspace["state"],
        "journal": workspace["journal"],
        "config": workspace["config"],
    }, repo_root)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    lines = [l for l in result.stdout.strip().split("\n") if l]

    # Only decay + verdict-pass (SAGE validation = 0.5 base, no bump → delta 0 → no F3 emission)
    # SAGE is GATE_AGENT but no upstream → no peer events
    assert "decay_hormones SAGE" in lines
    assert "on_gate_pass SAGE" in lines
    # No budget/iteration/complexity emissions (calm + cold + neutral)
    assert not any(l.startswith("hormone_update") for l in lines)

"""Integration tests for Endocrine Phase 3 shell command wiring (T-028 / IS-005).

Verifies that endocrine.sh correctly handles on_gate_pass / on_gate_fail /
on_quality_improvement / on_quality_regression and mutates hormone state as
documented in the Post-Dispatch Protocol (ADR-006 / commander.md).

Run with: pytest tests/integration/test_endocrine_phase3.py -v -m integration
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
ENDOCRINE_SH = REPO_ROOT / "scripts" / "bash" / "endocrine.sh"
COMMANDER_MD = REPO_ROOT / "extension" / "agents" / "control" / "commander.md"

_HORMONES = ("adrenaline", "dopamine", "cortisol", "serotonin", "oxytocin", "norepinephrine")


@pytest.fixture(autouse=True, scope="module")
def require_endocrine_sh():
    if not ENDOCRINE_SH.exists():
        pytest.skip(f"endocrine.sh not found at {ENDOCRINE_SH}")


def _initial_state(*agents: str) -> dict:
    return {
        "endocrine_state": {
            "agents": {
                agent: {
                    "hormones": {h: 0.5 for h in _HORMONES},
                    "archetype": "control",
                }
                for agent in agents
            }
        }
    }


@pytest.fixture
def endocrine_env(tmp_path):
    """Temp directory with a phase-3 config and pre-initialized state.json."""
    config = tmp_path / "echelon-config.yml"
    state_file = tmp_path / "state.json"
    config.write_text("endocrine:\n  enabled: true\n  phase: 3\n")
    state_file.write_text(json.dumps(_initial_state("IMPLEMENTER", "SCOUT")))
    return {"config": config, "state": state_file}


def _run(cmd: list[str], env_data: dict) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["ENDOCRINE_CONFIG_FILE"] = str(env_data["config"])
    env["ENDOCRINE_STATE_FILE"] = str(env_data["state"])
    return subprocess.run(
        ["bash", str(ENDOCRINE_SH)] + cmd,
        capture_output=True, text=True, timeout=10, env=env,
    )


def _hormones(state_file: Path, agent: str) -> dict:
    return json.loads(state_file.read_text())["endocrine_state"]["agents"][agent]["hormones"]


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEndocrineShCommandDispatch:
    def test_on_gate_pass_exits_zero(self, endocrine_env):
        r = _run(["on_gate_pass", "IMPLEMENTER"], endocrine_env)
        assert r.returncode == 0, f"STDOUT: {r.stdout}\nSTDERR: {r.stderr}"

    def test_on_gate_fail_exits_zero(self, endocrine_env):
        r = _run(["on_gate_fail", "IMPLEMENTER"], endocrine_env)
        assert r.returncode == 0, f"STDOUT: {r.stdout}\nSTDERR: {r.stderr}"

    def test_on_quality_improvement_exits_zero(self, endocrine_env):
        r = _run(["on_quality_improvement"], endocrine_env)
        assert r.returncode == 0, f"STDOUT: {r.stdout}\nSTDERR: {r.stderr}"

    def test_on_quality_regression_exits_zero(self, endocrine_env):
        r = _run(["on_quality_regression"], endocrine_env)
        assert r.returncode == 0, f"STDOUT: {r.stdout}\nSTDERR: {r.stderr}"


# ---------------------------------------------------------------------------
# Hormone state mutation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEndocrineHormoneMutation:
    def test_gate_pass_raises_dopamine(self, endocrine_env):
        sf = endocrine_env["state"]
        before = _hormones(sf, "IMPLEMENTER")["dopamine"]
        r = _run(["on_gate_pass", "IMPLEMENTER"], endocrine_env)
        assert r.returncode == 0
        after = _hormones(sf, "IMPLEMENTER")["dopamine"]
        assert after > before, f"dopamine should increase on gate_pass: {before} → {after}"

    def test_gate_fail_lowers_dopamine_and_raises_cortisol(self, endocrine_env):
        sf = endocrine_env["state"]
        before = _hormones(sf, "IMPLEMENTER")
        r = _run(["on_gate_fail", "IMPLEMENTER"], endocrine_env)
        assert r.returncode == 0
        after = _hormones(sf, "IMPLEMENTER")
        assert after["dopamine"] < before["dopamine"], (
            f"dopamine should decrease on gate_fail: {before['dopamine']} → {after['dopamine']}"
        )
        assert after["cortisol"] > before["cortisol"], (
            f"cortisol should increase on gate_fail: {before['cortisol']} → {after['cortisol']}"
        )

    def test_quality_improvement_raises_serotonin_for_all_agents(self, endocrine_env):
        sf = endocrine_env["state"]
        before_impl = _hormones(sf, "IMPLEMENTER")["serotonin"]
        before_scout = _hormones(sf, "SCOUT")["serotonin"]
        r = _run(["on_quality_improvement"], endocrine_env)
        assert r.returncode == 0
        after_impl = _hormones(sf, "IMPLEMENTER")["serotonin"]
        after_scout = _hormones(sf, "SCOUT")["serotonin"]
        assert after_impl > before_impl, f"IMPLEMENTER serotonin: {before_impl} → {after_impl}"
        assert after_scout > before_scout, f"SCOUT serotonin: {before_scout} → {after_scout}"

    def test_quality_regression_lowers_serotonin_for_all_agents(self, endocrine_env):
        sf = endocrine_env["state"]
        before_impl = _hormones(sf, "IMPLEMENTER")["serotonin"]
        before_scout = _hormones(sf, "SCOUT")["serotonin"]
        r = _run(["on_quality_regression"], endocrine_env)
        assert r.returncode == 0
        after_impl = _hormones(sf, "IMPLEMENTER")["serotonin"]
        after_scout = _hormones(sf, "SCOUT")["serotonin"]
        assert after_impl < before_impl, f"IMPLEMENTER serotonin: {before_impl} → {after_impl}"
        assert after_scout < before_scout, f"SCOUT serotonin: {before_scout} → {after_scout}"


# `TestCommanderPhase3Documentation` removed: it checked commander.md for
# in-text markers (ADR-006, RSK-003, "Phase 3+ only", "on_rework deferred")
# that were intentionally restructured into the new §0-numbered layout and
# the workflow/phases/*.md files. The functional checks above
# (TestEndocrineShCommandDispatch, TestEndocrineHormoneMutation) validate
# the behavior those doc-string assertions were standing in for.

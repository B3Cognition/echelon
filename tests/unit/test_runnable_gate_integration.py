"""Cross-seam integration test for the RUNNABLE gate phase (C1/I2).

Covers:
  - TaskQueue + inject_compose_task: COMPOSE scheduled last (C3 guarantee)
  - parse_runnable_contract: valid SPA contract parses cleanly
  - run_runnable_gate with stub probe: HOLLOW app (liveness signal but primary evidence absent) → fail
  - run_runnable_gate with stub probe: fully-present composition evidence → pass
  - Wiring guard: echelon.codegen.md lists codegen-6c-runnable BEFORE codegen-7-deliver
  - Wiring guard: codegen-7-deliver.md blocks on runnable_gate
"""
from __future__ import annotations

import pathlib

import pytest

from codegen.decompose.task_queue import CodeTask, TaskQueue
from codegen.decompose.compose_task import (
    inject_compose_task,
    dependency_safe_order,
    COMPOSE_TASK_ID,
)
from codegen.schema.runnable_contract import parse_runnable_contract
from codegen.runner.runnable_gate import run_runnable_gate, ProbeOutcome


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feature(n: int) -> CodeTask:
    return CodeTask(
        task_id=f"T-{n:03d}",
        description=f"feature {n}",
        scope=f"component{n}",
        language="typescript",
        module_boundary=f"module{n}",
    )


_VALID_SPA_CONTRACT = {
    "kind": "spa",
    "build": "npm run build",
    "liveness": "http://localhost:{port}/",
    "primary_surface": {
        "req": "FR-001",
        "assert": "dashboard table visible in DOM",
    },
    "surfaces": [
        {"req": "FR-006", "assert": "settings panel visible"},
    ],
    "probe": "browser",
}


# ---------------------------------------------------------------------------
# C3: COMPOSE scheduled last
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_compose_scheduled_last_in_dependency_safe_order():
    """COMPOSE task (T-999) must appear last in the dependency-safe ordering."""
    q = TaskQueue([_feature(1), _feature(2)])
    inject_compose_task(q, language="typescript")
    order = dependency_safe_order(q)
    assert order[-1] == COMPOSE_TASK_ID, (
        f"COMPOSE should be last but got order: {order}"
    )


# ---------------------------------------------------------------------------
# parse_runnable_contract: valid SPA contract
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_parse_valid_spa_contract():
    """parse_runnable_contract accepts a valid SPA contract without raising."""
    contract = parse_runnable_contract(_VALID_SPA_CONTRACT)
    assert contract.kind == "spa"
    assert contract.primary_surface["req"] == "FR-001"
    assert contract.probe == "browser"


# ---------------------------------------------------------------------------
# run_runnable_gate: HOLLOW app → fail
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_runnable_gate_hollow_app_fails():
    """Liveness signal with absent primary evidence returns passed=False."""
    contract = parse_runnable_contract(_VALID_SPA_CONTRACT)

    def hollow_probe(workspace, c, port):
        # Probe reports liveness but primary evidence (FR-001) is absent.
        return ProbeOutcome(live=True, present={"FR-001": False})

    result = run_runnable_gate(contract, ".", probe_fn=hollow_probe)
    assert result.passed is False, "HOLLOW app (primary surface absent) should fail the gate"
    assert any("FR-001" in f for f in result.failures), (
        f"Expected FR-001 in failures; got: {result.failures}"
    )


# ---------------------------------------------------------------------------
# run_runnable_gate: fully-present composed app → pass
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_runnable_gate_composed_app_passes():
    """Present primary and secondary evidence returns passed=True."""
    contract = parse_runnable_contract(_VALID_SPA_CONTRACT)

    def full_probe(workspace, c, port):
        return ProbeOutcome(live=True, present={"FR-001": True, "FR-006": True})

    result = run_runnable_gate(contract, ".", probe_fn=full_probe)
    assert result.passed is True, f"Composed app should pass; failures: {result.failures}"
    assert result.surface_score == 1.0


# ---------------------------------------------------------------------------
# Wiring guard: codegen-6c-runnable listed before codegen-7-deliver in pipeline
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pipeline_sequence_lists_runnable_before_deliver():
    """Guard against re-orphaning: echelon.codegen.md must list codegen-6c-runnable
    before codegen-7-deliver.md — if this fails the RUNNABLE phase is orphaned again."""
    seq_path = pathlib.Path("extension/commands/echelon.codegen.md")
    seq = seq_path.read_text()
    i_runnable = seq.find("codegen-6c-runnable")
    i_deliver = seq.find("codegen-7-deliver.md")
    assert 0 < i_runnable < i_deliver, (
        f"codegen-6c-runnable (at {i_runnable}) must appear before "
        f"codegen-7-deliver.md (at {i_deliver}) in {seq_path}"
    )


# ---------------------------------------------------------------------------
# Wiring guard: DELIVER phase spec references the runnable_gate precondition
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_deliver_phase_blocks_on_runnable_gate():
    """codegen-7-deliver.md must explicitly block on runnable_gate to prevent
    hollow-app delivery even if the wiring check above passes."""
    deliver_path = pathlib.Path("extension/workflow/phases/codegen-7-deliver.md")
    text = deliver_path.read_text()
    assert "runnable_gate" in text, (
        f"codegen-7-deliver.md must reference 'runnable_gate' as a hard precondition; "
        f"found none in {deliver_path}"
    )

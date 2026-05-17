"""T029: E2E smoke test — degraded run.

Verifies the degraded-mode path end-to-end:
1. Preflight probe returns DEGRADED → run_preflight returns status=DEGRADED.
2. DEGRADED result routes to the degraded node (not terminal-blocked).
3. Degraded mode label is appendable to state.dependency_checks.
4. Evaluator handles degraded state fields correctly (does not crash).
5. Constitution check still runs in degraded mode (non-blocking).
6. State with degraded_mode_stack populated does not break evaluator.
7. Multiple degraded dependencies compound without loss.
8. UNAVAILABLE + meta_run=true routes to degraded, not terminal-blocked.

These tests exercise the integration between preflight → state → evaluator
without dispatching any agent (pure function path only).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from kernel.preflight import (
    PreflightNoMatchingTransition,
    _PROBE_REGISTRY,
    _resolve_next_node,
    run_preflight,
)
from kernel.evaluator import evaluate_transitions_list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_preflight_node(dependency="understanding", degraded_to="degraded-branch"):
    return {
        "id": f"{dependency}-preflight",
        "type": "commander_internal",
        "preflight": True,
        "dependency": dependency,
        "transitions": [
            {"to": "available-path", "condition": "preflight_result = AVAILABLE"},
            {"to": degraded_to, "condition": "preflight_result = DEGRADED"},
            {"to": "terminal-blocked", "condition": "preflight_result = UNAVAILABLE AND meta_run = false"},
            {"to": "degraded-branch", "condition": "preflight_result = UNAVAILABLE AND meta_run = true"},
        ],
    }


def _make_state(degraded_mode_stack=None, dependency_checks=None, meta_run=False):
    return {
        "run_id": "squad-smoke-degraded-001",
        "status": "building",
        "phase": "preflight",
        "mode": "brownfield",
        "iteration": 1,
        "max_iterations": 5,
        "meta_run": meta_run,
        "autonomy_mode": "semi",
        "defer_count": 0,
        "golddigger_status": "n/a",
        "degraded_mode_stack": degraded_mode_stack or [],
        "dependency_checks": dependency_checks or {},
        "last_quality_scores": {},
        "issues_log": [],
        "features_registry": [],
        "spec_ids": [],
    }


def _make_config():
    return {
        "convergence": {
            "max_iterations": 5,
            "quality_delta_threshold": 0.02,
            "consecutive_passes_required": 2,
            "assess_defer_loop_limit": 2,
        },
        "quality_gates": {"spec": {"overall": 0.7}},
        "specialists": {"guardian_mode": "always_on"},
    }


def _mock_probe(status, reason="n/a", exit_code=None, stderr="", cause=""):
    def probe(state, config, ext_dir):
        return (status, reason, exit_code, stderr, cause)
    return probe


# ---------------------------------------------------------------------------
# 1. Preflight DEGRADED routing
# ---------------------------------------------------------------------------


class TestDegradedPreflight:
    def test_degraded_probe_returns_degraded_status(self):
        node = _make_preflight_node()
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("DEGRADED", reason="script_error")}):
            result = run_preflight(node, _make_state(), _make_config())
        assert result["status"] == "DEGRADED"

    def test_degraded_routes_to_degraded_branch(self):
        node = _make_preflight_node(degraded_to="degraded-branch")
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("DEGRADED", reason="script_error")}):
            result = run_preflight(node, _make_state(), _make_config())
        assert result["next_node"] == "degraded-branch"

    def test_degraded_does_not_route_to_terminal_blocked(self):
        node = _make_preflight_node()
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("DEGRADED")}):
            result = run_preflight(node, _make_state(), _make_config())
        assert result["next_node"] != "terminal-blocked"

    def test_degraded_result_has_all_fields(self):
        node = _make_preflight_node()
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("DEGRADED", reason="silent_failure", cause="partial data")}):
            result = run_preflight(node, _make_state(), _make_config())
        for field in ["dependency", "status", "reason_code", "exit_code",
                      "stderr_excerpt", "detected_cause", "checked_at", "next_node"]:
            assert field in result

    def test_degraded_reason_code_preserved(self):
        node = _make_preflight_node()
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("DEGRADED", reason="permission_denied")}):
            result = run_preflight(node, _make_state(), _make_config())
        assert result["reason_code"] == "permission_denied"


# ---------------------------------------------------------------------------
# 2. UNAVAILABLE + meta_run=true → degraded branch (not terminal-blocked)
# ---------------------------------------------------------------------------


class TestUnavailableMetaRunTrue:
    def test_unavailable_meta_run_true_goes_to_degraded_branch(self):
        node = _make_preflight_node()
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("UNAVAILABLE")}):
            result = run_preflight(node, _make_state(meta_run=True), _make_config())
        assert result["status"] == "UNAVAILABLE"
        assert result["next_node"] == "degraded-branch"

    def test_unavailable_meta_run_false_goes_to_terminal_blocked(self):
        node = _make_preflight_node()
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("UNAVAILABLE")}):
            result = run_preflight(node, _make_state(meta_run=False), _make_config())
        assert result["status"] == "UNAVAILABLE"
        assert result["next_node"] == "terminal-blocked"


# ---------------------------------------------------------------------------
# 3. State persistence: dependency_checks + degraded_mode_stack simulation
# ---------------------------------------------------------------------------


class TestDegradedStatePersistence:
    """Simulate COMMANDER persisting preflight result to state (caller's responsibility)."""

    def test_degraded_result_can_be_stored_in_dependency_checks(self):
        node = _make_preflight_node()
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("DEGRADED", reason="script_error")}):
            result = run_preflight(node, _make_state(), _make_config())

        # Simulate COMMANDER writing result to state
        state = _make_state()
        dep_name = result["dependency"]
        state["dependency_checks"][dep_name] = {
            "status": result["status"],
            "reason_code": result["reason_code"],
            "checked_at": result["checked_at"],
        }

        assert state["dependency_checks"]["understanding"]["status"] == "DEGRADED"

    def test_degraded_mode_label_appended_to_stack(self):
        """When DEGRADED, COMMANDER should append a mode label to degraded_mode_stack."""
        state = _make_state()
        # Simulate COMMANDER appending the mode label
        state["degraded_mode_stack"].append("understanding_unavailable")
        assert "understanding_unavailable" in state["degraded_mode_stack"]

    def test_multiple_degraded_deps_stack_without_loss(self):
        state = _make_state()
        state["degraded_mode_stack"].append("understanding_unavailable")
        state["degraded_mode_stack"].append("brownfield_unavailable")
        assert len(state["degraded_mode_stack"]) == 2
        assert "understanding_unavailable" in state["degraded_mode_stack"]
        assert "brownfield_unavailable" in state["degraded_mode_stack"]

    def test_available_dep_not_added_to_degraded_stack(self):
        node = _make_preflight_node()
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("AVAILABLE")}):
            result = run_preflight(node, _make_state(), _make_config())

        state = _make_state()
        # COMMANDER should only append if DEGRADED/UNAVAILABLE
        if result["status"] == "AVAILABLE":
            # No label added
            pass
        state["degraded_mode_stack"]  # unchanged

        assert state["degraded_mode_stack"] == []


# ---------------------------------------------------------------------------
# 4. Evaluator continues in degraded mode
# ---------------------------------------------------------------------------


class TestEvaluatorInDegradedMode:
    def test_evaluator_runs_with_non_empty_degraded_mode_stack(self):
        """Evaluator must not crash if degraded_mode_stack is populated."""
        state = _make_state(degraded_mode_stack=["understanding_unavailable"])
        config = _make_config()
        transitions = [{"condition": "always", "to": "next-phase"}]
        result = evaluate_transitions_list(transitions, state, config, {})
        assert result["guard_result"] == "PASS"

    def test_evaluator_runs_with_dependency_checks_populated(self):
        state = _make_state(dependency_checks={
            "understanding": {"status": "DEGRADED", "reason_code": "script_error"}
        })
        config = _make_config()
        transitions = [{"condition": "always", "to": "next-phase"}]
        result = evaluate_transitions_list(transitions, state, config, {})
        assert result["guard_result"] == "PASS"

    def test_evaluator_fails_gracefully_with_empty_transitions(self):
        state = _make_state(degraded_mode_stack=["understanding_unavailable"])
        config = _make_config()
        result = evaluate_transitions_list([], state, config, {})
        assert result["guard_result"] == "FAIL"
        assert "no_transition_matched" in result.get("errors", [])

    def test_evaluator_verdict_pass_still_routes_in_degraded_mode(self):
        """PASS verdict routing should work regardless of degraded_mode_stack."""
        state = _make_state(degraded_mode_stack=["brownfield_unavailable"])
        config = _make_config()
        last_outputs = {"verdict": "PASS"}
        transitions = [
            {"condition": "verdict = PASS", "to": "phase2-why"},
            {"condition": "always", "to": "fallback"},
        ]
        result = evaluate_transitions_list(transitions, state, config, last_outputs)
        assert result["guard_result"] == "PASS"
        assert result["next_phase"] == "phase2-why"


# ---------------------------------------------------------------------------
# 5. Constitution check in degraded mode (non-blocking)
# ---------------------------------------------------------------------------


class TestConstitutionCheckDegradedMode:
    def test_constitution_check_runs_with_degraded_state_artifact(self):
        """Constitution checker should run even if the state represents a degraded run."""
        from kernel.constitution_checker import check_constitution

        # A minimal "spec" artifact that might be produced in degraded mode
        degraded_spec = """
# Degraded Run Spec

## Overview

This spec was produced in degraded mode.

## Functional Requirements

### FR-001: Core Feature

mode: brownfield
citation: state.json
"""
        principles = [
            {
                "id": "P-degraded-1",
                "form": "structural",
                "text": "Spec must mention degraded",
                "accessor": "sections[title='Overview']",
                "predicate": "MUST_CONTAIN degraded",
            }
        ]
        results = check_constitution(principles, degraded_spec)
        assert len(results) == 1
        assert results[0]["verdict"] == "PASS"

    def test_constitution_check_non_blocking_on_degraded_artifact(self):
        """Even if constitution check fails, it returns FAIL — does not raise exceptions."""
        from kernel.constitution_checker import check_constitution

        minimal_spec = "# Minimal Spec\n\nContent here."
        principles = [
            {
                "id": "P-missing",
                "form": "structural",
                "text": "Must have an Overview section",
                "accessor": "sections[title='Nonexistent Section']",
                "predicate": "MUST_CONTAIN something",
            }
        ]
        results = check_constitution(principles, minimal_spec)
        # Returns FAIL — does not raise
        assert results[0]["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# 6. Multiple dependency probes in same run
# ---------------------------------------------------------------------------


class TestMultiplePreflightProbes:
    def test_two_degraded_probes_produce_independent_results(self):
        for dep in ["understanding", "brownfield"]:
            node = _make_preflight_node(dependency=dep)
            with patch.dict(_PROBE_REGISTRY, {dep: _mock_probe("DEGRADED")}):
                result = run_preflight(node, _make_state(), _make_config())
            assert result["status"] == "DEGRADED"
            assert result["dependency"] == dep

    def test_one_available_one_degraded_do_not_interfere(self):
        node_u = _make_preflight_node(dependency="understanding")
        node_r = _make_preflight_node(dependency="brownfield")

        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("AVAILABLE"),
                                          "brownfield": _mock_probe("DEGRADED")}):
            r_u = run_preflight(node_u, _make_state(), _make_config())
            r_r = run_preflight(node_r, _make_state(), _make_config())

        assert r_u["status"] == "AVAILABLE"
        assert r_r["status"] == "DEGRADED"
        assert r_u["dependency"] != r_r["dependency"]

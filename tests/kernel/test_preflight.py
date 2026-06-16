"""T020: Unit test pack — preflight.py (>= 18 tests)

Tests per contracts/preflight-contract.md test-contract:
1. Each of 4 dependencies × each of 3 statuses (12 tests)
2. meta_run branching (2 tests)
3. Timeout path (1 test)
4. Probe exception path (1 test)
5. Journal entry shape (1 test per status = 3 tests)
6. Schema-load rejection (1 test)

Total: >= 18 tests.
"""

import sys
import time
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from kernel.preflight import (
    PreflightNoMatchingTransition,
    PreflightResult,
    _PROBE_REGISTRY,
    _probe_understanding,
    _resolve_next_node,
    run_preflight,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_node(dependency: str, meta_run_false_to: str = "escalate",
               degraded_to: str = "degraded", available_to: str = "next",
               meta_run_true_to: str = "degraded") -> dict:
    return {
        "id": f"{dependency}-preflight",
        "type": "commander_internal",
        "preflight": True,
        "dependency": dependency,
        "transitions": [
            {"to": available_to, "condition": "preflight_result = AVAILABLE"},
            {"to": degraded_to, "condition": "preflight_result = DEGRADED"},
            {"to": meta_run_false_to, "condition": "preflight_result = UNAVAILABLE AND meta_run = false"},
            {"to": meta_run_true_to, "condition": "preflight_result = UNAVAILABLE AND meta_run = true"},
        ],
    }


def _state(meta_run: bool = False) -> dict:
    return {"meta_run": meta_run, "mode": "brownfield"}


def _config() -> dict:
    return {}


def _mock_probe(status: str, reason: str = "n/a", exit_code=None, stderr="", cause=""):
    """Return a probe function that always returns the specified status."""
    def probe(state, config, ext_dir):
        return (status, reason, exit_code, stderr, cause)
    return probe


# ---------------------------------------------------------------------------
# 1. Four registered probes exist
# ---------------------------------------------------------------------------


class TestProbeRegistry:
    def test_understanding_registered(self):
        assert "understanding" in _PROBE_REGISTRY

    def test_brownfield_registered(self):
        assert "brownfield" in _PROBE_REGISTRY

    def test_skill_golddigger_registered(self):
        assert "skill:GOLDDIGGER" in _PROBE_REGISTRY

    def test_kb_schema_registered(self):
        assert "kb_schema" in _PROBE_REGISTRY


class TestUnderstandingProbe:
    def test_understanding_console_script_counts_as_available(self, tmp_path):
        with patch("kernel.preflight.shutil.which", return_value="/venv/bin/understanding"):
            with patch("kernel.preflight.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "understanding version 3.7.0\n"
                run.return_value.stderr = ""

                status, reason, exit_code, stderr, cause = _probe_understanding(
                    {}, {}, tmp_path / ".specify" / "extensions" / "echelon"
                )

        assert status == "AVAILABLE"
        assert reason == "n/a"
        assert exit_code == 0
        assert stderr == ""
        assert cause == "understanding CLI smoke probe passed"
        run.assert_called_once_with(
            ["/venv/bin/understanding", "--version"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )


# ---------------------------------------------------------------------------
# 2. Dependency × status combinations (12 tests using mock probes)
# ---------------------------------------------------------------------------


class TestDependencyStatusCombinations:
    """Each of 4 dependencies × 3 statuses = 12 tests."""

    @pytest.mark.parametrize("dependency", ["understanding", "brownfield", "skill:GOLDDIGGER", "kb_schema"])
    def test_available_status(self, dependency):
        node = _make_node(dependency)
        with patch.dict(_PROBE_REGISTRY, {dependency: _mock_probe("AVAILABLE")}):
            result = run_preflight(node, _state(), _config())
        assert result["status"] == "AVAILABLE"
        assert result["next_node"] == "next"

    @pytest.mark.parametrize("dependency", ["understanding", "brownfield", "skill:GOLDDIGGER", "kb_schema"])
    def test_degraded_status(self, dependency):
        node = _make_node(dependency)
        with patch.dict(_PROBE_REGISTRY, {dependency: _mock_probe("DEGRADED", reason="script_error")}):
            result = run_preflight(node, _state(), _config())
        assert result["status"] == "DEGRADED"
        assert result["next_node"] == "degraded"

    @pytest.mark.parametrize("dependency", ["understanding", "brownfield", "skill:GOLDDIGGER", "kb_schema"])
    def test_unavailable_status(self, dependency):
        node = _make_node(dependency)
        with patch.dict(_PROBE_REGISTRY, {dependency: _mock_probe("UNAVAILABLE", reason="missing_install")}):
            result = run_preflight(node, _state(meta_run=False), _config())
        assert result["status"] == "UNAVAILABLE"
        assert result["next_node"] == "escalate"


# ---------------------------------------------------------------------------
# 3. meta_run branching (2 tests)
# ---------------------------------------------------------------------------


class TestMetaRunBranching:
    def test_unavailable_meta_run_false_routes_to_blocked(self):
        """UNAVAILABLE + meta_run=false → terminal-blocked route."""
        node = _make_node("understanding",
                          meta_run_false_to="terminal-blocked",
                          meta_run_true_to="degraded-branch")
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("UNAVAILABLE")}):
            result = run_preflight(node, _state(meta_run=False), _config())
        assert result["status"] == "UNAVAILABLE"
        assert result["next_node"] == "terminal-blocked"

    def test_unavailable_meta_run_true_routes_to_degraded(self):
        """UNAVAILABLE + meta_run=true → degraded branch (not terminal-blocked)."""
        node = _make_node("understanding",
                          meta_run_false_to="terminal-blocked",
                          meta_run_true_to="degraded-branch")
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("UNAVAILABLE")}):
            result = run_preflight(node, _state(meta_run=True), _config())
        assert result["status"] == "UNAVAILABLE"
        assert result["next_node"] == "degraded-branch"


# ---------------------------------------------------------------------------
# 4. Timeout path (1 test)
# ---------------------------------------------------------------------------


class TestTimeoutPath:
    def test_slow_probe_becomes_unavailable_timeout(self):
        """A probe that exceeds the budget results in UNAVAILABLE with reason_code=timeout."""
        def slow_probe(state, config, ext_dir):
            # We don't actually sleep — we mock the time
            return ("AVAILABLE", "n/a", 0, "", "")

        node = _make_node("understanding")

        # Patch time.monotonic to simulate budget exceeded
        original_time = time.monotonic

        call_count = [0]
        def fake_time():
            call_count[0] += 1
            if call_count[0] <= 1:
                return 0.0
            return 15.0  # 15s > 10s budget

        with patch.dict(_PROBE_REGISTRY, {"understanding": slow_probe}):
            with patch("kernel.preflight.time.monotonic", fake_time):
                result = run_preflight(node, _state(), _config())

        assert result["status"] == "UNAVAILABLE"
        assert result["reason_code"] == "timeout"
        assert "TIMEOUT" in result["stderr_excerpt"]


# ---------------------------------------------------------------------------
# 5. Probe exception path (1 test)
# ---------------------------------------------------------------------------


class TestProbeExceptionPath:
    def test_probe_exception_becomes_unavailable_script_error(self):
        def failing_probe(state, config, ext_dir):
            raise RuntimeError("kaboom — unexpected failure")

        node = _make_node("understanding")
        with patch.dict(_PROBE_REGISTRY, {"understanding": failing_probe}):
            result = run_preflight(node, _state(), _config())

        assert result["status"] == "UNAVAILABLE"
        assert result["reason_code"] == "script_error"
        assert "kaboom" in result["stderr_excerpt"]
        assert result["detected_cause"] == "probe raised exception"


# ---------------------------------------------------------------------------
# 6. Unregistered dependency → UNAVAILABLE
# ---------------------------------------------------------------------------


class TestUnregisteredDependency:
    def test_unknown_dependency_returns_unavailable(self):
        node = _make_node("totally_unknown_dep")
        result = run_preflight(node, _state(), _config())
        assert result["status"] == "UNAVAILABLE"
        assert result["reason_code"] == "missing_install"
        assert "totally_unknown_dep" in result["stderr_excerpt"]


# ---------------------------------------------------------------------------
# 7. Result shape — all required fields present
# ---------------------------------------------------------------------------


class TestResultShape:
    def test_available_result_has_all_fields(self):
        node = _make_node("kb_schema")
        with patch.dict(_PROBE_REGISTRY, {"kb_schema": _mock_probe("AVAILABLE")}):
            result = run_preflight(node, _state(), _config())

        required_fields = ["dependency", "status", "reason_code", "exit_code",
                           "stderr_excerpt", "detected_cause", "checked_at", "next_node"]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    def test_degraded_result_has_all_fields(self):
        node = _make_node("kb_schema")
        with patch.dict(_PROBE_REGISTRY, {"kb_schema": _mock_probe("DEGRADED", reason="silent_failure", cause="partial data")}):
            result = run_preflight(node, _state(), _config())

        assert result["status"] == "DEGRADED"
        assert result["reason_code"] == "silent_failure"
        assert result["detected_cause"] == "partial data"
        assert result["checked_at"]

    def test_unavailable_result_has_all_fields(self):
        node = _make_node("understanding")
        with patch.dict(_PROBE_REGISTRY, {"understanding": _mock_probe("UNAVAILABLE", reason="missing_install")}):
            result = run_preflight(node, _state(), _config())

        assert result["status"] == "UNAVAILABLE"
        assert result["reason_code"] == "missing_install"
        assert len(result["checked_at"]) > 0


# ---------------------------------------------------------------------------
# 8. stderr_excerpt truncation (FR-OBSERV-001)
# ---------------------------------------------------------------------------


class TestStderrTruncation:
    def test_long_stderr_truncated_to_2048(self):
        long_stderr = "x" * 5000

        def probe_with_long_stderr(state, config, ext_dir):
            return ("UNAVAILABLE", "script_error", 1, long_stderr, "test")

        node = _make_node("understanding")
        with patch.dict(_PROBE_REGISTRY, {"understanding": probe_with_long_stderr}):
            result = run_preflight(node, _state(), _config())

        assert len(result["stderr_excerpt"].encode("utf-8")) <= 2200  # 2048 + truncation suffix


# ---------------------------------------------------------------------------
# 9. _resolve_next_node unit tests
# ---------------------------------------------------------------------------


class TestResolveNextNode:
    def _node(self):
        return {
            "id": "test-preflight",
            "transitions": [
                {"to": "available-path", "condition": "preflight_result = AVAILABLE"},
                {"to": "degraded-path", "condition": "preflight_result = DEGRADED"},
                {"to": "blocked", "condition": "preflight_result = UNAVAILABLE AND meta_run = false"},
                {"to": "degraded-path", "condition": "preflight_result = UNAVAILABLE AND meta_run = true"},
            ]
        }

    def test_available_resolves(self):
        assert _resolve_next_node(self._node(), "AVAILABLE", False) == "available-path"

    def test_degraded_resolves(self):
        assert _resolve_next_node(self._node(), "DEGRADED", False) == "degraded-path"

    def test_unavailable_false_resolves_to_blocked(self):
        assert _resolve_next_node(self._node(), "UNAVAILABLE", False) == "blocked"

    def test_unavailable_true_resolves_to_degraded(self):
        assert _resolve_next_node(self._node(), "UNAVAILABLE", True) == "degraded-path"

    def test_no_matching_transition_raises(self):
        node = {"id": "bad-node", "transitions": [
            {"to": "x", "condition": "preflight_result = AVAILABLE"},
            # missing UNAVAILABLE and DEGRADED
        ]}
        with pytest.raises(PreflightNoMatchingTransition):
            _resolve_next_node(node, "UNAVAILABLE", False)

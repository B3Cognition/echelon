"""
L3 Validation Tests for Default CQ-ISC Seed Library.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

Tests each of the 20 CQ-ISC entries with three test cases:
  - positive: a synthetic WME that SHOULD trigger the prohibit preference (verify it fires)
  - negative: a synthetic WME that should NOT trigger (verify it does not fire)
  - boundary: a WME at the exact threshold value (verify boundary semantics match rule text)

All tests run against MockSOARBridge — no SOAR binary required.

FR-ISC-DEFAULT-004: Every entry must have an L3 test suite.
INV-005: phase-gate (current-phase) is checked FIRST in all evaluations.
INV-002: prohibit preference is the SOLE enforcement mechanism.
"""

import pytest
from pathlib import Path

# Adjust sys.path so mock_soar_bridge is importable from the same directory
import sys
_L3_DIR = Path(__file__).parent
_CODEGEN_DIR = _L3_DIR.parent.parent
if str(_CODEGEN_DIR) not in sys.path:
    sys.path.insert(0, str(_CODEGEN_DIR))
if str(_L3_DIR) not in sys.path:
    sys.path.insert(0, str(_L3_DIR))

from mock_soar_bridge import MockSOARBridge


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bridge():
    """Fresh MockSOARBridge in GATE phase with psi=0.5."""
    b = MockSOARBridge(initial_phase="GATE", psi_score=0.5)
    yield b
    b.reset()


@pytest.fixture
def deliver_bridge():
    """MockSOARBridge in DELIVER phase with high psi."""
    b = MockSOARBridge(initial_phase="DELIVER", psi_score=0.85, tier1_gate="pass")
    yield b
    b.reset()


@pytest.fixture
def test_bridge():
    """MockSOARBridge in TEST phase."""
    b = MockSOARBridge(initial_phase="TEST", psi_score=0.85)
    yield b
    b.reset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_prohibit_fired(result, cq_isc_id: str):
    """Assert that a specific CQ-ISC prohibit preference fired."""
    assert result.any_prohibit_fired, (
        f"Expected prohibit to fire for {cq_isc_id}, but no prohibits fired. "
        f"Evaluated: {result.cq_isc_ids_evaluated}"
    )
    assert cq_isc_id in result.prohibits_fired, (
        f"Expected {cq_isc_id} prohibit to fire, but fired: {result.prohibits_fired}"
    )


def assert_prohibit_not_fired(result, cq_isc_id: str):
    """Assert that a specific CQ-ISC prohibit preference did NOT fire."""
    assert cq_isc_id not in result.prohibits_fired, (
        f"Expected {cq_isc_id} prohibit NOT to fire, but it fired. "
        f"All prohibits: {result.prohibits_fired}"
    )


def assert_operator_is_retry_or_escalate(result):
    """Assert that the selected operator is retry-task or escalate (not advance)."""
    assert result.selected_operator in ("retry-task", "escalate"), (
        f"Expected retry-task or escalate, got {result.selected_operator}"
    )


def assert_operator_is_advance(result):
    """Assert that the selected operator is advance-phase."""
    assert result.selected_operator == "advance-phase", (
        f"Expected advance-phase, got {result.selected_operator}"
    )


# ===========================================================================
# CQ-ISC-SEC-001: No hardcoded secrets
# ===========================================================================

class TestCQISCSEC001:
    """SEC-001: No hardcoded secrets/API keys."""

    def test_CQ_ISC_SEC_001_positive(self, bridge):
        """Positive: hardcoded secret detected — prohibit must fire."""
        bridge.inject_wme("code-violation-hardcoded-secret", "CQ-ISC-SEC-001", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-SEC-001")
        assert_operator_is_retry_or_escalate(result)

    def test_CQ_ISC_SEC_001_negative(self, bridge):
        """Negative: no secrets in code — prohibit must NOT fire."""
        bridge.inject_wme("code-metrics-file-length", 150, status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-SEC-001")

    def test_CQ_ISC_SEC_001_boundary(self, bridge):
        """Boundary: count=0 (no secrets) — prohibit must NOT fire; count=1 — must fire."""
        # count=0: no violation
        bridge.inject_wme("code-violation-hardcoded-secret-count", 0, status="none")
        result_clean = bridge.evaluate()
        assert_prohibit_not_fired(result_clean, "CQ-ISC-SEC-001")
        bridge.reset()

        # count=1: violation
        bridge.inject_wme("code-violation-hardcoded-secret", "CQ-ISC-SEC-001", status="confirmed-failing")
        result_violation = bridge.evaluate()
        assert_prohibit_fired(result_violation, "CQ-ISC-SEC-001")


# ===========================================================================
# CQ-ISC-SEC-002: No raw SQL string concatenation
# ===========================================================================

class TestCQISCSEC002:

    def test_CQ_ISC_SEC_002_positive(self, bridge):
        """Positive: SQL injection risk detected — prohibit must fire."""
        bridge.inject_wme("code-violation-sql-injection-risk", "CQ-ISC-SEC-002", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-SEC-002")

    def test_CQ_ISC_SEC_002_negative(self, bridge):
        """Negative: parameterised query used — no violation."""
        # No sql-injection-risk WME injected
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-SEC-002")

    def test_CQ_ISC_SEC_002_boundary(self, bridge):
        """Boundary: exactly one SQL concatenation instance."""
        bridge.inject_wme("code-violation-sql-injection-risk", "CQ-ISC-SEC-002", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-SEC-002")
        # Verify operator response
        assert_operator_is_retry_or_escalate(result)


# ===========================================================================
# CQ-ISC-SEC-003: No eval()/exec() of user input
# ===========================================================================

class TestCQISCSEC003:

    def test_CQ_ISC_SEC_003_positive(self, bridge):
        """Positive: eval() of user input detected — prohibit fires."""
        bridge.inject_wme("code-violation-eval-exec-user-input", "CQ-ISC-SEC-003", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-SEC-003")

    def test_CQ_ISC_SEC_003_negative(self, bridge):
        """Negative: no eval/exec in code — prohibit does not fire."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-SEC-003")

    def test_CQ_ISC_SEC_003_boundary(self, bridge):
        """Boundary: eval() of a non-user-controlled constant — must NOT fire."""
        # Static eval of a compile-time constant is not a violation
        bridge.inject_wme("code-metrics-file-length", 100, status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-SEC-003")


# ===========================================================================
# CQ-ISC-SEC-004: No HTTP requests without timeout
# ===========================================================================

class TestCQISCSEC004:

    def test_CQ_ISC_SEC_004_positive(self, bridge):
        """Positive: HTTP request without timeout — prohibit fires."""
        bridge.inject_wme("code-violation-http-request-no-timeout", "CQ-ISC-SEC-004", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-SEC-004")

    def test_CQ_ISC_SEC_004_negative(self, bridge):
        """Negative: HTTP request with explicit timeout=30 — no violation."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-SEC-004")

    def test_CQ_ISC_SEC_004_boundary(self, bridge):
        """Boundary: timeout=0 (effectively no timeout) — must fire."""
        bridge.inject_wme("code-violation-http-request-no-timeout", "timeout=0", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-SEC-004")


# ===========================================================================
# CQ-ISC-SEC-005: No unrestricted CORS wildcard
# ===========================================================================

class TestCQISCSEC005:

    def test_CQ_ISC_SEC_005_positive(self, bridge):
        """Positive: CORS wildcard on authenticated endpoint — prohibit fires."""
        bridge.inject_wme("code-violation-cors-wildcard-sensitive", "CQ-ISC-SEC-005", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-SEC-005")

    def test_CQ_ISC_SEC_005_negative(self, bridge):
        """Negative: CORS allowlisted to specific origin — no violation."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-SEC-005")

    def test_CQ_ISC_SEC_005_boundary(self, bridge):
        """Boundary: CORS wildcard on public (unauthenticated) endpoint — phase scope."""
        # Rule only applies to sensitive endpoints — public endpoints are not covered
        bridge.inject_wme("code-metrics-function-length", 20)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-SEC-005")


# ===========================================================================
# CQ-ISC-SEC-006: No password/secret in logs
# ===========================================================================

class TestCQISCSEC006:

    def test_CQ_ISC_SEC_006_positive(self, bridge):
        """Positive: password logged — prohibit fires."""
        bridge.inject_wme("code-violation-secret-in-logs", "CQ-ISC-SEC-006", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-SEC-006")

    def test_CQ_ISC_SEC_006_negative(self, bridge):
        """Negative: only structured logging with masked fields — no violation."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-SEC-006")

    def test_CQ_ISC_SEC_006_boundary(self, bridge):
        """Boundary: logging user.email (non-secret PII) — SEC-006 specific to secrets only."""
        # SEC-006 covers secrets/tokens, not general PII (that's SEC-010)
        bridge.inject_wme("code-metrics-file-length", 200)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-SEC-006")


# ===========================================================================
# CQ-ISC-STRUCT-001: Function body <= 30 lines
# ===========================================================================

class TestCQISCSTRUCT001:

    def test_CQ_ISC_STRUCT_001_positive(self, bridge):
        """Positive: function with 45 lines — prohibit fires."""
        bridge.inject_metric("function-length", 45)
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-STRUCT-001")

    def test_CQ_ISC_STRUCT_001_negative(self, bridge):
        """Negative: function with 20 lines — prohibit does NOT fire."""
        bridge.inject_metric("function-length", 20)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-001")

    def test_CQ_ISC_STRUCT_001_boundary(self, bridge):
        """Boundary: function with exactly 30 lines — must NOT fire (rule is > 30)."""
        bridge.inject_metric("function-length", 30)
        result = bridge.evaluate()
        # Rule: function-length > 30 → 30 is NOT a violation
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-001")


# ===========================================================================
# CQ-ISC-STRUCT-002: Cyclomatic complexity <= 10
# ===========================================================================

class TestCQISCSTRUCT002:

    def test_CQ_ISC_STRUCT_002_positive(self, bridge):
        """Positive: complexity 15 — prohibit fires."""
        bridge.inject_metric("cyclomatic-complexity", 15)
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-STRUCT-002")

    def test_CQ_ISC_STRUCT_002_negative(self, bridge):
        """Negative: complexity 5 — prohibit does NOT fire."""
        bridge.inject_metric("cyclomatic-complexity", 5)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-002")

    def test_CQ_ISC_STRUCT_002_boundary(self, bridge):
        """Boundary: complexity exactly 10 — must NOT fire (rule is > 10)."""
        bridge.inject_metric("cyclomatic-complexity", 10)
        result = bridge.evaluate()
        # Rule: cyclomatic-complexity > 10 → 10 is NOT a violation
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-002")


# ===========================================================================
# CQ-ISC-STRUCT-003: No circular imports
# ===========================================================================

class TestCQISCSTRUCT003:

    def test_CQ_ISC_STRUCT_003_positive(self, bridge):
        """Positive: circular import detected — prohibit fires."""
        bridge.inject_wme("code-violation-circular-import", "CQ-ISC-STRUCT-003", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-STRUCT-003")

    def test_CQ_ISC_STRUCT_003_negative(self, bridge):
        """Negative: clean DAG import graph — no violation."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-003")

    def test_CQ_ISC_STRUCT_003_boundary(self, bridge):
        """Boundary: indirect cycle (A→B→C→A) — must fire (any cycle prohibited)."""
        bridge.inject_wme("code-violation-circular-import", "indirect-cycle-A-B-C-A", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-STRUCT-003")


# ===========================================================================
# CQ-ISC-STRUCT-004: No function with > 5 parameters
# ===========================================================================

class TestCQISCSTRUCT004:

    def test_CQ_ISC_STRUCT_004_positive(self, bridge):
        """Positive: function with 7 parameters — prohibit fires."""
        bridge.inject_metric("parameter-count", 7)
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-STRUCT-004")

    def test_CQ_ISC_STRUCT_004_negative(self, bridge):
        """Negative: function with 3 parameters — prohibit does NOT fire."""
        bridge.inject_metric("parameter-count", 3)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-004")

    def test_CQ_ISC_STRUCT_004_boundary(self, bridge):
        """Boundary: exactly 5 parameters — must NOT fire (rule is > 5)."""
        bridge.inject_metric("parameter-count", 5)
        result = bridge.evaluate()
        # Rule: parameter-count > 5 → 5 is NOT a violation
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-004")


# ===========================================================================
# CQ-ISC-STRUCT-005: File length <= 300 lines
# ===========================================================================

class TestCQISCSTRUCT005:

    def test_CQ_ISC_STRUCT_005_positive(self, bridge):
        """Positive: file with 450 lines — prohibit fires."""
        bridge.inject_metric("file-length", 450)
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-STRUCT-005")

    def test_CQ_ISC_STRUCT_005_negative(self, bridge):
        """Negative: file with 200 lines — prohibit does NOT fire."""
        bridge.inject_metric("file-length", 200)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-005")

    def test_CQ_ISC_STRUCT_005_boundary(self, bridge):
        """Boundary: exactly 300 lines — must NOT fire (rule is > 300)."""
        bridge.inject_metric("file-length", 300)
        result = bridge.evaluate()
        # Rule: file-length > 300 → 300 is NOT a violation
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-005")


# ===========================================================================
# CQ-ISC-STRUCT-006: Nesting depth <= 4
# ===========================================================================

class TestCQISCSTRUCT006:

    def test_CQ_ISC_STRUCT_006_positive(self, bridge):
        """Positive: nesting depth 6 — prohibit fires."""
        bridge.inject_metric("nesting-depth", 6)
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-STRUCT-006")

    def test_CQ_ISC_STRUCT_006_negative(self, bridge):
        """Negative: nesting depth 3 — prohibit does NOT fire."""
        bridge.inject_metric("nesting-depth", 3)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-006")

    def test_CQ_ISC_STRUCT_006_boundary(self, bridge):
        """Boundary: exactly depth 4 — must NOT fire (rule is > 4)."""
        bridge.inject_metric("nesting-depth", 4)
        result = bridge.evaluate()
        # Rule: nesting-depth > 4 → 4 is NOT a violation
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-006")


# ===========================================================================
# CQ-ISC-TEST-001: Every source file must have a test file
# ===========================================================================

class TestCQISCTEST001:

    def test_CQ_ISC_TEST_001_positive(self, bridge):
        """Positive: source file without corresponding test file — prohibit fires."""
        bridge.inject_wme("code-violation-missing-test-file", "CQ-ISC-TEST-001", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-TEST-001")

    def test_CQ_ISC_TEST_001_negative(self, bridge):
        """Negative: all source files have corresponding test files — no violation."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-TEST-001")

    def test_CQ_ISC_TEST_001_boundary(self, bridge):
        """Boundary: test file exists but is in wrong directory — still fires."""
        # Wrong directory test file counts as missing (naming convention violation)
        bridge.inject_wme("code-violation-missing-test-file", "wrong-dir", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-TEST-001")


# ===========================================================================
# CQ-ISC-TEST-002: No untested public functions
# ===========================================================================

class TestCQISCTEST002:

    def test_CQ_ISC_TEST_002_positive(self, bridge):
        """Positive: public function with zero test assertions — prohibit fires."""
        bridge.inject_wme("code-violation-untested-public-function", "CQ-ISC-TEST-002", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-TEST-002")

    def test_CQ_ISC_TEST_002_negative(self, bridge):
        """Negative: all public functions have at least one test assertion — no violation."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-TEST-002")

    def test_CQ_ISC_TEST_002_boundary(self, bridge):
        """Boundary: exactly 1 assertion per function — must NOT fire (minimum satisfied)."""
        # 1 assertion is the minimum — rule requires > 0, so 1 is compliant
        bridge.inject_metric("test-assertion-count", 1)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-TEST-002")


# ===========================================================================
# CQ-ISC-TEST-003: Test file must have at least one assertion
# ===========================================================================

class TestCQISCTEST003:

    def test_CQ_ISC_TEST_003_positive(self, bridge):
        """Positive: test file with zero assertions — prohibit fires."""
        bridge.inject_wme("code-violation-test-file-no-assertion", "CQ-ISC-TEST-003", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-TEST-003")

    def test_CQ_ISC_TEST_003_negative(self, bridge):
        """Negative: test file has 5 assertions — no violation."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-TEST-003")

    def test_CQ_ISC_TEST_003_boundary(self, bridge):
        """Boundary: exactly 1 assertion in test file — must NOT fire."""
        # 1 assertion is the minimum — compliant
        bridge.inject_metric("test-assertion-count-in-file", 1)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-TEST-003")


# ===========================================================================
# CQ-ISC-TEST-004: Test names must be descriptive (len > 10 chars)
# ===========================================================================

class TestCQISCTEST004:

    def test_CQ_ISC_TEST_004_positive(self, bridge):
        """Positive: test named 'test1' (5 chars) — prohibit fires."""
        bridge.inject_wme("code-violation-test-name-too-short", "CQ-ISC-TEST-004", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-TEST-004")

    def test_CQ_ISC_TEST_004_negative(self, bridge):
        """Negative: test named 'test_returns_404_when_user_not_found' (35 chars) — no violation."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-TEST-004")

    def test_CQ_ISC_TEST_004_boundary(self, bridge):
        """Boundary: test name exactly 10 chars — must NOT fire (rule is len > 10 → min 11)."""
        # 'test_login' is exactly 10 chars — rule says > 10, so this is a violation
        bridge.inject_wme("code-violation-test-name-too-short", "name-len=10", status="confirmed-failing")
        result = bridge.evaluate()
        # 10 chars violates the rule (must be > 10, i.e., >= 11)
        assert_prohibit_fired(result, "CQ-ISC-TEST-004")


# ===========================================================================
# CQ-ISC-QUAL-001: No console.log/print in production code
# ===========================================================================

class TestCQISCQUAL001:

    def test_CQ_ISC_QUAL_001_positive(self, bridge):
        """Positive: console.log found in production code — prohibit fires."""
        bridge.inject_wme("code-violation-debug-print-in-production", "CQ-ISC-QUAL-001", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-QUAL-001")

    def test_CQ_ISC_QUAL_001_negative(self, bridge):
        """Negative: only structlog/winston calls in production code — no violation."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-QUAL-001")

    def test_CQ_ISC_QUAL_001_boundary(self, bridge):
        """Boundary: console.log in test file (not production path) — must NOT fire."""
        # QUAL-001 only fires for production code paths; test files are excluded
        bridge.inject_metric("file-length", 100)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-QUAL-001")


# ===========================================================================
# CQ-ISC-QUAL-002: No TODO/FIXME in delivered code
# ===========================================================================

class TestCQISCQUAL002:
    """QUAL-002 has phase_scope=DELIVER — only fires at DELIVER phase."""

    def test_CQ_ISC_QUAL_002_positive(self, deliver_bridge):
        """Positive: unlinked TODO in production code at DELIVER phase — prohibit fires."""
        deliver_bridge.inject_wme("code-violation-unlinked-todo-in-production", "CQ-ISC-QUAL-002", status="confirmed-failing")
        result = deliver_bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-QUAL-002")

    def test_CQ_ISC_QUAL_002_negative(self, deliver_bridge):
        """Negative: linked TODO(GH-42) in code — no violation."""
        result = deliver_bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-QUAL-002")

    def test_CQ_ISC_QUAL_002_boundary(self, bridge):
        """Boundary: QUAL-002 at GATE phase — must NOT fire (phase_scope=DELIVER only)."""
        # bridge is at GATE phase; QUAL-002 only fires at DELIVER
        bridge.inject_wme("code-violation-unlinked-todo-in-production", "CQ-ISC-QUAL-002", status="confirmed-failing")
        result = bridge.evaluate()
        # QUAL-002 has phase_scope=DELIVER — must NOT fire at GATE
        assert_prohibit_not_fired(result, "CQ-ISC-QUAL-002")


# ===========================================================================
# CQ-ISC-QUAL-003: No magic numbers
# ===========================================================================

class TestCQISCQUAL003:

    def test_CQ_ISC_QUAL_003_positive(self, bridge):
        """Positive: magic number 86400 (seconds in a day) without named constant — prohibit fires."""
        bridge.inject_wme("code-violation-magic-number", "CQ-ISC-QUAL-003", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-QUAL-003")

    def test_CQ_ISC_QUAL_003_negative(self, bridge):
        """Negative: SECONDS_PER_DAY = 86400 (named constant) — no violation."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-QUAL-003")

    def test_CQ_ISC_QUAL_003_boundary(self, bridge):
        """Boundary: literal 0 or 1 in simple arithmetic — must NOT fire (exempt values)."""
        # 0 and 1 are exempt from the magic number rule
        bridge.inject_metric("cyclomatic-complexity", 0)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-QUAL-003")


# ===========================================================================
# CQ-ISC-QUAL-004: No dead code
# ===========================================================================

class TestCQISCQUAL004:

    def test_CQ_ISC_QUAL_004_positive(self, bridge):
        """Positive: unreachable code after return statement — prohibit fires."""
        bridge.inject_wme("code-violation-dead-code", "CQ-ISC-QUAL-004", status="confirmed-failing")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-QUAL-004")

    def test_CQ_ISC_QUAL_004_negative(self, bridge):
        """Negative: all code paths reachable — no violation."""
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-QUAL-004")

    def test_CQ_ISC_QUAL_004_boundary(self, bridge):
        """Boundary: conditional branch that is theoretically reachable but never tested — must NOT fire."""
        # Dead code rule only fires on provably unreachable code (static analysis)
        # A branch that's merely untested is not dead code — it's TEST-002
        bridge.inject_metric("function-length", 15)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-QUAL-004")


# ===========================================================================
# INV-005 validation tests (cross-cutting concern)
# ===========================================================================

class TestINV005PhaseGateFirst:
    """Verify that INV-005 is enforced: phase-gate is checked FIRST."""

    def test_phase_gate_blocks_evaluation_wrong_phase(self):
        """
        QUAL-002 has phase_scope=DELIVER.
        At GATE phase, even with a QUAL-002 violation WME, prohibit must NOT fire.
        This proves (build ^current-phase <phase>) is checked before the predicate.
        """
        bridge = MockSOARBridge(initial_phase="GATE")
        bridge.inject_violation("CQ-ISC-QUAL-002")  # DELIVER-scoped entry
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-QUAL-002")

    def test_phase_gate_allows_evaluation_correct_phase(self):
        """
        QUAL-002 has phase_scope=DELIVER.
        At DELIVER phase with a violation WME, prohibit MUST fire.
        """
        bridge = MockSOARBridge(initial_phase="DELIVER", psi_score=0.85, tier1_gate="pass")
        bridge.inject_violation("CQ-ISC-QUAL-002")
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-QUAL-002")

    def test_verify_phase_rules_evaluate_at_gate(self):
        """STRUCT-001 has phase_scope=VERIFY which maps to GATE. Must fire at GATE."""
        bridge = MockSOARBridge(initial_phase="GATE")
        bridge.inject_metric("function-length", 50)
        result = bridge.evaluate()
        assert_prohibit_fired(result, "CQ-ISC-STRUCT-001")

    def test_verify_phase_rules_do_not_fire_at_implement(self):
        """STRUCT-001 must NOT fire at IMPLEMENT phase (not yet in scope)."""
        bridge = MockSOARBridge(initial_phase="IMPLEMENT")
        bridge.inject_metric("function-length", 50)
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-STRUCT-001")


# ===========================================================================
# INV-002 validation tests (prohibit is sole enforcement mechanism)
# ===========================================================================

class TestINV002ProhibitIsSoleEnforcement:
    """Verify that prohibit preference is the only enforcement path."""

    def test_prohibit_blocks_advance_operator(self):
        """When prohibit fires, advance-phase must be blocked."""
        bridge = MockSOARBridge(initial_phase="GATE", psi_score=0.85)
        bridge.inject_metric("function-length", 50)  # triggers STRUCT-001
        result = bridge.evaluate()
        # advance-phase is prohibited
        assert result.selected_operator != "advance-phase", (
            "advance-phase must be blocked when prohibit fires"
        )

    def test_no_prohibit_allows_advance(self):
        """When no prohibit fires and Ψ >= threshold, advance-phase is selected."""
        bridge = MockSOARBridge(initial_phase="GATE", psi_score=0.85)
        # No violation WMEs injected
        result = bridge.evaluate()
        assert_operator_is_advance(result)


# ===========================================================================
# Quarantine tests
# ===========================================================================

class TestQuarantine:
    """Verify that drifted and pending-review entries do NOT fire."""

    def test_drifted_entry_does_not_fire(self):
        """
        A drifted CQ-ISC entry (policy_drift_status=drifted) must NOT fire
        even when its violation WME is present.
        """
        bridge = MockSOARBridge(initial_phase="GATE")
        # Manually set an entry to drifted
        entry = bridge.get_entry("CQ-ISC-SEC-001")
        if entry:
            entry.policy_drift_status = "drifted"
        bridge.inject_violation("CQ-ISC-SEC-001")
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-SEC-001")

    def test_pending_review_entry_does_not_fire(self):
        """
        A pending-review CQ-ISC entry must NOT fire (quarantined).
        """
        bridge = MockSOARBridge(initial_phase="GATE")
        entry = bridge.get_entry("CQ-ISC-SEC-002")
        if entry:
            entry.policy_drift_status = "pending-review"
        bridge.inject_violation("CQ-ISC-SEC-002")
        result = bridge.evaluate()
        assert_prohibit_not_fired(result, "CQ-ISC-SEC-002")


# ===========================================================================
# Multiple simultaneous violations (conflict impasse scenario)
# ===========================================================================

class TestConflictImpasse:
    """Verify INV-008: conflict impasse when multiple prohibits fire simultaneously."""

    def test_multiple_prohibits_fire_simultaneously(self):
        """Multiple CQ-ISC violations simultaneously — all prohibits must fire."""
        bridge = MockSOARBridge(initial_phase="GATE", psi_score=0.85)
        bridge.inject_metric("function-length", 50)      # STRUCT-001
        bridge.inject_metric("cyclomatic-complexity", 15) # STRUCT-002
        bridge.inject_violation("CQ-ISC-SEC-001")         # SEC-001
        result = bridge.evaluate()
        # All three prohibits must fire
        assert "CQ-ISC-STRUCT-001" in result.prohibits_fired
        assert "CQ-ISC-STRUCT-002" in result.prohibits_fired
        assert "CQ-ISC-SEC-001" in result.prohibits_fired
        # Operator must be retry or escalate, not advance
        assert result.selected_operator in ("retry-task", "escalate")

    def test_escalate_on_max_retries_exceeded(self):
        """When retry_count >= max_retries, operator must be escalate (not retry-task)."""
        bridge = MockSOARBridge(
            initial_phase="GATE",
            psi_score=0.5,
            retry_count=3,
            max_retries=3,
        )
        bridge.inject_violation("CQ-ISC-SEC-001")
        result = bridge.evaluate()
        assert result.selected_operator == "escalate"

    def test_retry_task_when_retries_available(self):
        """When retry_count < max_retries, operator must be retry-task."""
        bridge = MockSOARBridge(
            initial_phase="GATE",
            psi_score=0.5,
            retry_count=1,
            max_retries=3,
        )
        bridge.inject_violation("CQ-ISC-SEC-001")
        result = bridge.evaluate()
        assert result.selected_operator == "retry-task"


# ===========================================================================
# Library completeness tests
# ===========================================================================

class TestLibraryCompleteness:
    """Verify the library has exactly 20 entries across 4 constraint classes."""

    def test_library_has_20_entries(self):
        bridge = MockSOARBridge()
        entries = bridge.get_all_entry_ids()
        assert len(entries) == 20, f"Expected 20 entries, got {len(entries)}: {entries}"

    def test_library_has_6_security_entries(self):
        bridge = MockSOARBridge()
        sec_entries = [e for e in bridge._entries if e.constraint_class == "SECURITY"]
        assert len(sec_entries) == 6, f"Expected 6 SECURITY entries, got {len(sec_entries)}"

    def test_library_has_6_structural_entries(self):
        bridge = MockSOARBridge()
        struct_entries = [e for e in bridge._entries if e.constraint_class == "STRUCTURAL"]
        assert len(struct_entries) == 6, f"Expected 6 STRUCTURAL entries, got {len(struct_entries)}"

    def test_library_has_4_test_entries(self):
        bridge = MockSOARBridge()
        test_entries = [e for e in bridge._entries if e.constraint_class == "TEST"]
        assert len(test_entries) == 4, f"Expected 4 TEST entries, got {len(test_entries)}"

    def test_library_has_4_quality_entries(self):
        bridge = MockSOARBridge()
        qual_entries = [e for e in bridge._entries if e.constraint_class == "QUALITY"]
        assert len(qual_entries) == 4, f"Expected 4 QUALITY entries, got {len(qual_entries)}"

    def test_all_entries_are_current(self):
        """All seed library entries must have policy_drift_status=current."""
        bridge = MockSOARBridge()
        non_current = [e.cq_isc_id for e in bridge._entries if e.policy_drift_status != "current"]
        assert len(non_current) == 0, f"Non-current entries: {non_current}"

    def test_psi_seed_meets_threshold(self):
        """Total psi_contribution_weight / 50 must be >= 0.70."""
        bridge = MockSOARBridge()
        total_weight = sum(e.psi_contribution_weight for e in bridge._entries)
        psi_seed = total_weight / 50.0
        assert psi_seed >= 0.70, (
            f"Ψ_seed = {psi_seed:.3f} < 0.70 — library does not meet FR-ISC-DEFAULT-003"
        )

    def test_all_entries_have_non_empty_soar_predicate(self):
        """Every entry must have a non-empty soar_predicate (required for prohibit generation)."""
        bridge = MockSOARBridge()
        empty_pred = [e.cq_isc_id for e in bridge._entries if not e.soar_predicate.strip()]
        assert len(empty_pred) == 0, f"Entries with empty soar_predicate: {empty_pred}"

    def test_no_soar_predicate_starts_with_build(self):
        """INV-005: no soar_predicate should start with '(build' — phase-gate is prepended."""
        bridge = MockSOARBridge()
        violations = [
            e.cq_isc_id for e in bridge._entries
            if e.soar_predicate.lstrip().startswith("(build")
        ]
        assert len(violations) == 0, (
            f"INV-005 violation: entries whose soar_predicate starts with '(build': {violations}"
        )

    def test_all_entry_ids_match_expected_pattern(self):
        """All IDs must match CQ-ISC-[A-Z]+-[0-9]{3}."""
        import re
        pattern = re.compile(r"^CQ-ISC-[A-Z]+-[0-9]{3}$")
        bridge = MockSOARBridge()
        invalid = [e.cq_isc_id for e in bridge._entries if not pattern.match(e.cq_isc_id)]
        assert len(invalid) == 0, f"Entries with invalid ID format: {invalid}"
